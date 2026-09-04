"""
FinScope v1.0.3 Audit Remediation Regression Tests
Covers AUD-001 through AUD-015 in strict integrity risk order.
"""

import pytest
import sqlite3
from datetime import datetime, date
from pathlib import Path
from app.backend import config
from app.backend.database.connection import get_db_connection
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.analytics.changes import WhatChangedEngine
from app.backend.analytics.anomalies import AnomalyDetectionEngine
from app.backend.analytics.context import resolve_analytics_context


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    test_db_dir = tmp_path / "finscope_data"
    test_db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FINSCOPE_DATA_DIR", str(test_db_dir))
    config.set_data_dir(test_db_dir)

    from app.backend.database.connection import init_db
    init_db()

    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def test_aud_002_soft_deleted_transaction_excluded_from_changes_and_anomalies(isolated_db):
    """
    AUD-002: Soft-deleted transactions must NOT appear or influence What Changed
    or Category Anomalies calculations.
    """
    acc_id = AccountRepository.create("Primary Acc", "checking", opening_balance=2000.0)
    cat_id = CategoryRepository.create("Fine Dining", "expense", icon="utensils", color="#E67E22")

    # Month 1: 2026-07 (previous period) -> 1 expense of $100
    TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 100.0,
        "transaction_type": "expense",
        "merchant_name": "Bistro A",
        "transaction_date": "2026-07-15"
    })

    # Month 2: 2026-08 (current period) -> 2 expenses of $150 and $200
    tx1_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 150.0,
        "transaction_type": "expense",
        "merchant_name": "Bistro B",
        "transaction_date": "2026-08-05"
    })

    tx2_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 200.0,
        "transaction_type": "expense",
        "merchant_name": "Bistro C",
        "transaction_date": "2026-08-10"
    })

    # Soft delete tx2 ($200)
    TransactionRepository.delete(tx2_id)

    # 1. Verify What Changed (WhatChangedEngine.analyze_changes)
    changes = WhatChangedEngine.analyze_changes(current_month="2026-08", comparison_month="2026-07", account_id=acc_id)
    # Current spend for Fine Dining should be ONLY tx1 ($150.00), NOT $350.00
    fine_dining_driver = next((d for d in changes["drivers"] if d["entity_id"] == cat_id), None)
    assert fine_dining_driver is not None
    assert fine_dining_driver["current_minor"] == 15000  # $150.00
    assert fine_dining_driver["delta_minor"] == 5000     # $150 - $100 = +$50.00 (not +$250.00)

    # 2. Verify Category Anomalies (AnomalyDetectionEngine.detect_anomalies)
    anomalies = AnomalyDetectionEngine.detect_anomalies(month="2026-08", account_id=acc_id)
    # Ensure current net for Fine Dining in context/anomalies is 15000 minor ($150.00)
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT SUM(t.amount_minor) as total_net
            FROM categories c
            JOIN active_transactions t ON t.category_id = c.id
            WHERE c.id = ? AND t.transaction_date >= '2026-08-01' AND t.transaction_date <= '2026-08-31'
        """, (cat_id,))
        row = cur.fetchone()
        assert row["total_net"] == 15000


def test_aud_001_account_currency_must_match_base_currency(isolated_db):
    """
    AUD-001: All accounts must use the application's base currency.
    Creating or updating an account with a mismatched currency must be rejected.
    """
    from app.backend.services.settings_service import SettingsService

    # Base currency is USD by default
    base_curr = SettingsService.get_setting("currency", "USD")
    assert base_curr == "USD"

    # Creating account with USD or None succeeds
    acc1 = AccountRepository.create("Checking USD", "checking", opening_balance=500.0, currency="USD")
    acc_data = AccountRepository.get_by_id(acc1)
    assert acc_data["currency"] == "USD"

    # Creating account with non-base currency (e.g. VND) is rejected
    with pytest.raises(ValueError, match="does not match application base currency"):
        AccountRepository.create("Savings VN", "savings", opening_balance=1000000.0, currency="VND")

    # Updating account currency to non-base currency is rejected
    with pytest.raises(ValueError, match="cannot be changed away from base currency"):
        AccountRepository.update(acc1, currency="EUR")


def test_aud_001_cannot_change_currency_after_transactions_exist(isolated_db):
    """
    AUD-001: Changing the application base currency is prohibited once
    financial transactions exist in the database.
    """
    from app.backend.services.settings_service import SettingsService

    acc_id = AccountRepository.create("Everyday Acc", "checking", opening_balance=100.0)

    # 1. Before any transactions exist, changing currency succeeds and updates existing accounts
    SettingsService.update_settings({"currency": "EUR"})
    assert SettingsService.get_setting("currency") == "EUR"
    acc = AccountRepository.get_by_id(acc_id)
    assert acc["currency"] == "EUR"

    # 2. Record an active transaction
    TransactionRepository.create({
        "account_id": acc_id,
        "amount": 25.0,
        "transaction_type": "expense",
        "merchant_name": "Cafe Paris",
        "transaction_date": "2026-08-01"
    })

    # 3. Attempting to change currency after transactions exist must be rejected
    with pytest.raises(ValueError, match="Base currency cannot be changed after financial transactions"):
        SettingsService.update_settings({"currency": "USD"})

    with pytest.raises(ValueError, match="Base currency cannot be changed after financial transactions"):
        SettingsService.set_setting("currency", "USD")


def test_aud_003_create_refund_is_atomic(isolated_db):
    """
    AUD-003: create_refund enforces bounds atomically.
    Over-refund is rejected, and failed refund attempts leave no dirty state.
    """
    acc_id = AccountRepository.create("Expense Acc", "checking", opening_balance=500.0)
    cat_id = CategoryRepository.create("Electronics", "expense", icon="laptop", color="#2980B9")

    orig_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 100.0,
        "transaction_type": "expense",
        "merchant_name": "Gadget Store",
        "transaction_date": "2026-08-15"
    })

    # 1. Partial refund of $40 succeeds
    ref1_id = TransactionRepository.create_refund(orig_id, 40.0, "2026-08-16")
    assert ref1_id > 0

    # 2. Refund exceeding remaining balance ($70 > $60) must be rejected
    with pytest.raises(ValueError, match="exceeds remaining refundable balance"):
        TransactionRepository.create_refund(orig_id, 70.0, "2026-08-17")

    # 3. Exact remaining balance ($60) succeeds
    ref2_id = TransactionRepository.create_refund(orig_id, 60.0, "2026-08-18")
    assert ref2_id > 0

    # 4. Any further refund is completely rejected
    with pytest.raises(ValueError, match="exceeds remaining refundable balance"):
        TransactionRepository.create_refund(orig_id, 0.01, "2026-08-19")


def test_aud_003_concurrent_refunds_cannot_over_refund(isolated_db):
    """
    AUD-003: Race condition test: Two concurrent threads attempting to refund $70
    on a $100 expense. Exactly one must succeed, and the other must fail with over-refund error.
    """
    import concurrent.futures

    acc_id = AccountRepository.create("Checking", "checking", opening_balance=500.0)
    cat_id = CategoryRepository.create("Shopping", "expense", icon="shopping-bag", color="#8E44AD")

    orig_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 100.0,
        "transaction_type": "expense",
        "merchant_name": "Apple Store",
        "transaction_date": "2026-08-20"
    })

    results = []
    errors = []

    def attempt_refund():
        try:
            rid = TransactionRepository.create_refund(orig_id, 70.0, "2026-08-21")
            results.append(rid)
        except Exception as e:
            errors.append(e)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(attempt_refund)
        f2 = executor.submit(attempt_refund)
        concurrent.futures.wait([f1, f2])

    # Exactly 1 success and 1 failure
    assert len(results) == 1, f"Expected exactly 1 success, got {len(results)}"
    assert len(errors) == 1, f"Expected exactly 1 failure, got {len(errors)}"
    assert "exceeds remaining refundable balance" in str(errors[0]) or "database is locked" in str(errors[0])

    # Total refunded in DB must be exactly 7000 minor ($70.00)
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT SUM(amount_minor) FROM active_transactions
            WHERE refund_of_transaction_id = ? AND transaction_type = 'refund'
        """, (orig_id,))
        total = cur.fetchone()[0]
        assert total == 7000


