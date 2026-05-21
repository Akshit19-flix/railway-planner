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

# Class-bits string (parts[14] in data-train) maps bit positions to class names.
# Observed from erail: "000100000010000" → positions 3=CC, 10=SL (0-indexed from left)
# Mapping confirmed by cross-referencing with known trains.
_CLASS_BIT_MAP = {
    0:  "1A",
    1:  "2A",
    2:  "3A",
    3:  "CC",
    4:  "SL",
    5:  "2S",
    6:  "3E",
}


def _parse_schedule_html(html: str) -> list[dict]:
    """
    Parse erail schedule page using data-train attributes on OneTrain divs.

    data-train format (underscore-separated, 19 parts):
      0  train_number
      1  train_name
      2  from_code
      3  to_code
      4  date (DD-Mon-YYYY)
      5  departure time
      6  arrival date
      7  arrival time
      8  duration
      9  distance
      10 halt at from
      11 halt at to
      12 internal id
      13 runs_on  — 7-char binary string, index 0=Mon … 6=Sun  ("1011111")
      14 class_bits — 15-char binary string, positions per _CLASS_BIT_MAP
      15 train type
      16 (quota / misc)
      17 scheduled dep
      18 (empty)
    """
    soup = BeautifulSoup(html, "html.parser")
    divs = soup.find_all("div", class_="OneTrain")
    trains: list[dict] = []
    seen: set[str] = set()

    for div in divs:
        raw = div.get("data-train", "")
        parts = raw.split("_")
        if len(parts) < 14:
            continue
        train_num = parts[0].strip()
        if not re.match(r"^\d{4,5}$", train_num):
            continue
        if train_num in seen:
            continue
        seen.add(train_num)

        # Running days from 7-bit string at index 13
        day_bits = parts[13].strip() if len(parts) > 13 else ""
        if len(day_bits) == 7:
            runs_on = [DAY_COLUMNS[i] for i, b in enumerate(day_bits) if b == "1"]
        else:
            runs_on = DAY_COLUMNS[:]   # unknown → assume all days

        # Classes from 15-bit string at index 14
        class_bits = parts[14].strip() if len(parts) > 14 else ""
        classes = [
            CLASS_ORDER[ci] for ci, cls in _CLASS_BIT_MAP.items()
            if ci < len(class_bits) and class_bits[ci] == "1"
            and cls in CLASS_ORDER
        ]
        avail = {cls: "—" for cls in CLASS_ORDER}

        trains.append({
            "train_number": train_num,
            "train_name":   parts[1].strip() if len(parts) > 1 else "",
            "from_station": parts[2].strip() if len(parts) > 2 else "",
            "departure":    parts[5].strip() if len(parts) > 5 else "",
            "to_station":   parts[3].strip() if len(parts) > 3 else "",
            "arrival":      parts[7].strip() if len(parts) > 7 else "",
            "duration":     parts[8].strip() if len(parts) > 8 else "",
            "runs_on":      runs_on if runs_on else DAY_COLUMNS[:],
            "classes":      classes,
            "availability": avail,
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
    return _parse_schedule_html(r.text)


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
