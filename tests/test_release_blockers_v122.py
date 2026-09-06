import pytest
import urllib.request
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.backend.database.connection import get_db_connection
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.services.settings_service import SettingsService
from app.backend.fx.service import FxService
from app.backend.domain.money import major_to_minor, minor_to_major, format_money
from app.backend.analytics.changes import WhatChangedEngine
from app.backend.analytics.anomalies import AnomalyDetectionEngine
from app.backend.analytics.fingerprint import SpendingFingerprintEngine
from app.backend.analytics.forecast_replay import HistoricalReplayRunner
from app.backend.analytics.models import MetricResult, DriverDecomposition, AnomalyResult, ForecastResult, FingerprintResult, Insight


@pytest.fixture(autouse=True)
def setup_test_environment(isolated_db, monkeypatch):
    SettingsService.set_setting("currency", "USD")
    monkeypatch.setattr(FxService, "get_provider", lambda: None)
    
    from app.backend.fx.models import FxQuote
    orig_get_historical_rate = FxService.get_historical_rate
    def mock_get_historical_rate(base, quote, on_date):
        b = base.upper()
        q = quote.upper()
        if b == q:
            return FxQuote(b, q, Decimal("1.0"), on_date, "identity", "2026-01-01T00:00:00Z", False)
        rates_map = {
            ("EUR", "USD"): Decimal("1.10"),
            ("USD", "EUR"): Decimal("0.909091"),
            ("VND", "USD"): Decimal("0.00004"),
            ("USD", "VND"): Decimal("25000"),
        }
        if (b, q) in rates_map:
            return FxQuote(b, q, rates_map[(b, q)], on_date, "manual_fixed", "2026-01-01T00:00:00Z", False)
        return orig_get_historical_rate(b, q, on_date)
    monkeypatch.setattr(FxService, "get_historical_rate", mock_get_historical_rate)
    yield


def test_fs001_multicurrency_what_changed_portfolio():
    """FS-001: What Changed must use base currency amounts in portfolio scope, preserving decomposition identity."""
    acc_usd = AccountRepository.create("USD Checking", "checking", opening_balance=5000.0, currency="USD")
    acc_eur = AccountRepository.create("EUR Checking", "checking", opening_balance=5000.0, currency="EUR")
    acc_vnd = AccountRepository.create("VND Wallet", "cash", opening_balance=5000000.0, currency="VND")
    
    # Previous month: 2026-05. USD spend = $100 (10,000 minor)
    TransactionRepository.create({
        "account_id": acc_usd,
        "amount": 100.0,
        "transaction_type": "expense",
        "transaction_date": "2026-05-15",
        "description": "May USD Dinner",
        "category_id": 1
    })
    
    # Current month: 2026-06.
    # 1. USD: $100 -> $100 base (10,000 minor)
    TransactionRepository.create({
        "account_id": acc_usd,
        "amount": 100.0,
        "transaction_type": "expense",
        "transaction_date": "2026-06-10",
        "description": "June USD Dinner",
        "category_id": 1
    })
    # 2. EUR: €100 @ 1.10 -> $110 base (11,000 minor)
    TransactionRepository.create({
        "account_id": acc_eur,
        "amount": 100.0,
        "transaction_type": "expense",
        "transaction_date": "2026-06-12",
        "description": "June EUR Hotel",
        "category_id": 1
    })
    # 3. VND: 250,000 VND @ 0.00004 -> $10 base (1,000 minor)
    TransactionRepository.create({
        "account_id": acc_vnd,
        "amount": 250000.0,
        "transaction_type": "expense",
        "transaction_date": "2026-06-15",
        "description": "June VND Street Food",
        "category_id": 1
    })

    # Portfolio analysis for 2026-06 vs 2026-05
    res = WhatChangedEngine.analyze_changes("2026-06", comparison_month="2026-05", account_id=None)
    
    # Expected base spend:
    # 2026-05 base spend = $100.00 = 10,000 minor
    # 2026-06 base spend = $100 + $110 + $10 = $220.00 = 22,000 minor
    assert res["current_spend_minor"] == 22000, f"Expected 22,000 base minor, got {res['current_spend_minor']}"
    assert res["previous_spend_minor"] == 10000, f"Expected 10,000 base minor, got {res['previous_spend_minor']}"
    assert res["net_spend_delta_minor"] == 12000

    # Decomposition identity: freq + ticket + refund == net_delta
    cat_driver = next(d for d in res["drivers"] if d["entity_id"] == 1)
    assert cat_driver["current_minor"] == 22000
    assert cat_driver["previous_minor"] == 10000
    assert cat_driver["delta_minor"] == 12000
    assert (
        cat_driver["frequency_effect_minor"] + 
        cat_driver["ticket_effect_minor"] + 
        cat_driver["refund_effect_minor"] == cat_driver["delta_minor"]
    )


