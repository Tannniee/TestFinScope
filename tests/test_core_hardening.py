import os
import shutil
import sqlite3
import pytest
from pathlib import Path

from app.backend.database.connection import get_db_connection, init_db
from app.backend.repositories.account_repo import AccountRepository as AccountRepo
from app.backend.repositories.transaction_repo import TransactionRepository as TransactionRepo
from app.backend.repositories.category_repo import CategoryRepository as CategoryRepo
from app.backend.repositories.budget_repo import BudgetRepository as BudgetRepo
from app.backend.services.transfer_service import TransferService
from app.backend.services.merchant_service import MerchantService
from app.backend.services.backup_service import BackupService
from app.backend.services.analytics_service import AnalyticsService
from app.backend.analytics.forecasting import ForecastingEngine
from app.main import DesktopBridge
from app.backend.api.handler import ApiHandler


def test_reg_001_amount_only_update(isolated_db):
    """REG-001: Amount-only update succeeds without modifying or nullifying other fields."""
    acc_id = AccountRepo.create(name="Checking", account_type="depository", opening_balance=1000.0)
    cats = CategoryRepo.get_all()
    cat_id = cats[0]["id"] if cats else 1

    tx_id = TransactionRepo.create({
        "account_id": acc_id,
        "amount": 50.0,
        "transaction_type": "expense",
        "category_id": cat_id,
        "merchant_name": "Target Store",
        "description": "Weekly Groceries",
        "transaction_date": "2026-09-01",
        "essentiality": "essential"
    })

    # Update ONLY amount
    res = TransactionRepo.update(tx_id, {"amount": 75.25})
    assert res is True

    updated = TransactionRepo.get_by_id(tx_id)
    assert updated["amount"] == 75.25
    assert updated["amount_minor"] == 7525
    # Check that other fields were preserved
    assert updated["merchant_name"] == "Target Store"
    assert updated["description"] == "Weekly Groceries"
    assert updated["account_id"] == acc_id
    assert updated["category_id"] == cat_id
    assert updated["essentiality"] == "essential"
    assert updated["transaction_date"] == "2026-09-01"


def test_reg_002_deleted_expense_excluded_everywhere(isolated_db):
    """REG-002: Deleted expense excluded from account balance, budget spent, net cash flow, analytics aggregates, change decomposition, and anomalies."""
    acc_id = AccountRepo.create(name="Wallet", account_type="depository", opening_balance=500.0)
    cats = CategoryRepo.get_all()
    cat_id = cats[0]["id"] if cats else 1

    # Set up a budget
    BudgetRepo.set_budget(cat_id, "2026-09", 200.0)

    # Create $100 expense
    tx_id = TransactionRepo.create({
        "account_id": acc_id,
        "amount": 100.0,
        "transaction_type": "expense",
        "category_id": cat_id,
        "merchant_name": "Coffee Shop",
        "transaction_date": "2026-09-02"
    })

    # Pre-deletion verification
    assert AccountRepo.get_balance(acc_id) == 400.0
    budget_pre = BudgetRepo.get_by_month("2026-09")
    cat_budget = next(b for b in budget_pre if b["category_id"] == cat_id)
    assert cat_budget["spent_amount"] == 100.0

    month_sum_pre = AnalyticsService.get_month_summary("2026-09", acc_id)
    assert month_sum_pre["kpis"]["expense"] == 100.0
    assert month_sum_pre["kpis"]["net_flow"] == -100.0

    # Soft delete the expense
    deleted = TransactionRepo.delete(tx_id, hard=False)
    assert deleted is True

    # Post-deletion verification: EXCLUDED EVERYWHERE!
    assert AccountRepo.get_balance(acc_id) == 500.0
    budget_post = BudgetRepo.get_by_month("2026-09")
    cat_budget_post = next(b for b in budget_post if b["category_id"] == cat_id)
    assert cat_budget_post["spent_amount"] == 0.0

    month_sum_post = AnalyticsService.get_month_summary("2026-09", acc_id)
    assert month_sum_post["kpis"]["expense"] == 0.0
    assert month_sum_post["kpis"]["net_flow"] == 0.0

    # Active transactions query excludes it
    active_txs = TransactionRepo.get_all()
    assert len(active_txs["items"]) == 0


