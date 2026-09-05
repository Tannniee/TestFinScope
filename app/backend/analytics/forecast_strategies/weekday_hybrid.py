from datetime import date
from typing import Dict, Any
from app.backend.analytics.forecast_strategies.base import ForecastStrategy, ForecastEstimate
from app.backend.analytics.forecast_strategies.context import ForecastContext


class WeekdayHybridStrategy(ForecastStrategy):
    """
    Weekday Hybrid Strategy (FinScope Hybrid):
    Projects remaining variable expense using day-of-week historical spending patterns
    (median daily rate blended with MAD-capped mean).
    """
    id = "weekday_hybrid"
    name = "FinScope Hybrid"
    description = "Projects remaining spend using calendar weekday rates and known recurring commitments."

    def is_eligible(self, context: ForecastContext) -> bool:
        # Eligible when there is historical weekday data or current month activity
        return context.completed_months >= 2 or sum(context.weekday_avg_minor.values()) > 0 or context.elapsed_day > 0

    def predict(self, context: ForecastContext) -> ForecastEstimate:
        wday_rates = dict(context.weekday_avg_minor)

        # Fallback if historical weekday rates are completely 0
        if sum(wday_rates.values()) == 0 and context.elapsed_day > 0:
            daily_pace = context.actual_net_spend_to_date // context.elapsed_day
            for w in range(7):
                wday_rates[w] = daily_pace

        remaining_variable_minor = 0
        for d in range(context.elapsed_day + 1, context.num_days + 1):
            day_obj = date(context.year, context.month, d)
            sqlite_w = (day_obj.weekday() + 1) % 7  # 0=Sunday, 1=Monday, ..., 6=Saturday
            remaining_variable_minor += wday_rates.get(sqlite_w, 0)

        if context.replay_mode or context.forced_method:
            display_name = "FinScope Hybrid"
        else:
            display_name = "FinScope Hybrid (Actual + Scheduled Recurring + Robust Weekday Variable)"

        explanation = self.explain(context)

        diagnostics: Dict[str, Any] = {
            "weekday_avg_minor": wday_rates,
            "remaining_days": context.remaining_days,
            "completed_months": context.completed_months
        }

        return ForecastEstimate(
            model_id=self.id,
            method_name=display_name,
            remaining_variable_minor=remaining_variable_minor,
            explanation=explanation,
            diagnostics=diagnostics
        )


    def explain(self, context: ForecastContext) -> str:
        if context.forced_method == "weekday_hybrid":
            return "Evaluated candidate weekday hybrid model"
        if context.completed_months >= 12:
            return f"Seasonal history available ({context.completed_months} complete months)"
        if context.completed_months >= 6:
            return f"Established history ({context.completed_months} complete months); using weekday hybrid"
        return f"Mature history ({context.completed_months} complete months); using weekday-aware pattern"

