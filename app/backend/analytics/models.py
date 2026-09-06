from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from app.backend.domain.money import minor_to_major


def _to_major(minor: Optional[int], currency: str) -> Optional[float]:
    if minor is None:
        return None
    return float(minor_to_major(minor, currency))


@dataclass
class AnalyticsPeriod:
    """Represents an analytical period with comparison boundaries."""
    start_date: str
    end_date: str
    comparison_start: Optional[str] = None
    comparison_end: Optional[str] = None
    granularity: str = "month"  # "day", "week", "month", "quarter", "year"


@dataclass
class MetricResult:
    """Core numeric metric output with comparison and confidence."""
    metric_name: str
    current_value_minor: int
    comparison_value_minor: int = 0
    absolute_delta_minor: int = 0
    percent_delta: float = 0.0
    sample_size: int = 0
    confidence: str = "moderate"  # "low", "moderate", "high"
    metadata: Dict[str, Any] = field(default_factory=dict)
    currency: str = "USD"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "currency": self.currency,
            "current_value_minor": self.current_value_minor,
            "current_value": _to_major(self.current_value_minor, self.currency),
            "comparison_value_minor": self.comparison_value_minor,
            "comparison_value": _to_major(self.comparison_value_minor, self.currency),
            "absolute_delta_minor": self.absolute_delta_minor,
            "absolute_delta": _to_major(self.absolute_delta_minor, self.currency),
            "percent_delta": round(self.percent_delta, 1),
            "sample_size": self.sample_size,
            "confidence": self.confidence,
            "metadata": self.metadata
        }


@dataclass
class DriverDecomposition:
    """What Changed v2 Driver decomposition."""
    dimension: str  # "category", "merchant", "time"
    name: str
    entity_id: Optional[int]
    color: str
    current_minor: int
    previous_minor: int
    delta_minor: int
    share_of_increase: float
    frequency_effect_minor: int
    ticket_effect_minor: int
    tag: str  # "NEW", "INCREASED_FREQUENCY", "HIGHER_TICKET", "ONE_OFF", "REDUCED", etc.
    refund_effect_minor: int = 0
    details: Dict[str, Any] = field(default_factory=dict)
    currency: str = "USD"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "name": self.name,
            "entity_id": self.entity_id,
            "color": self.color,
            "currency": self.currency,
            "current_minor": self.current_minor,
            "current": _to_major(self.current_minor, self.currency),
            "previous_minor": self.previous_minor,
            "previous": _to_major(self.previous_minor, self.currency),
            "delta_minor": self.delta_minor,
            "delta": _to_major(self.delta_minor, self.currency),
            "share_of_increase": round(self.share_of_increase, 3),
            "frequency_effect_minor": self.frequency_effect_minor,
            "frequency_effect": _to_major(self.frequency_effect_minor, self.currency),
            "ticket_effect_minor": self.ticket_effect_minor,
            "ticket_effect": _to_major(self.ticket_effect_minor, self.currency),
            "refund_effect_minor": self.refund_effect_minor,
            "refund_effect": _to_major(self.refund_effect_minor, self.currency),
            "tag": self.tag,
            "details": self.details
        }


@dataclass
class AnomalyResult:
    """Statistical anomaly with robust baselines and normal range."""
    anomaly_id: str
    anomaly_type: str  # "transaction_amount", "category_monthly", "recurring_jump", "daily_spike"
    title: str
    entity_type: str  # "transaction", "category", "merchant", "day"
    entity_id: Optional[int]
    entity_name: str
    actual_minor: int
    expected_median_minor: int
    normal_range_lower_minor: int
    normal_range_upper_minor: int
    robust_score: float  # scaled z-score
    severity: str  # "mild", "moderate", "strong"
    confidence: str  # "low", "moderate", "high"
    explanation: str
    drilldown_filter: Dict[str, Any] = field(default_factory=dict)
    currency: str = "USD"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "anomaly_id": self.anomaly_id,
            "anomaly_type": self.anomaly_type,
            "title": self.title,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "currency": self.currency,
            "actual_minor": self.actual_minor,
            "actual": _to_major(self.actual_minor, self.currency),
            "expected_median_minor": self.expected_median_minor,
            "expected_median": _to_major(self.expected_median_minor, self.currency),
            "normal_range_lower_minor": self.normal_range_lower_minor,
            "normal_range_lower": _to_major(self.normal_range_lower_minor, self.currency),
            "normal_range_upper_minor": self.normal_range_upper_minor,
            "normal_range_upper": _to_major(self.normal_range_upper_minor, self.currency),
            "robust_score": round(self.robust_score, 2),
            "severity": self.severity,
            "confidence": self.confidence,
            "explanation": self.explanation,
            "drilldown_filter": self.drilldown_filter
        }