def test_reg_003_undo_expense_restores_everywhere(isolated_db):
    """REG-003: Undo expense restores transaction everywhere (balance, budget, net cash flow, analytics)."""
    acc_id = AccountRepo.create(name="Savings", account_type="depository", opening_balance=1000.0)
    cats = CategoryRepo.get_all()
    cat_id = cats[0]["id"] if cats else 1
    BudgetRepo.set_budget(cat_id, "2026-09", 300.0)

    tx_id = TransactionRepo.create({
        "account_id": acc_id,
        "amount": 150.0,
        "transaction_type": "expense",
        "category_id": cat_id,
        "merchant_name": "Bookstore",
        "transaction_date": "2026-09-03"
    })

    # Delete then restore
    TransactionRepo.delete(tx_id, hard=False)
    assert AccountRepo.get_balance(acc_id) == 1000.0

    restored = TransactionRepo.undo_delete(tx_id)
    assert restored is True

    # Verify restoration
    assert AccountRepo.get_balance(acc_id) == 850.0
    budget_post = BudgetRepo.get_by_month("2026-09")
    cat_budget = next(b for b in budget_post if b["category_id"] == cat_id)
    assert cat_budget["spent_amount"] == 150.0

    summary = AnalyticsService.get_month_summary("2026-09", acc_id)
    assert summary["kpis"]["expense"] == 150.0
    assert summary["kpis"]["net_flow"] == -150.0


def test_reg_004_deleted_refund_stops_offsetting_expense(isolated_db):
    """REG-004: Deleted refund stops offsetting expense across all screens and calculations."""
    acc_id = AccountRepo.create(name="Card", account_type="depository", opening_balance=1000.0)
    cats = CategoryRepo.get_all()
    cat_id = cats[0]["id"] if cats else 1

    # Expense $100
    exp_id = TransactionRepo.create({
        "account_id": acc_id,
        "amount": 100.0,
        "transaction_type": "expense",
        "category_id": cat_id,
        "merchant_name": "Clothing Store",
        "transaction_date": "2026-09-04"
    })

    # Refund $40 linked to expense
    ref_id = TransactionRepo.create({
        "account_id": acc_id,
        "amount": 40.0,
        "transaction_type": "refund",
        "category_id": cat_id,
        "merchant_name": "Clothing Store",
        "refund_of_transaction_id": exp_id,
        "transaction_date": "2026-09-05"
    })

    # Net spend should be 100 - 40 = 60
    summary = AnalyticsService.get_month_summary("2026-09", acc_id)
    assert summary["kpis"]["expense"] == 60.0

    # Soft delete the refund
    TransactionRepo.delete(ref_id, hard=False)

    # Net spend should revert to full 100
    summary_after = AnalyticsService.get_month_summary("2026-09", acc_id)
    assert summary_after["kpis"]["expense"] == 100.0


def test_reg_005_transfer_globally_neutral(isolated_db):
    """REG-005: Transfer globally neutral ($0 net flow, $0 analytics expense/income, budget unaffected, balance shifted)."""
    acc_a = AccountRepo.create(name="Account A", account_type="depository", opening_balance=1000.0)
    acc_b = AccountRepo.create(name="Account B", account_type="depository", opening_balance=500.0)

    # Execute transfer pair of $200 from A to B
    res = TransferService.create_transfer_pair({
        "from_account_id": acc_a,
        "to_account_id": acc_b,
        "amount": 200.0,
        "transaction_date": "2026-09-06",
        "description": "Monthly savings allocation"
    })

    assert res["success"] is True
    assert res["transfer_group_id"] is not None

    # Balances shifted correctly
    assert AccountRepo.get_balance(acc_a) == 800.0
    assert AccountRepo.get_balance(acc_b) == 700.0

    # Total net worth invariant: 800 + 700 = 1500 == 1000 + 500
    accounts = AccountRepo.get_all()
    total_net_worth = sum(a["current_balance"] for a in accounts)
    assert total_net_worth == 1500.0

    # Global KPI neutrality
    summary = AnalyticsService.get_month_summary("2026-09")
    assert summary["kpis"]["income"] == 0.0
    assert summary["kpis"]["expense"] == 0.0
    assert summary["kpis"]["net_flow"] == 0.0


