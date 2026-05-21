"""
Fast cloud-compatible scraper for Indian Railways data via erail.in.

Schedule:      HTTP GET  erail.in/trains-between-stations  (BeautifulSoup)
Availability:  POST      s.erail.in/getvalue               (direct IRCTC cache API)

No Playwright / no browser needed — works on Render free tier.
30 dates completes in ~5-8 seconds instead of 2+ minutes.
"""

import asyncio
import concurrent.futures
import json
import re
import sys
import time
import warnings
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")

# ── Constants ──────────────────────────────────────────────────────────────────

SCHEDULE_URL     = "https://erail.in/trains-between-stations/{from_code}/{to_code}"
AVAILABILITY_URL = "https://erail.in/_TrainsPair.aspx?from={from_code}&to={to_code}&date={date_str}"
AVL_API_URL      = "https://s.erail.in/getvalue"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://erail.in/",
}

DAY_COLUMNS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
CLASS_ORDER  = ["1A", "2A", "3A", "CC", "SL", "2S", "3E"]


# ── Parsing helpers ────────────────────────────────────────────────────────────

def _clean(v: str) -> str:
    v = v.strip().replace("\xa0", "").strip()
    if v in ("x", "", "Departed"):
        return "—"
    return v


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    lines = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if cells:
            lines.append("\t".join(c.get_text(" ", strip=True) for c in cells))
    for tag in soup.find_all(["h1", "h2", "h3", "p"]):
        if not tag.find("table"):
            text = tag.get_text(" ", strip=True)
            if text:
                lines.append(text)
    return "\n".join(lines)


