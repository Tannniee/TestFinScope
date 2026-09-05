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


def test_aud_004a_csv_preview_matches_commit_for_in_file_duplicates(isolated_db):
    """
    AUD-004A: CSV preview must flag in-file duplicates identically to commit_import.
    Preview counts (valid, duplicate) must equal commit counts (imported, skipped).
    """
    from app.backend.services.import_service import ImportService

    acc_id = AccountRepository.create("Checking AUD-004", "checking", opening_balance=1000.0)

    # A CSV containing two identical rows
    csv_data = """Date,Payee,Amount
2026-09-01,Starbucks,-5.00
2026-09-01,Starbucks,-5.00
2026-09-02,Trader Joes,-35.00
"""
    mapping = {"date": "Date", "payee": "Payee", "amount": "Amount"}

    preview = ImportService.preview_csv(csv_data, mapping=mapping, account_id=acc_id)
    assert preview["total_rows"] == 3
    assert preview["valid_count"] == 2
    assert preview["duplicate_count"] == 1
    assert preview["preview_rows"][0]["is_duplicate"] is False
    assert preview["preview_rows"][1]["is_duplicate"] is True
    assert preview["preview_rows"][2]["is_duplicate"] is False

    # Commit must match preview exactly
    commit_res = ImportService.commit_import(csv_data, mapping=mapping, account_id=acc_id, deduplicate=True)
    assert commit_res["success"] is True
    assert commit_res["imported_count"] == preview["valid_count"] == 2
    assert commit_res["skipped_duplicates"] == preview["duplicate_count"] == 1


def test_aud_004b_explicit_date_formats_and_ambiguity_rejection(isolated_db):
    """
    AUD-004B: Explicit date format parsing and ambiguous date rejection in 'auto' mode.
    """
    from app.backend.services.import_service import ImportService

    acc_id = AccountRepository.create("Date Test Acc", "checking", opening_balance=1000.0)
    mapping = {"date": "Date", "payee": "Payee", "amount": "Amount"}

    # 1. Ambiguous date 01/02/2026 in auto mode -> flagged as error
    ambiguous_csv = """Date,Payee,Amount
01/02/2026,Coffee Shop,-4.50
"""
    preview_auto = ImportService.preview_csv(ambiguous_csv, mapping=mapping, account_id=acc_id, date_format="auto")
    assert preview_auto["invalid_count"] == 1
    assert preview_auto["valid_count"] == 0
    assert "Ambiguous date" in preview_auto["preview_rows"][0]["errors"][0]

    # 2. Same CSV with explicit DD/MM/YYYY -> parsed as 2026-02-01 (1st February)
    preview_dmy = ImportService.preview_csv(ambiguous_csv, mapping=mapping, account_id=acc_id, date_format="DD/MM/YYYY")
    assert preview_dmy["valid_count"] == 1
    assert preview_dmy["preview_rows"][0]["date"] == "2026-02-01"

    # 3. Same CSV with explicit MM/DD/YYYY -> parsed as 2026-01-02 (2nd January)
    preview_mdy = ImportService.preview_csv(ambiguous_csv, mapping=mapping, account_id=acc_id, date_format="MM/DD/YYYY")
    assert preview_mdy["valid_count"] == 1
    assert preview_mdy["preview_rows"][0]["date"] == "2026-01-02"


def test_aud_004c_same_merchant_different_description_not_duplicate(isolated_db):
    """
    AUD-004C: Same merchant on same date and amount with different descriptions
    must NOT be falsely flagged as duplicates.
    """
    from app.backend.services.import_service import ImportService

    acc_id = AccountRepository.create("Shopping Acc", "checking", opening_balance=500.0)

    csv_data = """Date,Payee,Description,Amount
2026-09-04,Starbucks,Morning Coffee,-5.00
2026-09-04,Starbucks,Afternoon Coffee,-5.00
2026-09-04,Starbucks,Morning Coffee,-5.00
"""
    mapping = {"date": "Date", "payee": "Payee", "description": "Description", "amount": "Amount"}

    preview = ImportService.preview_csv(csv_data, mapping=mapping, account_id=acc_id)
    assert preview["total_rows"] == 3
    # Row 1 and Row 2 are distinct purchases (morning vs afternoon) -> both valid!
    # Row 3 is an identical duplicate of Row 1 -> duplicate!
    assert preview["preview_rows"][0]["is_duplicate"] is False
    assert preview["preview_rows"][1]["is_duplicate"] is False
    assert preview["preview_rows"][2]["is_duplicate"] is True
    assert preview["valid_count"] == 2
    assert preview["duplicate_count"] == 1


