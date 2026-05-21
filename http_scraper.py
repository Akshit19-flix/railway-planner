"""
Cloud-compatible HTTP scraper for Indian Railways data via erail.in.
Uses httpx (async) + BeautifulSoup — no Playwright dependency.

Exported API (mirrors the subset used by scraper.py):
  scrape_schedule_http(from_code, to_code)          -> list[dict]
  scrape_availability_http(from_code, to_code,
                           dates, progress_cb=None,
                           concurrency=8)            -> dict[str, list[dict]]
  is_viable(results, dates, threshold=0.6)           -> bool
"""

import asyncio
import concurrent.futures
import re
import sys
import warnings
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")

# ── Constants ──────────────────────────────────────────────────────────────────

SCHEDULE_URL     = "https://erail.in/trains-between-stations/{from_code}/{to_code}"
AVAILABILITY_URL = "https://erail.in/_TrainsPair.aspx?from={from_code}&to={to_code}&date={date_str}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://erail.in/",
}

DAY_COLUMNS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
CLASS_ORDER  = ["1A", "2A", "3A", "CC", "SL", "2S", "3E"]


# ── HTML → plain text ──────────────────────────────────────────────────────────

def _html_to_text(html: str) -> str:
    """
    Convert HTML to tab-separated plain text mimicking Playwright's inner_text.

    - For each <tr>: join all <td>/<th> text with "\\t" and append as a line.
    - For non-table block elements (h1-h3, p) that don't contain a <table>:
      append their text as a line.
    """
    soup = BeautifulSoup(html, "html.parser")
    lines = []

    # Collect all <tr> rows from every table
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if cells:
            lines.append("\t".join(c.get_text(" ", strip=True) for c in cells))

    # Collect block-level text outside tables
    for tag in soup.find_all(["h1", "h2", "h3", "p"]):
        if not tag.find("table"):
            text = tag.get_text(" ", strip=True)
            if text:
                lines.append(text)

    return "\n".join(lines)


# ── Parsing helpers (duplicated exactly from scraper_worker.py) ────────────────

def _clean(v: str) -> str:
    v = v.strip().replace("\xa0", "").strip()
    if v in ("x", "", "Departed"):
        return "—"
    return v


def _parse_schedule(body_text: str) -> list[dict]:
    trains = []
    lines = [l for l in body_text.splitlines() if l.strip()]
    header_idx = -1
    class_start = 17
    for i, line in enumerate(lines):
        if re.search(r'\bM\b.*\bT\b.*\bW\b.*\bT\b.*\bF\b.*\bS\b.*\bS\b', line):
            header_idx = i
            parts = re.split(r'\t+', line)
            for j, p in enumerate(parts):
                if p.strip() == "1A":
                    class_start = j
                    break
            break
    if header_idx == -1:
        return _fallback_parse(body_text)
    for line in lines[header_idx + 1:]:
        parts = re.split(r'\t+', line.strip())
        if not parts or not re.match(r'^\d{4,5}$', parts[0].strip()):
            continue
        try:
            day_values = parts[10:17] if len(parts) > 16 else []
            runs_on = [DAY_COLUMNS[i] for i, v in enumerate(day_values) if v.strip().upper() == "Y"]
            avail = {}
            for ci, cls in enumerate(CLASS_ORDER):
                col = class_start + ci
                avail[cls] = _clean(parts[col]) if col < len(parts) else "—"
            classes = [cls for cls in CLASS_ORDER if avail[cls] != "—"]
            trains.append({
                "train_number": parts[0].strip(),
                "train_name":   parts[1].strip() if len(parts) > 1 else "",
                "from_station": parts[2].strip() if len(parts) > 2 else "",
                "departure":    parts[3].strip() if len(parts) > 3 else "",
                "to_station":   parts[5].strip() if len(parts) > 5 else "",
                "arrival":      parts[6].strip() if len(parts) > 6 else "",
                "duration":     parts[8].strip() if len(parts) > 8 else "",
                "runs_on":      runs_on,
                "classes":      classes,
                "availability": avail,
            })
        except (IndexError, ValueError):
            continue
    return trains


def _fallback_parse(body_text: str) -> list[dict]:
    trains, seen = [], set()
    for m in re.finditer(r'(\d{5})\s+([A-Z][A-Z0-9 \(\)]{3,50})', body_text):
        num, name = m.group(1), m.group(2).strip()
        if num not in seen and len(name) > 3:
            seen.add(num)
            trains.append({
                "train_number": num, "train_name": name[:50],
                "from_station": "", "departure": "",
                "to_station": "", "arrival": "", "duration": "",
                "runs_on": DAY_COLUMNS, "classes": [],
                "availability": {cls: "—" for cls in CLASS_ORDER},
            })
    return trains


