import pytest
import io
import csv
from datetime import datetime, date
from app.backend.services.transfer_service import TransferService
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.repositories.budget_repo import BudgetRepository
from app.backend.services.budget_service import BudgetService
from app.backend.services.backup_service import BackupService
from app.backend.services.import_service import ImportService
from app.backend.services.recurring_service import RecurringService
from app.backend.analytics.forecasting import ForecastingEngine
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository


def test_stage1_update_transfer_atomic_and_account_switch(isolated_db):
    # Setup accounts
    acc1_id = AccountRepository.create("Bank Checking", "checking", opening_balance=1000.0)
    acc2_id = AccountRepository.create("Savings Goal", "savings", opening_balance=500.0)
    acc3_id = AccountRepository.create("Emergency Fund", "savings", opening_balance=200.0)

    # 1. Create transfer from acc1 to acc2 ($100.00)
    create_res = TransferService.create_transfer(
        from_account_id=acc1_id,
        to_account_id=acc2_id,
        amount=100.0,
        transaction_date="2026-09-01",
        description="Transfer to Savings",
        note="Initial deposit"
    )
    assert create_res["success"] is True
    tx1_id = create_res["outflow_tx_id"]
    tx2_id = create_res["inflow_tx_id"]

    # Verify initial balances
    bal1 = AccountRepository.get_balance(acc1_id)
    bal2 = AccountRepository.get_balance(acc2_id)
    bal3 = AccountRepository.get_balance(acc3_id)
    assert bal1 == 900.0  # 1000 - 100
    assert bal2 == 600.0  # 500 + 100
    assert bal3 == 200.0

    # 2. Update transfer: change destination to acc3 and amount to $150.00
    success = TransferService.update_transfer(
        tx_id=tx1_id,
        from_account_id=acc1_id,
        to_account_id=acc3_id,
        amount=150.0,
        transaction_date="2026-09-02",
        description="Transfer to Emergency",
        note="Adjusted plan"
    )
    assert success is True

    # Check updated transactions
    t1 = TransactionRepository.get_by_id(tx1_id)
    t2 = TransactionRepository.get_by_id(tx2_id)
    assert t1["amount_minor"] == 15000
    assert t2["amount_minor"] == 15000
    assert t1["account_id"] == acc1_id
    assert t2["account_id"] == acc3_id

    # Verify updated balances
    bal1_new = AccountRepository.get_balance(acc1_id)
    bal2_new = AccountRepository.get_balance(acc2_id)
    bal3_new = AccountRepository.get_balance(acc3_id)
    assert bal1_new == 850.0  # 1000 - 150
    assert bal2_new == 500.0  # Reverted back to 500
    assert bal3_new == 350.0  # 200 + 150

    # Net total cash across accounts remains unchanged ($1700.00)
    assert (bal1_new + bal2_new + bal3_new) == 1700.0

    # Test error: from_account == to_account
    with pytest.raises(ValueError, match="Source and destination accounts must be different"):
        TransferService.update_transfer(
            tx_id=tx1_id,
            from_account_id=acc1_id,
            to_account_id=acc1_id,
            amount=100.0,
            transaction_date="2026-09-02"
        )


def test_stage1_update_refund_enforces_parent_boundary(isolated_db):
    acc_id = AccountRepository.create("Credit Card", "credit", opening_balance=0.0)
    cat_id = CategoryRepository.create("Shopping", cat_type="expense", icon="🛍️", color="#f1c40f")

    # Parent expense: $100.00
    parent_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "transaction_type": "expense",
        "amount": 100.0,
        "transaction_date": "2026-09-01",
        "description": "Shoes purchase"
    })

    # Create refund 1: $40.00
    ref1_id = TransactionRepository.create_refund(
        original_tx_id=parent_id,
        amount=40.0,
        transaction_date="2026-09-02",
        account_id=acc_id
    )

    # Create refund 2: $30.00 (Total refunded so far = $70.00, remaining max for ref2 = $60.00)
    ref2_id = TransactionRepository.create_refund(
        original_tx_id=parent_id,
        amount=30.0,
        transaction_date="2026-09-03",
        account_id=acc_id
    )

    # Update ref2 to $50.00 (Total = 40 + 50 = 90 <= 100) -> should succeed
    success = TransactionRepository.update_refund(
        tx_id=ref2_id,
        amount=50.0,
        transaction_date="2026-09-04",
        note="Updated partial refund 2"
    )
    assert success is True
    t_ref2 = TransactionRepository.get_by_id(ref2_id)
    assert t_ref2["amount_minor"] == 5000

    # Update ref2 to $65.00 (Total = 40 + 65 = 105 > 100) -> must fail atomically
    with pytest.raises(ValueError, match="exceeds remaining refundable balance"):
        TransactionRepository.update_refund(
            tx_id=ref2_id,
            amount=65.0,
            transaction_date="2026-09-04"
        )


