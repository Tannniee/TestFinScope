from typing import Dict, Any
from app.backend.analytics.forecast_strategies.base import ForecastStrategy, ForecastEstimate
from app.backend.analytics.forecast_strategies.context import ForecastContext
from app.backend.analytics.rolling import calculate_median


class RecentMedianStrategy(ForecastStrategy):
    """
    Recent Median Strategy:
    Uses median total spending of recent complete months (up to 3),
    subtracts upcoming recurring commitments, and prorates variable spending across remaining days.
    """
    id = "three_month_median"
    name = "Recent Median + Known Recurring"
    description = "Projects remaining spend using 3-month median baseline and known recurring bills."

    def is_eligible(self, context: ForecastContext) -> bool:
        return context.completed_months >= 2 and len(context.hist_monthly_spends) >= 1

    def predict(self, context: ForecastContext) -> ForecastEstimate:
        med_monthly = 0
        if context.hist_monthly_spends and context.remaining_days > 0:
            med_monthly = calculate_median(context.hist_monthly_spends[-3:])
            est_variable_total = max(0, med_monthly - context.upcoming_recurring_minor)
            remaining_variable_minor = round(est_variable_total * (context.remaining_days / float(context.num_days)))
        else:
            remaining_variable_minor = 0

        diagnostics: Dict[str, Any] = {
            "median_monthly_spend_minor": med_monthly,
            "sample_months": len(context.hist_monthly_spends[-3:]),
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
        if context.forced_method == "three_month_median":
            return "Evaluated recent median baseline"
        return f"Early history ({context.completed_months} complete months); using recent median"

