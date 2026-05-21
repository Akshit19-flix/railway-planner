"""
Scraper facade — launches scraper_worker.py as a subprocess (clean event loop).
Supports:
  - scrape_schedule()       : one call, gets all trains + running days
  - scrape_availability()   : per-date seat counts via _TrainsPair.aspx
  - scrape_availability_range() : scrapes a date range in parallel batches
"""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

try:
    from http_scraper import scrape_schedule_http, scrape_availability_http, is_viable
    HTTP_AVAILABLE = True
except ImportError:
    HTTP_AVAILABLE = False

DAY_COLUMNS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
CLASS_ORDER = ["1A", "2A", "3A", "CC", "SL", "2S", "3E"]
WORKER = str(Path(__file__).parent / "scraper_worker.py")


@dataclass
class TrainInfo:
    train_number: str
    train_name:   str
    from_station: str
    departure:    str
    to_station:   str
    arrival:      str
    duration:     str
    runs_on:      list[str]      = field(default_factory=list)
    classes:      list[str]      = field(default_factory=list)
    availability: dict[str,str]  = field(default_factory=dict)
    date:         Optional[date] = None


def _run_worker(*args) -> list[dict]:
    """Run scraper_worker.py with given args, return parsed JSON."""
    result = subprocess.run(
        [sys.executable, WORKER, *args],
        capture_output=True,
        timeout=180,
    )
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Worker failed:\n{err}")
    return json.loads(result.stdout.decode("utf-8", errors="replace"))


def _run_batch_worker(from_code, to_code, dates, iso_dates, progress_cb):
    import subprocess as _sp
    import threading

    proc = _sp.Popen(
        [sys.executable, WORKER, "batch_availability", from_code, to_code, *iso_dates],
        stdout=_sp.PIPE,
        stderr=_sp.PIPE,
    )
    total = len(dates)

    # Drain stdout in a background thread to prevent pipe-buffer deadlock.
    # The worker writes potentially hundreds of KB of JSON to stdout; if we
    # don't consume it concurrently, the OS pipe buffer fills and both sides
    # block indefinitely.
    stdout_buf: list[bytes] = []
    def _drain():
        stdout_buf.append(proc.stdout.read())
    drain_thread = threading.Thread(target=_drain, daemon=True)
    drain_thread.start()

    # Read stderr for live PROGRESS lines while stdout is being drained.
    for raw_line in iter(proc.stderr.readline, b""):
        line = raw_line.decode("utf-8", errors="replace").strip()
        if line.startswith("PROGRESS:") and progress_cb:
            _, rest = line.split(":", 1)
            parts = rest.split(":", 1)
            try:
                done_n, _ = map(int, parts[0].split("/"))
                date_str = parts[1] if len(parts) > 1 else ""
                progress_cb(done_n, total, date_str)
            except (ValueError, IndexError):
                pass

    proc.wait()
    drain_thread.join()

    if proc.returncode != 0:
        raise RuntimeError("batch worker failed")

    raw_out = (stdout_buf[0] if stdout_buf else b"").decode("utf-8", errors="replace")
    raw = json.loads(raw_out)

    return {
        date.fromisoformat(k): {r["train_number"]: r["availability"] for r in v}
        for k, v in raw.items()
    }


def scrape_schedule(from_code: str, to_code: str) -> list[TrainInfo]:
    """Fetch all trains + running days in a single scrape."""
    if HTTP_AVAILABLE:
        try:
            trains = scrape_schedule_http(from_code.upper(), to_code.upper())
            if trains:
                return [_to_train(t) for t in trains]
        except Exception:
            pass
    # Playwright fallback
    raw = _run_worker("schedule", from_code.upper(), to_code.upper())
    return [_to_train(t) for t in raw]