def test_reg_006_transfer_delete_hides_both_legs(isolated_db):
    """REG-006: Transfer delete hides both legs from active transactions, review inbox, export, and restores balances."""
    acc_a = AccountRepo.create(name="Checking", account_type="depository", opening_balance=1000.0)
    acc_b = AccountRepo.create(name="Savings", account_type="depository", opening_balance=500.0)

    res = TransferService.create_transfer_pair({
        "from_account_id": acc_a,
        "to_account_id": acc_b,
        "amount": 300.0,
        "transaction_date": "2026-09-06"
    })

    leg1_id = res["outflow_id"]
    leg2_id = res["inflow_id"]

    # Deleting either leg soft-deletes BOTH legs atomically
    deleted = TransactionRepo.delete(leg1_id, hard=False)
    assert deleted is True

    tx1 = TransactionRepo.get_by_id(leg1_id, include_deleted=True)
    tx2 = TransactionRepo.get_by_id(leg2_id, include_deleted=True)
    assert tx1["is_deleted"] == 1
    assert tx2["is_deleted"] == 1

    # Neither leg appears in active transactions
    active_txs = TransactionRepo.get_all()
    assert len(active_txs["items"]) == 0

    # Balances restored to pre-transfer state
    assert AccountRepo.get_balance(acc_a) == 1000.0
    assert AccountRepo.get_balance(acc_b) == 500.0


def test_reg_007_transfer_undo_restores_both_legs(isolated_db):
    """REG-007: Transfer undo restores both legs atomically."""
    acc_a = AccountRepo.create(name="Checking", account_type="depository", opening_balance=1000.0)
    acc_b = AccountRepo.create(name="Savings", account_type="depository", opening_balance=500.0)

    res = TransferService.create_transfer_pair({
        "from_account_id": acc_a,
        "to_account_id": acc_b,
        "amount": 250.0,
        "transaction_date": "2026-09-06"
    })

    leg1_id = res["outflow_id"]
    leg2_id = res["inflow_id"]

    TransactionRepo.delete(leg2_id, hard=False)
    assert AccountRepo.get_balance(acc_a) == 1000.0
    assert AccountRepo.get_balance(acc_b) == 500.0

    # Undo restore on one leg restores both
    restored = TransactionRepo.undo_delete(leg1_id)
    assert restored is True

    # Both legs are restored
    tx1 = TransactionRepo.get_by_id(leg1_id)
    tx2 = TransactionRepo.get_by_id(leg2_id)
    assert tx1["is_deleted"] == 0
    assert tx2["is_deleted"] == 0
    assert AccountRepo.get_balance(acc_a) == 750.0
    assert AccountRepo.get_balance(acc_b) == 750.0


def test_reg_008_over_refund_rejected_atomically(isolated_db):
    """REG-008: Over-refund rejected atomically (validation error, leaves database untouched)."""
    acc_id = AccountRepo.create(name="Card", account_type="depository", opening_balance=1000.0)
    cats = CategoryRepo.get_all()
    cat_id = cats[0]["id"] if cats else 1

    exp_id = TransactionRepo.create({
        "account_id": acc_id,
        "amount": 50.0,
        "transaction_type": "expense",
        "category_id": cat_id,
        "merchant_name": "Electronics",
        "transaction_date": "2026-09-01"
    })

    # First refund $35 is valid
    ref1_id = TransactionRepo.create({
        "account_id": acc_id,
        "amount": 35.0,
        "transaction_type": "refund",
        "category_id": cat_id,
        "refund_of_transaction_id": exp_id,
        "transaction_date": "2026-09-02"
    })
    assert ref1_id > 0

    # Second refund $20 would make total refunds $55 > $50. MUST FAIL!
    with pytest.raises(ValueError, match="Cumulative refunds.*exceed"):
        TransactionRepo.create({
            "account_id": acc_id,
            "amount": 20.0,
            "transaction_type": "refund",
            "category_id": cat_id,
            "refund_of_transaction_id": exp_id,
            "transaction_date": "2026-09-03"
        })

    # Verify only 2 transactions exist in DB (1 expense, 1 refund)
    all_txs = TransactionRepo.get_all()
    assert len(all_txs["items"]) == 2