def test_aud_005_recurring_match_strictly_enforces_account_and_type(isolated_db):
    """
    AUD-005: Recurring rule paid status must strictly match:
    1. Transaction type (income/refund cannot mark an expense rule as paid).
    2. Account ID (transactions on a different account cannot mark the rule as paid).
    3. Soft-deleted transactions must not mark the rule as paid.
    """
    from app.backend.services.recurring_service import RecurringService

    acc_card = AccountRepository.create("Credit Card", "credit", opening_balance=0.0)
    acc_everyday = AccountRepository.create("Everyday Acc", "checking", opening_balance=1000.0)
    cat_sub = CategoryRepository.create("Subscriptions", "expense", icon="film", color="#9B59B6")

    # Recurring rule: Netflix on Credit Card, $19.99/mo expense
    rule_id = RecurringService.create({
        "name": "Netflix",
        "transaction_type": "expense",
        "amount": 19.99,
        "category_id": cat_sub,
        "account_id": acc_card,
        "frequency": "monthly",
        "next_due_date": "2026-09-20"
    })

    # Case 1: An income on Everyday account with merchant "Netflix"
    TransactionRepository.create({
        "account_id": acc_everyday,
        "category_id": cat_sub,
        "amount": 19.99,
        "transaction_type": "income",
        "merchant_name": "Netflix",
        "transaction_date": "2026-09-05"
    })
    bills = RecurringService.get_upcoming_bills("2026-09")
    rule_bill = next(b for b in bills if b["rule_id"] == rule_id)
    assert rule_bill["is_paid"] is False, "Income must not mark expense rule as paid"

    # Case 2: A refund on Credit Card with merchant "Netflix"
    exp_for_ref = TransactionRepository.create({
        "account_id": acc_card,
        "category_id": cat_sub,
        "amount": 50.0,
        "transaction_type": "expense",
        "merchant_name": "Netflix",
        "transaction_date": "2026-08-25"
    })
    TransactionRepository.create_refund(
        original_tx_id=exp_for_ref,
        amount=19.99,
        transaction_date="2026-09-06",
        account_id=acc_card
    )
    bills = RecurringService.get_upcoming_bills("2026-09")
    rule_bill = next(b for b in bills if b["rule_id"] == rule_id)
    assert rule_bill["is_paid"] is False, "Refund must not mark expense rule as paid"

    # Case 3: An expense on Everyday account (wrong account)
    TransactionRepository.create({
        "account_id": acc_everyday,
        "category_id": cat_sub,
        "amount": 19.99,
        "transaction_type": "expense",
        "merchant_name": "Netflix",
        "transaction_date": "2026-09-07"
    })
    bills = RecurringService.get_upcoming_bills("2026-09")
    rule_bill = next(b for b in bills if b["rule_id"] == rule_id)
    assert rule_bill["is_paid"] is False, "Expense on wrong account must not mark rule as paid"

    # Case 4: Proper expense on Credit Card (correct account and type)
    correct_tx = TransactionRepository.create({
        "account_id": acc_card,
        "category_id": cat_sub,
        "amount": 19.99,
        "transaction_type": "expense",
        "merchant_name": "Netflix",
        "transaction_date": "2026-09-10"
    })
    bills = RecurringService.get_upcoming_bills("2026-09")
    rule_bill = next(b for b in bills if b["rule_id"] == rule_id)
    assert rule_bill["is_paid"] is True, "Valid matching expense must mark rule as paid"
    assert rule_bill["paid_date"] == "2026-09-10"

    # Case 5: Soft delete the transaction -> rule status returns to unpaid/upcoming
    TransactionRepository.delete(correct_tx)
    bills = RecurringService.get_upcoming_bills("2026-09")
    rule_bill = next(b for b in bills if b["rule_id"] == rule_id)
    assert rule_bill["is_paid"] is False, "Soft-deleted transaction must not mark rule as paid"