def test_fs002_anomaly_detection_normalization_and_materiality():
    """FS-002: Anomaly baseline samples must be normalized to base currency, and materiality must not use hardcoded $."""
    acc_usd = AccountRepository.create("USD Checking", "checking", opening_balance=5000.0, currency="USD")
    acc_vnd = AccountRepository.create("VND Wallet", "cash", opening_balance=50000000.0, currency="VND")

    # Baseline: 15 transactions of $20 in USD account over past months
    for i in range(1, 16):
        d_str = f"2026-05-{(i % 25) + 1:02d}"
        TransactionRepository.create({
            "account_id": acc_usd,
            "amount": 20.0,
            "transaction_type": "expense",
            "transaction_date": d_str,
            "description": "Coffee Shop",
            "category_id": 1
        })

    # Current month: A normal coffee in VND: 50,000 VND (rate 0.00004 -> $2.00 USD)
    # If unnormalized, 50,000 integer amount would trigger a massive false-positive anomaly!
    TransactionRepository.create({
        "account_id": acc_vnd,
        "amount": 50000.0,
        "transaction_type": "expense",
        "transaction_date": "2026-06-10",
        "description": "Coffee Shop",
        "category_id": 1
    })

    anomalies = AnomalyDetectionEngine.detect_anomalies("2026-06", account_id=None)
    vnd_anomalies = [a for a in anomalies if "50000" in str(a) or a.get("actual_minor") == 50000]
    assert len(vnd_anomalies) == 0, f"VND transaction was falsely flagged as anomaly due to integer magnitude: {vnd_anomalies}"


def test_fs003_spending_fingerprint_portfolio_currency():
    """FS-003: Fingerprint metrics must be normalized to reporting currency in portfolio mode and return currency."""
    acc_usd = AccountRepository.create("USD Checking", "checking", opening_balance=5000.0, currency="USD")
    acc_eur = AccountRepository.create("EUR Checking", "checking", opening_balance=5000.0, currency="EUR")

    # Create transactions in USD and EUR across recent months
    for m in ["2026-04", "2026-05", "2026-06"]:
        for d in [2, 5, 10, 15, 20, 25]:
            TransactionRepository.create({
                "account_id": acc_usd,
                "amount": 50.0,
                "transaction_type": "expense",
                "transaction_date": f"{m}-{d:02d}",
                "description": "Store USD",
                "category_id": 1
            })
            TransactionRepository.create({
                "account_id": acc_eur,
                "amount": 50.0,  # €50 = $55 base
                "transaction_type": "expense",
                "transaction_date": f"{m}-{d+1:02d}",
                "description": "Store EUR",
                "category_id": 1
            })

    fp = SpendingFingerprintEngine.generate_fingerprint(months_window=3, account_id=None)
    assert fp.get("available") is True
    assert fp.get("currency") == "USD"
    assert 5000 <= fp["median_transaction_minor"] <= 5500


def test_fs004_forecast_replay_reporting_currency_and_pit():
    """FS-004: Forecast replay target actuals must use base currency in portfolio mode."""
    acc_usd = AccountRepository.create("USD Checking", "checking", opening_balance=5000.0, currency="USD")
    acc_eur = AccountRepository.create("EUR Checking", "checking", opening_balance=5000.0, currency="EUR")

    # Month 2026-05: $100 USD + €100 EUR (@ 1.10 = $110 USD) = $210 base (21,000 minor)
    TransactionRepository.create({
        "account_id": acc_usd,
        "amount": 100.0,
        "transaction_type": "expense",
        "transaction_date": "2026-05-10",
        "description": "May USD"
    })
    TransactionRepository.create({
        "account_id": acc_eur,
        "amount": 100.0,
        "transaction_type": "expense",
        "transaction_date": "2026-05-12",
        "description": "May EUR"
    })

    actual_base_spend = HistoricalReplayRunner.get_actual_month_end_net_spend("2026-05", account_id=None)
    assert actual_base_spend == 21000, f"Expected 21,000 base minor, got {actual_base_spend}"


def test_fs005_currency_exponents_dto_no_hardcoded_100():
    """FS-005: DTO to_dict() must format values according to currency decimals (0 for VND, 2 for USD, 3 for KWD)."""
    # VND (0 decimals)
    m_vnd = MetricResult(
        metric_name="total_spend",
        current_value_minor=100000,
        currency="VND"
    )
    d_vnd = m_vnd.to_dict()
    assert d_vnd["currency"] == "VND"
    assert d_vnd["current_value"] == 100000.0, f"VND should have 0 decimal scale, got {d_vnd['current_value']}"

    # KWD (3 decimals)
    m_kwd = MetricResult(
        metric_name="total_spend",
        current_value_minor=1234,
        currency="KWD"
    )
    d_kwd = m_kwd.to_dict()
    assert d_kwd["currency"] == "KWD"
    assert d_kwd["current_value"] == 1.234, f"KWD should have 3 decimal scale, got {d_kwd['current_value']}"

    # USD (2 decimals)
    m_usd = MetricResult(
        metric_name="total_spend",
        current_value_minor=1025,
        currency="USD"
    )
    d_usd = m_usd.to_dict()
    assert d_usd["currency"] == "USD"
    assert d_usd["current_value"] == 10.25