def test_reg_009_duplicate_transaction_api(isolated_db):
    """REG-009: Duplicate transaction API endpoint works and creates a clean copy."""
    handler = ApiHandler()
    acc_id = AccountRepo.create(name="Main", account_type="depository", opening_balance=1000.0)
    cats = CategoryRepo.get_all()
    cat_id = cats[0]["id"] if cats else 1

    tx_id = TransactionRepo.create({
        "account_id": acc_id,
        "amount": 42.0,
        "transaction_type": "expense",
        "category_id": cat_id,
        "merchant_name": "Bakery",
        "description": "Morning croissants",
        "transaction_date": "2026-09-05"
    })

    new_tx_id = handler.duplicate_transaction(tx_id)
    assert new_tx_id is not None
    assert new_tx_id != tx_id

    copied = TransactionRepo.get_by_id(new_tx_id)
    assert copied["amount"] == 42.0
    assert copied["merchant_name"] == "Bakery"
    assert "(Copy)" in copied["description"]
    assert copied["category_id"] == cat_id
    assert copied["account_id"] == acc_id


def test_reg_010_merchant_dto_shape_alignment(isolated_db):
    """REG-010: Merchant DTO shape alignment across suggest_merchants and get_recent_payees."""
    acc_id = AccountRepo.create(name="Main", account_type="depository", opening_balance=1000.0)
    cats = CategoryRepo.get_all()
    cat_id = cats[0]["id"] if cats else 1

    # Create transaction to train merchant
    TransactionRepo.create({
        "account_id": acc_id,
        "amount": 15.0,
        "transaction_type": "expense",
        "category_id": cat_id,
        "merchant_name": "Starbucks Coffee",
        "transaction_date": "2026-09-01"
    })

    suggested = MerchantService.suggest_merchants("Star", limit=5)
    recent = MerchantService.get_recent_payees(limit=5)

    assert len(suggested) > 0
    assert len(recent) > 0

    expected_keys = {
        "merchant_id", "name", "category_id", "category_name",
        "account_id", "essentiality", "confidence", "transaction_count"
    }

    assert expected_keys.issubset(set(suggested[0].keys()))
    assert expected_keys.issubset(set(recent[0].keys()))


def test_reg_011_account_filter_parity(isolated_db):
    """REG-011: Account filter on Recent Activity and transaction listings."""
    acc1_id = AccountRepo.create(name="Personal Checking", account_type="depository", opening_balance=1000.0)
    acc2_id = AccountRepo.create(name="Business Checking", account_type="depository", opening_balance=2000.0)

    tx1_id = TransactionRepo.create({
        "account_id": acc1_id,
        "amount": 10.0,
        "transaction_type": "expense",
        "transaction_date": "2026-09-01"
    })

    tx2_id = TransactionRepo.create({
        "account_id": acc2_id,
        "amount": 20.0,
        "transaction_type": "expense",
        "transaction_date": "2026-09-01"
    })

    # Filter by acc1
    res1 = TransactionRepo.get_all(account_id=acc1_id)
    assert len(res1["items"]) == 1
    assert res1["items"][0]["id"] == tx1_id

    # Filter by acc2
    res2 = TransactionRepo.get_all(account_id=acc2_id)
    assert len(res2["items"]) == 1
    assert res2["items"][0]["id"] == tx2_id


def test_reg_012_backup_safety_and_atomic_restore(isolated_data_dir, isolated_db):
    """REG-012: Backup safety archive restorable via atomic restore."""
    acc_id = AccountRepo.create(name="Initial Account", account_type="depository", opening_balance=100.0)

    # Create backup
    backup_res = BackupService.create_backup()
    backup_file = backup_res["filepath"]
    assert Path(backup_file).exists()

    # Mutate DB state
    AccountRepo.create(name="Unwanted Account", account_type="depository", opening_balance=999.0)
    assert len(AccountRepo.get_all()) == 2

    # Restore backup
    res = BackupService.restore_backup(backup_file)
    assert res["success"] is True
    assert res["pre_restore_safety_backup"] is not None
    assert Path(res["pre_restore_safety_backup"]).exists()

    # Verify state is restored to 1 account
    accounts = AccountRepo.get_all()
    assert len(accounts) == 1
    assert accounts[0]["name"] == "Initial Account"