def _parse_schedule(body_text: str) -> list[dict]:
    trains = []
    seen: set[str] = set()          # deduplicate by train number
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
        train_num = parts[0].strip()
        if train_num in seen:
            continue
        seen.add(train_num)
        try:
            day_values = parts[10:17] if len(parts) > 16 else []
            runs_on = [DAY_COLUMNS[i] for i, v in enumerate(day_values) if v.strip().upper() == "Y"]
            # If we couldn't read day columns, assume all days rather than
            # leaving empty (empty → build() defaults to all days anyway,
            # but explicit is safer and avoids the conditional in build)
            if not runs_on:
                runs_on = DAY_COLUMNS[:]
            avail = {}
            for ci, cls in enumerate(CLASS_ORDER):
                col = class_start + ci
                avail[cls] = _clean(parts[col]) if col < len(parts) else "—"
            classes = [cls for cls in CLASS_ORDER if avail[cls] != "—"]
            trains.append({
                "train_number": train_num,
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


# ── Availability value normaliser ──────────────────────────────────────────────

def _parse_avl_value(raw: str) -> str:
    """
    Convert s.erail.in cache values to the display format used elsewhere.
      GNWL15/WL4     → WL4
      RLWL10/WL10    → WL10
      AVL 32         → 32
      AVAILABLE 32   → 32
      NOT AVAILABLE  → NA
    """
    v = raw.strip()
    if not v or v in ("NOT AVAILABLE", "NOT_AVAILABLE", "TRAIN_NOTRUNNING"):
        return "NA"
    if v == "AVAILABLE":
        return "AVL"
    # Current status is after the slash: GNWL15/WL4
    if "/" in v:
        v = v.split("/")[-1].strip()
    # AVL 32 or AVAILABLE 32 → 32
    if v.upper().startswith("AVL") or v.upper().startswith("AVAILABLE"):
        n = re.sub(r'[A-Z]+\s*', '', v, flags=re.IGNORECASE).strip()
        return n if n else "AVL"
    # WL4, RLWL4, GNWL4 → WL4
    if "WL" in v.upper():
        m = re.search(r'WL(\d+)', v, re.IGNORECASE)
        return f"WL{m.group(1)}" if m else "WL"
    # RAC → R#
    if v.upper().startswith("RAC"):
        m = re.search(r'(\d+)', v)
        return f"R{m.group(1)}" if m else "RAC"
    return v


# ── Schedule scraper ───────────────────────────────────────────────────────────

async def _scrape_schedule_async(from_code: str, to_code: str) -> list[dict]:
    url = SCHEDULE_URL.format(from_code=from_code.upper(), to_code=to_code.upper())
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as c:
        r = await c.get(url)
    body = _html_to_text(r.text)
    return _parse_schedule(body)


# ── Availability scraper — s.erail.in batch API ────────────────────────────────

async def _scrape_availability_async(
    from_code: str,
    to_code:   str,
    dates:     list[str],       # ["YYYY-MM-DD", ...]
    progress_cb=None,
    concurrency: int = 10,
) -> dict:
    """
    1. Fetch the base _TrainsPair.aspx page for the first date to extract
       all data-avlkey templates (TRAINNO_FROM_TO_CLASS_QUOTA).
    2. For every date, POST all keys to s.erail.in/getvalue in parallel.
       Returns {iso_date: {train_number: {cls: value}}}.
    """
    results = {}
    total   = len(dates)
    done    = [0]
    sem     = asyncio.Semaphore(concurrency)

    first_dt = datetime.strptime(dates[0], "%Y-%m-%d")
    base_url = AVAILABILITY_URL.format(
        from_code=from_code.upper(), to_code=to_code.upper(),
        date_str=first_dt.strftime("%d-%b-%Y"),
    )

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=40) as client:
        # Load the base page once to extract key templates
        await client.get(SCHEDULE_URL.format(from_code=from_code.upper(), to_code=to_code.upper()))
        base_resp = await client.get(base_url)
        soup = BeautifulSoup(base_resp.text, "html.parser")
        all_keys = [
            a.get("data-avlkey") for a in soup.find_all(attrs={"data-avlkey": True})
            if not a.get("data-avlkey", "").endswith("_f")
        ]
        # Strip the date part (last segment) to get reusable templates
        key_templates = list(dict.fromkeys(
            "_".join(k.split("_")[:-1]) for k in all_keys
        ))

        if not key_templates:
            return {}

        async def fetch_one_date(iso_date: str):
            dt      = datetime.strptime(iso_date, "%Y-%m-%d")
            day_key = f"{dt.day}-{dt.month}"
            keys    = [f"{t}_{day_key}" for t in key_templates]
            batch   = "~".join(keys) + "~"
            payload = json.dumps({"Action": "AVL_Data", "Data": batch})

            async with sem:
                try:
                    resp = await client.post(
                        AVL_API_URL,
                        content=payload,
                        headers={**HEADERS,
                                 "Content-Type": "application/json",
                                 "Accept":       "application/json",
                                 "Referer":      "https://erail.in/"},
                        timeout=20,
                    )
                    data = resp.json().get("data", "")
                except Exception as e:
                    print(f"[http_scraper] {iso_date} error: {e}", file=sys.stderr)
                    data = ""

            # Strip leading count^AVL_Response~ header
            if "AVL_Response~" in data:
                data = data.split("AVL_Response~", 1)[1]

            # Parse key^value entries
            trains: dict[str, dict] = {}
            for entry in data.split("~"):
                if "^" not in entry:
                    continue
                key, raw_val = entry.split("^", 1)
                raw_val = raw_val.split("^")[0]   # strip trailing ^timestamp
                parts = key.split("_")
                if len(parts) < 4:
                    continue
                train_num = parts[0]
                cls       = parts[3]
                if cls not in CLASS_ORDER:
                    continue
                if train_num not in trains:
                    trains[train_num] = {c: "—" for c in CLASS_ORDER}
                trains[train_num][cls] = _parse_avl_value(raw_val)

            results[iso_date] = [
                {"train_number": num, "availability": avail}
                for num, avail in trains.items()
            ]
            done[0] += 1
            if progress_cb:
                try:
                    disp = dt.strftime("%d %b")
                    progress_cb(done[0], total, disp)
                except Exception:
                    pass

        await asyncio.gather(*[fetch_one_date(d) for d in dates])

    return results


# ── Public sync wrappers ───────────────────────────────────────────────────────

def scrape_schedule_http(from_code: str, to_code: str) -> list[dict]:
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(
                asyncio.run, _scrape_schedule_async(from_code, to_code)
            ).result(timeout=60)
    except Exception as e:
        print(f"[http_scraper] schedule error: {e}", file=sys.stderr)
        return []


def scrape_availability_http(
    from_code:   str,
    to_code:     str,
    dates:       list[str],
    progress_cb  = None,
    concurrency: int = 10,
) -> dict:
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(
                asyncio.run,
                _scrape_availability_async(from_code, to_code, dates, progress_cb, concurrency),
            ).result(timeout=120)
    except Exception as e:
        print(f"[http_scraper] availability error: {e}", file=sys.stderr)
        return {}


def is_viable(results: dict, dates: list[str], threshold: float = 0.4) -> bool:
    if not dates:
        return False
    non_empty = sum(1 for d in dates if results.get(d))
    return (non_empty / len(dates)) >= threshold
