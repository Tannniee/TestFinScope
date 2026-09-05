from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class ForecastConfig:
    """Centralized thresholds and configuration parameters for FinScope Forecasting."""
    robust_weekly_min_complete_weeks: int = 4
    weekday_min_samples_per_day: int = 3
    adaptive_selection_min_origins: int = 6
    calibrated_range_min_residuals: int = 8
    meaningful_model_improvement_ratio: float = 0.05
    selection_cutoff_days: Tuple[int, ...] = (7, 14, 21)
    calibration_extra_cutoff_days: Tuple[int, ...] = (26,)
    fallback_priority: Tuple[str, ...] = (
        "weekday_hybrid",
        "robust_weekly",
        "three_month_median",
        "current_pace",
    )


FORECAST_CONFIG = ForecastConfig()