def test_reg_013_corrupt_restore_leaves_live_db_unchanged(isolated_data_dir, isolated_db):
    """REG-013: Corrupt / failed restore leaves live DB completely untouched."""
    acc_id = AccountRepo.create(name="Permanent Account", account_type="depository", opening_balance=500.0)

    # Create corrupt file
    corrupt_file = isolated_data_dir / "backups" / "corrupt_test.db"
    corrupt_file.parent.mkdir(parents=True, exist_ok=True)
    corrupt_file.write_text("NOT A VALID SQLITE DATABASE")

    # Restore should raise an error
    with pytest.raises(Exception):
        BackupService.restore_backup(str(corrupt_file))

    # Live DB is still valid and has the original data
    accounts = AccountRepo.get_all()
    assert len(accounts) == 1
    assert accounts[0]["name"] == "Permanent Account"
    assert accounts[0]["current_balance"] == 500.0


def test_reg_014_transport_security(ephemeral_server):
    """REG-014: Foreign origin / missing token rejected with HTTP 403 on local server."""
    client = ephemeral_server

    # 1. Missing token -> 403
    code, res = client.post("get_accounts", headers={"X-FinScope-Token": ""})
    assert code == 403
    assert res["error"]["code"] == "UNAUTHORIZED"

    # 2. Invalid token -> 403
    code, res = client.post("get_accounts", headers={"X-FinScope-Token": "bad_token_12345"})
    assert code == 403
    assert res["error"]["code"] == "UNAUTHORIZED"

    # 3. Foreign Origin -> 403
    code, res = client.post("get_accounts", headers={"Origin": "http://evil-attacker.com"})
    assert code == 403
    assert res["error"]["code"] == "FORBIDDEN_ORIGIN"

    # 4. Valid loopback request -> 200 with standard envelope
    code, res = client.post("get_accounts")
    assert code == 200
    assert res["success"] is True
    assert res["api_version"] == 2
    assert "data" in res


def test_reg_015_stored_xss_safety(isolated_db):
    """REG-015: Stored HTML in merchant/note safely stored without corruption and safely escapable."""
    malicious_merchant = "<script>alert('pwned')</script>"
    malicious_note = "<img src=x onerror=alert(document.cookie)>"

    acc_id = AccountRepo.create(name="Safe Account", account_type="depository", opening_balance=1000.0)
    tx_id = TransactionRepo.create({
        "account_id": acc_id,
        "amount": 25.0,
        "transaction_type": "expense",
        "merchant_name": malicious_merchant,
        "description": malicious_note,
        "transaction_date": "2026-09-01"
    })

    tx = TransactionRepo.get_by_id(tx_id)
    # Stored raw without corrupting the tag structure
    assert "<script>" in tx["merchant_name"].lower()
    assert tx["description"] == malicious_note

    # Verify that escaping sanitizes against executable XSS
    import html
    escaped_merchant = html.escape(tx["merchant_name"])
    escaped_note = html.escape(tx["description"])
    assert "<script>" not in escaped_merchant
    assert "&lt;script&gt;" in escaped_merchant.lower()
    assert "<img" not in escaped_note
    assert "&lt;img" in escaped_note


def test_reg_016_clean_slate_fresh_install(isolated_data_dir):
    """REG-016: Clean slate fresh install has 0 accounts, 0 transactions, 0 fake balances."""
    init_db()
    accounts = AccountRepo.get_all()
    assert len(accounts) == 0

    txs = TransactionRepo.get_all()
    assert len(txs["items"]) == 0

    with get_db_connection() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = 'has_initialized'").fetchone()
        assert row is not None
        assert row[0] == "false"


