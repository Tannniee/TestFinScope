from datetime import date, datetime, timedelta
from typing import Dict, List


def generate_calendar_months(start_m: str, end_m: str) -> List[str]:
    """Generates continuous sequence of calendar months YYYY-MM from start_m to end_m inclusive."""
    sy, sm = map(int, start_m.split("-"))
    ey, em = map(int, end_m.split("-"))
    res = []
    cy, cm = sy, sm
    while (cy < ey) or (cy == ey and cm <= em):
        res.append(f"{cy:04d}-{cm:02d}")
        cm += 1
        if cm > 12:
            cm = 1
            cy += 1
    return res


def same_month_previous_year(target_month: str) -> str:
    """Returns the same calendar month in the previous year (e.g., '2026-09' -> '2025-09')."""
    y_str, m_str = target_month.split("-")
    return f"{int(y_str) - 1:04d}-{int(m_str):02d}"


def build_dense_daily_series(
    start_date: date,
    end_date: date,
    activity_map: Dict[str, int]
) -> Dict[str, int]:
    """
    Constructs an unbroken daily calendar series from start_date to end_date.
    Days with zero spending are explicitly populated with 0.
    """
    dense_series: Dict[str, int] = {}
    cur = start_date
    while cur <= end_date:
        d_str = cur.isoformat()
        dense_series[d_str] = activity_map.get(d_str, 0)
        cur += timedelta(days=1)
    return dense_series


def build_dense_monthly_series(
    start_month: str,
    end_month: str,
    monthly_map: Dict[str, int]
) -> Dict[str, int]:
    """
    Constructs an unbroken monthly calendar series from start_month to end_month inclusive.
    Months with zero spending are explicitly populated with 0.
    """
    dense_months: Dict[str, int] = {}
    for m in generate_calendar_months(start_month, end_month):
        dense_months[m] = monthly_map.get(m, 0)
    return dense_months


def build_complete_calendar_weeks(
    dense_daily_series: Dict[str, int]
) -> List[int]:
    """
    Extracts complete, contiguous Monday-to-Sunday calendar weeks from a dense daily series.
    Leading partial weeks (before the first Monday) and trailing partial weeks
    (after the last Sunday) are strictly discarded.
    Returns a list of integer weekly totals (one per complete Monday-Sunday week).
    """
    if not dense_daily_series or len(dense_daily_series) < 7:
        return []

    sorted_dates = sorted(dense_daily_series.keys())
    date_objs = [datetime.strptime(d, "%Y-%m-%d").date() for d in sorted_dates]

    # Find the index of the first Monday (weekday == 0)
    first_mon_idx = None
    for i, d in enumerate(date_objs):
        if d.weekday() == 0:
            first_mon_idx = i
            break

    if first_mon_idx is None:
        return []

    weekly_totals: List[int] = []
    idx = first_mon_idx
    # Group in consecutive 7-day blocks: Mon(0)..Sun(6)
    while idx + 6 < len(date_objs):
        # Verify block starts on Monday and ends on Sunday
        if date_objs[idx].weekday() == 0 and date_objs[idx + 6].weekday() == 6:
            # Also verify dates are strictly consecutive (7 days)
            if (date_objs[idx + 6] - date_objs[idx]).days == 6:
                week_sum = sum(dense_daily_series[date_objs[k].isoformat()] for k in range(idx, idx + 7))
                weekly_totals.append(week_sum)
                idx += 7
                continue
        idx += 1

    return weekly_totals
