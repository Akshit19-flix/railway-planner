"""
Standalone scraper worker — always run as a subprocess (clean event loop, no nest_asyncio).

Two modes:
  python scraper_worker.py schedule NDLS BCT
      → returns full train schedule (running days, times) as JSON array

  python scraper_worker.py availability NDLS BCT 2026-05-25
      → returns train availability for that specific date as JSON array
        (scrapes erail /_TrainsPair.aspx?from=NDLS&to=BCT&date=25-May-2026)
"""

import asyncio
import json
import re
import sys
import time
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

DAY_COLUMNS  = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
CLASS_ORDER  = ["1A", "2A", "3A", "CC", "SL", "2S", "3E"]

SCHEDULE_URL     = "https://erail.in/trains-between-stations/{from_code}/{to_code}"
AVAILABILITY_URL = "https://erail.in/_TrainsPair.aspx?from={from_code}&to={to_code}&date={date_str}"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_browser(pw):
    browser = pw.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
    )
    ctx.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
    )
    return browser, ctx


def _fetch_page(pw, url: str, wait: int = 15) -> str:
    browser, ctx = _make_browser(pw)
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        try:
            page.wait_for_load_state("networkidle", timeout=wait * 1000)
        except PwTimeout:
            pass
        time.sleep(2)
        return page.inner_text("body")
    except Exception as e:
        print(f"[worker] fetch error {url}: {e}", file=sys.stderr)
        return ""
    finally:
        browser.close()


def _clean(v: str) -> str:
    """Normalise an availability cell."""
    v = v.strip().replace("\xa0", "").strip()
    if v in ("x", "", "Departed"):
        return "—"
    return v


# ── Schedule scraper ───────────────────────────────────────────────────────────

