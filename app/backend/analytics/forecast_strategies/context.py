from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any


@dataclass(frozen=True)
class ForecastContext:
    """
    Immutable consolidated context passed into all statistical forecast strategies.
    Centralizes precomputed actuals, recurring cashflows, dense series, and historical metadata.
    """
    target_month: str  # YYYY-MM
    as_of_date: Optional[str]  # YYYY-MM-DD
    account_id: Optional[int]
    elapsed_day: int
    remaining_days: int
    num_days: int

    actual_expense_minor: int
    actual_income_minor: int
    actual_refund_minor: int
    actual_net_spend_to_date: int

    actual_recurring_minor: int
    upcoming_recurring_minor: int
    upcoming_recurring_income_minor: int

    actual_cat_spends: Dict[int, int]
    cat_metadata: Dict[int, Dict[str, Any]]
    upcoming_by_cat: Dict[int, int]

    completed_months: int
    tx_count: int
    hist_monthly_spends: List[int]

    # Dense daily non-recurring expense series: YYYY-MM-DD -> daily_spend_minor (includes 0s)
    dense_daily_non_recurring: Dict[str, int]

    # Historical weekday rates
    actual_wday_counts: Dict[int, int]
    weekday_avg_minor: Dict[int, int]
    weekday_income_avg: Dict[int, int]

    replay_mode: bool = False
    forced_method: Optional[str] = None

    @property
    def year(self) -> int:
        return int(self.target_month.split("-")[0])

    @property
    def month(self) -> int:
        return int(self.target_month.split("-")[1])

    def get_complete_weekly_totals(self, max_weeks: int = 12) -> List[int]:
        """
        Extracts contiguous non-overlapping 7-day calendar weeks from the dense daily series,
        ending on the day immediately before the target month (or cutoff), and sums each 7-day block.
        Only complete 7-day weeks are included.
        """
        if not self.dense_daily_non_recurring:
            return []

        sorted_dates = sorted(self.dense_daily_non_recurring.keys())
        if len(sorted_dates) < 7:
            return []

        weekly_totals: List[int] = []
        # Group backwards from the most recent date in blocks of 7
        total_days = len(sorted_dates)
        num_weeks = min(max_weeks, total_days // 7)

        for w in range(num_weeks):
            end_idx = total_days - (w * 7)
            start_idx = end_idx - 7
            week_slice = sorted_dates[start_idx:end_idx]
            week_sum = sum(self.dense_daily_non_recurring[d] for d in week_slice)
            weekly_totals.append(week_sum)

        return weekly_totals
