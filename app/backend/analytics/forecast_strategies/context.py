from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple


@dataclass(frozen=True)
class ForecastContext:
    """
    Immutable consolidated context representing point-in-time financial facts.
    Contains strictly separated accounting datasets for deterministic cashflows
    and pure non-recurring statistical spending estimators.
    """
    target_month: str  # YYYY-MM
    as_of_date: str    # YYYY-MM-DD
    account_id: Optional[int]

    elapsed_day: int
    remaining_days: int
    num_days: int
    remaining_calendar_dates: Tuple[str, ...]

    # Deterministic Actuals to Cutoff
    actual_expense_minor: int
    actual_income_minor: int
    actual_refund_minor: int
    actual_net_spend_to_date_minor: int

    # Behavioural Variable vs Recurring Breakdown to Cutoff
    actual_non_recurring_expense_minor: int
    actual_recurring_expense_minor: int

    # Known Scheduled Commitments (Cutoff + 1 through Month End)
    upcoming_recurring_expense_minor: int
    upcoming_recurring_income_minor: int

    # Pure Non-Recurring Historical Series
    hist_monthly_non_recurring_expense: Dict[str, int]  # YYYY-MM -> non_recurring_minor
    dense_daily_non_recurring_expense: Dict[str, int]   # YYYY-MM-DD -> non_recurring_minor (with 0s)

    # Historical Weekday Variable Rates
    weekday_rates: Dict[int, int]          # SQLite %w (0=Sun..6=Sat) -> minor rate
    weekday_sample_counts: Dict[int, int]  # SQLite %w -> sample occurrence count
    global_non_recurring_daily_rate: int

    # Category Breakdowns
    actual_cat_spends_net: Dict[int, int]
    actual_cat_non_recurring_expense: Dict[int, int]
    historical_cat_non_recurring_expense: Dict[int, int]
    cat_metadata: Dict[int, Dict[str, Any]]
    upcoming_recurring_by_cat: Dict[int, int]

    # History volume
    completed_months: int
    transaction_count: int

    # --------------------------------------------------------------------------
    # Backward Compatibility Properties & Helpers
    # --------------------------------------------------------------------------

    @property
    def actual_net_spend_to_date(self) -> int:
        return self.actual_net_spend_to_date_minor

    @property
    def actual_recurring_minor(self) -> int:
        return self.actual_recurring_expense_minor

    @property
    def upcoming_recurring_minor(self) -> int:
        return self.upcoming_recurring_expense_minor

    @property
    def dense_daily_non_recurring(self) -> Dict[str, int]:
        return self.dense_daily_non_recurring_expense

    @property
    def hist_monthly_spends(self) -> List[int]:
        return list(self.hist_monthly_non_recurring_expense.values())

    @property
    def weekday_avg_minor(self) -> Dict[int, int]:
        return self.weekday_rates

    @property
    def actual_wday_counts(self) -> Dict[int, int]:
        return self.weekday_sample_counts

    @property
    def actual_cat_spends(self) -> Dict[int, int]:
        return self.actual_cat_spends_net

    @property
    def upcoming_by_cat(self) -> Dict[int, int]:
        return self.upcoming_recurring_by_cat

    @property
    def year(self) -> int:
        return int(self.target_month.split("-")[0])

    @property
    def month(self) -> int:
        return int(self.target_month.split("-")[1])

    def get_complete_weekly_totals(self, max_weeks: int = 12) -> List[int]:
        """Extracts complete Monday-to-Sunday weekly totals via series utilities."""
        from app.backend.analytics.forecast_strategies.series import build_complete_calendar_weeks
        weeks = build_complete_calendar_weeks(self.dense_daily_non_recurring_expense)
        return weeks[-max_weeks:] if len(weeks) > max_weeks else weeks
