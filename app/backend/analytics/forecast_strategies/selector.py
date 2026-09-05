from typing import Dict, Any, List, Optional, Tuple
from app.backend.analytics.forecast_strategies.base import ForecastStrategy
from app.backend.analytics.forecast_strategies.context import ForecastContext
from app.backend.analytics.forecast_strategies.registry import ModelRegistry, default_registry
from app.backend.analytics.forecast_strategies.config import FORECAST_CONFIG


class ModelSelector:
    """
    Selects the most suitable ForecastStrategy for a given ForecastContext.
    Implements:
    1. Explicit forced override with eligibility verification (F108-12)
    2. Adaptive selection via historical replay on true comparable origins (>= 6 origins, F108-10, F108-11)
    3. Meaningful improvement guardrail (5% threshold, F108-23)
    4. Configured deterministic fallback priority (F108-24)
    """
    def __init__(self, registry: Optional[ModelRegistry] = None):
        self.registry = registry or default_registry

    def select(
        self,
        context: ForecastContext,
        replay_scores: Optional[Dict[str, Any]] = None,
        forced_method: Optional[str] = None
    ) -> Tuple[ForecastStrategy, str]:
        """
        Returns (selected_strategy, selection_reason).
        """
        # 1. Forced method override
        if forced_method:
            strategy = self.registry.get(forced_method)
            if not strategy:
                raise ValueError(f"Unknown forecast method '{forced_method}'")
            if not strategy.is_eligible(context):
                return strategy, f"Ineligible candidate: {strategy.id}"
            return strategy, strategy.explain(context)

        eligible = self.registry.get_eligible(context)
        if not eligible:
            # Universal safety fallback
            pace = self.registry.get("current_pace")
            return (pace if pace else self.registry.list_models()[0]), "Universal emergency fallback"

        eligible_map = {s.id: s for s in eligible}

        # Determine deterministic fallback model based on configured priority
        fallback_strategy: Optional[ForecastStrategy] = None
        for model_id in FORECAST_CONFIG.fallback_priority:
            if model_id in eligible_map:
                fallback_strategy = eligible_map[model_id]
                break

        if not fallback_strategy:
            fallback_strategy = eligible[0]

        fallback_reason = fallback_strategy.explain(context)

        # 2. Adaptive Selection via Historical Replay Evidence
        if replay_scores and replay_scores.get("available"):
            # Support both format: dict of model_scores or top-level models
            model_scores_data = replay_scores.get("model_scores") or replay_scores.get("models", {})
            comp_origins = replay_scores.get("comparable_origin_count", 0)

            # Filter candidates that are eligible and have comparable score data
            candidate_ranks = []
            for mid, s in eligible_map.items():
                if mid in model_scores_data:
                    m_stat = model_scores_data[mid]
                    origins = m_stat.get("comparable_origins") or m_stat.get("sample_origins", 0)
                    if origins >= FORECAST_CONFIG.adaptive_selection_min_origins:
                        med_ae = m_stat.get("median_ae_minor")
                        mae = m_stat.get("mae_minor")
                        bias = abs(m_stat.get("bias_minor", 0))
                        if med_ae is not None and mae is not None:
                            candidate_ranks.append((med_ae, mae, bias, mid))

            if candidate_ranks:
                # Rank order: lowest Median AE -> lowest MAE -> lowest |bias|
                candidate_ranks.sort(key=lambda x: (x[0], x[1], x[2]))
                best_med_ae, best_mae, best_bias, best_id = candidate_ranks[0]
                best_strategy = eligible_map[best_id]

                # Check meaningful improvement over fallback strategy
                fallback_med_ae = None
                if fallback_strategy.id in model_scores_data:
                    fallback_med_ae = model_scores_data[fallback_strategy.id].get("median_ae_minor")

                if best_strategy.id != fallback_strategy.id and fallback_med_ae is not None and fallback_med_ae > 0:
                    improvement = (fallback_med_ae - best_med_ae) / float(fallback_med_ae)
                    if improvement < FORECAST_CONFIG.meaningful_model_improvement_ratio:
                        return fallback_strategy, f"Fallback retained: replay difference below {int(FORECAST_CONFIG.meaningful_model_improvement_ratio * 100)}% threshold"

                return best_strategy, f"Adaptive replay selection: lowest Median AE on comparable origins ({best_med_ae} minor)"

        # 3. Deterministic Configured Fallback
        return fallback_strategy, fallback_reason
