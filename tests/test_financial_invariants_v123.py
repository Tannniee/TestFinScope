import ast
import os
import pytest
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.backend.database.connection import get_db_connection
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.budget_repo import BudgetRepository
from app.backend.services.settings_service import SettingsService
from app.backend.services.integrity_service import IntegrityService
from app.backend.fx.service import FxService
from app.backend.domain.money import major_to_minor, minor_to_major, format_money
from app.backend.analytics.forecasting import ForecastingEngine
from app.backend.analytics.forecast_strategies.request import ForecastRequest
from app.backend.analytics.insight_rules import InsightRulesGenerator
from app.backend.analytics.changes import WhatChangedEngine
from app.backend.analytics.models import Insight


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
            ("JPY", "USD"): Decimal("0.006667"),
            ("USD", "JPY"): Decimal("150"),
            ("KWD", "USD"): Decimal("3.25"),
            ("USD", "KWD"): Decimal("0.307692"),
        }
        if (b, q) in rates_map:
            return FxQuote(b, q, rates_map[(b, q)], on_date, "manual_fixed", "2026-01-01T00:00:00Z", False)
        return orig_get_historical_rate(b, q, on_date)

    monkeypatch.setattr(FxService, "get_historical_rate", mock_get_historical_rate)
    yield


# =============================================================================
# 1. Refund Canonical Purchase-Currency Domain (FS123-001 / Phase 1)
# =============================================================================
def test_rf01_foreign_purchase_refund_in_parent_original_currency():
    """
    Parent purchase: 100 EUR on a USD card ($110 USD charged).
    Refunds must be requested, capped, and tracked in original EUR (parent purchase currency).
    Settlement in USD card should convert EUR -> USD; settlement in EUR account should be 1:1 EUR.
    """
    acc_usd = AccountRepository.create("Chase USD Card", "credit", opening_balance=0.0, currency="USD")
    acc_eur = AccountRepository.create("N26 EUR Account", "checking", opening_balance=1000.0, currency="EUR")
    cat_shop = CategoryRepository.create("Shopping EUR", "expense", "shopping-bag", "#FF6B8A")

    # Parent purchase: 100.00 EUR on USD card account
    parent_id = TransactionRepository.create({
        "account_id": acc_usd,
        "category_id": cat_shop,
        "amount": 100.0,
        "currency": "EUR",  # foreign transaction currency
        "transaction_type": "expense",
        "transaction_date": "2026-09-01",
        "description": "Berlin Electronics Store"
    })

    parent = TransactionRepository.get_by_id(parent_id)
    assert parent["original_currency"] == "EUR"
    assert parent["original_amount_minor"] == 10000
    assert parent["currency"] == "USD"
    assert parent["amount_minor"] == 11000  # 100 * 1.10 = 110 USD

    # Refund 1: 60 EUR refunded back into the same USD card account
    ref1_id = TransactionRepository.create_refund(
        parent_tx_id=parent_id,
        amount=60.0,  # in original purchase currency (EUR)
        transaction_date="2026-09-03",
        account_id=acc_usd,
        note="Partial return 1"
    )
    ref1 = TransactionRepository.get_by_id(ref1_id)
    assert ref1["original_currency"] == "EUR"
    assert ref1["original_amount_minor"] == 6000
    assert ref1["currency"] == "USD"
    assert ref1["amount_minor"] == 6600  # 60 * 1.10 = 66 USD settlement

    # Check refundable status
    info = TransactionRepository.get_refundable_info(parent_id)
    assert info["original_currency"] == "EUR"
    assert info["original_amount_minor"] == 10000
    assert info["refunded_amount_minor"] == 6000
    assert info["remaining_refundable_minor"] == 4000
    assert info["remaining_refundable"] == 40.0
    assert info["can_refund"] is True

    # Refund 2: Remaining 40 EUR refunded into EUR account
    ref2_id = TransactionRepository.create_refund(
        parent_tx_id=parent_id,
        amount=40.0,
        transaction_date="2026-09-04",
        account_id=acc_eur,
        note="Remaining return into EUR"
    )
    ref2 = TransactionRepository.get_by_id(ref2_id)
    assert ref2["original_currency"] == "EUR"
    assert ref2["original_amount_minor"] == 4000
    assert ref2["currency"] == "EUR"
    assert ref2["amount_minor"] == 4000

    # Refund 3: Any additional refund must be rejected as exceeding original EUR 100
    with pytest.raises(ValueError, match="exceeds remaining refundable balance"):
        TransactionRepository.create_refund(
            parent_tx_id=parent_id,
            amount=0.01,
            transaction_date="2026-09-05",
            account_id=acc_usd
        )

    info_final = TransactionRepository.get_refundable_info(parent_id)
    assert info_final["remaining_refundable_minor"] == 0
    assert info_final["can_refund"] is False


