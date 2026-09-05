from typing import Dict, Any
from app.backend.analytics.forecast_strategies.base import ForecastStrategy, ForecastEstimate
from app.backend.analytics.forecast_strategies.context import ForecastContext
from app.backend.analytics.rolling import calculate_median


class RecentMedianStrategy(ForecastStrategy):
    """
    Recent Median Strategy (F108-02):
    Uses the median of recent complete-month non-recurring expense (up to 3 months),
    and prorates it across remaining days in the target month.
    Does NOT mix historical recurring with current upcoming recurring.
    """
    id = "three_month_median"
    name = "Recent Median + Known Recurring"
    description = "Projects remaining spend using 3-month median non-recurring baseline and known recurring bills."

    def is_eligible(self, context: ForecastContext) -> bool:
        return context.completed_months >= 2 and len(context.hist_monthly_non_recurring_expense) >= 1

    def predict(self, context: ForecastContext) -> ForecastEstimate:
        sorted_months = sorted(context.hist_monthly_non_recurring_expense.keys())
        recent_months = sorted_months[-3:] if len(sorted_months) >= 3 else sorted_months
        monthly_vals = [context.hist_monthly_non_recurring_expense[m] for m in recent_months]

        if not monthly_vals or context.remaining_days <= 0:
            remaining_variable_minor = 0
            median_monthly_variable = 0
        else:
            median_monthly_variable = calculate_median(monthly_vals)
            remaining_variable_minor = round(
                median_monthly_variable
                * context.remaining_days
                / float(context.num_days)
            )

        diagnostics: Dict[str, Any] = {
            "calendar_months_used": recent_months,
            "monthly_variable_values": monthly_vals,
            "median_monthly_variable": median_monthly_variable,
            "median_monthly_spend_minor": median_monthly_variable,
            "sample_months": len(recent_months),
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
        return f"Recent history ({context.completed_months} complete months); using recent median non-recurring pace"
