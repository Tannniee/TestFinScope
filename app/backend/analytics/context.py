import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Dict, Any, Tuple

@dataclass(frozen=True)
class AnalyticsContext:
    """
    Canonical temporal and filter context for FinScope Analytics V2.
    Ensures every analytics module operates on identical time and scope boundaries.
    """
    as_of_month: str
    start_date: date
    end_date: date
    account_id: Optional[int]
    category_id: Optional[int]
    merchant_id: Optional[int]
    comparison_mode: str
    comparison_start: Optional[date]
    comparison_end: Optional[date]
    is_current_month: bool
    is_completed: bool
    max_day: int
    include_pending: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert context to a frontend-friendly dictionary with ISO date strings."""
        return {
            "as_of_month": self.as_of_month,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "account_id": self.account_id,
            "category_id": self.category_id,
            "merchant_id": self.merchant_id,
            "comparison_mode": self.comparison_mode,
            "comparison_start": self.comparison_start.isoformat() if self.comparison_start else None,
            "comparison_end": self.comparison_end.isoformat() if self.comparison_end else None,
            "is_current_month": self.is_current_month,
            "is_completed": self.is_completed,
            "max_day": self.max_day,
            "include_pending": self.include_pending,
            "period_label": self.format_period_label(),
            "comparison_label": self.format_comparison_label()
        }

    @property
    def period_label(self) -> str:
        return self.format_period_label()

    @property
    def comparison_label(self) -> str:
        return self.format_comparison_label()

    def format_period_label(self) -> str:
        month_name = calendar.month_name[self.start_date.month]
        if self.is_current_month:
            return f"{month_name} 1–{self.end_date.day}, {self.start_date.year} (MTD)"
        return f"{month_name} {self.start_date.year} (Full Month)"

    def format_comparison_label(self) -> str:
        if not self.comparison_start or not self.comparison_end:
            return "No comparison"
        comp_month_name = calendar.month_name[self.comparison_start.month]
        if self.comparison_mode == "previous_month_matched":
            return f"{comp_month_name} 1–{self.comparison_end.day}, {self.comparison_start.year} (Matched)"
        elif self.comparison_mode == "previous_month_full":
            return f"{comp_month_name} {self.comparison_start.year} (Full Month)"
        elif self.comparison_mode == "previous_year_same_period":
            return f"{comp_month_name} 1–{self.comparison_end.day}, {self.comparison_start.year}"
        return f"{self.comparison_start.isoformat()} to {self.comparison_end.isoformat()}"

    def sql_date_range(self) -> Tuple[str, str]:
        return self.start_date.isoformat(), self.end_date.isoformat()

    def comparison_sql_date_range(self) -> Optional[Tuple[str, str]]:
        if self.comparison_start and self.comparison_end:
            return self.comparison_start.isoformat(), self.comparison_end.isoformat()
        return None


def resolve_analytics_context(
    month: Optional[str] = None,
    account_id: Optional[int] = None,
    category_id: Optional[int] = None,
    merchant_id: Optional[int] = None,
    comparison_mode: Optional[str] = None,
    today: Optional[date] = None,
    include_pending: bool = False
) -> AnalyticsContext:
    """
    Resolves canonical temporal boundaries and comparison parameters.
    The backend owns time semantics to guarantee consistency across all modules.
    """
    ref_today = today or date.today()
    selected_month = month or ref_today.strftime("%Y-%m")

    try:
        year, m = map(int, selected_month.split("-"))
    except Exception:
        year, m = ref_today.year, ref_today.month
        selected_month = f"{year:04d}-{m:02d}"

    days_in_month = calendar.monthrange(year, m)[1]
    is_current = (selected_month == ref_today.strftime("%Y-%m"))

    if is_current:
        is_completed = False
        start_d = date(year, m, 1)
        end_d = min(ref_today, date(year, m, days_in_month))
        max_d = end_d.day
        resolved_comp_mode = comparison_mode or "previous_month_matched"
    else:
        is_completed = True
        start_d = date(year, m, 1)
        end_d = date(year, m, days_in_month)
        max_d = days_in_month
        resolved_comp_mode = comparison_mode or "previous_month_full"

    # Resolve comparison period
    if m == 1:
        prev_year, prev_m = year - 1, 12
    else:
        prev_year, prev_m = year, m - 1
    prev_days = calendar.monthrange(prev_year, prev_m)[1]

    if resolved_comp_mode == "previous_month_matched":
        matched_day = min(max_d, prev_days)
        comp_start = date(prev_year, prev_m, 1)
        comp_end = date(prev_year, prev_m, matched_day)
    elif resolved_comp_mode == "previous_month_full":
        comp_start = date(prev_year, prev_m, 1)
        comp_end = date(prev_year, prev_m, prev_days)
    elif resolved_comp_mode == "previous_year_same_period":
        py_year = year - 1
        py_days = calendar.monthrange(py_year, m)[1]
        matched_day = min(max_d, py_days)
        comp_start = date(py_year, m, 1)
        comp_end = date(py_year, m, matched_day)
    elif resolved_comp_mode == "previous_period":
        delta_days = (end_d - start_d).days + 1
        comp_end = start_d - timedelta(days=1)
        comp_start = comp_end - timedelta(days=delta_days - 1)
    else:
        # Default fallback
        if is_current:
            matched_day = min(max_d, prev_days)
            comp_start = date(prev_year, prev_m, 1)
            comp_end = date(prev_year, prev_m, matched_day)
        else:
            comp_start = date(prev_year, prev_m, 1)
            comp_end = date(prev_year, prev_m, prev_days)

    return AnalyticsContext(
        as_of_month=selected_month,
        start_date=start_d,
        end_date=end_d,
        account_id=account_id,
        category_id=category_id,
        merchant_id=merchant_id,
        comparison_mode=resolved_comp_mode,
        comparison_start=comp_start,
        comparison_end=comp_end,
        is_current_month=is_current,
        is_completed=is_completed,
        max_day=max_d,
        include_pending=include_pending
    )
