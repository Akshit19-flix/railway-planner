"""
Aggregate scraped train data into date-wise, weekly, weekday, and heatmap structures.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from scraper import TrainInfo, CLASS_ORDER


def _avail_pressure(val: str) -> Optional[float]:
    """
    Categorical load score 0.0–1.0 (1 = fully booked).
    None = class not on this train (excluded from all averages).

    Bands:
      50+ seats  → 0.0  (comfortable — green)
      10–49      → 0.3  (filling up — light green)
      1–9        → 0.6  (very limited — yellow)
      RAC        → 0.8  (waitlist-adjacent, likely confirms — amber)
      Pooled     → 0.75
      WL / NA    → 1.0  (no confirmed seat — red)
    """
    if val in ("—", "", None, "None"):
        return None
    s = str(val).strip()
    if s == "AVL":
        return 0.0
    if s == "NA" or s.startswith("WL"):
        return 1.0
    if s.startswith("R"):    # RAC
        return 0.8
    if s.startswith("P"):    # Pooled quota
        return 0.75
    try:
        n = int(s)
        if n >= 50:  return 0.0
        if n >= 10:  return 0.3
        if n >= 1:   return 0.6
        return 1.0
    except ValueError:
        return None

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass
class DaySummary:
    date:       date
    weekday:    str
    week_number: int
    trains:     list[TrainInfo] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.trains)


@dataclass
class AggregatedResults:
    from_code:  str
    to_code:    str
    from_name:  str
    to_name:    str
    start_date: date
    end_date:   date

    date_wise:  dict[date, DaySummary] = field(default_factory=dict)

    # Filled in by merge_availability()
    # avail_by_date[date][train_number][class] = "35" / "NA" / "R7" etc.
    avail_by_date: dict[date, dict[str, dict[str,str]]] = field(default_factory=dict)

    def build(self, trains: list[TrainInfo]) -> None:
        """Expand each train across dates where its running day matches."""
        week_offset: dict[int, int] = {}
        week_counter = 1
        cur = self.start_date
        while cur <= self.end_date:
            iso_week = cur.isocalendar()[1]
            if iso_week not in week_offset:
                week_offset[iso_week] = week_counter
                week_counter += 1
            self.date_wise[cur] = DaySummary(
                date=cur,
                weekday=cur.strftime("%a"),
                week_number=week_offset[iso_week],
            )
            cur += timedelta(days=1)

        # Deduplicate incoming train list by train number before expanding
        seen_nums: set[str] = set()
        unique_trains: list[TrainInfo] = []
        for train in trains:
            if train.train_number not in seen_nums:
                seen_nums.add(train.train_number)
                unique_trains.append(train)

        for train in unique_trains:
            running = set(train.runs_on) if train.runs_on else set(WEEKDAY_NAMES)
            for d, summary in self.date_wise.items():
                if summary.weekday in running:
                    summary.trains.append(TrainInfo(
                        train_number=train.train_number,
                        train_name=train.train_name,
                        from_station=train.from_station,
                        departure=train.departure,
                        to_station=train.to_station,
                        arrival=train.arrival,
                        duration=train.duration,
                        runs_on=train.runs_on,
                        classes=train.classes,
                        availability=train.availability,
                        date=d,
                    ))

    def merge_availability(
        self,
        avail_by_date: dict[date, dict[str, dict[str,str]]]
    ) -> None:
        """
        Overwrite each train's availability with per-date scraped data.
        avail_by_date[date][train_number][class] = string
        """
        self.avail_by_date = avail_by_date
        for d, summary in self.date_wise.items():
            date_avail = avail_by_date.get(d, {})
            for t in summary.trains:
                if t.train_number in date_avail:
                    t.availability = date_avail[t.train_number]

    # ── Summaries ────────────────────────────────────────────────────────────

    def weekly_summary(self) -> list[dict]:
        weeks: dict[int, dict] = defaultdict(lambda: {
            "week": 0, "total": 0, "date_range": "",
            **{d: 0 for d in WEEKDAY_NAMES}
        })
        week_dates: dict[int, list[date]] = defaultdict(list)
        for d, s in self.date_wise.items():
            w = s.week_number
            weeks[w]["week"] = w
            weeks[w][s.weekday] += s.count
            weeks[w]["total"] += s.count
            week_dates[w].append(d)
        for w, dates in week_dates.items():
            dates.sort()
            weeks[w]["date_range"] = (
                f"{dates[0].strftime('%d %b')} – {dates[-1].strftime('%d %b')}"
            )
        return sorted(weeks.values(), key=lambda x: x["week"])

    def weekday_totals(self) -> dict[str, int]:
        totals = {d: 0 for d in WEEKDAY_NAMES}
        for s in self.date_wise.values():
            totals[s.weekday] += s.count
        return totals

    def unique_trains(self) -> list[dict]:
        seen: dict[str, dict] = {}
        for s in self.date_wise.values():
            for t in s.trains:
                if t.train_number not in seen:
                    row = {
                        "Train No.":  t.train_number,
                        "Train Name": t.train_name,
                        "From":       t.from_station,
                        "Departure":  t.departure,
                        "To":         t.to_station,
                        "Arrival":    t.arrival,
                        "Duration":   t.duration,
                        "Runs On":    ", ".join(t.runs_on) if t.runs_on else "Daily",
                    }
                    for cls in CLASS_ORDER:
                        row[cls] = t.availability.get(cls, "—")
                    seen[t.train_number] = row
        return sorted(seen.values(), key=lambda x: x["Train No."])

    # ── Heatmap builders ─────────────────────────────────────────────────────

    def train_count_heatmap(self) -> dict:
        """
        Returns a pivot suitable for a heatmap:
          rows = weekday (Mon–Sun), cols = week number
          values = number of trains running
        """
        dates = sorted(self.date_wise.keys())
        weeks = sorted({self.date_wise[d].week_number for d in dates})

        # {weekday: {week_number: count}}
        matrix: dict[str, dict[int, int]] = {
            day: {w: 0 for w in weeks} for day in WEEKDAY_NAMES
        }
        week_labels: dict[int, str] = {}
        for d, s in self.date_wise.items():
            matrix[s.weekday][s.week_number] = s.count
            if s.week_number not in week_labels:
                week_labels[s.week_number] = d.strftime("%d %b")

        return {"matrix": matrix, "weeks": weeks, "week_labels": week_labels}

    def availability_heatmap(self, cls: str) -> dict:
        """
        Returns a pivot for seat availability of a given class:
          rows = train (number + name), cols = date
          cell = numeric seats (None if train doesn't run / class missing)
        """
        dates = sorted(self.date_wise.keys())
        train_keys: list[tuple[str,str]] = []  # (number, name)
        seen_nums: set[str] = set()
        for d in dates:
            for t in self.date_wise[d].trains:
                if t.train_number not in seen_nums:
                    seen_nums.add(t.train_number)
                    train_keys.append((t.train_number, t.train_name))
        train_keys.sort(key=lambda x: x[0])

        # Build matrix
        matrix: dict[str, dict[str, Optional[str]]] = {}
        for num, name in train_keys:
            label = f"{num} {name}"
            matrix[label] = {}
            for d in dates:
                col = d.strftime("%d %b")
                s = self.date_wise[d]
                match = next((t for t in s.trains if t.train_number == num), None)
                if match is None:
                    matrix[label][col] = None        # doesn't run this day
                else:
                    matrix[label][col] = match.availability.get(cls, "—")

        date_labels = [d.strftime("%d %b") for d in dates]
        return {"matrix": matrix, "train_keys": train_keys, "date_labels": date_labels}

    def combined_weekday_analysis(self) -> list[dict]:
        """
        Per-weekday: avg daily trains + avg occupancy % + demand level.
        Demand is occupancy-driven when data is available, else relative train count.
        """
        wd_counts: dict[str, list[int]] = {d: [] for d in WEEKDAY_NAMES}
        wd_pressure: dict[str, list[float]] = {d: [] for d in WEEKDAY_NAMES}

        for d, s in self.date_wise.items():
            wd_counts[s.weekday].append(s.count)
            for t in s.trains:
                for cls in CLASS_ORDER:
                    p = _avail_pressure(t.availability.get(cls))
                    if p is not None:
                        wd_pressure[s.weekday].append(p)

        all_totals = [sum(wd_counts[d]) for d in WEEKDAY_NAMES if wd_counts[d]]
        max_total = max(all_totals) if all_totals else 1

        rows = []
        for day in WEEKDAY_NAMES:
            counts = wd_counts[day]
            pressures = wd_pressure[day]
            avg_trains = round(sum(counts) / len(counts), 1) if counts else 0.0
            avg_occ = round(sum(pressures) / len(pressures) * 100) if pressures else None

            if avg_occ is not None:
                demand = "High" if avg_occ >= 70 else "Medium" if avg_occ >= 40 else "Low"
            else:
                total = sum(counts)
                demand = "High" if total >= max_total * 0.8 else "Medium" if total >= max_total * 0.5 else "Low"

            rows.append({
                "day":            day,
                "avg_trains":     avg_trains,
                "avg_occupancy":  avg_occ,
                "demand_level":   demand,
            })
        return rows

    def weekly_demand_analysis(self) -> list[dict]:
        """
        Week-by-week: total trains + avg occupancy % + demand level.
        """
        weeks: dict[int, dict] = {}
        week_pressures: dict[int, list[float]] = {}

        for d, s in self.date_wise.items():
            w = s.week_number
            if w not in weeks:
                weeks[w] = {"week": w, "total_trains": 0, "dates": []}
                week_pressures[w] = []
            weeks[w]["total_trains"] += s.count
            weeks[w]["dates"].append(d)
            for t in s.trains:
                for cls in CLASS_ORDER:
                    p = _avail_pressure(t.availability.get(cls))
                    if p is not None:
                        week_pressures[w].append(p)

        rows = []
        for w in sorted(weeks):
            dates = sorted(weeks[w]["dates"])
            pressures = week_pressures[w]
            avg_occ = round(sum(pressures) / len(pressures) * 100) if pressures else None
            demand = (
                "High"   if avg_occ is not None and avg_occ >= 70 else
                "Medium" if avg_occ is not None and avg_occ >= 40 else
                "Low"    if avg_occ is not None else "—"
            )
            rows.append({
                "week":         w,
                "date_range":   f"{dates[0].strftime('%d %b')} – {dates[-1].strftime('%d %b')}",
                "total_trains": weeks[w]["total_trains"],
                "avg_occupancy": avg_occ,
                "demand_level": demand,
            })
        return rows

    def bus_suggestions(self, classes: Optional[list[str]] = None) -> dict:
        """
        Analyse train pressure across the date range and return bus deployment suggestions.

        Returns:
          {
            "weekday_pressure": {day: avg_pressure 0-1},  # averaged across all trains & classes
            "high_demand_dates": [(date, pressure, num_trains)],  # top dates
            "suggestions": [str],   # plain-English recommendations
            "has_avail_data": bool,
          }
        """
        check_classes = classes or CLASS_ORDER

        # Pressure per weekday (list of float values)
        wd_pressure: dict[str, list[float]] = {d: [] for d in WEEKDAY_NAMES}
        # Pressure per date
        date_pressure: dict[date, list[float]] = {}

        for d, s in self.date_wise.items():
            dp: list[float] = []
            for t in s.trains:
                for cls in check_classes:
                    val = t.availability.get(cls)
                    p = _avail_pressure(val)
                    if p is not None:
                        dp.append(p)
                        wd_pressure[s.weekday].append(p)
            if dp:
                date_pressure[d] = dp

        has_avail_data = bool(date_pressure)

        # Average weekday pressure
        weekday_avg: dict[str, Optional[float]] = {}
        for day in WEEKDAY_NAMES:
            vals = wd_pressure[day]
            weekday_avg[day] = round(sum(vals) / len(vals), 3) if vals else None

        # Top 5 high-demand dates
        date_avg = {
            d: round(sum(v) / len(v), 3)
            for d, v in date_pressure.items()
        }
        high_demand = sorted(date_avg.items(), key=lambda x: -x[1])[:5]
        high_demand_dates = [
            (d, p, self.date_wise[d].count) for d, p in high_demand
        ]

        # Generate plain-English suggestions
        suggestions: list[str] = []
        if not has_avail_data:
            suggestions.append(
                "Enable 'Fetch real-time availability' to get personalised bus suggestions."
            )
        else:
            sorted_days = sorted(
                [(d, p) for d, p in weekday_avg.items() if p is not None],
                key=lambda x: -x[1],
            )
            high_days  = [d for d, p in sorted_days if p >= 0.70]
            med_days   = [d for d, p in sorted_days if 0.40 <= p < 0.70]
            light_days = [d for d, p in sorted_days if p < 0.40]

            if high_days:
                suggestions.append(
                    f"**High demand ({', '.join(high_days)}):** Trains are heavily booked. "
                    "Deploy extra buses — consider +2 buses per high-demand departure slot."
                )
            if med_days:
                suggestions.append(
                    f"**Moderate demand ({', '.join(med_days)}):** Some trains have limited seats. "
                    "Maintain normal bus frequency; add 1 supplementary bus if bookings pick up."
                )
            if light_days:
                suggestions.append(
                    f"**Low demand ({', '.join(light_days)}):** Trains have good availability. "
                    "Standard bus schedule is sufficient; monitor for spikes closer to travel date."
                )
            if high_demand_dates:
                peak_strs = [
                    f"{d.strftime('%d %b')} ({int(p*100)}% full)"
                    for d, p, _ in high_demand_dates[:3]
                ]
                suggestions.append(
                    f"**Peak dates:** {', '.join(peak_strs)} — ensure bus capacity is maximised."
                )

        return {
            "weekday_pressure": weekday_avg,
            "high_demand_dates": high_demand_dates,
            "suggestions": suggestions,
            "has_avail_data": has_avail_data,
        }

    def weekday_availability_summary(self, cls: str) -> dict[str, dict]:
        """
        For each weekday, compute:
          avg_seats, min_seats, max_seats across all trains and dates on that day.
        Only counts cells that are real numbers (ignores NA, R#, P#, —).
        """
        buckets: dict[str, list[int]] = {d: [] for d in WEEKDAY_NAMES}
        for d, s in self.date_wise.items():
            for t in s.trains:
                val = t.availability.get(cls, "—")
                try:
                    buckets[s.weekday].append(int(val))
                except (ValueError, TypeError):
                    pass
        out: dict[str, dict] = {}
        for day in WEEKDAY_NAMES:
            vals = buckets[day]
            out[day] = {
                "avg":   round(sum(vals) / len(vals)) if vals else None,
                "min":   min(vals) if vals else None,
                "max":   max(vals) if vals else None,
                "count": len(vals),
            }
        return out
