from dataclasses import dataclass
from typing import Dict, List, Set, Any, Optional
from app.backend.analytics.rolling import calculate_median, calculate_mean


@dataclass(frozen=True)
class ReplayOrigin:
    """Represents a discrete historical backtesting cutoff."""
    origin_id: str        # e.g. "2026-03|2026-03-14"
    target_month: str     # "2026-03"
    as_of_date: str       # "2026-03-14"
    progress_bucket: int  # 0 to 3


@dataclass(frozen=True)
class CandidateReplayRecord:
    """Historical forecast prediction and error for a candidate strategy at a specific origin."""
    origin_id: str
    model_id: str
    predicted_minor: int
    actual_minor: int
    error_minor: int      # actual - predicted
    abs_error_minor: int  # abs(actual - predicted)


def compute_comparable_scores(
    candidate_records_by_model: Dict[str, List[CandidateReplayRecord]],
    eligible_model_ids: List[str]
) -> Dict[str, Any]:
    """
    Computes fair, comparable-origin error scores across eligible strategies.
    Strictly evaluates models ONLY on the exact intersection of origin IDs
    where all participating eligible models produced valid predictions.
    """
    valid_models = [m for m in eligible_model_ids if m in candidate_records_by_model and candidate_records_by_model[m]]
    if not valid_models:
        return {
            "comparable_origin_count": 0,
            "common_origins": [],
            "model_scores": {}
        }

    # Find common origins across all valid eligible candidate models
    origin_sets = [
        {r.origin_id for r in candidate_records_by_model[m]}
        for m in valid_models
    ]
    common_origins: Set[str] = set.intersection(*origin_sets) if origin_sets else set()

    model_scores: Dict[str, Dict[str, Any]] = {}
    for m in valid_models:
        records_in_common = [r for r in candidate_records_by_model[m] if r.origin_id in common_origins]
        if not records_in_common:
            continue

        abs_errors = [r.abs_error_minor for r in records_in_common]
        signed_errors = [r.error_minor for r in records_in_common]

        med_ae = calculate_median(abs_errors)
        mean_ae = round(calculate_mean(abs_errors))
        bias = round(calculate_mean(signed_errors))

        model_scores[m] = {
            "model_id": m,
            "comparable_origins": len(records_in_common),
            "median_ae_minor": med_ae,
            "mae_minor": mean_ae,
            "bias_minor": bias
        }

    return {
        "comparable_origin_count": len(common_origins),
        "common_origins": sorted(list(common_origins)),
        "model_scores": model_scores
    }