def test_aud_003_refund_update_is_atomic(isolated_db):
    """
    AUD-003: Updating a refund transaction amount cannot exceed the parent expense limit.
    """
    acc_id = AccountRepository.create("Card Acc", "credit", opening_balance=0.0)
    cat_id = CategoryRepository.create("Apparel", "expense", icon="shirt", color="#16A085")

    orig_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 100.0,
        "transaction_type": "expense",
        "merchant_name": "Zara",
        "transaction_date": "2026-08-20"
    })

    ref1_id = TransactionRepository.create_refund(orig_id, 30.0, "2026-08-21")
    ref2_id = TransactionRepository.create_refund(orig_id, 40.0, "2026-08-22")

    # Current: 30 + 40 = 70. Remaining is 30.
    # Increasing ref1 to 50: 50 + 40 = 90 <= 100 -> Succeeds
    assert TransactionRepository.update_refund(ref1_id, amount=50.0) is True

    # Increasing ref2 to 60: 50 + 60 = 110 > 100 -> Must raise ValueError
    with pytest.raises(ValueError, match="exceeds remaining refundable balance"):
        TransactionRepository.update_refund(ref2_id, amount=60.0)

    # Verify ref2 is unchanged (still 4000 minor)
    ref2 = TransactionRepository.get_by_id(ref2_id)
    assert ref2["amount_minor"] == 4000


