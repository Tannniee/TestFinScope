import pytest
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.services.transfer_service import TransferService
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.services.import_service import ImportService
from app.backend.services.backup_service import BackupService
from app.backend import config


def test_bug_001_duplicate_expense_succeeds(isolated_db):
    acc_id = AccountRepository.create("Checking", "checking", opening_balance=500.0)
    cat_id = CategoryRepository.create("Groceries", cat_type="expense", icon="🛒", color="#27ae60")

    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "amount": 25.50,
        "transaction_type": "expense",
        "category_id": cat_id,
        "merchant_name": "Supermarket",
        "description": "Weekly food",
        "transaction_date": "2026-09-01"
    })

    new_tx_id = TransactionRepository.duplicate(tx_id)
    assert new_tx_id is not None
    assert new_tx_id != tx_id

    copied = TransactionRepository.get_by_id(new_tx_id)
    assert copied["amount_minor"] == 2550
    assert copied["merchant_name"] == "Supermarket"
    assert "(Copy)" in copied["description"]
    assert copied["transaction_type"] == "expense"


def test_bug_001_duplicate_transfer_rejected_no_orphan(isolated_db):
    acc1_id = AccountRepository.create("Source Acc", "checking", opening_balance=1000.0)
    acc2_id = AccountRepository.create("Dest Acc", "savings", opening_balance=500.0)

    res = TransferService.create_transfer(
        from_account_id=acc1_id,
        to_account_id=acc2_id,
        amount=100.0,
        transaction_date="2026-09-01"
    )
    assert res["success"] is True
    outflow_id = res["outflow_tx_id"]
    inflow_id = res["inflow_tx_id"]

    # Attempt to duplicate transfer legs individually
    with pytest.raises(ValueError, match="Transfer transactions cannot be duplicated individually"):
        TransactionRepository.duplicate(outflow_id)

    with pytest.raises(ValueError, match="Transfer transactions cannot be duplicated individually"):
        TransactionRepository.duplicate(inflow_id)

    # Invariant: No orphan transfers exist in the database
    with isolated_db:
        cur = isolated_db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM active_transactions
            WHERE transaction_type = 'transfer' AND (transfer_group_id IS NULL OR transfer_role IS NULL)
        """)
        orphans = cur.fetchone()[0]
        assert orphans == 0


def test_bug_001_generic_create_rejects_transfer(isolated_db):
    acc_id = AccountRepository.create("Main", "checking", opening_balance=500.0)

    with pytest.raises(ValueError, match="Transfers must be created through TransferService"):
        TransactionRepository.create({
            "account_id": acc_id,
            "amount": 50.0,
            "transaction_type": "transfer",
            "transaction_date": "2026-09-01"
        })


def test_bug_002_generic_update_rejects_transfer(isolated_db):
    acc1_id = AccountRepository.create("Checking A", "checking", opening_balance=1000.0)
    acc2_id = AccountRepository.create("Savings B", "savings", opening_balance=500.0)

    res = TransferService.create_transfer(
        from_account_id=acc1_id,
        to_account_id=acc2_id,
        amount=100.0,
        transaction_date="2026-09-01"
    )
    tx_id = res["outflow_tx_id"]

    with pytest.raises(ValueError, match="Transfers must be updated through TransferService"):
        TransactionRepository.update(tx_id, {"amount": 200.0})


def test_bug_002_generic_update_rejects_refund(isolated_db):
    acc_id = AccountRepository.create("Card", "credit", opening_balance=0.0)
    cat_id = CategoryRepository.create("Retail", cat_type="expense")

    parent_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "transaction_type": "expense",
        "amount": 100.0,
        "transaction_date": "2026-09-01"
    })

    ref_id = TransactionRepository.create_refund(
        original_tx_id=parent_id,
        amount=20.0,
        transaction_date="2026-09-02",
        account_id=acc_id
    )

    with pytest.raises(ValueError, match="Refunds must be updated through TransactionRepository.update_refund"):
        TransactionRepository.update(ref_id, {"amount": 50.0})


def test_bug_002_generic_update_cannot_convert_type_to_specialised(isolated_db):
    acc_id = AccountRepository.create("Card", "credit", opening_balance=0.0)
    cat_id = CategoryRepository.create("Retail", cat_type="expense")

    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "transaction_type": "expense",
        "amount": 50.0,
        "transaction_date": "2026-09-01"
    })

    with pytest.raises(ValueError, match="Cannot convert a standard transaction into a specialised transfer"):
        TransactionRepository.update(tx_id, {"transaction_type": "transfer"})

    with pytest.raises(ValueError, match="Cannot convert a standard transaction into a specialised refund"):
        TransactionRepository.update(tx_id, {"transaction_type": "refund"})


def test_bug_002_specialised_updates_succeed(isolated_db):
    acc1_id = AccountRepository.create("Checking A", "checking", opening_balance=1000.0)
    acc2_id = AccountRepository.create("Savings B", "savings", opening_balance=500.0)
    cat_id = CategoryRepository.create("Electronics", cat_type="expense")

    # 1. Transfer update via TransferService
    transfer_res = TransferService.create_transfer(
        from_account_id=acc1_id,
        to_account_id=acc2_id,
        amount=100.0,
        transaction_date="2026-09-01"
    )
    t_success = TransferService.update_transfer(
        tx_id=transfer_res["outflow_tx_id"],
        amount=150.0,
        transaction_date="2026-09-02"
    )
    assert t_success is True
    t1 = TransactionRepository.get_by_id(transfer_res["outflow_tx_id"])
    t2 = TransactionRepository.get_by_id(transfer_res["inflow_tx_id"])
    assert t1["amount_minor"] == 15000
    assert t2["amount_minor"] == 15000

    # 2. Refund update via TransactionRepository.update_refund
    exp_id = TransactionRepository.create({
        "account_id": acc1_id,
        "category_id": cat_id,
        "transaction_type": "expense",
        "amount": 200.0,
        "transaction_date": "2026-09-01"
    })
    ref_id = TransactionRepository.create_refund(
        original_tx_id=exp_id,
        amount=50.0,
        transaction_date="2026-09-02",
        account_id=acc1_id
    )
    r_success = TransactionRepository.update_refund(
        tx_id=ref_id,
        amount=80.0,
        transaction_date="2026-09-03"
    )
    assert r_success is True
    r_updated = TransactionRepository.get_by_id(ref_id)
    assert r_updated["amount_minor"] == 8000


def test_bug_003a_amount_parsing_vnd_and_formats():
    # 1. VND format with dots as thousands
    val1, type1 = ImportService.parse_amount("50.000 VND")
    assert val1 == 50000.0

    val2, type2 = ImportService.parse_amount("1.500.000 đ")
    assert val2 == 1500000.0

    # 2. European format
    val3, type3 = ImportService.parse_amount("1.250,50 EUR")
    assert val3 == 1250.50

    # 3. US format
    val4, type4 = ImportService.parse_amount("1,250.50")
    assert val4 == 1250.50

    # 4. Accounting parentheses negative
    val5, type5 = ImportService.parse_amount("(123.45)")
    assert val5 == 123.45
    assert type5 == "expense"

    # 5. Invalid amount throws ValueError
    with pytest.raises(ValueError, match="Unable to parse amount"):
        ImportService.parse_amount("invalid-amount")


def test_bug_003b_invalid_date_not_turned_into_today(isolated_db):
    acc_id = AccountRepository.create("Checking Bank", "checking", opening_balance=500.0)

    csv_data = """Date,Payee,Amount