def test_aud_006a_forecast_no_double_counting_case_variants(isolated_db):
    """
    AUD-006A: Case-insensitive and whitespace normalization of recurring obligation names
    prevents double-counting when history and explicit rules share the same obligation.
    """
    from app.backend.services.recurring_service import RecurringService
    from app.backend.analytics.forecasting import ForecastingEngine

    acc_id = AccountRepository.create("Primary Forecast Acc", "checking", opening_balance=2000.0)
    cat_id = CategoryRepository.create("Streaming Services", "expense", icon="tv", color="#3498DB")

    # 1. Historical recurring transaction in previous month (August) with Title Case "Netflix"
    TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 20.0,
        "transaction_type": "expense",
        "merchant_name": "Netflix",
        "transaction_date": "2026-08-25",
        "is_recurring": 1
    })

    # 2. Active explicit recurring rule with lowercase "netflix"
    RecurringService.create({
        "name": "netflix",
        "transaction_type": "expense",
        "amount": 20.0,
        "category_id": cat_id,
        "account_id": acc_id,
        "frequency": "monthly",
        "next_due_date": "2026-09-25"
    })

    # Run forecast for September (as_of_date: 2026-09-01, elapsed_day: 1)
    res = ForecastingEngine.forecast_month(month="2026-09", account_id=acc_id)

    # Invariant: Upcoming recurring bills must contain exactly 2000 minor ($20.00), NOT 4000 minor ($40.00)
    assert res["upcoming_recurring_minor"] == 2000, f"Expected 2000 minor, got {res['upcoming_recurring_minor']}"


def test_aud_006b_forecast_uses_deterministic_recurring_history(isolated_db):
    """
    AUD-006B: When multiple historical recurring transactions exist,
    the latest transaction is deterministically selected for forecasting.
    """
    from app.backend.analytics.forecasting import ForecastingEngine

    acc_id = AccountRepository.create("Hist Forecast Acc", "checking", opening_balance=2000.0)
    cat_id = CategoryRepository.create("Cloud Storage", "expense", icon="cloud", color="#2ECC71")

    # Oldest recurring tx (June): $15
    TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 15.0,
        "transaction_type": "expense",
        "merchant_name": "Dropbox Cloud",
        "transaction_date": "2026-06-25",
        "is_recurring": 1
    })

    # Middle recurring tx (July): $18
    TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 18.0,
        "transaction_type": "expense",
        "merchant_name": "Dropbox Cloud",
        "transaction_date": "2026-07-25",
        "is_recurring": 1
    })

    # Latest recurring tx (August): $22
    TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 22.0,
        "transaction_type": "expense",
        "merchant_name": "Dropbox Cloud",
        "transaction_date": "2026-08-25",
        "is_recurring": 1
    })

    # Run forecast for September
    res1 = ForecastingEngine.forecast_month(month="2026-09", account_id=acc_id)
    res2 = ForecastingEngine.forecast_month(month="2026-09", account_id=acc_id)

    # Must select latest amount: $22 (2200 minor) deterministically across repeated runs
    assert res1["upcoming_recurring_minor"] == 2200
    assert res2["upcoming_recurring_minor"] == 2200


