"""
Automated Test Suite for FinScope Multi-Currency Transactions & Transfers.
Verifies Phase 5 & Phase 6:
- Foreign purchase on accounts (auto FX conversion & user settlement override)
- Cross-currency transfers (dual-currency minor legs, base valuation, validation invariants)
- Linked multi-currency refunds (ceiling bounds, multi-currency columns, exact formatting)
- Transaction updates with currency & FX revaluation
"""

import pytest
import sqlite3
from decimal import Decimal
from app.backend.database.connection import get_db_connection, init_db
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.services.transfer_service import TransferService
from app.backend.services.settings_service import SettingsService
from app.backend.fx.service import FxService
from app.backend.domain.money import major_to_minor, minor_to_major


@pytest.fixture(autouse=True)
def setup_mc_db(isolated_db):
    """Ensures base currency is USD and DB is initialized."""
    SettingsService.set_setting("currency", "USD")
    # Seed fixed FX rates in DB to ensure deterministic, offline test execution
    FxService.store_manual_rate("EUR", "USD", Decimal("1.08000000"), on_date="2026-09-01")
    FxService.store_manual_rate("USD", "VND", Decimal("25400.00000000"), on_date="2026-09-01")
    FxService.store_manual_rate("EUR", "VND", Decimal("27432.00000000"), on_date="2026-09-01")


def test_foreign_currency_purchase_auto_fx():
    """MC-TX-01: Foreign currency purchase on account converted using FX service."""
    acc_id = AccountRepository.create(name="USD Card", account_type="credit", currency="USD")
    cat_id = CategoryRepository.create(name="Software", cat_type="expense", icon="💻", color="#3498db")

    # Purchase 50 EUR on USD card on 2026-09-01
    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "transaction_type": "expense",
        "original_currency": "EUR",
        "original_amount": 50.0,
        "transaction_date": "2026-09-01",
        "description": "JetBrains License"
    })

    tx = TransactionRepository.get_by_id(tx_id)
    assert tx is not None
    # 50 EUR * 1.08 = 54.00 USD
    assert tx["original_currency"] == "EUR"
    assert tx["original_amount_minor"] == 5000
    assert tx["original_amount"] == 50.0
    assert tx["currency"] == "USD"
    assert tx["amount_minor"] == 5400
    assert tx["amount"] == 54.0
    assert tx["base_currency"] == "USD"
    assert tx["base_amount_minor"] == 5400
    assert tx["base_amount"] == 54.0
    assert tx["fx_status"] == "market_estimate"


def test_foreign_currency_purchase_user_settlement():
    """MC-TX-02: Foreign currency purchase with user settlement amount override."""
    acc_id = AccountRepository.create(name="USD Card", account_type="credit", currency="USD")
    cat_id = CategoryRepository.create(name="Travel", cat_type="expense", icon="✈️", color="#e67e22")

    # Purchase 100 EUR on USD card, but bank settled at exactly 109.50 USD
    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "transaction_type": "expense",
        "original_currency": "EUR",
        "original_amount": 100.0,
        "settlement_amount": 109.50,
        "transaction_date": "2026-09-01",
        "description": "Hotel Paris"
    })

    tx = TransactionRepository.get_by_id(tx_id)
    assert tx["original_currency"] == "EUR"
    assert tx["original_amount_minor"] == 10000
    assert tx["currency"] == "USD"
    assert tx["amount_minor"] == 10950
    assert tx["amount"] == 109.50
    assert tx["base_amount_minor"] == 10950
    assert tx["fx_status"] == "user_settlement"


def test_cross_currency_transfer():
    """MC-TX-03: Cross-currency transfer between USD checking and VND cash."""
    usd_acc_id = AccountRepository.create(name="USD Checking", account_type="depository", currency="USD", opening_balance=1000.0)
    vnd_acc_id = AccountRepository.create(name="VND Cash", account_type="cash", currency="VND", opening_balance=0.0)

    # Transfer $100 USD to VND cash with explicit to_amount 2,540,000 VND
    res = TransferService.create_transfer(
        from_account_id=usd_acc_id,
        to_account_id=vnd_acc_id,
        amount=100.0,
        to_amount=2540000,
        transaction_date="2026-09-01",
        description="ATM Withdrawal in Hanoi"
    )
    assert res["success"] is True
    group_id = res["transfer_group_id"]

    # Validate group invariants
    val = TransferService.validate_transfer_group(group_id)
    assert val["valid"] is True

    # Check source leg ($100 USD = 10000 cents)
    src_tx = TransactionRepository.get_by_id(res["outflow_tx_id"])
    assert src_tx["currency"] == "USD"
    assert src_tx["amount_minor"] == 10000
    assert src_tx["amount"] == 100.0
    assert src_tx["base_amount_minor"] == 10000

    # Check destination leg (2,540,000 VND = 2540000 minor)
    dest_tx = TransactionRepository.get_by_id(res["inflow_tx_id"])
    assert dest_tx["currency"] == "VND"
    assert dest_tx["amount_minor"] == 2540000
    assert dest_tx["amount"] == 2540000.0
    # In base currency (USD): 2,540,000 / 25400 = 100.0 USD = 10000 minor
    assert dest_tx["base_currency"] == "USD"
    assert dest_tx["base_amount_minor"] == 10000


