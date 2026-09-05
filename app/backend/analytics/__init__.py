"""
FinScope Analytics Package V2.
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
from app.backend.analytics.context import (
    AnalyticsContext,
    resolve_analytics_context
)
from app.backend.analytics.period_series import (
    PeriodValue,
    DataSufficiency,
    calendar_month_series,
    check_data_sufficiency
)
from app.backend.analytics.reconciliation import (
    ReconciliationResult,
    reconcile_period_totals,
    reconcile_category_totals,
    reconcile_change_decomposition,
    reconcile_forecast_components
)
from app.backend.analytics.insight_history import InsightHistoryTracker
from app.backend.analytics.aggregates import AggregateQueries
from app.backend.analytics.rolling import RollingAnalyticsEngine
from app.backend.analytics.changes import WhatChangedEngine
from app.backend.analytics.fingerprint import SpendingFingerprintEngine
from app.backend.analytics.anomalies import AnomalyDetectionEngine
from app.backend.analytics.forecasting import ForecastingEngine, generate_occurrences
from app.backend.analytics.forecast_replay import HistoricalReplayRunner
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
    "AnalyticsContext",
    "resolve_analytics_context",
    "PeriodValue",
    "DataSufficiency",
    "calendar_month_series",
    "check_data_sufficiency",
    "ReconciliationResult",
    "reconcile_period_totals",
    "reconcile_category_totals",
    "reconcile_change_decomposition",
    "reconcile_forecast_components",
    "InsightHistoryTracker",
    "AggregateQueries",
    "RollingAnalyticsEngine",
    "WhatChangedEngine",
    "SpendingFingerprintEngine",
    "AnomalyDetectionEngine",
    "ForecastingEngine",
    "generate_occurrences",
    "HistoricalReplayRunner",
    "BacktestingEngine",
    "InsightRulesGenerator",
    "InsightRanker"
]
