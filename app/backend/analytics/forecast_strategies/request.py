from dataclasses import dataclass
from typing import Optional, Literal, Mapping, Any

ForecastMode = Literal["live", "candidate_replay", "production_replay"]


@dataclass(frozen=True)
class ForecastRequest:
    """
    Canonical operational execution contract for FinScope forecasting (F110-04).
    Encapsulates execution mode, cutoff, account scope, and replay evidence outside
    of the immutable mathematical ForecastContext.

    Modes:
    - 'live': standard production evaluation with cached replay evidence
    - 'candidate_replay': evaluation of a single candidate model during historical replay
    - 'production_replay': evaluation of the adaptive production policy at a historical origin
    """
    target_month: str
    as_of_date: Optional[str] = None
    account_id: Optional[int] = None
    mode: ForecastMode = "live"
    forced_method: Optional[str] = None
    replay_evidence: Optional[Mapping[str, Any]] = None

    def __post_init__(self):
        if self.mode not in ("live", "candidate_replay", "production_replay"):
            raise ValueError(f"Invalid forecast mode: '{self.mode}'")
        if self.mode == "candidate_replay":
            if not self.forced_method:
                raise ValueError("candidate_replay mode requires forced_method")
            if not self.as_of_date:
                raise ValueError("candidate_replay mode requires explicit as_of_date")
        elif self.mode == "production_replay":
            if self.forced_method:
                raise ValueError("production_replay mode does not allow forced_method")
            if not self.as_of_date:
                raise ValueError("production_replay mode requires explicit as_of_date")
