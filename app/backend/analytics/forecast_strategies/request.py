from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ForecastRequest:
    """
    Encapsulates operational execution state outside of the mathematical ForecastContext.
    Modes:
    - 'live': standard production evaluation with cached replay evidence
    - 'candidate_replay': evaluation of a single candidate model during historical replay
    - 'production_replay': evaluation of the adaptive production policy at a historical origin
    """
    target_month: str
    as_of_date: str
    account_id: Optional[int] = None
    mode: str = "live"
    forced_method: Optional[str] = None