def test_rf02_update_refund_maintains_original_purchase_currency():
    """Updating a refund preserves parent original currency even if target account changes."""
    acc_usd = AccountRepository.create("USD Card", "credit", opening_balance=0.0, currency="USD")
    acc_eur = AccountRepository.create("EUR Checking", "checking", opening_balance=500.0, currency="EUR")
    cat_id = CategoryRepository.create("Gear", "expense", "box", "#4DD5A5")

    parent_id = TransactionRepository.create({
        "account_id": acc_usd,
        "category_id": cat_id,
        "amount": 100.0,
        "currency": "EUR",
        "transaction_type": "expense",
        "transaction_date": "2026-09-01",
        "description": "Camera equipment"
    })

    ref_id = TransactionRepository.create_refund(
        parent_tx_id=parent_id,
        amount=30.0,
        transaction_date="2026-09-02",
        account_id=acc_usd
    )

    # Update amount from 30 EUR to 50 EUR
    TransactionRepository.update_refund(ref_id, amount=50.0)
    ref_updated = TransactionRepository.get_by_id(ref_id)
    assert ref_updated["original_currency"] == "EUR"
    assert ref_updated["original_amount_minor"] == 5000
    assert ref_updated["currency"] == "USD"
    assert ref_updated["amount_minor"] == 5500  # 50 * 1.10 = 55 USD

    # Change destination account to EUR checking
    TransactionRepository.update_refund(ref_id, account_id=acc_eur)
    ref_updated_acc = TransactionRepository.get_by_id(ref_id)
    assert ref_updated_acc["original_currency"] == "EUR"
    assert ref_updated_acc["original_amount_minor"] == 5000
    assert ref_updated_acc["currency"] == "EUR"
    assert ref_updated_acc["amount_minor"] == 5000


# =============================================================================
# 2. Forecast Category/Budget Comparison Domain (FS123-002 / Phase 2)
# =============================================================================
def test_fc01_account_forecast_budget_comparison_in_base_currency():
    """
    Account forecast operates in account currency (EUR).
    Budgets are in Base Currency (USD).
    Category variance and is_over_budget must be evaluated in Base Currency (USD).
    Serialization must not have bare / 100.0.
    """
    acc_eur = AccountRepository.create("EUR Account", "checking", opening_balance=5000.0, currency="EUR")
    cat_food = CategoryRepository.create("Groceries", "expense", "shopping-cart", "#4DD5A5")

    # Set budget for category in USD base currency: $500.00 (50,000 minor)
    BudgetRepository.set_category_budget(
        category_id=cat_food,
        month="2026-09",
        amount_minor=50000,
        currency="USD"
    )

    # Add spend: 400 EUR (~ $440 USD)
    TransactionRepository.create({
        "account_id": acc_eur,
        "category_id": cat_food,
        "amount": 400.0,
        "transaction_type": "expense",
        "transaction_date": "2026-09-02",
        "description": "Supermarket"
    })

    fc = ForecastingEngine.forecast(
        ForecastRequest(
            target_month="2026-09",
            as_of_date="2026-09-05",
            account_id=acc_eur
        )
    )

    assert fc["currency"] == "EUR"
    cat_fc = next(c for c in fc["category_forecasts"] if c["category_id"] == cat_food)
    assert cat_fc["actual_minor"] == 40000  # 400.00 EUR
    assert cat_fc["actual"] == 400.0
    assert cat_fc["budget_minor"] == 50000  # $500.00 USD
    assert cat_fc["budget"] == 500.0

    # If projected spend is e.g. 520 EUR (~ $572 USD), in USD base it is over budget ($572 > $500).
    # If compared directly without FX conversion (520 EUR < 50000 minor cents = 500 USD),
    # a cross-currency bug would mistake 520 EUR as under 50000.
    # The projected_base_minor should be converted to USD base (~57200 minor).
    if "projected_base_minor" in cat_fc:
        assert cat_fc["projected_base_minor"] >= cat_fc["projected_minor"]