31-ABC-2025,Woolworths,-50.00
2026-09-01,Coles Supermarket,-30.00
"""
    mapping = {"date": "Date", "payee": "Payee", "amount": "Amount"}

    # Preview must flag invalid date
    preview = ImportService.preview_csv(csv_data, mapping=mapping, account_id=acc_id)
    assert preview["invalid_count"] == 1
    assert preview["valid_count"] == 1
    assert preview["preview_rows"][0]["is_valid"] is False
    assert "Invalid date" in preview["preview_rows"][0]["errors"][0]
    assert preview["preview_rows"][0]["date"] is None
    assert preview["preview_rows"][1]["is_valid"] is True

    # Commit must reject the invalid date row and only import the valid one
    commit_res = ImportService.commit_import(csv_data, mapping=mapping, account_id=acc_id)
    assert commit_res["imported_count"] == 1
    assert commit_res["invalid_count"] == 1

    # Invariant: Database must not contain Woolworths with today's date
    txs = TransactionRepository.get_all(account_id=acc_id)
    assert txs["total"] == 1
    assert txs["items"][0]["merchant_name"] == "Coles Supermarket"


def test_bug_003c_duplicate_detection_not_flagging_different_merchants(isolated_db):
    acc_id = AccountRepository.create("Everyday Acc", "checking", opening_balance=1000.0)

    # 1. Existing purchase at Woolworths on 2026-09-01 for $25.00
    TransactionRepository.create({
        "account_id": acc_id,
        "amount": 25.0,
        "transaction_type": "expense",
        "merchant_name": "Woolworths",
        "transaction_date": "2026-09-01"
    })

    # CSV has two transactions on 2026-09-01 with the same amount ($25.00):
    # - Row 1: Chemist Warehouse (DIFFERENT merchant) -> NOT duplicate
    # - Row 2: Woolworths (SAME merchant) -> DUPLICATE
    csv_data = """Date,Payee,Amount
