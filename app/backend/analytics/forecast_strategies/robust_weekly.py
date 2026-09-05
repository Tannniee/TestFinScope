from typing import Dict, Any, List
from app.backend.analytics.forecast_strategies.base import ForecastStrategy, ForecastEstimate
from app.backend.analytics.forecast_strategies.context import ForecastContext
from app.backend.analytics.rolling import calculate_median


class RobustWeeklyResidualStrategy(ForecastStrategy):
    """
    Robust Weekly Residual Strategy (inspired by BudgetPilot):
    Aggregates dense non-recurring daily spending into complete 7-day calendar weeks,
    calculates the median weekly spend, and derives the daily variable run-rate.
    Highly resistant to single-day outlier spikes and sparse spending days.
    """
    id = "robust_weekly"
    name = "Robust Weekly Residual"
    description = "Projects remaining variable spend using 7-day median weekly totals to resist outlier spikes."

    def is_eligible(self, context: ForecastContext) -> bool:
        weekly_totals = context.get_complete_weekly_totals(max_weeks=12)
        return len(weekly_totals) >= 2 and context.remaining_days >= 0

    def predict(self, context: ForecastContext) -> ForecastEstimate:
        weekly_totals = context.get_complete_weekly_totals(max_weeks=12)
        if not weekly_totals or context.remaining_days <= 0:
            remaining_variable_minor = 0
            med_weekly = 0
            daily_rate = 0
        else:
            med_weekly = calculate_median(weekly_totals)
            daily_rate = round(med_weekly / 7.0)
            remaining_variable_minor = max(0, round((med_weekly / 7.0) * context.remaining_days))

        diagnostics: Dict[str, Any] = {
            "complete_weeks_count": len(weekly_totals),
            "weekly_totals_minor": weekly_totals,
            "median_weekly_minor": med_weekly,
            "daily_variable_rate_minor": daily_rate,
            "remaining_days": context.remaining_days
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
        weekly_totals = context.get_complete_weekly_totals(max_weeks=12)
        return f"Robust weekly median over {len(weekly_totals)} complete weeks ({round(calculate_median(weekly_totals) / 7.0) if weekly_totals else 0} minor/day)"