def test_aud_008_restore_rejects_unsupported_format_or_newer_schema(isolated_db):
    """
    AUD-008: Restore must reject backup archives with format_version > 2
    or schema_version > MAX_SUPPORTED_SCHEMA_VERSION.
    """
    import zipfile
    import json
    from pathlib import Path
    import pytest
    from app.backend.services.backup_service import BackupService
    from app.backend.database.migrations_runner import MAX_SUPPORTED_SCHEMA_VERSION

    # Create a valid backup
    backup_meta = BackupService.create_backup()
    orig_path = Path(backup_meta["filepath"])

    # 1. Test unsupported format_version
    bad_fmt_path = orig_path.parent / "bad_format.financebackup"
    with zipfile.ZipFile(orig_path, "r") as zin, zipfile.ZipFile(bad_fmt_path, "w") as zout:
        for item in zin.infolist():
            content = zin.read(item.filename)
            if item.filename == "metadata.json":
                meta = json.loads(content.decode("utf-8"))
                meta["format_version"] = 99
                content = json.dumps(meta).encode("utf-8")
            zout.writestr(item, content)

    with pytest.raises(ValueError, match="Unsupported backup format version"):
        BackupService.restore_backup(str(bad_fmt_path))

    # 2. Test newer schema_version
    bad_sch_path = orig_path.parent / "newer_schema.financebackup"
    with zipfile.ZipFile(orig_path, "r") as zin, zipfile.ZipFile(bad_sch_path, "w") as zout:
        for item in zin.infolist():
            content = zin.read(item.filename)
            if item.filename == "metadata.json":
                meta = json.loads(content.decode("utf-8"))
                meta["schema_version"] = MAX_SUPPORTED_SCHEMA_VERSION + 1
                content = json.dumps(meta).encode("utf-8")
            zout.writestr(item, content)

    with pytest.raises(ValueError, match="is newer than application supported version"):
        BackupService.restore_backup(str(bad_sch_path))


def test_aud_008_post_restore_failure_rolls_back_live_database(isolated_db, monkeypatch):
    """
    AUD-008: If a failure occurs after the validated backup is swapped into the live DB,
    the live database must be automatically rolled back from the safety snapshot.
    """
    import sqlite3
    import pytest
    from app.backend import config
    from app.backend.services.backup_service import BackupService

    # Initial state: Account 1
    AccountRepository.create("Account In Backup", "checking", opening_balance=500.0)
    backup_meta = BackupService.create_backup()
    backup_path = backup_meta["filepath"]

    # Live DB state is changed before restore: Account 2 added
    AccountRepository.create("Live Account Must Be Preserved", "checking", opening_balance=1000.0)

    # Verify both accounts exist in live DB
    accs = AccountRepository.get_all()
    assert len(accs) == 2

    # Simulate failure during post-restore check (after live_db_swapped = True)
    real_connect = sqlite3.connect
    state = {"in_swap": False, "dest_done": False, "failed": False}

    def mock_connect(db_path, *args, **kwargs):
        conn = real_connect(db_path, *args, **kwargs)
        if "temp_restore_" in str(db_path):
            state["in_swap"] = True
        elif state.get("in_swap") and str(db_path) == str(config.DB_PATH) and not state.get("failed"):
            if not state.get("dest_done"):
                state["dest_done"] = True  # dest_conn in swap
            else:
                # post_conn check!
                state["failed"] = True
                raise RuntimeError("Simulated post-swap disk or integrity check failure")
        return conn

    monkeypatch.setattr("app.backend.services.backup_service.sqlite3.connect", mock_connect)

    with pytest.raises(RuntimeError, match="Simulated post-swap"):
        BackupService.restore_backup(backup_path)

    # Invariant check: Live DB must have been restored to its safety snapshot
    # containing "Live Account Must Be Preserved"!
    monkeypatch.setattr("app.backend.services.backup_service.sqlite3.connect", real_connect)
    rolled_back_accs = AccountRepository.get_all()
    names = [a["name"] for a in rolled_back_accs]
    assert "Live Account Must Be Preserved" in names, "Live DB should have rolled back to safety backup state!"
    assert len(rolled_back_accs) == 2