def test_cross_currency_transfer_update():
    """MC-TX-04: Updating a cross-currency transfer recalculates legs properly."""
    usd_acc = AccountRepository.create(name="USD Checking", account_type="depository", currency="USD", opening_balance=1000.0)
    eur_acc = AccountRepository.create(name="EUR Savings", account_type="savings", currency="EUR", opening_balance=500.0)

    res = TransferService.create_transfer(
        from_account_id=usd_acc,
        to_account_id=eur_acc,
        amount=108.0,
        to_amount=100.0,
        transaction_date="2026-09-01"
    )
    group_id = res["transfer_group_id"]

    # Update transfer amount to $216.00 USD -> 200.0 EUR
    success = TransferService.update_transfer(
        transfer_group_id=group_id,
        amount=216.0,
        to_amount=200.0,
        transaction_date="2026-09-02"
    )
    assert success is True

    src_tx = TransactionRepository.get_by_id(res["outflow_tx_id"])
    dest_tx = TransactionRepository.get_by_id(res["inflow_tx_id"])
    assert src_tx["amount_minor"] == 21600
    assert dest_tx["amount_minor"] == 20000
    assert src_tx["transaction_date"] == "2026-09-02"
    assert dest_tx["transaction_date"] == "2026-09-02"


def test_multicurrency_refund_limits():
    """MC-TX-05: Multi-currency refund enforces bounds in original expense currency."""
    eur_acc = AccountRepository.create(name="EUR Account", account_type="checking", currency="EUR")
    cat_id = CategoryRepository.create(name="Electronics", cat_type="expense", icon="📱", color="#9b59b6")

    orig_id = TransactionRepository.create({
        "account_id": eur_acc,
        "category_id": cat_id,
        "transaction_type": "expense",
        "amount": 200.0,
        "transaction_date": "2026-09-01",
        "description": "Headphones"
    })

    # First refund: 80.00 EUR
    ref1_id = TransactionRepository.create_refund(
        original_tx_id=orig_id,
        amount=80.0,
        transaction_date="2026-09-02"
    )
    ref1 = TransactionRepository.get_by_id(ref1_id)
    assert ref1["currency"] == "EUR"
    assert ref1["amount_minor"] == 8000
    assert ref1["amount"] == 80.0

    # Exceeding refund: 150.00 EUR (80 + 150 = 230 > 200)
    with pytest.raises(ValueError, match="exceeds remaining refundable balance"):
        TransactionRepository.create_refund(
            original_tx_id=orig_id,
            amount=150.0,
            transaction_date="2026-09-03"
        )

    # Valid final refund: 120.00 EUR
    ref2_id = TransactionRepository.create_refund(
        original_tx_id=orig_id,
        amount=120.0,
        transaction_date="2026-09-03"
    )
    ref2 = TransactionRepository.get_by_id(ref2_id)
    assert ref2["amount_minor"] == 12000


def test_transaction_update_recalculates_fx():
    """MC-TX-06: Updating a transaction's amount or currency recalculates base amount."""
    acc_id = AccountRepository.create(name="USD Card", account_type="credit", currency="USD")
    cat_id = CategoryRepository.create(name="Dining", cat_type="expense", icon="🍔", color="#e74c3c")

    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "transaction_type": "expense",
        "amount": 30.0,
        "transaction_date": "2026-09-01",
        "description": "Lunch"
    })

    tx = TransactionRepository.get_by_id(tx_id)
    assert tx["amount_minor"] == 3000
    assert tx["base_amount_minor"] == 3000

    # Update to foreign currency: 50 EUR (50 * 1.08 = 54.00 USD)
    TransactionRepository.update(tx_id, {
        "original_currency": "EUR",
        "original_amount": 50.0
    })

    tx_updated = TransactionRepository.get_by_id(tx_id)
    assert tx_updated["original_currency"] == "EUR"
    assert tx_updated["original_amount_minor"] == 5000
    assert tx_updated["amount_minor"] == 5400
    assert tx_updated["base_amount_minor"] == 5400