def scrape_availability(from_code: str, to_code: str, travel_date: date) -> dict[str, dict[str,str]]:
    """
    Scrape seat availability for a specific date.
    Returns {train_number: {class: availability_string}}.
    """
    raw = _run_worker("availability", from_code.upper(), to_code.upper(),
                      travel_date.strftime("%Y-%m-%d"))
    return {r["train_number"]: r["availability"] for r in raw}


def scrape_availability_range(
    from_code: str,
    to_code: str,
    start: date,
    end: date,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    batch_size: int = 2,
) -> dict[date, dict[str, dict[str,str]]]:
    """
    Scrape availability for every date in [start, end].
    Strategy:
      1. HTTP path (fast, cloud-compatible) — httpx async, concurrency=8.
      2. Batch Playwright subprocess — streams stderr for progress updates.
      3. Legacy per-date scraping — original ThreadPoolExecutor fallback.
    Returns {date: {train_number: {class: value}}}.
    progress_cb(done, total, date_str) called after each date completes.
    """
    import time as _time

    dates = []
    d = start
    while d <= end:
        dates.append(d)
        d += timedelta(days=1)

    iso_dates = [d.strftime("%Y-%m-%d") for d in dates]
    total = len(dates)

    # ── Path 1: HTTP API (fast, no browser, works on Render) ────────────────
    if HTTP_AVAILABLE:
        try:
            raw = scrape_availability_http(
                from_code.upper(), to_code.upper(),
                iso_dates, progress_cb=progress_cb, concurrency=10,
            )
            if is_viable(raw, iso_dates, threshold=0.4):
                return {
                    date.fromisoformat(k): {r["train_number"]: r["availability"] for r in v}
                    for k, v in raw.items()
                }
        except Exception:
            pass

    # ── Path 2: Batch Playwright subprocess (local fallback if HTTP fails) ──
    try:
        return _run_batch_worker(
            from_code.upper(), to_code.upper(),
            dates, iso_dates, progress_cb,
        )
    except Exception:
        pass

    # ── Path 3: Original per-date scraping (last resort) ─────────────────
    return _legacy_range(from_code, to_code, dates, progress_cb)


def _legacy_range(
    from_code: str,
    to_code: str,
    dates: list[date],
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    batch_size: int = 2,
) -> dict[date, dict[str, dict[str,str]]]:
    """
    Original per-date scraping logic: ThreadPoolExecutor batches of batch_size=2
    with a 3-second pause between batches to respect erail rate limits.
    """
    import time as _time

    total = len(dates)
    results: dict[date, dict[str, dict[str,str]]] = {}
    done = 0

    def fetch_one(dt: date):
        try:
            return dt, scrape_availability(from_code, to_code, dt)
        except Exception:
            return dt, {}

    # Process in batches with a pause between each batch
    for batch_start in range(0, total, batch_size):
        batch = dates[batch_start: batch_start + batch_size]
        with ThreadPoolExecutor(max_workers=batch_size) as pool:
            futures = {pool.submit(fetch_one, dt): dt for dt in batch}
            for future in as_completed(futures):
                dt, avail = future.result()
                results[dt] = avail
                done += 1
                if progress_cb:
                    progress_cb(done, total, dt.strftime("%d %b"))

        # Polite pause between batches to avoid rate limiting
        if batch_start + batch_size < total:
            _time.sleep(3)

    return results


def _to_train(t: dict) -> TrainInfo:
    return TrainInfo(
        train_number  = t["train_number"],
        train_name    = t["train_name"],
        from_station  = t["from_station"],
        departure     = t["departure"],
        to_station    = t["to_station"],
        arrival       = t["arrival"],
        duration      = t["duration"],
        runs_on       = t["runs_on"],
        classes       = t["classes"],
        availability  = t.get("availability", {}),
    )


# Legacy aliases
def scrape_trains_between_stations(from_code, to_code, headless=True):
    return scrape_schedule(from_code, to_code)

def scrape_trains_in_thread(from_code, to_code, headless=True):
    return scrape_schedule(from_code, to_code)