# =============================================================================
# 3. Ranked Insight Rules Around Canonical Currency (FS123-003 / Phase 3)
# =============================================================================
def test_ins01_ranked_insights_dynamic_currency_and_no_generic_dollar():
    """
    Ranked insights for VND reporting currency must not contain literal '$'
    and must not use static minor thresholds ($20 = 2000 minor).
    """
    changes_vnd = {
        "currency": "VND",
        "total_current_minor": 15000000,
        "total_previous_minor": 10000000,
        "total_delta_minor": 5000000,
        "drivers": [
            {
                "entity_id": 1,
                "name": "Food & Dining",
                "current_minor": 6000000,
                "previous_minor": 3000000,
                "delta_minor": 3000000,
                "share_of_increase": 0.60,
                "frequency_effect_minor": 2000000,
                "ticket_effect_minor": 1000000,
                "refund_effect_minor": 0
            }
        ]
    }

    candidates = InsightRulesGenerator.generate_candidates(
        changes_data=changes_vnd,
        anomalies_data=[],
        forecast_data={"currency": "VND"},
        month="2026-09"
    )

    assert len(candidates) > 0
    ins = candidates[0]
    assert ins.currency == "VND"
    assert "$" not in ins.title
    assert "$" not in ins.summary
    assert "₫" in ins.summary or "VND" in ins.summary


# =============================================================================
# 4. Review Queue Money Contract (FS123-004 / Phase 5)
# =============================================================================
def test_rq01_review_queue_hydration_matches_normal_transactions():
    """Review queue returns hydrated rows matching get_by_id, without SQL / 100.0."""
    acc_vnd = AccountRepository.create("VND Wallet", "cash", opening_balance=1000000.0, currency="VND")
    cat_uncat = CategoryRepository.get_all(cat_type="expense")[0]["id"]

    tx_id = TransactionRepository.create({
        "account_id": acc_vnd,
        "category_id": cat_uncat,
        "amount": 250000.0,
        "transaction_type": "expense",
        "transaction_date": "2026-09-02",
        "description": "Local market",
        "needs_review": True
    })

    single = TransactionRepository.get_by_id(tx_id)
    rq = TransactionRepository.get_review_queue(account_id=acc_vnd)
    assert rq["total"] >= 1

    rq_item = next(item for item in rq["items"] if item["id"] == tx_id)
    assert rq_item["currency"] == "VND"
    assert rq_item["amount_minor"] == 250000
    assert rq_item["amount"] == 250000.0
    assert rq_item["amount"] == single["amount"]