def test_stage2_budget_account_scoping(isolated_db):
    acc1_id = AccountRepository.create("Personal Checking", "checking", opening_balance=0.0)
    acc2_id = AccountRepository.create("Business Account", "checking", opening_balance=0.0)
    cat_id = CategoryRepository.create("Office Supplies", cat_type="expense", icon="📎", color="#3498db")

    month = "2026-09"
    # Create budget of $500.00
    BudgetRepository.set_budget(cat_id, month, 500.0)

    # Add expense in acc1: $150.00
    TransactionRepository.create({
        "account_id": acc1_id,
        "category_id": cat_id,
        "transaction_type": "expense",
        "amount": 150.0,
        "transaction_date": "2026-09-05",
        "description": "Acc1 Supplies"
    })

    # Add expense in acc2: $200.00
    TransactionRepository.create({
        "account_id": acc2_id,
        "category_id": cat_id,
        "transaction_type": "expense",
        "amount": 200.0,
        "transaction_date": "2026-09-06",
        "description": "Acc2 Supplies"
    })

    # 1. Global budget query (account_id=None)
    global_status = BudgetService.get_monthly_budget_status(month, account_id=None)
    item = next(b for b in global_status["items"] if b["category_id"] == cat_id)
    assert item["spent"] == 350.0 # 150 + 200 = 350

    # 2. Scoped budget query for acc1
    acc1_status = BudgetService.get_monthly_budget_status(month, account_id=acc1_id)
    item1 = next(b for b in acc1_status["items"] if b["category_id"] == cat_id)
    assert item1["spent"] == 150.0 # Only 150

    # 3. Scoped budget query for acc2
    acc2_status = BudgetService.get_monthly_budget_status(month, account_id=acc2_id)
    item2 = next(b for b in acc2_status["items"] if b["category_id"] == cat_id)
    assert item2["spent"] == 200.0 # Only 200


def test_stage2_csv_export_scoping(isolated_db):
    acc1_id = AccountRepository.create("Primary Bank", "checking", opening_balance=0.0)
    acc2_id = AccountRepository.create("Secondary Bank", "checking", opening_balance=0.0)
    cat_id = CategoryRepository.create("Dining", cat_type="expense", icon="🍔", color="#e74c3c")

    # September txs
    TransactionRepository.create({
        "account_id": acc1_id,
        "category_id": cat_id,
        "transaction_type": "expense",
        "amount": 25.0,
        "transaction_date": "2026-09-10",
        "description": "Lunch"
    })
    TransactionRepository.create({
        "account_id": acc2_id,
        "category_id": cat_id,
        "transaction_type": "expense",
        "amount": 45.0,
        "transaction_date": "2026-09-15",
        "description": "Dinner"
    })
    # August tx
    TransactionRepository.create({
        "account_id": acc1_id,
        "category_id": cat_id,
        "transaction_type": "expense",
        "amount": 30.0,
        "transaction_date": "2026-08-20",
        "description": "Old Lunch"
    })

    # 1. Export All
    all_csv_path = BackupService.export_csv()
    with open(all_csv_path, "r", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 4 # Header + 3 txs

    # 2. Export by Month "2026-09"
    sep_csv_path = BackupService.export_csv(month="2026-09")
    with open(sep_csv_path, "r", encoding="utf-8") as f:
        sep_rows = list(csv.reader(f))
    assert len(sep_rows) == 3 # Header + 2 txs

    # 3. Export by Month and Account acc1
    scoped_csv_path = BackupService.export_csv(month="2026-09", account_id=acc1_id)
    with open(scoped_csv_path, "r", encoding="utf-8") as f:
        scoped_rows = list(csv.reader(f))
    assert len(scoped_rows) == 2 # Header + 1 tx
    assert scoped_rows[1][10] == "Lunch" # Index 10 is Description
    assert scoped_rows[1][7] == "Primary Bank" # Index 7 is Account


def test_stage3_import_service_preview_duplicate_and_commit(isolated_db):
    acc_id = AccountRepository.create("Main Checking", "checking", opening_balance=500.0)
    cat_id = CategoryRepository.create("Coffee & Cafe", cat_type="expense", icon="☕", color="#795548")

    # Add existing tx
    TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "transaction_type": "expense",
        "amount": 5.50,
        "transaction_date": "2026-09-01",
        "description": "Starbucks Coffee"
    })

    csv_data = """Date,Payee,Amount
2026-09-01,Starbucks Coffee,-5.50
2026-09-02,Starbucks Coffee,-6.00
2026-09-03,Client Salary,2500.00
"""

    mapping = {
        "date": "Date",
        "payee": "Payee",
        "amount": "Amount"
    }

    # 1. Preview with duplicate detection
    preview = ImportService.preview_csv(csv_data, mapping=mapping, account_id=acc_id)
    assert len(preview["headers"]) == 3
    assert preview["total_rows"] == 3
    assert preview["duplicate_count"] == 1
    assert preview["preview_rows"][0]["is_duplicate"] is True
    assert preview["preview_rows"][1]["is_duplicate"] is False
    assert preview["preview_rows"][2]["is_duplicate"] is False

    # 2. Commit batch with deduplicate=True
    commit_res = ImportService.commit_import(csv_data, mapping=mapping, account_id=acc_id, deduplicate=True)
    assert commit_res["success"] is True
    assert commit_res["imported_count"] == 2
    assert commit_res["skipped_duplicates"] == 1

    # Verify total transactions in acc_id now equals 3 (1 existing + 2 imported)
    txs = TransactionRepository.get_all(account_id=acc_id)
    assert txs["total"] == 3


