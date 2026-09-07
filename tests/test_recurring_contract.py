import pytest
from datetime import date
from app.backend.services.recurring_service import RecurringService
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.analytics.recurring_schedule import generate_occurrences


def test_recurring_transaction_type_restricted(isolated_db):
    acc_id = AccountRepository.create(name="Checking", account_type="checking", currency="USD")
    cat_id = CategoryRepository.create(name="Subscription", cat_type="expense")

    # Expense and income succeed
    r_exp = RecurringService.create_rule(
        name="Netflix",
        amount=15.99,
        transaction_type="expense",
        category_id=cat_id,
        account_id=acc_id
    )
    assert r_exp > 0

    inc_cat_id = CategoryRepository.create(name="Salary", cat_type="income")
    r_inc = RecurringService.create_rule(
        name="Payroll",
        amount=3000.0,
        transaction_type="income",
        category_id=inc_cat_id,
        account_id=acc_id
    )
    assert r_inc > 0

    # Transfer, refund, adjustment are rejected
    with pytest.raises(ValueError, match="Invalid recurring transaction type"):
        RecurringService.create_rule(
            name="Savings Transfer",
            amount=500.0,
            transaction_type="transfer",
            account_id=acc_id
        )

    with pytest.raises(ValueError, match="Invalid recurring transaction type"):
        RecurringService.create_rule(
            name="Mystery Refund",
            amount=50.0,
            transaction_type="refund",
            account_id=acc_id
        )

    with pytest.raises(ValueError, match="Invalid recurring transaction type"):
        RecurringService.update_rule(r_exp, transaction_type="adjustment")


def test_daily_recurrence_occurrences():
    # FSC-H07: Daily occurrences generation
    from datetime import timedelta
    occs = generate_occurrences(
        next_due_date="2026-06-01",
        frequency="daily",
        start_date=date(2026, 6, 1) - timedelta(days=1),
        end_date=date(2026, 6, 30)
    )
    assert len(occs) == 30
    assert occs[0] == date(2026, 6, 1)
    assert occs[-1] == date(2026, 6, 30)


def test_empty_description_paid_match_prevented(isolated_db):
    # FSC-M11: Empty merchant/description must NOT match a recurring rule
    acc_id = AccountRepository.create(name="Checking", account_type="checking", currency="USD")
    cat_id = CategoryRepository.create(name="Utilities", cat_type="expense")

    RecurringService.create_rule(
        name="Electricity Bill",
        amount=100.0,
        transaction_type="expense",
        category_id=cat_id,
        account_id=acc_id,
        frequency="monthly",
        next_due_date="2026-10-15"
    )

    # Insert an expense with empty merchant and description, but different amount and no category
    TransactionRepository.create({
        "account_id": acc_id,
        "transaction_type": "expense",
        "amount": 42.0,
        "transaction_date": "2026-10-10",
        "merchant_name": "",
        "description": ""
    })

    # Check upcoming bills in future month 2026-10
    bills = RecurringService.get_upcoming_bills_for_month("2026-10", account_id=acc_id)
    assert len(bills) == 1
    # The rule must NOT be marked as paid
    assert bills[0]["is_paid"] is False
    assert bills[0]["status"] == "upcoming"


def test_recurring_category_compatibility_and_currency_immutability(isolated_db):
    acc_id = AccountRepository.create(name="Checking", account_type="checking", currency="USD")
    exp_cat = CategoryRepository.create(name="Rent", cat_type="expense")
    inc_cat = CategoryRepository.create(name="Salary", cat_type="income")

    # Mismatched category type rejected on create
    with pytest.raises(ValueError, match="does not match recurring rule transaction type"):
        RecurringService.create_rule(
            name="Invalid Rent",
            amount=1200.0,
            transaction_type="income",
            category_id=exp_cat,
            account_id=acc_id
        )

    # Archived category rejected on create
    archived_cat = CategoryRepository.create(name="Old Bills", cat_type="expense")
    CategoryRepository.update(archived_cat, is_archived=1)
    with pytest.raises(ValueError, match="is archived and cannot be used"):
        RecurringService.create_rule(
            name="Old Bill",
            amount=50.0,
            transaction_type="expense",
            category_id=archived_cat,
            account_id=acc_id
        )

    # Valid rule creation
    rule_id = RecurringService.create_rule(
        name="Apartment Rent",
        amount=1500.0,
        transaction_type="expense",
        category_id=exp_cat,
        account_id=acc_id,
        currency="USD"
    )
    assert rule_id > 0

    # Updating category to incompatible type rejected
    with pytest.raises(ValueError, match="does not match recurring rule transaction type"):
        RecurringService.update_rule(rule_id, category_id=inc_cat)

    # Updating currency without providing new amount rejected
    with pytest.raises(ValueError, match="Cannot change recurring rule currency without providing an explicit new amount"):
        RecurringService.update_rule(rule_id, currency="EUR")

    # Updating currency WITH explicit amount succeeds
    success = RecurringService.update_rule(rule_id, currency="EUR", amount=1400.0)
    assert success is True