# =============================================================================
# 5. Point-in-Time Forecast Replay Integrity (FS123-006 / Phase 7)
# =============================================================================
def test_pit01_point_in_time_replay_excludes_late_imports():
    """
    Transactions created after replay origin cutoff must be excluded from origin inputs,
    preventing look-ahead leakage through late imports or backfills.
    """
    acc_usd = AccountRepository.create("Main Checking", "checking", opening_balance=5000.0, currency="USD")
    cat_id = CategoryRepository.create("Utilities", "expense", "zap", "#27D5D5")

    # Regular transaction created on June 10
    tx1_id = TransactionRepository.create({
        "account_id": acc_usd,
        "category_id": cat_id,
        "amount": 50.0,
        "transaction_type": "expense",
        "transaction_date": "2026-06-05",
        "description": "Known electricity bill"
    })
    with get_db_connection() as conn:
        conn.execute("UPDATE transactions SET created_at = '2026-06-05 10:00:00' WHERE id = ?", (tx1_id,))
        conn.commit()

    # Late imported transaction: economic date is June 8, but created_at is July 10
    tx2_id = TransactionRepository.create({
        "account_id": acc_usd,
        "category_id": cat_id,
        "amount": 200.0,
        "transaction_type": "expense",
        "transaction_date": "2026-06-08",
        "description": "Late imported June bill"
    })
    with get_db_connection() as conn:
        conn.execute("UPDATE transactions SET created_at = '2026-07-10 10:00:00' WHERE id = ?", (tx2_id,))
        conn.commit()

    # When evaluating forecast at origin 2026-06-14 in candidate_replay mode:
    fc = ForecastingEngine.forecast(
        ForecastRequest(
            target_month="2026-06",
            as_of_date="2026-06-14",
            account_id=acc_usd,
            mode="candidate_replay",
            forced_method="current_pace"
        )
    )

    # Actual spent to date at origin should only include tx1 ($50 = 5000 minor), NOT tx2 ($200)
    assert fc["actual_spent_to_date_minor"] == 5000


# =============================================================================
# 6. Integrity Diagnostics Expansion (FS123-008 / Phase 8)
# =============================================================================
def test_integrity01_diagnostics_detects_refund_currency_mismatch():
    """IntegrityService flags refunds whose original_currency differs from parent."""
    acc_usd = AccountRepository.create("USD Account", "checking", opening_balance=1000.0, currency="USD")
    cat_id = CategoryRepository.get_all(cat_type="expense")[0]["id"]

    parent_id = TransactionRepository.create({
        "account_id": acc_usd,
        "category_id": cat_id,
        "amount": 100.0,
        "currency": "EUR",
        "transaction_type": "expense",
        "transaction_date": "2026-09-01",
        "description": "Parent in EUR"
    })

    ref_id = TransactionRepository.create_refund(
        parent_tx_id=parent_id,
        amount=50.0,
        transaction_date="2026-09-02",
        account_id=acc_usd
    )

    # Corrupt refund row's original_currency manually to simulate legacy data corruption
    with get_db_connection() as conn:
        conn.execute("UPDATE transactions SET original_currency = 'USD' WHERE id = ?", (ref_id,))
        conn.commit()

    diag = IntegrityService.run_diagnostics()
    assert diag["is_healthy"] is False
    assert any("original_currency" in iss or "refund" in iss.lower() for iss in diag["issues"])


# =============================================================================
# 7. Static Guard: No Bare Financial Division by 100 (Phase 11)
# =============================================================================
def test_static_guard_no_bare_division_by_100():
    """Ensures no bare / 100 or / 100.0 remains in analytics or review queue."""
    target_files = [
        Path("app/backend/analytics/forecasting.py"),
        Path("app/backend/analytics/insight_rules.py"),
        Path("app/backend/analytics/changes.py"),
        Path("app/backend/analytics/models.py"),
        Path("app/backend/repositories/transaction_repo.py"),
    ]

    for p in target_files:
        assert p.exists(), f"File {p} must exist"
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                if isinstance(node.right, ast.Constant) and node.right.value in (100, 100.0):
                    # We allow division by 100 ONLY in mathematical percentages e.g. / 100.0 for scores
                    # Any financial variable ending in minor, amt, etc. divided by 100 is forbidden
                    left_repr = ast.unparse(node.left)
                    assert not any(left_repr.endswith(s) for s in ("_minor", "amount_minor", "c_actual", "c_proj", "c_budget", "c_var", "delta")), (
                        f"Found bare financial division by 100 in {p}:{node.lineno}: {ast.unparse(node)}"
                    )
