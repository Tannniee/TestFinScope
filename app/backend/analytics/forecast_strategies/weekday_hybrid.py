from datetime import date, datetime
from typing import Dict, Any
from app.backend.analytics.forecast_strategies.base import ForecastStrategy, ForecastEstimate
from app.backend.analytics.forecast_strategies.context import ForecastContext
from app.backend.analytics.forecast_strategies.config import FORECAST_CONFIG


class WeekdayHybridStrategy(ForecastStrategy):
    """
    Weekday Hybrid Strategy (F108-03):
    Projects remaining variable expense using day-of-week historical spending patterns.
    Sparse weekdays fall back to the global non-recurring daily rate, avoiding zero forecasts
    and preventing recurring actual contamination.
    """
    id = "weekday_hybrid"
    name = "FinScope Hybrid"
    description = "Projects remaining spend using calendar weekday rates and known recurring commitments."

    def is_eligible(self, context: ForecastContext) -> bool:
        # Requires at least 2 complete calendar months and usable daily non-recurring history
        has_months = context.completed_months >= 2
        has_history = sum(context.weekday_sample_counts.values()) >= 7 or len(context.dense_daily_non_recurring_expense) >= 14
        return has_months and has_history and context.remaining_days >= 0

    def predict(self, context: ForecastContext) -> ForecastEstimate:
        remaining_variable_minor = 0
        wday_applied_rates: Dict[int, int] = {}

        for d_str in context.remaining_calendar_dates:
            day_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
            sqlite_w = (day_obj.weekday() + 1) % 7  # 0=Sunday, 1=Monday, ..., 6=Saturday

            # Use weekday rate if sufficient samples exist, otherwise global daily rate
            if context.weekday_sample_counts.get(sqlite_w, 0) >= FORECAST_CONFIG.weekday_min_samples_per_day:
                rate = context.weekday_rates.get(sqlite_w, 0)
            else:
                rate = context.global_non_recurring_daily_rate

            wday_applied_rates[sqlite_w] = rate
            remaining_variable_minor += rate

        diagnostics: Dict[str, Any] = {
            "weekday_avg_minor": context.weekday_rates,
            "weekday_sample_counts": context.weekday_sample_counts,
            "global_non_recurring_daily_rate": context.global_non_recurring_daily_rate,
            "applied_rates_sample": wday_applied_rates,
            "remaining_days": context.remaining_days,
            "completed_months": context.completed_months
        }

        explanation = self.explain(context)

        return ForecastEstimate(
            model_id=self.id,
            method_name="FinScope Hybrid (Actual + Scheduled Recurring + Robust Weekday Variable)",
            remaining_variable_minor=max(0, remaining_variable_minor),
            explanation=explanation,
            diagnostics=diagnostics
        )

    def explain(self, context: ForecastContext) -> str:
        if context.completed_months >= 12:
            return f"Long history available ({context.completed_months} complete months); weekday hybrid selected"
        if context.completed_months >= 6:
            return f"Established history ({context.completed_months} complete months); using weekday hybrid"
        return f"Weekday-aware non-recurring spending pattern ({context.completed_months} complete months)"
