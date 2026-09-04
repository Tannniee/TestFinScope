from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import date

@dataclass
class PeriodValue:
    period: str  # "YYYY-MM"
    value_minor: int
    has_transactions: bool
    coverage: str  # "complete", "partial", "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "period": self.period,
            "value_minor": self.value_minor,
            "value": round(self.value_minor / 100.0, 2),
            "has_transactions": self.has_transactions,
            "coverage": self.coverage
        }

@dataclass
class DataSufficiency:
    available: bool
    sample_size: int
    months_history: int
    reason: Optional[str]
    confidence_band: str  # "high", "medium", "low", "insufficient"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "sample_size": self.sample_size,
            "months_history": self.months_history,
            "reason": self.reason,
            "confidence_band": self.confidence_band
        }

# Standard minimum thresholds for personal finance analytics
THRESHOLDS = {
    "previous_compare": {"min_months": 2, "min_tx": 2},
    "rolling_3m": {"min_months": 3, "min_tx": 5},
    "rolling_6m": {"min_months": 6, "min_tx": 10},
    "rolling_12m": {"min_months": 12, "min_tx": 20},
    "fingerprint": {"min_months": 2, "min_tx": 30},
    "category_persistence": {"min_months": 3, "min_tx": 10},
    "merchant_anomaly": {"min_months": 1, "min_tx": 5},
    "category_anomaly": {"min_months": 1, "min_tx": 10},
    "overall_anomaly": {"min_months": 1, "min_tx": 20},
    "hybrid_forecast": {"min_months": 1, "min_tx": 5},
    "backtesting": {"min_months": 4, "min_tx": 10}
}

def check_data_sufficiency(
    feature: str,
    sample_size: int,
    months_history: int
) -> DataSufficiency:
    """Evaluates data sufficiency against centralized thresholds without fake certainty."""
    cfg = THRESHOLDS.get(feature, {"min_months": 1, "min_tx": 5})
    min_m = cfg["min_months"]
    min_tx = cfg["min_tx"]

    if months_history < min_m:
        return DataSufficiency(
            available=False,
            sample_size=sample_size,
            months_history=months_history,
            reason=f"Insufficient history: {months_history}/{min_m} months available.",
            confidence_band="insufficient"
        )
    if sample_size < min_tx:
        return DataSufficiency(
            available=False,
            sample_size=sample_size,
            months_history=months_history,
            reason=f"Insufficient sample size: {sample_size}/{min_tx} transactions available.",
            confidence_band="insufficient"
        )

    # Determine confidence band
    if sample_size >= min_tx * 3 and months_history >= min_m * 2:
        band = "high"
    elif sample_size >= min_tx * 1.5:
        band = "medium"
    else:
        band = "low"

    return DataSufficiency(
        available=True,
        sample_size=sample_size,
        months_history=months_history,
        reason=None,
        confidence_band=band
    )

def generate_month_range(start_month: str, end_month: str) -> List[str]:
    """Generates contiguous list of 'YYYY-MM' strings between start and end (inclusive)."""
    sy, sm = map(int, start_month.split("-"))
    ey, em = map(int, end_month.split("-"))

    months = []
    cy, cm = sy, sm
    while (cy < ey) or (cy == ey and cm <= em):
        months.append(f"{cy:04d}-{cm:02d}")
        cm += 1
        if cm > 12:
            cm = 1
            cy += 1
    return months

def calendar_month_series(
    start_month: str,
    end_month: str,
    raw_dict: Dict[str, int],
    earliest_recorded_month: Optional[str] = None,
    current_month: Optional[str] = None,
    default_val: int = 0
) -> List[PeriodValue]:
    """
    Creates zero-filled monthly time series, ensuring missing months are preserved
    as $0 (not omitted) while marking data coverage accurately.
    """
    all_months = generate_month_range(start_month, end_month)
    result: List[PeriodValue] = []

    for m in all_months:
        has_tx = m in raw_dict
        val = raw_dict.get(m, default_val)

        # Determine coverage
        if current_month and m == current_month:
            coverage = "partial"
        elif earliest_recorded_month and m < earliest_recorded_month:
            coverage = "unknown"
        else:
            coverage = "complete"

        result.append(PeriodValue(
            period=m,
            value_minor=val,
            has_transactions=has_tx,
            coverage=coverage
        ))

    return result
