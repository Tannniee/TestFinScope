from typing import Dict, Any, List
from app.backend.analytics.forecast_strategies.base import ForecastStrategy, ForecastEstimate
from app.backend.analytics.forecast_strategies.context import ForecastContext
from app.backend.analytics.forecast_strategies.config import FORECAST_CONFIG
from app.backend.analytics.rolling import calculate_median


class RobustWeeklyResidualStrategy(ForecastStrategy):
    """
    Robust Weekly Residual Strategy (F108-05, F108-06):
    Aggregates dense non-recurring daily spending into complete Monday-to-Sunday calendar weeks,
    calculates the median weekly spend, and derives the daily variable run-rate.
    Requires at least 4 complete Monday-Sunday weeks for robustness.
    """
    id = "robust_weekly"
    name = "Robust Weekly Residual"
    description = "Projects remaining variable spend using complete Monday-Sunday median weekly totals."

    def is_eligible(self, context: ForecastContext) -> bool:
        weekly_totals = context.get_complete_weekly_totals(max_weeks=12)
        return len(weekly_totals) >= FORECAST_CONFIG.robust_weekly_min_complete_weeks and context.remaining_days >= 0

    def predict(self, context: ForecastContext) -> ForecastEstimate:
        weekly_totals = context.get_complete_weekly_totals(max_weeks=12)
        if not weekly_totals or context.remaining_days <= 0:
            remaining_variable_minor = 0
            med_weekly = 0
            daily_rate = 0
        else:
            med_weekly = calculate_median(weekly_totals)
            daily_rate = round(med_weekly / 7.0)
            remaining_variable_minor = round(med_weekly * context.remaining_days / 7.0)

        diagnostics: Dict[str, Any] = {
            "complete_weeks_count": len(weekly_totals),
            "weekly_totals_minor": weekly_totals,
            "median_weekly_minor": med_weekly,
            "daily_variable_rate_minor": daily_rate,
            "implied_daily_rate": daily_rate,
            "remaining_days": context.remaining_days
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
        weekly_totals = context.get_complete_weekly_totals(max_weeks=12)
        med_weekly = calculate_median(weekly_totals) if weekly_totals else 0
        return f"Robust weekly median over {len(weekly_totals)} complete Monday-Sunday weeks ({round(med_weekly / 7.0)} minor/day)"
