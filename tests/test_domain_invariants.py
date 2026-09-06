import pytest
from datetime import datetime
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.repositories.budget_repo import BudgetRepository
from app.backend.services.transfer_service import TransferService


def test_category_type_mismatch_rejected(isolated_db):
    food_id = CategoryRepository.create(name="Food Expense", cat_type="expense")
    salary_id = CategoryRepository.create(name="Salary Income", cat_type="income")
    acc_id = AccountRepository.create(name="Checking", account_type="checking", currency="USD")

    # Expense with income category rejected
    with pytest.raises(ValueError, match="expense transactions require a expense category"):
        TransactionRepository.create({
            "account_id": acc_id,
            "category_id": salary_id,
            "transaction_type": "expense",
            "amount": 25.0,
            "transaction_date": "2026-05-01"
        })

    # Income with expense category rejected
    with pytest.raises(ValueError, match="income transactions require a income category"):
        TransactionRepository.create({
            "account_id": acc_id,
            "category_id": food_id,
            "transaction_type": "income",
            "amount": 1000.0,
            "transaction_date": "2026-05-01"
        })

    # Valid creations succeed
    exp_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": food_id,
        "transaction_type": "expense",
        "amount": 25.0,
        "transaction_date": "2026-05-01"
    })
    assert exp_id > 0

    inc_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": salary_id,
        "transaction_type": "income",
        "amount": 1000.0,
        "transaction_date": "2026-05-01"
    })
    assert inc_id > 0

    # Updating transaction to incompatible category rejected
    with pytest.raises(ValueError, match="expense transactions require a expense category"):
        TransactionRepository.update(exp_id, {"category_id": salary_id})


def test_generic_refund_rejected_without_linkage(isolated_db):
    acc_id = AccountRepository.create(name="Checking", account_type="checking", currency="USD")
    with pytest.raises(ValueError, match="Refunds must be created through create_refund"):
        TransactionRepository.create({
            "account_id": acc_id,
            "transaction_type": "refund",
            "amount": 15.0,
            "transaction_date": "2026-05-01"
        })


def test_archived_category_assignment_rejected(isolated_db):
    cat_id = CategoryRepository.create(name="Old Category", cat_type="expense")
    CategoryRepository.update(cat_id, is_archived=1)
    acc_id = AccountRepository.create(name="Checking", account_type="checking", currency="USD")

    with pytest.raises(ValueError, match="Archived categories cannot be assigned to new transactions"):
        TransactionRepository.create({
            "account_id": acc_id,
            "category_id": cat_id,
            "transaction_type": "expense",
            "amount": 10.0,
            "transaction_date": "2026-05-01"
        })


def test_category_type_mutation_rejected_if_in_use(isolated_db):
    gym_id = CategoryRepository.create(name="Gym", cat_type="expense")
    acc_id = AccountRepository.create(name="Checking", account_type="checking", currency="USD")
    TransactionRepository.create({
        "account_id": acc_id,
        "category_id": gym_id,
        "transaction_type": "expense",
        "amount": 50.0,
        "transaction_date": "2026-05-01"
    })

    with pytest.raises(ValueError, match="Cannot change category type when historical transactions or budgets exist"):
        CategoryRepository.update(gym_id, type="income")

    books_id = CategoryRepository.create(name="Books", cat_type="expense")
    BudgetRepository.set_budget(books_id, "2026-05", 100.0)

    with pytest.raises(ValueError, match="Cannot change category type when historical transactions or budgets exist"):
        CategoryRepository.update(books_id, type="income")


def test_category_delete_non_existent_returns_false(isolated_db):
    assert CategoryRepository.delete(999999) is False


def test_budget_category_and_month_validation(isolated_db):
    salary_id = CategoryRepository.create(name="Salary", cat_type="income")
    dining_id = CategoryRepository.create(name="Dining", cat_type="expense")
    CategoryRepository.update(dining_id, is_archived=1)
    utilities_id = CategoryRepository.create(name="Utilities", cat_type="expense")

    # Income category rejected for budget
    with pytest.raises(ValueError, match="Budget categories must be expense categories, not 'income'"):
        BudgetRepository.set_budget(salary_id, "2026-05", 500.0)

    # Archived category rejected for budget
    with pytest.raises(ValueError, match="Archived categories cannot have active budgets"):
        BudgetRepository.set_budget(dining_id, "2026-05", 500.0)

    # Invalid month formats rejected
    with pytest.raises(ValueError, match="Invalid Month format"):
        BudgetRepository.set_budget(utilities_id, "2026-13", 100.0)

    with pytest.raises(ValueError, match="Invalid Month format"):
        BudgetRepository.set_budget(utilities_id, "not-a-month", 100.0)

    with pytest.raises(ValueError, match="Invalid Month format"):
        BudgetRepository.get_by_month("2026-99")

    # Valid budget creation succeeds
    res_id = BudgetRepository.set_budget(utilities_id, "2026-05", 150.0)
    assert res_id > 0
    budgets = BudgetRepository.get_by_month("2026-05")
    assert any(b["category_id"] == utilities_id for b in budgets)


def test_adjustment_negative_amount_on_edit(isolated_db):
    acc_id = AccountRepository.create(name="Checking", account_type="checking", currency="USD")
    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "transaction_type": "adjustment",
        "amount": -25.0,
        "transaction_date": "2026-05-01",
        "description": "Initial balance adjustment"
    })
    tx = TransactionRepository.get_by_id(tx_id)
    assert tx["amount"] == -25.0

    # Update adjustment with a new negative amount without explicitly passing transaction_type
    res = TransactionRepository.update(tx_id, {"amount": -40.0})
    assert res is True

    updated_tx = TransactionRepository.get_by_id(tx_id)
    assert updated_tx["amount"] == -40.0


def test_transfer_pair_integrity_checks(isolated_db):
    from_acc = AccountRepository.create(name="FromAcct", account_type="checking", currency="USD")
    to_acc = AccountRepository.create(name="ToAcct", account_type="savings", currency="USD")

    transfer_res = TransferService.create_transfer(
        from_account_id=from_acc,
        to_account_id=to_acc,
        amount=100.0,
        transaction_date="2026-05-01"
    )
    group_id = transfer_res["transfer_group_id"]
    val = TransferService.validate_transfer_group(group_id)
    assert val["valid"] is True

    # Intentionally corrupt deletion parity
    with isolated_db as conn:
        conn.execute("UPDATE transactions SET is_deleted = 1 WHERE id = ?", (transfer_res["outflow_id"],))
        conn.commit()

    val_corrupt = TransferService.validate_transfer_group(group_id)
    assert val_corrupt["valid"] is False
    assert "Inconsistent deletion state" in val_corrupt["reason"]

    # Attempting to update a corrupted transfer raises ValueError
    with pytest.raises(ValueError, match="Inconsistent deletion state"):
        TransferService.update_transfer(transfer_group_id=group_id, amount=120.0)
