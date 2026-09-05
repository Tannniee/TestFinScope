from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.backend.analytics.forecast_strategies.context import ForecastContext


@dataclass
class ForecastEstimate:
    """
    Result of a single statistical strategy prediction for remaining variable spending.
    Always measured in integer minor units (e.g., cents).
    """
    model_id: str
    method_name: str
    remaining_variable_minor: int
    explanation: str
    diagnostics: Dict[str, Any] = field(default_factory=dict)


class ForecastStrategy(ABC):
    """
    Abstract Base Class for all FinScope statistical forecast strategies.
    Every model owns its own eligibility rules, variable spend prediction,
    and user-facing explanation.
    """
    id: str
    name: str
    description: str

    @abstractmethod
    def is_eligible(self, context: "ForecastContext") -> bool:
        """
        Evaluates whether this strategy is mathematically and historically
        eligible to make a prediction given the current forecast context.
        """
        pass

    @abstractmethod
    def predict(self, context: "ForecastContext") -> ForecastEstimate:
        """
        Estimates the remaining variable spending (in minor units) for the target month.
        Must return an integer minor amount (>= 0).
        """
        pass

    @abstractmethod
    def explain(self, context: "ForecastContext") -> str:
        """
        Provides a clear, human-understandable explanation of how the prediction was derived.
        """
        pass