def test_fs006_cross_currency_refund_bounds_in_original_currency():
    """FS-006: Cumulative refund limits must strictly evaluate in original purchase currency."""
    acc_eur = AccountRepository.create("EUR Checking", "checking", opening_balance=1000.0, currency="EUR")
    acc_usd = AccountRepository.create("USD Wallet", "cash", opening_balance=1000.0, currency="USD")

    # Original purchase: €100 in EUR account
    orig_id = TransactionRepository.create({
        "account_id": acc_eur,
        "amount": 100.0,
        "transaction_type": "expense",
        "transaction_date": "2026-06-10",
        "description": "Hotel in Paris",
        "category_id": 1
    })

    # Refund €60 of the €100 purchase, credited into USD account
    ref1_id = TransactionRepository.create_refund(
        original_tx_id=orig_id,
        amount=60.0,
        transaction_date="2026-06-15",
        account_id=acc_usd,
        note="Partial refund"
    )
    assert ref1_id > 0

    # Second refund of €40 (should succeed, reaching €100 total)
    ref2_id = TransactionRepository.create_refund(
        original_tx_id=orig_id,
        amount=40.0,
        transaction_date="2026-06-20",
        account_id=acc_usd,
        note="Final refund"
    )
    assert ref2_id > 0

    # Third refund of €1 (must fail: exceeds original €100 limit)
    with pytest.raises(ValueError, match="exceeds remaining refundable balance"):
        TransactionRepository.create_refund(
            original_tx_id=orig_id,
            amount=1.0,
            transaction_date="2026-06-25",
            account_id=acc_usd
        )

    # Check get_refundable_info
    info = TransactionRepository.get_refundable_info(orig_id)
    assert info["original_amount_minor"] == 10000
    assert info["refunded_amount_minor"] == 10000
    assert info["remaining_refundable_minor"] == 0
    assert info["original_currency"] == "EUR"


def test_fs007_budget_reporting_currency_comparison():
    """FS-007: Category budget comparisons must evaluate account-scoped spend in Base Currency."""
    from app.backend.repositories.budget_repo import BudgetRepository

    acc_eur = AccountRepository.create("EUR Checking", "checking", opening_balance=5000.0, currency="EUR")
    
    # Set Category 1 budget: $500 USD for 2026-06
    BudgetRepository.set_budget(category_id=1, month="2026-06", amount=500.0, currency="USD")

    # Spend €200 in EUR account @ 1.10 rate = $220 USD
    TransactionRepository.create({
        "account_id": acc_eur,
        "amount": 200.0,
        "transaction_type": "expense",
        "transaction_date": "2026-06-10",
        "description": "EUR Expense",
        "category_id": 1
    })

    # Portfolio query: budget is $500, spent is $220 USD
    budgets_portfolio = BudgetRepository.get_by_month("2026-06", account_id=None)
    b_item = next(b for b in budgets_portfolio if b["category_id"] == 1)
    assert b_item["currency"] == "USD"
    assert b_item["budget_amount"] == 500.0
    assert b_item["spent_amount"] == 220.0

    # Account-scoped query: when filtered by acc_eur, spent should be evaluated in base currency or properly matched
    budgets_acc = BudgetRepository.get_by_month("2026-06", account_id=acc_eur)
    b_acc_item = next(b for b in budgets_acc if b["category_id"] == 1)
    assert b_acc_item["spent_amount"] == 220.0
    assert b_acc_item["currency"] == "USD"


def test_fs008_dom_xss_protection_and_csp(ephemeral_server):
    """FS-008: Server must include Content-Security-Policy header, and analytics.js must escape insight text."""
    client = ephemeral_server
    
    req = urllib.request.Request(f"{client.base_url}/")
    with urllib.request.urlopen(req) as resp:
        headers = dict(resp.headers)
        csp = headers.get("Content-Security-Policy") or headers.get("content-security-policy")
        assert csp is not None, "Content-Security-Policy header is missing"
        assert "default-src 'self'" in csp
        assert "object-src 'none'" in csp

    analytics_js_path = Path("app/frontend/assets/js/pages/analytics.js")
    content = analytics_js_path.read_text(encoding="utf-8")
    assert "${ins.title}" not in content, "Unescaped ${ins.title} found in analytics.js"
    assert "${ins.summary}" not in content, "Unescaped ${ins.summary} found in analytics.js"


def test_static_guard_no_bare_division_by_100_in_analytics():
    """Static AST check: No bare `/ 100` or `/ 100.0` in app/backend/analytics/ DTO models."""
    import ast

    models_path = Path("app/backend/analytics/models.py")
    tree = ast.parse(models_path.read_text(encoding="utf-8"))

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv)):
            if isinstance(node.right, ast.Constant) and node.right.value in (100, 100.0):
                violations.append(f"Line {node.lineno}: division by {node.right.value}")

    assert len(violations) == 0, f"Found prohibited / 100 conversions in models.py:\n" + "\n".join(violations)