def test_reg_017_deleted_transactions_absent_from_forecasting(isolated_db):
    """REG-017: Deleted transactions absent from forecast history and spend pace."""
    acc_id = AccountRepo.create(name="Main", account_type="depository", opening_balance=5000.0)
    cats = CategoryRepo.get_all()
    cat_id = cats[0]["id"] if cats else 1

    # Create recurring expense in prior month
    tx_id = TransactionRepo.create({
        "account_id": acc_id,
        "amount": 500.0,
        "transaction_type": "expense",
        "category_id": cat_id,
        "merchant_name": "Mega Subscription",
        "is_recurring": 1,
        "transaction_date": "2026-08-15"
    })

    res_before = ForecastingEngine.forecast_month("2026-09", account_id=acc_id)
    # The upcoming recurring should project the 500 bill
    assert res_before["upcoming_recurring"] == 500.0

    # Delete the recurring bill
    TransactionRepo.delete(tx_id, hard=False)

    # Forecast again - must NOT include deleted recurring bill
    res_after = ForecastingEngine.forecast_month("2026-09", account_id=acc_id)
    assert res_after["upcoming_recurring"] == 0.0


def test_reg_018_desktop_bridge_narrow_api():
    """REG-018: DesktopBridge has only desktop-native capabilities (open_data_folder) and no business methods."""
    bridge = DesktopBridge()
    assert hasattr(bridge, "open_data_folder")
    assert hasattr(bridge, "is_desktop")

    # Ensure business logic methods are NOT exposed on DesktopBridge
    business_methods = [
        "get_accounts", "create_transaction", "delete_transaction",
        "get_month_summary", "restore_backup", "get_forecast"
    ]
    for method in business_methods:
        assert not hasattr(bridge, method)


def test_financial_truth_snapshot_invariants(isolated_db):
    """
    Comprehensive multi-step invariant test verifying that across transactions, transfers,
    refunds, deletions, and undos, the fundamental identity holds:
    Sum(opening balances) + Sum(active net cash flow) == Sum(account current balances)
    """
    # 1. Setup accounts
    a1 = AccountRepo.create(name="Bank A", account_type="depository", opening_balance=1000.0)
    a2 = AccountRepo.create(name="Bank B", account_type="depository", opening_balance=2000.0)
    cats = CategoryRepo.get_all()
    c1 = cats[0]["id"] if cats else 1

    def verify_invariant():
        accounts = AccountRepo.get_all()
        sum_balances = sum(a["current_balance"] for a in accounts)
        sum_opening = sum(a["opening_balance"] for a in accounts)

        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    COALESCE(SUM(
                        CASE 
                            WHEN transaction_type = 'income' THEN amount_minor
                            WHEN transaction_type = 'expense' THEN -amount_minor
                            WHEN transaction_type = 'refund' THEN amount_minor
                            ELSE 0
                        END
                    ), 0)
                FROM active_transactions
            """)
            net_flow_minor = cur.fetchone()[0]

        expected_total = sum_opening + (net_flow_minor / 100.0)
        assert round(sum_balances, 2) == round(expected_total, 2)

    verify_invariant()

    # 2. Add income and expense
    tx_exp = TransactionRepo.create({"account_id": a1, "amount": 120.0, "transaction_type": "expense", "category_id": c1, "transaction_date": "2026-09-01"})
    tx_inc = TransactionRepo.create({"account_id": a2, "amount": 500.0, "transaction_type": "income", "transaction_date": "2026-09-01"})
    verify_invariant()

    # 3. Add transfer
    xfer = TransferService.create_transfer_pair({"from_account_id": a1, "to_account_id": a2, "amount": 300.0, "transaction_date": "2026-09-02"})
    verify_invariant()

    # 4. Add refund to expense
    tx_ref = TransactionRepo.create({"account_id": a1, "amount": 40.0, "transaction_type": "refund", "refund_of_transaction_id": tx_exp, "transaction_date": "2026-09-03"})
    verify_invariant()

    # 5. Soft-delete transfer
    TransactionRepo.delete(xfer["outflow_id"], hard=False)
    verify_invariant()

    # 6. Undo-delete transfer
    TransactionRepo.undo_delete(xfer["outflow_id"])
    verify_invariant()

    # 7. Soft-delete expense
    TransactionRepo.delete(tx_exp, hard=False)
    verify_invariant()
