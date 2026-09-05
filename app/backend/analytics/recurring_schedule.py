"""
Central Recurring Schedule & Occurrence Engine for FinScope (v1.0.6).
Provides deterministic point-in-time occurrence generation shared across:
- ForecastingEngine (upcoming recurring commitments)
- RecurringService (upcoming bills timeline)
"""

import calendar
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any


def generate_occurrences(
    next_due_date: Optional[str],
    frequency: str,
    start_date: date,
    end_date: date
) -> List[date]:
    """
    Expands a recurring rule into occurrences strictly falling within:
    start_date < occurrence_date <= end_date.
    Frequencies supported: weekly, fortnightly, monthly, quarterly, yearly.
    """
    if not next_due_date:
        return []
    try:
        cur_due = datetime.strptime(str(next_due_date)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return []

    freq = (frequency or "monthly").strip().casefold()

    # If the due date is already beyond end_date, no occurrences can fall in the window
    if cur_due > end_date:
        return []

    def advance_date(d: date, step_idx: int) -> date:
        if freq in ("weekly", "week"):
            return d + timedelta(days=7 * step_idx)
        elif freq in ("fortnightly", "biweekly", "bi-weekly"):
            return d + timedelta(days=14 * step_idx)
        elif freq in ("monthly", "month"):
            y = d.year + (d.month - 1 + step_idx) // 12
            m = (d.month - 1 + step_idx) % 12 + 1
            max_d = calendar.monthrange(y, m)[1]
            return date(y, m, min(d.day, max_d))
        elif freq in ("quarterly", "quarter"):
            step = step_idx * 3
            y = d.year + (d.month - 1 + step) // 12
            m = (d.month - 1 + step) % 12 + 1
            max_d = calendar.monthrange(y, m)[1]
            return date(y, m, min(d.day, max_d))
        elif freq in ("yearly", "annual", "annually"):
            y = d.year + step_idx
            max_d = calendar.monthrange(y, d.month)[1]
            return date(y, d.month, min(d.day, max_d))
        else:
            # Default monthly
            y = d.year + (d.month - 1 + step_idx) // 12
            m = (d.month - 1 + step_idx) % 12 + 1
            max_d = calendar.monthrange(y, m)[1]
            return date(y, m, min(d.day, max_d))

    occurrences: List[date] = []
    step = 0
    while True:
        occ = advance_date(cur_due, step)
        if occ > end_date:
            break
        if occ > start_date:
            occurrences.append(occ)
        step += 1
        if step > 500:
            break

    return occurrences


def get_month_window(target_month: str, as_of_date: Optional[str] = None) -> tuple[date, date, int, int]:
    """
    Computes (window_start, window_end, elapsed_day, total_days) for `target_month` ('YYYY-MM').
    Strictly isolates occurrences to those after the current elapsed cutoff up to month-end.
    """
    year, m_int = map(int, target_month.split("-"))
    total_days = calendar.monthrange(year, m_int)[1]

    if as_of_date:
        cur_dt = datetime.strptime(as_of_date[:10], "%Y-%m-%d").date()
        if cur_dt.year == year and cur_dt.month == m_int:
            elapsed_day = min(total_days, max(1, cur_dt.day))
            window_start = cur_dt
        elif cur_dt < date(year, m_int, 1):
            elapsed_day = 0
            window_start = date(year, m_int, 1) - timedelta(days=1)
        else:
            elapsed_day = total_days
            window_start = date(year, m_int, total_days)
    else:
        elapsed_day = min(15, total_days)
        window_start = date(year, m_int, elapsed_day)

    window_end = date(year, m_int, total_days)
    return (window_start, window_end, elapsed_day, total_days)