2026-09-01,Chemist Warehouse,-25.00
2026-09-01,Woolworths,-25.00
"""
    mapping = {"date": "Date", "payee": "Payee", "amount": "Amount"}

    preview = ImportService.preview_csv(csv_data, mapping=mapping, account_id=acc_id)
    assert preview["duplicate_count"] == 1
    assert preview["valid_count"] == 1

    # First row (Chemist Warehouse) is NOT duplicate
    assert preview["preview_rows"][0]["payee"] == "Chemist Warehouse"
    assert preview["preview_rows"][0]["is_duplicate"] is False

    # Second row (Woolworths) IS duplicate
    assert preview["preview_rows"][1]["payee"] == "Woolworths"
    assert preview["preview_rows"][1]["is_duplicate"] is True

    # Commit with deduplicate=True imports Chemist Warehouse and skips Woolworths
    commit_res = ImportService.commit_import(csv_data, mapping=mapping, account_id=acc_id, deduplicate=True)
    assert commit_res["imported_count"] == 1
    assert commit_res["skipped_duplicates"] == 1

    txs = TransactionRepository.get_all(account_id=acc_id)
    assert txs["total"] == 2 # 1 pre-existing Woolworths + 1 imported Chemist Warehouse


def test_bug_004_restore_invalid_backup_preserves_root_exception(isolated_db):
    import zipfile

    acc_id = AccountRepository.create("Safe Acc", "checking", opening_balance=999.0)
    config.BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    corrupt_zip = config.BACKUPS_DIR / "corrupt_test.financebackup"

    # Create a corrupted zip with empty dummy file instead of valid finance.db
    with zipfile.ZipFile(corrupt_zip, "w") as zf:
        zf.writestr("not_finance.db", b"garbage data")

    # Restoring must raise ValueError, and critically MUST NOT throw NameError (unbound logger)
    with pytest.raises(ValueError, match="Invalid backup archive: finance.db missing"):
        BackupService.restore_backup(str(corrupt_zip))

    # Live database must remain completely intact
    bal = AccountRepository.get_balance(acc_id)
    assert bal == 999.0


def test_bug_005_frontend_xss_prevention_in_templates(isolated_db):
    """
    BUG-005: Ensure user-supplied account/category names with XSS payloads
    are safely handled in both backend persistence and frontend JS templates.
    """
    from app.backend.repositories.category_repo import CategoryRepository
    import re

    # 1. Backend safely stores dangerous characters verbatim
    xss_account = "<img src=x onerror=alert('xss-acc')>"
    xss_category = "</option><script>alert('xss-cat')</script>"

    acc_id = AccountRepository.create(xss_account, "checking", opening_balance=100.0)
    cat_id = CategoryRepository.create(xss_category, "expense", icon="alert", color="#FF0000")

    acc = AccountRepository.get_by_id(acc_id)
    cat = CategoryRepository.get_by_id(cat_id)
    assert acc["name"] == xss_account
    assert cat["name"] == xss_category

    # 2. Frontend inspection: verify no raw, unescaped interpolation in modal dropdowns & filter bars
    modals_js = (config.PROJECT_ROOT / "app" / "frontend" / "assets" / "js" / "components" / "modals.js").read_text(encoding="utf-8")
    assert "${escapeHtml(a.name)}" in modals_js
    assert "${escapeHtml(a.account_type)}" in modals_js
    assert "${escapeHtml(c.name)}" in modals_js
    assert "${a.name} (" not in modals_js

    tx_js = (config.PROJECT_ROOT / "app" / "frontend" / "assets" / "js" / "pages" / "transactions.js").read_text(encoding="utf-8")
    assert "${escapeHtml(c.name)}" in tx_js
    assert "${escapeHtml(a.name)}" in tx_js
    # Ensure raw unescaped select options do not exist
    assert ">${c.name}</option>" not in tx_js
    assert ">${a.name}</option>" not in tx_js

    budget_js = (config.PROJECT_ROOT / "app" / "frontend" / "assets" / "js" / "pages" / "budget.js").read_text(encoding="utf-8")
    assert "escapeHtml" in budget_js
    assert "${escapeHtml(cat.category_name)}" in budget_js
    assert "data-name=\"${escapeHtml(cat.category_name)}\"" in budget_js
    assert ">${cat.category_name}</div>" not in budget_js