@dataclass
class ForecastResult:
    """Explainable month-end projection."""
    target_month: str
    projected_expense_minor: int
    lower_bound_minor: int
    upper_bound_minor: int
    confidence: str  # "low", "moderate", "high"
    method: str
    actual_spent_to_date_minor: int
    upcoming_recurring_minor: int
    expected_variable_minor: int
    expected_refunds_minor: int
    budget_minor: Optional[int] = None
    projected_variance_minor: Optional[int] = None
    category_forecasts: List[Dict[str, Any]] = field(default_factory=list)
    components: Dict[str, Any] = field(default_factory=dict)
    projected_income_minor: Optional[int] = None
    projected_net_flow_minor: Optional[int] = None
    projected_savings_rate: Optional[float] = None
    actual_income_to_date_minor: Optional[int] = None
    range_type: str = "early_estimate"
    confidence_score: int = 50
    model_method: str = "weekday_hybrid"
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    currency: str = "USD"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_month": self.target_month,
            "currency": self.currency,
            "projected_expense_minor": self.projected_expense_minor,
            "projected_expense": _to_major(self.projected_expense_minor, self.currency),
            "lower_bound_minor": self.lower_bound_minor,
            "lower_bound": _to_major(self.lower_bound_minor, self.currency),
            "upper_bound_minor": self.upper_bound_minor,
            "upper_bound": _to_major(self.upper_bound_minor, self.currency),
            "range_type": self.range_type,
            "confidence": self.confidence,
            "confidence_score": self.confidence_score,
            "method": self.method,
            "model_method": self.model_method,
            "actual_spent_to_date_minor": self.actual_spent_to_date_minor,
            "actual_spent_to_date": _to_major(self.actual_spent_to_date_minor, self.currency),
            "upcoming_recurring_minor": self.upcoming_recurring_minor,
            "upcoming_recurring": _to_major(self.upcoming_recurring_minor, self.currency),
            "expected_variable_minor": self.expected_variable_minor,
            "expected_variable": _to_major(self.expected_variable_minor, self.currency),
            "expected_refunds_minor": self.expected_refunds_minor,
            "expected_refunds": _to_major(self.expected_refunds_minor, self.currency),
            "budget_minor": self.budget_minor,
            "budget": _to_major(self.budget_minor, self.currency) if self.budget_minor is not None else None,
            "projected_variance_minor": self.projected_variance_minor,
            "projected_variance": _to_major(self.projected_variance_minor, self.currency) if self.projected_variance_minor is not None else None,
            "category_forecasts": self.category_forecasts,
            "components": self.components,
            "projected_income_minor": self.projected_income_minor,
            "projected_income": _to_major(self.projected_income_minor, self.currency) if self.projected_income_minor is not None else None,
            "projected_net_flow_minor": self.projected_net_flow_minor,
            "projected_net_flow": _to_major(self.projected_net_flow_minor, self.currency) if self.projected_net_flow_minor is not None else None,
            "projected_savings_rate": self.projected_savings_rate,
            "actual_income_to_date_minor": self.actual_income_to_date_minor,
            "actual_income_to_date": _to_major(self.actual_income_to_date_minor, self.currency) if self.actual_income_to_date_minor is not None else None,
            "diagnostics": self.diagnostics
        }


