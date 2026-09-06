import pytest
from datetime import date
from decimal import Decimal

from app.backend.database.connection import get_db_connection
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.services.settings_service import SettingsService
from app.backend.services.analytics_service import AnalyticsService
from app.backend.analytics.forecasting import ForecastingEngine
from app.backend.fx.service import FxService

@pytest.fixture(autouse=True)
def setup_multicurrency_analytics(isolated_db, monkeypatch):
    SettingsService.set_setting("currency", "USD")
    # Mock remote provider so tests run fully deterministic and offline
    monkeypatch.setattr(FxService, "get_provider", lambda: None)
    # Store fixed FX rates across dates
    for d in ["2026-06-01", "2026-06-02", "2026-06-05", "2026-06-10", "2026-06-12", "2026-06-15", "2026-06-25", "2026-06-30",
              "2026-09-01", "2026-09-02", "2026-09-10", "2026-09-15", "2026-09-25", "2026-09-30"]:
        FxService.store_manual_rate("EUR", "USD", Decimal("1.10"), on_date=d)
        FxService.store_manual_rate("USD", "EUR", Decimal("0.909091"), on_date=d)
        FxService.store_manual_rate("VND", "USD", Decimal("0.00004"), on_date=d)
        FxService.store_manual_rate("USD", "VND", Decimal("25000"), on_date=d)
    yield

def test_analytics_month_summary_portfolio_and_account():
    # Account 1: USD checking (base)
    acc_usd = AccountRepository.create("USD Checking", "checking", opening_balance=1000.0, currency="USD")
    # Account 2: EUR checking
    acc_eur = AccountRepository.create("EUR Checking", "checking", opening_balance=1000.0, currency="EUR")
    # Account 3: VND wallet (0 minor exponent)
    acc_vnd = AccountRepository.create("VND Wallet", "cash", opening_balance=500000.0, currency="VND")

    # Transaction 1 in USD account: $100 expense
    TransactionRepository.create({
        "account_id": acc_usd,
        "amount": 100.0,
        "transaction_type": "expense",
        "transaction_date": "2026-06-10",
        "description": "US Dinner"
    })

    # Transaction 2 in EUR account: €100 expense. Rate 1.10 -> $110 base
    TransactionRepository.create({
        "account_id": acc_eur,
        "amount": 100.0,
        "transaction_type": "expense",
        "transaction_date": "2026-06-12",
        "description": "Euro Hotel"
    })

    # Transaction 3 in VND wallet: 250,000 VND expense. Rate 0.00004 -> $10 base
    TransactionRepository.create({
        "account_id": acc_vnd,
        "amount": 250000.0,
        "transaction_type": "expense",
        "transaction_date": "2026-06-15",
        "description": "VND Street Food"
    })

    # Portfolio level (account_id = None):
    # Total expense should be $100 + $110 + $10 = $220.0
    summary_portfolio = AnalyticsService.get_month_summary("2026-06")
    assert summary_portfolio["currency"] == "USD"
    assert summary_portfolio["kpis"]["expense"] == 220.0

    # Specific account level (acc_eur):
    # Expense in EUR account should be €100.0
    summary_eur = AnalyticsService.get_month_summary("2026-06", account_id=acc_eur)
    assert summary_eur["currency"] == "EUR"
    assert summary_eur["kpis"]["expense"] == 100.0

    # Specific account level (acc_vnd):
    # Expense in VND account should be 250,000 VND with 0 minor exponent
    summary_vnd = AnalyticsService.get_month_summary("2026-06", account_id=acc_vnd)
    assert summary_vnd["currency"] == "VND"
    assert summary_vnd["kpis"]["expense"] == 250000.0

def test_calendar_data_multicurrency():
    acc_eur = AccountRepository.create("EUR Acc", "checking", opening_balance=500.0, currency="EUR")
    TransactionRepository.create({
        "account_id": acc_eur,
        "amount": 50.0,
        "transaction_type": "expense",
        "transaction_date": "2026-06-05",
        "description": "EUR Lunch"
    })

    cal_portfolio = AnalyticsService.get_calendar_data("2026-06")
    assert cal_portfolio["currency"] == "USD"
    # €50 * 1.10 = $55.0
    assert cal_portfolio["days"]["2026-06-05"]["expense"] == 55.0

    cal_eur = AnalyticsService.get_calendar_data("2026-06", account_id=acc_eur)
    assert cal_eur["currency"] == "EUR"
    assert cal_eur["days"]["2026-06-05"]["expense"] == 50.0

def test_deep_dive_multicurrency():
    acc_usd = AccountRepository.create("USD Acc", "checking", opening_balance=500.0, currency="USD")
    acc_eur = AccountRepository.create("EUR Acc", "checking", opening_balance=500.0, currency="EUR")

    TransactionRepository.create({
        "account_id": acc_usd,
        "amount": 40.0,
        "transaction_type": "expense",
        "transaction_date": "2026-06-05",
        "merchant_name": "Merchant A"
    })
    TransactionRepository.create({
        "account_id": acc_eur,
        "amount": 100.0, # €100 = $110
        "transaction_type": "expense",
        "transaction_date": "2026-06-05",
        "merchant_name": "Merchant B"
    })

    dive_portfolio = AnalyticsService.get_analytics_deep_dive("2026-06")
    assert dive_portfolio["currency"] == "USD"
    merchants = {m["merchant"]: m["total"] for m in dive_portfolio["merchants"]}
    assert merchants["Merchant A"] == 40.0
    assert merchants["Merchant B"] == 110.0

    dive_eur = AnalyticsService.get_analytics_deep_dive("2026-06", account_id=acc_eur)
    assert dive_eur["currency"] == "EUR"
    merchants_eur = {m["merchant"]: m["total"] for m in dive_eur["merchants"]}
    assert "Merchant A" not in merchants_eur
    assert merchants_eur["Merchant B"] == 100.0

def test_forecasting_multicurrency_foreign_recurring():
    from app.backend.services.recurring_service import RecurringService

    acc_usd = AccountRepository.create("USD Main", "checking", opening_balance=1000.0, currency="USD")
    acc_eur = AccountRepository.create("EUR Sub", "checking", opening_balance=1000.0, currency="EUR")

    # Actual spend: $50 on 2026-09-02
    TransactionRepository.create({
        "account_id": acc_usd,
        "amount": 50.0,
        "transaction_type": "expense",
        "transaction_date": "2026-09-02"
    })

    # Recurring rule in EUR account: €100 due on 2026-09-25 (€100 * 1.10 = $110)
    rule_id = RecurringService.create({
        "name": "Cloud Hosting EUR",
        "amount": 100.0,
        "currency": "EUR",
        "account_id": acc_eur,
        "frequency": "monthly",
        "next_due_date": "2026-09-25",
        "transaction_type": "expense"
    })

    # Run forecast as of 2026-09-10 for the whole portfolio (account_id = None)
    forecast_portfolio = ForecastingEngine.forecast_month(
        month="2026-09",
        account_id=None,
        as_of_date="2026-09-10"
    )

    # In portfolio view, the €100 upcoming recurring bill must be converted to base currency ($110 = 11000 cents)
    assert forecast_portfolio["upcoming_recurring_minor"] == 11000
    assert forecast_portfolio["actual_spent_to_date_minor"] == 5000
