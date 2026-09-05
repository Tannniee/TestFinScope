from typing import Dict, Any
from app.backend.analytics.forecast_strategies.base import ForecastStrategy, ForecastEstimate
from app.backend.analytics.forecast_strategies.context import ForecastContext


class CurrentPaceStrategy(ForecastStrategy):
    """
    Current Pace Strategy (F108-01):
    Extrapolates observed non-recurring daily spending pace in the current month
    across remaining days. Excludes actual recurring commitments and refunds from the variable pace.
    """
    id = "current_pace"
    name = "Current Pace + Known Recurring"
    description = "Projects remaining spend using current month non-recurring pace and known recurring bills."

    def is_eligible(self, context: ForecastContext) -> bool:
        return context.remaining_days >= 0

    def predict(self, context: ForecastContext) -> ForecastEstimate:
        if context.elapsed_day <= 0 or context.remaining_days <= 0:
            remaining_variable_minor = 0
            daily_pace = 0
        else:
            remaining_variable_minor = round(
                context.actual_non_recurring_expense_minor
                * context.remaining_days
                / float(context.elapsed_day)
            )
            daily_pace = round(context.actual_non_recurring_expense_minor / float(context.elapsed_day))

        diagnostics: Dict[str, Any] = {
            "actual_non_recurring_expense_minor": context.actual_non_recurring_expense_minor,
            "elapsed_days": context.elapsed_day,
            "remaining_days": context.remaining_days,
            "implied_daily_variable_rate": daily_pace,
            "daily_pace_minor": daily_pace
        }

        explanation = self.explain(context)

        return ForecastEstimate(
            model_id=self.id,
            method_name=self.name,
            remaining_variable_minor=max(0, remaining_variable_minor),
            explanation=explanation,
            diagnostics=diagnostics
        )

    def explain(self, context: ForecastContext) -> str:
        if context.completed_months < 2:
            return "Minimal history (< 2 complete months); using current non-recurring pace"
        return "Current month daily non-recurring pace extrapolated across remaining days"