@dataclass
class FingerprintResult:
    """Personal spending fingerprint description."""
    period_label: str
    sample_months: int
    transaction_count: int
    median_transaction_minor: int
    mean_transaction_minor: int
    p75_transaction_minor: int
    p90_transaction_minor: int
    largest_transaction_minor: int
    spending_variability: float  # MAD / median
    weekend_concentration: float  # Weekend / Total Discretionary
    recurring_expense_ratio: float  # Recurring / Total Spend
    essential_ratio: float  # Essential / Total Spend
    category_diversity_score: int  # 0 to 100
    spending_consistency_score: int  # 0 to 100
    burstiness_score: float  # -1.0 (regular) to +1.0 (bursty)
    category_persistence_score: float  # 0.0 to 1.0 (cosine similarity)
    most_active_weekday: str
    most_variable_category: str
    most_stable_category: str
    top_merchants_share: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    currency: str = "USD"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "period_label": self.period_label,
            "currency": self.currency,
            "sample_months": self.sample_months,
            "transaction_count": self.transaction_count,
            "median_transaction_minor": self.median_transaction_minor,
            "median_transaction": _to_major(self.median_transaction_minor, self.currency),
            "mean_transaction_minor": self.mean_transaction_minor,
            "mean_transaction": _to_major(self.mean_transaction_minor, self.currency),
            "p75_transaction_minor": self.p75_transaction_minor,
            "p75_transaction": _to_major(self.p75_transaction_minor, self.currency),
            "p90_transaction_minor": self.p90_transaction_minor,
            "p90_transaction": _to_major(self.p90_transaction_minor, self.currency),
            "largest_transaction_minor": self.largest_transaction_minor,
            "largest_transaction": _to_major(self.largest_transaction_minor, self.currency),
            "spending_variability": round(self.spending_variability, 2),
            "weekend_concentration": round(self.weekend_concentration * 100.0, 1),
            "recurring_expense_ratio": round(self.recurring_expense_ratio * 100.0, 1),
            "essential_ratio": round(self.essential_ratio * 100.0, 1),
            "category_diversity_score": self.category_diversity_score,
            "spending_consistency_score": self.spending_consistency_score,
            "burstiness_score": round(self.burstiness_score, 2),
            "category_persistence_score": round(self.category_persistence_score, 2),
            "most_active_weekday": self.most_active_weekday,
            "most_variable_category": self.most_variable_category,
            "most_stable_category": self.most_stable_category,
            "top_merchants_share": round(self.top_merchants_share * 100.0, 1),
            "metadata": self.metadata
        }


@dataclass
class Insight:
    """Canonical ranked user insight."""
    id: str
    insight_type: str  # "CHANGE", "TREND", "ANOMALY", "BUDGET", "FORECAST", "BEHAVIOUR", "ACHIEVEMENT"
    title: str
    summary: str
    metric: str
    entity_type: str  # "category", "merchant", "overview", "budget"
    entity_id: Optional[int]
    current_value_minor: int
    baseline_value_minor: int
    delta_value_minor: int
    delta_percent: float
    severity: str  # "info", "warning", "critical", "success"
    confidence: str  # "low", "moderate", "high"
    impact_score: float
    unusualness_score: float
    actionability_score: float
    novelty_score: float
    final_rank_score: float
    drilldown_filter: Dict[str, Any]
    evidence: Dict[str, Any]
    generated_at: str
    insight_key: str = ""
    currency: str = "USD"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "insight_key": self.insight_key or self.id,
            "insight_type": self.insight_type,
            "title": self.title,
            "summary": self.summary,
            "metric": self.metric,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "currency": self.currency,
            "current_value": _to_major(self.current_value_minor, self.currency),
            "baseline_value": _to_major(self.baseline_value_minor, self.currency),
            "delta_value": _to_major(self.delta_value_minor, self.currency),
            "delta_percent": round(self.delta_percent, 1),
            "severity": self.severity,
            "confidence": self.confidence,
            "impact_score": round(self.impact_score, 2),
            "novelty_score": round(self.novelty_score, 2),
            "final_rank_score": round(self.final_rank_score, 2),
            "drilldown_filter": self.drilldown_filter,
            "evidence": self.evidence,
            "generated_at": self.generated_at
        }
