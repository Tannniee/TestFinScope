"""
FinScope Analytics Package.
Modular, explainable, deterministic personal financial intelligence engine.
"""

from app.backend.analytics.models import (
    AnalyticsPeriod,
    MetricResult,
    DriverDecomposition,
    AnomalyResult,
    ForecastResult,
    FingerprintResult,
    Insight
)
from app.backend.analytics.semantics import (
    calculate_net_spending,
    calculate_net_cash_flow,
    calculate_savings,
    calculate_savings_rate,
    classify_transaction_pnl_effect
)
from app.backend.analytics.aggregates import AggregateQueries
from app.backend.analytics.rolling import RollingAnalyticsEngine
from app.backend.analytics.changes import WhatChangedEngine
from app.backend.analytics.fingerprint import SpendingFingerprintEngine
from app.backend.analytics.anomalies import AnomalyDetectionEngine
from app.backend.analytics.forecasting import ForecastingEngine
from app.backend.analytics.backtesting import BacktestingEngine
from app.backend.analytics.insight_rules import InsightRulesGenerator
from app.backend.analytics.insight_ranker import InsightRanker

__all__ = [
    "AnalyticsPeriod",
    "MetricResult",
    "DriverDecomposition",
    "AnomalyResult",
    "ForecastResult",
    "FingerprintResult",
    "Insight",
    "calculate_net_spending",
    "calculate_net_cash_flow",
    "calculate_savings",
    "calculate_savings_rate",
    "classify_transaction_pnl_effect",
    "AggregateQueries",
    "RollingAnalyticsEngine",
    "WhatChangedEngine",
    "SpendingFingerprintEngine",
    "AnomalyDetectionEngine",
    "ForecastingEngine",
    "BacktestingEngine",
    "InsightRulesGenerator",
    "InsightRanker"
]
