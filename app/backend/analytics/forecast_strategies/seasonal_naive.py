from typing import Dict, Any
from app.backend.analytics.forecast_strategies.base import ForecastStrategy, ForecastEstimate
from app.backend.analytics.forecast_strategies.context import ForecastContext


class SeasonalNaiveStrategy(ForecastStrategy):
    """
    Seasonal Naive Strategy:
    Projects variable spending based on the identical calendar month 12 months ago.
    Only eligible when at least 12 full calendar months of history exist.
    """
    id = "seasonal_naive"
    name = "Seasonal Naive"
    description = "Projects remaining spend using the same calendar month from the previous year."

    def is_eligible(self, context: ForecastContext) -> bool:
        return context.completed_months >= 12 and len(context.hist_monthly_spends) >= 12

    def predict(self, context: ForecastContext) -> ForecastEstimate:
        if not self.is_eligible(context) or context.remaining_days <= 0:
            remaining_variable_minor = 0
            prior_seasonal_spend = 0
        else:
            prior_seasonal_spend = context.hist_monthly_spends[-12]
            variable_seasonal = max(0, prior_seasonal_spend - context.upcoming_recurring_minor)
            remaining_variable_minor = round(variable_seasonal * (context.remaining_days / float(context.num_days)))

        diagnostics: Dict[str, Any] = {
            "prior_seasonal_spend_minor": prior_seasonal_spend,
            "remaining_days": context.remaining_days,
            "total_days": context.num_days
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
        return "Seasonally matched to the same calendar month last year"
