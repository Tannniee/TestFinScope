from typing import Dict, Any
from app.backend.analytics.forecast_strategies.base import ForecastStrategy, ForecastEstimate
from app.backend.analytics.forecast_strategies.context import ForecastContext
from app.backend.analytics.forecast_strategies.series import same_month_previous_year


class SeasonalNaiveStrategy(ForecastStrategy):
    """
    Seasonal Naive Strategy (F108-04):
    Projects variable spending based on the identical calendar month 12 months ago
    (YYYY - 1, identical MM) using pure non-recurring expense history.
    Does not use positional list indexing. Zero-spend reference months are valid data (0).
    """
    id = "seasonal_naive"
    name = "Seasonal Naive"
    description = "Projects remaining spend using the exact same calendar month from the previous year."

    def is_eligible(self, context: ForecastContext) -> bool:
        ref_month = same_month_previous_year(context.target_month)
        return (
            context.completed_months >= 12 and
            ref_month in context.hist_monthly_non_recurring_expense and
            context.remaining_days >= 0
        )

    def predict(self, context: ForecastContext) -> ForecastEstimate:
        ref_month = same_month_previous_year(context.target_month)
        if not self.is_eligible(context) or context.remaining_days <= 0:
            remaining_variable_minor = 0
            prior_seasonal_spend = 0
        else:
            prior_seasonal_spend = context.hist_monthly_non_recurring_expense.get(ref_month, 0)
            remaining_variable_minor = round(
                prior_seasonal_spend * (context.remaining_days / float(context.num_days))
            )

        diagnostics: Dict[str, Any] = {
            "reference_month": ref_month,
            "prior_seasonal_spend_minor": prior_seasonal_spend,
            "remaining_days": context.remaining_days,
            "total_days": context.num_days
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
        ref_month = same_month_previous_year(context.target_month)
        return f"Seasonally matched to exact calendar month {ref_month} last year"
