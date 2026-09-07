import csv
import os
import pytest
from app.backend.services.backup_service import BackupService
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository


def test_export_multicurrency_decimal_places(isolated_db):
    """
    Verifies that export_csv outputs exact decimal representations for:
    - 0-decimal currencies: VND (85,000 -> 85000), JPY (1,500 -> 1500)
    - 2-decimal currencies: USD (10.50 -> 10.50)
    - 3-decimal currencies: KWD (1.250 -> 1.250)
    Without truncating or falsely assuming 2 decimal places.
    """
    cat_id = CategoryRepository.create("General", "expense", "tag", "#5B8CFF")

    acc_vnd = AccountRepository.create("MBBank VND", "checking", opening_balance=10000000.0, currency="VND")
    acc_jpy = AccountRepository.create("Mizuho JPY", "checking", opening_balance=50000.0, currency="JPY")
    acc_usd = AccountRepository.create("Chase USD", "checking", opening_balance=1000.0, currency="USD")
    acc_kwd = AccountRepository.create("NBK KWD", "checking", opening_balance=500.0, currency="KWD")

    TransactionRepository.create({
        "account_id": acc_vnd,
        "category_id": cat_id,
        "amount": 85000,
        "transaction_type": "expense",
        "transaction_date": "2026-09-01",
        "description": "Grab Taxi VND"
    })

    TransactionRepository.create({
        "account_id": acc_jpy,
        "category_id": cat_id,
        "amount": 1500,
        "transaction_type": "expense",
        "transaction_date": "2026-09-02",
        "description": "Ramen JPY"
    })

    TransactionRepository.create({
        "account_id": acc_usd,
        "category_id": cat_id,
        "amount": 10.50,
        "transaction_type": "expense",
        "transaction_date": "2026-09-03",
        "description": "Coffee USD"
    })

    TransactionRepository.create({
        "account_id": acc_kwd,
        "category_id": cat_id,
        "amount": 1.250,
        "transaction_type": "expense",
        "transaction_date": "2026-09-04",
        "description": "Souq KWD"
    })

    csv_path = BackupService.export_csv(month="2026-09")
    assert os.path.exists(csv_path)

    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = {r["Description"]: r for r in reader}

        assert "Grab Taxi VND" in rows
        assert rows["Grab Taxi VND"]["Amount"] == "85000"
        assert rows["Grab Taxi VND"]["Currency"] == "VND"
        assert rows["Grab Taxi VND"]["Amount Minor"] == "85000"

        assert "Ramen JPY" in rows
        assert rows["Ramen JPY"]["Amount"] == "1500"
        assert rows["Ramen JPY"]["Currency"] == "JPY"
        assert rows["Ramen JPY"]["Amount Minor"] == "1500"

        assert "Coffee USD" in rows
        assert rows["Coffee USD"]["Amount"] == "10.50"
        assert rows["Coffee USD"]["Currency"] == "USD"
        assert rows["Coffee USD"]["Amount Minor"] == "1050"

        assert "Souq KWD" in rows
        assert rows["Souq KWD"]["Amount"] == "1.250"
        assert rows["Souq KWD"]["Currency"] == "KWD"
        assert rows["Souq KWD"]["Amount Minor"] == "1250"

    finally:
        if os.path.exists(csv_path):
            os.remove(csv_path)