def scrape_schedule(from_code: str, to_code: str) -> list[dict]:
    url = SCHEDULE_URL.format(from_code=from_code.upper(), to_code=to_code.upper())
    with sync_playwright() as pw:
        body = _fetch_page(pw, url)
    return _parse_schedule(body)


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
            runs_on = [
                DAY_COLUMNS[i] for i, v in enumerate(day_values)
                if v.strip().upper() == "Y"
            ]
            if not runs_on:
                runs_on = DAY_COLUMNS[:]
            avail: dict[str, str] = {}
            for ci, cls in enumerate(CLASS_ORDER):
                col = class_start + ci
                avail[cls] = _clean(parts[col]) if col < len(parts) else "—"

            classes = [cls for cls in CLASS_ORDER if avail[cls] != "—"]

            trains.append({
                "train_number":  train_num,
                "train_name":    parts[1].strip() if len(parts) > 1 else "",
                "from_station":  parts[2].strip() if len(parts) > 2 else "",
                "departure":     parts[3].strip() if len(parts) > 3 else "",
                "to_station":    parts[5].strip() if len(parts) > 5 else "",
                "arrival":       parts[6].strip() if len(parts) > 6 else "",
                "duration":      parts[8].strip() if len(parts) > 8 else "",
                "runs_on":       runs_on,
                "classes":       classes,
                "availability":  avail,
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


# ── Per-date availability scraper ──────────────────────────────────────────────

def scrape_availability(from_code: str, to_code: str, iso_date: str) -> list[dict]:
    """
    iso_date: 'YYYY-MM-DD'
    Navigates erail, uses JS to set DateFromTo, clicks Get Trains,
    then parses the resulting availability table.
    Returns list of {train_number, availability: {cls: value}}.
    """
    dt = datetime.strptime(iso_date, "%Y-%m-%d")
    year, month, day = dt.year, dt.month - 1, dt.day  # JS month is 0-indexed

    url = SCHEDULE_URL.format(from_code=from_code.upper(), to_code=to_code.upper())

    with sync_playwright() as pw:
        browser, ctx = _make_browser(pw)
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PwTimeout:
                pass
            time.sleep(2)

            # Set DateFromTo JS variable and update the date button display
            page.evaluate(f"""
                () => {{
                    if (typeof DateFromTo !== 'undefined') {{
                        DateFromTo = new Date({year}, {month}, {day});
                    }}
                    // Update the visible date button
                    var btns = document.querySelectorAll('input[type=button]');
                    for (var b of btns) {{
                        if (b.value && /-[A-Za-z]+-/.test(b.value)) {{
                            var d = new Date({year}, {month}, {day});
                            var months = ['Jan','Feb','Mar','Apr','May','Jun',
                                          'Jul','Aug','Sep','Oct','Nov','Dec'];
                            var days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
                            var dd = String(d.getDate()).padStart(2,'0');
                            var yy = String(d.getFullYear()).slice(-2);
                            b.value = dd + '-' + months[d.getMonth()] + '-' + yy + ' ' + days[d.getDay()];
                            break;
                        }}
                    }}
                }}
            """)
            time.sleep(0.5)

            # Click Get Trains
            get_btn = page.query_selector("#buttonFromTo, input[value='Get Trains']")
            if get_btn:
                get_btn.click()
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except PwTimeout:
                    pass
                time.sleep(2)

            body_text = page.inner_text("body")
        except Exception as e:
            print(f"[worker] availability error for {iso_date}: {e}", file=sys.stderr)
            body_text = ""
        finally:
            browser.close()

    return _parse_availability(body_text)


def _parse_availability(body_text: str) -> list[dict]:
    """Parse the erail table after a date change — same columns as schedule."""
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
            avail: dict[str, str] = {}
            for ci, cls in enumerate(CLASS_ORDER):
                col = class_start + ci
                avail[cls] = _clean(parts[col]) if col < len(parts) else "—"
            result.append({
                "train_number": parts[0].strip(),
                "availability": avail,
            })
        except (IndexError, ValueError):
            continue

    return result


# ── Batch availability scraper — page-pool architecture ────────────────────────
#
# Key insight from profiling:
#   - First page load (domcontentloaded + networkidle): ~22 s
#   - Subsequent date change on an ALREADY LOADED page: ~13 s
#   - Creating a new page/context per date: wastes 22 s × N reloads
#
# Solution: pre-load POOL_SIZE pages once, then feed dates through them as a
# queue.  Each page loads the URL exactly once, then cycles through dates by
# JS-injecting the date and clicking "Get Trains" — no full reload needed.
# POOL_SIZE=3 → 30 dates / 3 workers = 10 cycles × ~13 s = ~130 s total
# vs old approach: 30 × (22+13) s ÷ 4 concurrency = ~263 s

async def _scrape_batch_async(from_code: str, to_code: str, dates: list[str]) -> dict:
    from playwright.async_api import async_playwright, TimeoutError as PwAsyncTimeout

    POOL_SIZE = 4
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    url     = SCHEDULE_URL.format(from_code=from_code.upper(), to_code=to_code.upper())
    total   = len(dates)
    results = {}
    done    = [0]

    async def _set_date_and_fetch(page, iso_date: str) -> list[dict]:
        """Change date on an already-loaded page and return parsed availability."""
        dt    = datetime.strptime(iso_date, "%Y-%m-%d")
        year  = dt.year
        month = dt.month - 1   # JS months are 0-indexed
        day   = dt.day

        await page.evaluate(f"""() => {{
            if (typeof DateFromTo !== 'undefined') {{
                DateFromTo = new Date({year}, {month}, {day});
            }}
            var btns = document.querySelectorAll('input[type=button]');
            for (var b of btns) {{
                if (b.value && /-[A-Za-z]+-/.test(b.value)) {{
                    var d = new Date({year}, {month}, {day});
                    var months = ['Jan','Feb','Mar','Apr','May','Jun',
                                  'Jul','Aug','Sep','Oct','Nov','Dec'];
                    var days2  = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
                    var dd = String(d.getDate()).padStart(2,'0');
                    var yy = String(d.getFullYear()).slice(-2);
                    b.value = dd+'-'+months[d.getMonth()]+'-'+yy+' '+days2[d.getDay()];
                    break;
                }}
            }}
        }}""")
        await asyncio.sleep(0.3)

        btn = await page.query_selector("#buttonFromTo, input[value='Get Trains']")
        if not btn:
            return []

        await btn.click()

        # erail never reaches true networkidle (background ad scripts keep firing),
        # so wait_for_load_state("networkidle") always burns its full timeout.
        # Instead: poll until a train-number cell appears, cap at 8s.
        for _ in range(16):
            await asyncio.sleep(0.5)
            ready = await page.evaluate("""() => {
                var rows = document.querySelectorAll('table tr');
                for (var r of rows) {
                    var cells = r.querySelectorAll('td');
                    if (cells.length > 0 && /^\\d{4,5}$/.test(cells[0].innerText.trim()))
                        return true;
                }
                return false;
            }""")
            if ready:
                break

        body_text = await page.inner_text("body")
        return _parse_availability(body_text)

    async def worker(page, date_queue: asyncio.Queue):
        """Pull dates off the queue and scrape each one on the pre-loaded page."""
        while True:
            try:
                iso_date = date_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                parsed = await _set_date_and_fetch(page, iso_date)
            except Exception as e:
                print(f"[batch] error {iso_date}: {e}", file=sys.stderr)
                parsed = []
            results[iso_date] = parsed
            done[0] += 1
            dt_disp = datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d %b")
            print(f"PROGRESS:{done[0]}/{total}:{dt_disp}", file=sys.stderr, flush=True)
            date_queue.task_done()

    async def make_page(browser) -> object:
        """Create a context + page and load the schedule URL once."""
        ctx = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 900},
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        # Poll for train rows instead of waiting for networkidle (which never fires on erail)
        for _ in range(20):
            await asyncio.sleep(0.5)
            ready = await page.evaluate("""() => {
                var rows = document.querySelectorAll('table tr');
                for (var r of rows) {
                    var cells = r.querySelectorAll('td');
                    if (cells.length > 0 && /^\\d{4,5}$/.test(cells[0].innerText.trim()))
                        return true;
                }
                return false;
            }""")
            if ready:
                break
        return page

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )

        # Load all pool pages concurrently (parallel initial loads)
        pages = await asyncio.gather(*[make_page(browser) for _ in range(POOL_SIZE)])

        # Fill the work queue
        queue: asyncio.Queue = asyncio.Queue()
        for d in dates:
            await queue.put(d)

        # Run one worker coroutine per page — they pull from the shared queue
        await asyncio.gather(*[worker(p, queue) for p in pages])

        await browser.close()

    return results


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python scraper_worker.py <schedule|availability> FROM TO [YYYY-MM-DD]",
              file=sys.stderr)
        sys.exit(1)

    mode       = sys.argv[1]
    from_code  = sys.argv[2]
    to_code    = sys.argv[3]

    if mode == "schedule":
        result = scrape_schedule(from_code, to_code)
    elif mode == "availability":
        if len(sys.argv) < 5:
            print("availability mode requires a date (YYYY-MM-DD)", file=sys.stderr)
            sys.exit(1)
        result = scrape_availability(from_code, to_code, sys.argv[4])
    elif mode == "batch_availability":
        if len(sys.argv) < 5:
            print("batch_availability requires at least one date", file=sys.stderr)
            sys.exit(1)
        dates = sys.argv[4:]
        result = asyncio.run(_scrape_batch_async(from_code, to_code, dates))
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)

    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