def _parse_availability(body_text: str) -> list[dict]:
    result = []
    lines = [l for l in body_text.splitlines() if l.strip()]
    header_idx = -1
    class_start = 17
    for i, line in enumerate(lines):
        if re.search(r'\bM\b.*\bT\b.*\bW\b.*\bT\b.*\bF\b.*\bS\b.*\bS\b', line):
            header_idx = i
            parts = re.split(r'\t+', line)
            for j, p in enumerate(parts):
                if p.strip() == "1A":
                    class_start = j
                    break
            break
    if header_idx == -1:
        return result
    for line in lines[header_idx + 1:]:
        parts = re.split(r'\t+', line.strip())
        if not parts or not re.match(r'^\d{4,5}$', parts[0].strip()):
            continue
        try:
            avail = {}
            for ci, cls in enumerate(CLASS_ORDER):
                col = class_start + ci
                avail[cls] = _clean(parts[col]) if col < len(parts) else "—"
            result.append({"train_number": parts[0].strip(), "availability": avail})
        except (IndexError, ValueError):
            continue
    return result


# ── Async HTTP core ────────────────────────────────────────────────────────────

async def _fetch_html(client: httpx.AsyncClient, url: str) -> str:
    """GET url, return response text or "" on any error."""
    try:
        resp = await client.get(url, timeout=30)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"[http_scraper] fetch error {url}: {e}", file=sys.stderr)
        return ""


async def _scrape_schedule_async(from_code: str, to_code: str) -> list[dict]:
    url = SCHEDULE_URL.format(
        from_code=from_code.upper(),
        to_code=to_code.upper(),
    )
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        html = await _fetch_html(client, url)
    if not html:
        return []
    body_text = _html_to_text(html)
    return _parse_schedule(body_text)


async def _scrape_availability_async(
    from_code: str,
    to_code: str,
    dates: list[str],
    progress_cb,
    concurrency: int,
) -> dict:
    """
    Fetch availability for every date concurrently, honouring `concurrency`.
    Calls progress_cb(done, total, date_str) after each date completes.
    """
    results  = {}
    total    = len(dates)
    done_ctr = [0]   # mutable counter; GIL protects single-element list writes in CPython
    sem      = asyncio.Semaphore(concurrency)

    # Build the warm-up / schedule URL to seed cookies
    schedule_url = SCHEDULE_URL.format(
        from_code=from_code.upper(),
        to_code=to_code.upper(),
    )

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        # Warm up — load schedule page to acquire any session cookies
        await _fetch_html(client, schedule_url)

        async def fetch_one(iso_date: str):
            dt       = datetime.strptime(iso_date, "%Y-%m-%d")
            date_str = dt.strftime("%d-%b-%Y")   # e.g. "25-May-2026"
            url = AVAILABILITY_URL.format(
                from_code=from_code.upper(),
                to_code=to_code.upper(),
                date_str=date_str,
            )
            async with sem:
                html = await _fetch_html(client, url)

            body_text      = _html_to_text(html) if html else ""
            parsed         = _parse_availability(body_text)
            results[iso_date] = parsed

            done_ctr[0] += 1
            if progress_cb is not None:
                try:
                    progress_cb(done_ctr[0], total, iso_date)
                except Exception:
                    pass

        # Fire all tasks; asyncio.as_completed ensures progress_cb is called
        # as each finishes rather than waiting for the whole batch.
        tasks = [asyncio.ensure_future(fetch_one(d)) for d in dates]
        for coro in asyncio.as_completed(tasks):
            await coro

    return results


# ── Public sync wrappers ───────────────────────────────────────────────────────
# Run async code in a dedicated thread to avoid nest_asyncio issues when the
# caller is already inside an event loop (e.g. Jupyter, Streamlit).

def scrape_schedule_http(from_code: str, to_code: str) -> list[dict]:
    """Return schedule list for trains running between from_code and to_code."""
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(
                asyncio.run, _scrape_schedule_async(from_code, to_code)
            ).result(timeout=60)
    except Exception as e:
        print(f"[http_scraper] scrape_schedule_http error: {e}", file=sys.stderr)
        return []


def scrape_availability_http(
    from_code: str,
    to_code: str,
    dates: list[str],
    progress_cb=None,
    concurrency: int = 8,
) -> dict:
    """
    Return {iso_date_str: [{"train_number": ..., "availability": {cls: val}}]}
    for every date in `dates` (list of "YYYY-MM-DD" strings).

    progress_cb(done: int, total: int, date_str: str) is called after each date.
    """
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(
                asyncio.run,
                _scrape_availability_async(
                    from_code, to_code, dates, progress_cb, concurrency
                ),
            ).result(timeout=300)
    except Exception as e:
        print(f"[http_scraper] scrape_availability_http error: {e}", file=sys.stderr)
        return {}


# ── Viability check ────────────────────────────────────────────────────────────

def is_viable(results: dict, dates: list[str], threshold: float = 0.6) -> bool:
    """
    Return True if at least `threshold` fraction of dates have non-empty results.
    """
    if not dates:
        return False
    non_empty = sum(1 for d in dates if results.get(d))
    return (non_empty / len(dates)) >= threshold