def test_stage4_recurring_rules_crud_and_forecasting_v3(isolated_db):
    acc_id = AccountRepository.create("Living Expenses", "checking", opening_balance=2000.0)
    cat_rent_id = CategoryRepository.create("Rent & Housing", cat_type="expense", icon="🏠", color="#34495e")
    cat_salary_id = CategoryRepository.create("Salary", cat_type="income", icon="💰", color="#2ecc71")

    # 1. Create recurring rules
    rule_rent_id = RecurringService.create_rule(
        name="Apartment Rent",
        amount=1200.0,
        transaction_type="expense",
        category_id=cat_rent_id,
        account_id=acc_id,
        frequency="monthly",
        next_due_date="2026-09-05"
    )
    assert rule_rent_id > 0

    rule_salary_id = RecurringService.create_rule(
        name="Biweekly Paycheck",
        amount=2000.0,
        transaction_type="income",
        category_id=cat_salary_id,
        account_id=acc_id,
        frequency="biweekly",
        next_due_date="2026-09-10"
    )
    assert rule_salary_id > 0

    # 2. Get upcoming bills for September 2026
    upcoming = RecurringService.get_upcoming_bills_for_month("2026-09")
    rent_bills = [b for b in upcoming if b["name"] == "Apartment Rent"]
    salary_bills = [b for b in upcoming if b["name"] == "Biweekly Paycheck"]
    assert len(rent_bills) == 1
    assert rent_bills[0]["amount_minor"] == 120000
    assert len(salary_bills) >= 1

    # 3. Add actual transaction for salary on 2026-09-01
    TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_salary_id,
        "transaction_type": "income",
        "amount": 2000.0,
        "transaction_date": "2026-09-01",
        "description": "First Salary"
    })

    # Add actual transaction for groceries on 2026-09-02
    TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_rent_id,
        "transaction_type": "expense",
        "amount": 150.0,
        "transaction_date": "2026-09-02",
        "description": "Groceries"
    })

    # 4. Run Forecast V3
    engine = ForecastingEngine()
    forecast = engine.forecast_month("2026-09", account_id=acc_id)

    # Verify ForecastResult dictionary fields
    assert forecast["target_month"] == "2026-09"
    assert forecast["actual_spent_to_date_minor"] == 15000 # $150.00 actual expense
    assert forecast["actual_income_to_date_minor"] == 200000 # $2000.00 actual income
    assert forecast["projected_expense_minor"] >= forecast["actual_spent_to_date_minor"]
    assert forecast["projected_income_minor"] >= forecast["actual_income_to_date_minor"]
    assert forecast["projected_net_flow_minor"] == (forecast["projected_income_minor"] - forecast["projected_expense_minor"])
    assert 0.0 <= forecast["projected_savings_rate"] <= 100.0

    # Verify confidence bounds shrink towards actuals
    assert forecast["lower_bound_minor"] <= forecast["projected_expense_minor"] <= forecast["upper_bound_minor"]
