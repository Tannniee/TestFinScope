from typing import Dict, Any
from app.backend.analytics.forecast_strategies.base import ForecastStrategy, ForecastEstimate
from app.backend.analytics.forecast_strategies.context import ForecastContext


class CurrentPaceStrategy(ForecastStrategy):
    """
    Current Pace Strategy:
    Extrapolates observed non-recurring daily spending pace in the current month
    across remaining days. Primary fallback for zero or minimal historical data.
    """
    id = "current_pace"
    name = "Current Pace + Known Recurring"
    description = "Projects remaining spend using current month daily pace and known recurring bills."

    def is_eligible(self, context: ForecastContext) -> bool:
        # Universal baseline, always eligible
        return context.remaining_days >= 0

    def predict(self, context: ForecastContext) -> ForecastEstimate:
        daily_pace = (context.actual_net_spend_to_date // context.elapsed_day) if context.elapsed_day > 0 else 0
        remaining_variable_minor = max(0, daily_pace * context.remaining_days)

        diagnostics: Dict[str, Any] = {
            "daily_pace_minor": daily_pace,
            "elapsed_day": context.elapsed_day,
            "remaining_days": context.remaining_days,
            "net_spend_to_date_minor": context.actual_net_spend_to_date
        }

        explanation = self.explain(context)

        return ForecastEstimate(
            model_id=self.id,
            method_name=self.name,
            remaining_variable_minor=remaining_variable_minor,
            explanation=explanation,
            diagnostics=diagnostics
        )

    def explain(self, context: ForecastContext) -> str:
        if context.forced_method == "current_pace":
            return "Evaluated current pace baseline"
        if context.completed_months < 2:
            return "Minimal history (< 2 complete months); using current pace"
        return "Current month daily spending pace extrapolated across remaining days"