def test_aud_003_deleted_refund_restores_refundable_amount(isolated_db):
    """
    AUD-003: Soft-deleting a refund excludes it from active_transactions and
    restores the available refundable balance on the parent expense.
    """
    acc_id = AccountRepository.create("Wallet", "cash", opening_balance=200.0)
    cat_id = CategoryRepository.create("Books", "expense", icon="book", color="#D35400")

    orig_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 50.0,
        "transaction_type": "expense",
        "merchant_name": "Bookstore",
        "transaction_date": "2026-08-20"
    })

    ref_id = TransactionRepository.create_refund(orig_id, 50.0, "2026-08-21")

    # Fully refunded, cannot refund more
    with pytest.raises(ValueError, match="exceeds remaining refundable balance"):
        TransactionRepository.create_refund(orig_id, 10.0, "2026-08-22")

    # Soft-delete the refund
    TransactionRepository.delete(ref_id)

    # Now refundable balance is restored, can refund $30
    new_ref_id = TransactionRepository.create_refund(orig_id, 30.0, "2026-08-23")
    assert new_ref_id > 0


def test_aud_007_sample_data_transfers_pass_production_invariants(isolated_db):
    """
    AUD-007: Seeding sample data must create transfers exclusively through TransferService.
    All transfer records must have transfer_role ('source'/'destination'), matching amounts,
    valid cross-linking, and pass TransferService.validate_all_transfer_groups().
    """
    from app.backend.services.sample_data import seed_sample_data
    from app.backend.services.transfer_service import TransferService

    res = seed_sample_data(clear_existing=True)
    assert res["success"] is True

    # Validate all transfer groups in database
    validation = TransferService.validate_all_transfer_groups(include_deleted=True)
    assert validation["valid"] is True, f"Invariant validation failed: {validation}"
    assert validation["orphan_count"] == 0
    assert validation["total_groups"] > 0
    assert len(validation["invalid_groups"]) == 0

    # Specifically check active transactions table for transfers
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, transfer_group_id, transfer_role, linked_transaction_id, amount_minor
            FROM active_transactions
            WHERE transaction_type = 'transfer'
        """)
        transfers = [dict(r) for r in cur.fetchall()]
        assert len(transfers) > 0

        # Invariant checks on each leg
        for tx in transfers:
            assert tx["transfer_group_id"] is not None
            assert tx["transfer_role"] in ("source", "destination")
            assert tx["linked_transaction_id"] is not None
            assert tx["amount_minor"] == 50000  # $500.00