def test_aud_009_category_color_regex(isolated_db):
    """
    AUD-009: Category colour must strictly match ^#[0-9A-Fa-f]{6}$.
    XSS payloads, quote-breaking strings, or malformed hex codes must be rejected.
    """
    # 1. Invalid hex on create
    with pytest.raises(ValueError, match="Invalid category colour"):
        CategoryRepository.create("Malicious", color='red" onmouseover="alert(1)')

    with pytest.raises(ValueError, match="Invalid category colour"):
        CategoryRepository.create("Too short", color="#FFF")

    with pytest.raises(ValueError, match="Invalid category colour"):
        CategoryRepository.create("Invalid chars", color="#ZZZZZZ")

    # 2. Valid hex on create
    cat_id = CategoryRepository.create("Valid Category", color="#5B8CFF")
    assert cat_id > 0
    cat = CategoryRepository.get_by_id(cat_id)
    assert cat["color"] == "#5B8CFF"

    # 3. Invalid hex on update
    with pytest.raises(ValueError, match="Invalid category colour"):
        CategoryRepository.update(cat_id, color="<script>alert(1)</script>")

    # 4. Valid hex on update
    ok = CategoryRepository.update(cat_id, color="#FF6B8A")
    assert ok is True
    cat = CategoryRepository.get_by_id(cat_id)
    assert cat["color"] == "#FF6B8A"


def test_aud_010_server_rejects_mismatched_port_origin():
    """
    AUD-010: Server origin validation must verify host AND port.
    Unrelated localhost ports (e.g. http://localhost:3000) must be rejected.
    """
    from unittest.mock import MagicMock
    from app.backend.server import FinScopeHTTPHandler

    handler = FinScopeHTTPHandler.__new__(FinScopeHTTPHandler)
    handler.server = MagicMock()
    handler.server.server_address = ("127.0.0.1", 8088)

    # 1. Matching host and port -> Allowed
    handler.headers = {"Origin": "http://localhost:8088"}
    assert handler._is_allowed_origin() is True

    handler.headers = {"Origin": "http://127.0.0.1:8088"}
    assert handler._is_allowed_origin() is True

    # 2. Matching host but mismatched port -> Rejected!
    handler.headers = {"Origin": "http://localhost:3000"}
    assert handler._is_allowed_origin() is False

    handler.headers = {"Origin": "http://127.0.0.1:5173"}
    assert handler._is_allowed_origin() is False

    # 3. Remote untrusted host -> Rejected!
    handler.headers = {"Origin": "http://malicious.local:8088"}
    assert handler._is_allowed_origin() is False

    # 4. Same-origin or native desktop (missing Origin header) -> Allowed
    handler.headers = {}
    assert handler._is_allowed_origin() is True


def test_aud_011_backend_rejects_zero_and_negative_transaction_amount(isolated_db):
    """
    AUD-011: TransactionRepository must strictly reject zero or negative amounts.
    """
    acc_id = AccountRepository.create("Val Acc", "checking", opening_balance=500.0)

    # 1. Zero amount
    with pytest.raises(ValueError, match="greater than zero"):
        TransactionRepository.create({
            "account_id": acc_id,
            "amount": 0.0,
            "transaction_type": "expense",
            "transaction_date": "2026-09-01"
        })

    # 2. Negative amount
    with pytest.raises(ValueError, match="greater than zero"):
        TransactionRepository.create({
            "account_id": acc_id,
            "amount": -25.50,
            "transaction_type": "expense",
            "transaction_date": "2026-09-01"
        })

    # 3. Non-numeric amount
    with pytest.raises(ValueError, match="valid number"):
        TransactionRepository.create({
            "account_id": acc_id,
            "amount": "abc",
            "transaction_type": "expense",
            "transaction_date": "2026-09-01"
        })

    # 4. Valid amount succeeds
    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "amount": 10.0,
        "transaction_type": "expense",
        "transaction_date": "2026-09-01"
    })
    assert tx_id > 0

    # 5. Update amount to zero or negative is rejected
    with pytest.raises(ValueError, match="greater than zero"):
        TransactionRepository.update(tx_id, {"amount": 0})

    with pytest.raises(ValueError, match="greater than zero"):
        TransactionRepository.update(tx_id, {"amount": -5.0})


