from app.backend.analytics.forecast_strategies.base import ForecastStrategy, ForecastEstimate
from app.backend.analytics.forecast_strategies.context import ForecastContext
from app.backend.analytics.forecast_strategies.request import ForecastRequest
from app.backend.analytics.forecast_strategies.config import ForecastConfig, FORECAST_CONFIG
from app.backend.analytics.forecast_strategies.series import (
    generate_calendar_months,
    same_month_previous_year,
    build_dense_daily_series,
    build_dense_monthly_series,
    build_complete_calendar_weeks,
)
from app.backend.analytics.forecast_strategies.scoring import (
    ReplayOrigin,
    CandidateReplayRecord,
    compute_comparable_scores,
)
from app.backend.analytics.forecast_strategies.current_pace import CurrentPaceStrategy
from app.backend.analytics.forecast_strategies.recent_median import RecentMedianStrategy
from app.backend.analytics.forecast_strategies.robust_weekly import RobustWeeklyResidualStrategy
from app.backend.analytics.forecast_strategies.weekday_hybrid import WeekdayHybridStrategy
from app.backend.analytics.forecast_strategies.seasonal_naive import SeasonalNaiveStrategy
from app.backend.analytics.forecast_strategies.registry import ModelRegistry, default_registry, get_default_registry
from app.backend.analytics.forecast_strategies.selector import (
    ModelSelector,
    IneligibleForecastStrategyError,
    IneligibleForecastStrategy
)

__all__ = [
    "ForecastStrategy",
    "ForecastEstimate",
    "ForecastContext",
    "ForecastRequest",
    "ForecastConfig",
    "FORECAST_CONFIG",
    "generate_calendar_months",
    "same_month_previous_year",
    "build_dense_daily_series",
    "build_dense_monthly_series",
    "build_complete_calendar_weeks",
    "ReplayOrigin",
    "CandidateReplayRecord",
    "compute_comparable_scores",
    "CurrentPaceStrategy",
    "RecentMedianStrategy",
    "RobustWeeklyResidualStrategy",
    "WeekdayHybridStrategy",
    "SeasonalNaiveStrategy",
    "ModelRegistry",
    "default_registry",
    "get_default_registry",
    "ModelSelector",
    "IneligibleForecastStrategyError",
    "IneligibleForecastStrategy",
]
