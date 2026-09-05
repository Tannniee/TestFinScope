from typing import Dict, Any, List, Optional, Tuple
from app.backend.analytics.forecast_strategies.base import ForecastStrategy
from app.backend.analytics.forecast_strategies.context import ForecastContext
from app.backend.analytics.forecast_strategies.registry import ModelRegistry, default_registry


class ModelSelector:
    """
    Selects the most suitable ForecastStrategy for the given ForecastContext.
    Implements:
    1. Explicit forced override (e.g. forced_method="weekday_hybrid" during candidate evaluation)
    2. Adaptive selection via historical replay performance on comparable origins
    3. Deterministic data-sufficiency fallback ladder
    """
    def __init__(self, registry: Optional[ModelRegistry] = None):
        self.registry = registry or default_registry

    def select(
        self,
        context: ForecastContext,
        replay_scores: Optional[Dict[str, Any]] = None
    ) -> Tuple[ForecastStrategy, str]:
        """
        Returns (selected_strategy, selection_reason).
        """
        # 1. Forced method override
        if context.forced_method:
            strategy = self.registry.get(context.forced_method)
            if strategy:
                return strategy, strategy.explain(context)

        eligible = self.registry.get_eligible(context)
        eligible_map = {s.id: s for s in eligible}

        # 2. Adaptive selection via Historical Replay (if replay evidence is available and reliable)
        if replay_scores and replay_scores.get("available") and not context.replay_mode:
            models_data = replay_scores.get("models", {})
            valid_candidates: List[Tuple[float, int, str]] = []
            for mid, mstats in models_data.items():
                if mid in eligible_map and mstats.get("sample_origins", 0) >= 3:
                    score = mstats.get("median_ae_minor") or mstats.get("mae_minor") or float("inf")
                    valid_candidates.append((score, mstats.get("sample_origins", 0), mid))

            if valid_candidates:
                # Rank by lowest error, then highest sample count
                valid_candidates.sort(key=lambda x: (x[0], -x[1]))
                best_model_id = valid_candidates[0][2]
                best_score = valid_candidates[0][0]
                winning_strategy = eligible_map[best_model_id]
                return winning_strategy, f"Adaptive replay selection: lowest error on comparable origins ({best_score} minor)"

        # 3. Deterministic Data-Sufficiency Fallback Ladder
        if context.completed_months < 2:
            s = self.registry.get("current_pace")
            strategy = s if s else eligible[0]
            return strategy, strategy.explain(context)
        elif context.completed_months < 6:
            s = self.registry.get("three_month_median")
            strategy = s if s else eligible[0]
            return strategy, strategy.explain(context)
        else:
            s = self.registry.get("weekday_hybrid")
            strategy = s if s else eligible[0]
            return strategy, strategy.explain(context)