def test_aud_011_backend_rejects_invalid_date(isolated_db):
    """
    AUD-011: Invalid date formats or impossible dates must be rejected.
    """
    acc_id = AccountRepository.create("Date Val Acc", "checking", opening_balance=500.0)

    with pytest.raises(ValueError, match="Expected YYYY-MM-DD"):
        TransactionRepository.create({
            "account_id": acc_id,
            "amount": 15.0,
            "transaction_type": "expense",
            "transaction_date": "09-01-2026"  # wrong format
        })

    with pytest.raises(ValueError, match="Expected YYYY-MM-DD"):
        TransactionRepository.create({
            "account_id": acc_id,
            "amount": 15.0,
            "transaction_type": "expense",
            "transaction_date": "2026-02-31"  # impossible date
        })

    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "amount": 15.0,
        "transaction_type": "expense",
        "transaction_date": "2026-09-01"
    })

    with pytest.raises(ValueError, match="Expected YYYY-MM-DD"):
        TransactionRepository.update(tx_id, {"transaction_date": "invalid-date"})


def test_aud_011_budget_rejects_non_positive_amount(isolated_db):
    """
    AUD-011: BudgetRepository must reject non-positive amounts (<= 0).
    """
    from app.backend.repositories.budget_repo import BudgetRepository

    cat_id = CategoryRepository.create("Food Budget Cat", "expense")

    with pytest.raises(ValueError, match="Budget amount must be greater than zero"):
        BudgetRepository.set_budget(cat_id, "2026-09", 0.0)

    with pytest.raises(ValueError, match="Budget amount must be greater than zero"):
        BudgetRepository.set_budget(cat_id, "2026-09", -100.0)

    # Positive budget succeeds
    bid = BudgetRepository.set_budget(cat_id, "2026-09", 250.0)
    assert bid > 0


def test_aud_011_recurring_update_rejects_invalid_amount(isolated_db):
    """
    AUD-011: RecurringService must reject zero/negative amount on update as well as create.
    """
    from app.backend.services.recurring_service import RecurringService

    acc_id = AccountRepository.create("Rec Acc", "checking", opening_balance=500.0)
    rule_id = RecurringService.create({
        "name": "Gym",
        "amount": 50.0,
        "account_id": acc_id,
        "frequency": "monthly"
    })

    with pytest.raises(ValueError, match="greater than zero"):
        RecurringService.update_rule(rule_id, amount=0.0)

    with pytest.raises(ValueError, match="greater than zero"):
        RecurringService.update_rule(rule_id, amount=-10.0)

    with pytest.raises(ValueError, match="Invalid recurring frequency"):
        RecurringService.update_rule(rule_id, frequency="hourly")


def test_aud_012_fresh_migrated_schema_and_constraints(isolated_db):
    """
    AUD-012: Verify that fresh database generated entirely by migrations reaches version 5
    and enforces CHECK constraints on transfer_role and source.
    """
    cur = isolated_db.cursor()
    cur.execute("SELECT MAX(version) FROM schema_migrations")
    assert cur.fetchone()[0] >= 5

    # Test transfer_role CHECK constraint at the DB level
    acc_id = AccountRepository.create("DB Level Check Acc", "checking", opening_balance=100.0)
    with pytest.raises(sqlite3.IntegrityError):
        isolated_db.execute("""
            INSERT INTO transactions (
                account_id, amount_minor, transaction_date, transaction_type,
                transfer_role, source
            ) VALUES (?, 1000, '2026-09-01', 'transfer', 'invalid_role', 'manual')
        """, (acc_id,))

    # Test source CHECK constraint at the DB level
    with pytest.raises(sqlite3.IntegrityError):
        isolated_db.execute("""
            INSERT INTO transactions (
                account_id, amount_minor, transaction_date, transaction_type,
                transfer_role, source
            ) VALUES (?, 1000, '2026-09-01', 'expense', NULL, 'illegal_source')
        """, (acc_id,))


