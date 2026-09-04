"""
Multi-Factor Insight Ranker & Deduplicator for FinScope.
Scores candidate insights:
Score = 0.30*Impact + 0.20*Unusualness + 0.15*Confidence + 0.15*Actionability + 0.10*Novelty + 0.10*Relevance
Filters duplicates and returns top meaningful insights.
"""

from typing import Dict, Any, List, Optional
from app.backend.analytics.models import Insight

CONFIDENCE_WEIGHTS = {
    "high": 1.0,
    "moderate": 0.7,
    "low": 0.4
}

SEVERITY_BONUS = {
    "critical": 0.15,
    "warning": 0.08,
    "success": 0.05,
    "info": 0.0
}

class InsightRanker:
    @staticmethod
    def rank_and_deduplicate(
        candidates: List[Insight],
        limit: int = 5,
        w_impact: float = 0.30,
        w_unusualness: float = 0.20,
        w_confidence: float = 0.15,
        w_actionability: float = 0.15,
        w_novelty: float = 0.10,
        w_relevance: float = 0.10
    ) -> List[Dict[str, Any]]:
        """
        Ranks candidate insights, eliminates redundant entity duplicates,
        and returns the top `limit` results as dictionaries.
        """
        if not candidates:
            return []

        # 1. Compute multi-factor final score
        scored_candidates: List[Insight] = []
        for c in candidates:
            conf_val = CONFIDENCE_WEIGHTS.get(c.confidence, 0.7)
            sev_bonus = SEVERITY_BONUS.get(c.severity, 0.0)

            score = (
                w_impact * c.impact_score +
                w_unusualness * c.unusualness_score +
                w_confidence * conf_val +
                w_actionability * c.actionability_score +
                w_novelty * c.novelty_score +
                w_relevance * 1.0 +
                sev_bonus
            )
            c.final_rank_score = round(score, 3)
            scored_candidates.append(c)

        # 2. Sort by final score descending
        scored_candidates.sort(key=lambda x: x.final_rank_score, reverse=True)

        # 3. Deduplicate by entity (e.g. don't show 3 different insights for Food category)
        deduped: List[Insight] = []
        seen_entities = set()

        for c in scored_candidates:
            entity_key = f"{c.entity_type}_{c.entity_id}" if c.entity_id else c.id
            if entity_key in seen_entities:
                continue
            seen_entities.add(entity_key)
            deduped.append(c)

            if len(deduped) >= limit:
                break

        return [item.to_dict() for item in deduped]
