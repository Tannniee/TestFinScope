from typing import Dict, List, Optional
from app.backend.analytics.forecast_strategies.base import ForecastStrategy
from app.backend.analytics.forecast_strategies.context import ForecastContext
from app.backend.analytics.forecast_strategies.current_pace import CurrentPaceStrategy
from app.backend.analytics.forecast_strategies.recent_median import RecentMedianStrategy
from app.backend.analytics.forecast_strategies.robust_weekly import RobustWeeklyResidualStrategy
from app.backend.analytics.forecast_strategies.weekday_hybrid import WeekdayHybridStrategy
from app.backend.analytics.forecast_strategies.seasonal_naive import SeasonalNaiveStrategy


class ModelRegistry:
    """
    Central registry for statistical forecasting strategies.
    Decouples model definitions from the forecasting engine.
    """
    def __init__(self):
        self._strategies: Dict[str, ForecastStrategy] = {}

    def register(self, strategy: ForecastStrategy) -> None:
        self._strategies[strategy.id] = strategy

    def get(self, model_id: str) -> Optional[ForecastStrategy]:
        return self._strategies.get(model_id)

    def get_eligible(self, context: ForecastContext) -> List[ForecastStrategy]:
        """Returns all strategies that are eligible given the context."""
        return [s for s in self._strategies.values() if s.is_eligible(context)]

    def list_models(self) -> List[ForecastStrategy]:
        return list(self._strategies.values())


def get_default_registry() -> ModelRegistry:
    """Initializes and returns a registry pre-populated with standard FinScope strategies."""
    registry = ModelRegistry()
    registry.register(CurrentPaceStrategy())
    registry.register(RecentMedianStrategy())
    registry.register(RobustWeeklyResidualStrategy())
    registry.register(WeekdayHybridStrategy())
    registry.register(SeasonalNaiveStrategy())
    return registry


# Global default registry instance
default_registry = get_default_registry()
