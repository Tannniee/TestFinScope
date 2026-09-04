import pytest
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.services.transfer_service import TransferService
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository


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