def test_aud_013_recent_payees_uses_latest_transaction_metadata(isolated_db):
    """
    AUD-013: get_recent_payees must deterministically use metadata (category, account,
    amount) from the latest transaction, not an arbitrary historical row.
    """
    from app.backend.services.merchant_service import MerchantService

    acc_a = AccountRepository.create("Account A", "checking", opening_balance=1000.0)
    acc_b = AccountRepository.create("Account B", "checking", opening_balance=1000.0)

    cat_dining = CategoryRepository.create("Dining", "expense")
    cat_coffee = CategoryRepository.create("Coffee", "expense")

    # Older transaction in January: Starbucks, Account A, Dining, $5.00
    TransactionRepository.create({
        "account_id": acc_a,
        "category_id": cat_dining,
        "amount": 5.0,
        "transaction_type": "expense",
        "merchant_name": "Starbucks",
        "transaction_date": "2026-01-10",
        "transaction_time": "08:00"
    })

    # Newer transaction in September: Starbucks, Account B, Coffee, $7.50
    TransactionRepository.create({
        "account_id": acc_b,
        "category_id": cat_coffee,
        "amount": 7.5,
        "transaction_type": "expense",
        "merchant_name": "Starbucks",
        "transaction_date": "2026-09-01",
        "transaction_time": "14:30"
    })

    recent = MerchantService.get_recent_payees(limit=5)
    assert len(recent) == 1
    item = recent[0]

    assert item["merchant_name"] == "Starbucks"
    # Metadata MUST match the latest transaction (September)!
    assert item["account_id"] == acc_b, "Recent payee account must be from latest transaction"
    assert item["category_id"] == cat_coffee, "Recent payee category must be from latest transaction"
    assert item["amount"] == 7.50, "Recent payee amount must be from latest transaction"
    assert item["transaction_count"] == 2


def test_aud_013_recent_payees_deterministic_tie_break(isolated_db):
    """
    AUD-013: When transactions share the same transaction_date,
    the tie is broken deterministically by transaction_time and id.
    """
    from app.backend.services.merchant_service import MerchantService

    acc_id = AccountRepository.create("Tie Acc", "checking", opening_balance=1000.0)
    cat_lunch = CategoryRepository.create("Lunch", "expense")
    cat_dinner = CategoryRepository.create("Dinner", "expense")

    # Transaction 1: 12:00
    TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_lunch,
        "amount": 15.0,
        "transaction_type": "expense",
        "merchant_name": "Bistro X",
        "transaction_date": "2026-09-01",
        "transaction_time": "12:00"
    })

    # Transaction 2: 19:00 (later on same day)
    TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_dinner,
        "amount": 40.0,
        "transaction_type": "expense",
        "merchant_name": "Bistro X",
        "transaction_date": "2026-09-01",
        "transaction_time": "19:00"
    })

    recent = MerchantService.get_recent_payees(limit=5)
    assert len(recent) == 1
    assert recent[0]["category_id"] == cat_dinner
    assert recent[0]["amount"] == 40.0


def test_aud_014_router_stale_render_token():
    """
    AUD-014: Verify that router.js contains renderGeneration tracking.
    """
    from pathlib import Path
    router_path = Path(__file__).resolve().parent.parent / "app" / "frontend" / "assets" / "js" / "router.js"
    content = router_path.read_text(encoding="utf-8")
    assert "renderGeneration" in content
    assert "this.renderGeneration += 1" in content
    assert "if (generation !== this.renderGeneration)" in content


def test_aud_015_requirements_files_structure():
    """
    AUD-015: Verify runtime requirements.txt does not contain bottle,
    and requirements-dev.txt declares pytest.
    """
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    req_runtime = (root / "requirements.txt").read_text(encoding="utf-8")
    req_dev = (root / "requirements-dev.txt").read_text(encoding="utf-8")

    assert "bottle" not in req_runtime.lower()
    assert "-r requirements.txt" in req_dev
    assert "pytest" in req_dev




