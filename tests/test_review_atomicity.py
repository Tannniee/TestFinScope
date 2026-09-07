import pytest
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.services.merchant_service import MerchantService
from app.backend.database.connection import get_db_connection


def test_resolve_review_atomic_success(isolated_db):
    """
    Verifies resolve_review atomically sets category, clears review flag,
    and trains merchant defaults.
    """
    acc_id = AccountRepository.create("Main Checking", "checking", opening_balance=500.0)
    cat_initial = CategoryRepository.create("Uncategorized", "expense", "help-circle", "#8E8E93")
    cat_target = CategoryRepository.create("Dining & Coffee", "expense", "coffee", "#FF9500")

    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_initial,
        "merchant_name": "STARBUCKS #1234",
        "amount": 7.50,
        "transaction_type": "expense",
        "transaction_date": "2026-09-01",
        "needs_review": 1
    })

    # Initially needs review
    tx = TransactionRepository.get_by_id(tx_id)
    assert tx["needs_review"] == 1
    assert tx["category_id"] == cat_initial

    # Resolve review
    success = TransactionRepository.resolve_review(tx_id, cat_target, merchant_name="Starbucks")
    assert success is True

    # Check updated transaction
    tx_after = TransactionRepository.get_by_id(tx_id)
    assert tx_after["needs_review"] == 0
    assert tx_after["category_id"] == cat_target
    assert tx_after["merchant_name"] == "Starbucks"

    # Check merchant learned defaults
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT default_category_id, preferred_account_id FROM merchants WHERE name = 'Starbucks'")
        m = cur.fetchone()
        assert m is not None
        assert m["default_category_id"] == cat_target
        assert m["preferred_account_id"] == acc_id


def test_resolve_review_atomic_rollback_on_failure(isolated_db, monkeypatch):
    """
    Verifies that if the update fails, any merchant modifications within the
    connection are rolled back completely.
    """
    acc_id = AccountRepository.create("Card Account", "credit", opening_balance=0.0)
    cat_id = CategoryRepository.create("Shopping", "expense", "shopping-bag", "#AF52DE")

    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "merchant_name": "Zara Retail",
        "amount": 45.0,
        "transaction_type": "expense",
        "transaction_date": "2026-09-02",
        "needs_review": 1
    })

    # Force a failure during update inside resolve_review
    from app.backend.services.merchant_service import MerchantService
    original_learn = MerchantService.learn_defaults_in_conn

    def failing_learn(*args, **kwargs):
        original_learn(*args, **kwargs)
        raise RuntimeError("Simulated DB error during review resolution")

    monkeypatch.setattr(MerchantService, "learn_defaults_in_conn", failing_learn)

    with pytest.raises(RuntimeError, match="Simulated DB error"):
        TransactionRepository.resolve_review(tx_id, cat_id, merchant_name="Zara Retail")

    # Transaction should still need review
    tx = TransactionRepository.get_by_id(tx_id)
    assert tx["needs_review"] == 1

    # Merchant should NOT have the new default committed due to rollback
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT default_category_id FROM merchants WHERE name = 'Zara Retail'")
        m = cur.fetchone()
        assert m is None or m["default_category_id"] is None
