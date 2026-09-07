import pytest
from decimal import Decimal
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.analytics.aggregates import AggregateQueries
from app.backend.analytics.money_context import get_portfolio_fx_completeness
from app.backend.fx.reconciliation import FxReconciliationService
from app.backend.fx.service import FxService
from app.backend.fx.models import FxQuote

class MockFxProvider:
    def get_rate(self, base: str, quote: str, on_date=None) -> FxQuote:
        # 1 EUR = 1.10 USD, or 1 USD = 0.90 EUR
        return FxQuote(
            base_currency=base,
            quote_currency=quote,
            rate=Decimal("1.10") if base == "EUR" else Decimal("0.909"),
            rate_date="2026-03-01",
            provider="mock_fx",
            fetched_at="2026-03-01T12:00:00Z"
        )

def test_portfolio_safe_aggregation_and_fx_reconciliation(isolated_db):
    FxService.set_provider(MockFxProvider())

    # Base currency is USD
    acc_usd = AccountRepository.create("Primary USD", "checking", currency="USD")
    acc_eur = AccountRepository.create("European EUR", "checking", currency="EUR")
    cat = CategoryRepository.create("Tech Gadgets", "expense")

    # 1. Add USD transaction ($100) -> base_amount_minor = 10000
    TransactionRepository.create({
        "account_id": acc_usd,
        "category_id": cat,
        "amount": 100.0,
        "merchant_name": "Apple Store US",
        "transaction_date": "2026-03-01",
        "transaction_type": "expense"
    })

    # 2. Add EUR transaction (50 EUR) with fx_status='pending' and base_amount_minor=None
    tx_eur_id = TransactionRepository.create({
        "account_id": acc_eur,
        "category_id": cat,
        "amount": 50.0,
        "merchant_name": "Apple Store Paris",
        "transaction_date": "2026-03-01",
        "transaction_type": "expense"
    })

    # Manually simulate an offline pending state for EUR tx
    with isolated_db as conn:
        conn.execute("UPDATE transactions SET base_amount_minor = NULL, fx_status = 'pending' WHERE id = ?", (tx_eur_id,))
        conn.commit()

    # 3. Test Portfolio Safe Aggregation (P0-07):
    # The portfolio sum must ONLY include the USD transaction ($100 = 10000 minor)
    # and MUST NOT add 5000 (50 EUR) directly into USD minor!
    pnl = AggregateQueries.get_monthly_pnl("2026-03", account_id=None)
    assert pnl["gross_expense_minor"] == 10000  # Exactly $100 USD, 50 EUR pending is excluded from USD total

    # Check completeness
    completeness = get_portfolio_fx_completeness("2026-03")
    assert completeness["total_transactions"] == 2
    assert completeness["foreign_transactions"] == 1
    assert completeness["pending_valuations"] == 1
    assert completeness["is_complete"] is False
    assert completeness["reconciled_percentage"] == 0.0

    # 4. Reconcile pending FX (WP-06)
    rec_res = FxReconciliationService.reconcile_pending_fx()
    assert rec_res["reconciled"] == 1
    assert rec_res["remaining_pending"] == 0

    # Check that EUR transaction was backfilled
    tx_eur = TransactionRepository.get_by_id(tx_eur_id)
    assert tx_eur["base_amount_minor"] is not None
    assert tx_eur["fx_status"] == "market_estimate"
    assert tx_eur["base_amount_minor"] == 5500  # 50 EUR * 1.10 = 55.00 USD (5500 minor)

    # 5. Verify portfolio sum now includes properly converted base amount
    pnl_after = AggregateQueries.get_monthly_pnl("2026-03", account_id=None)
    assert pnl_after["gross_expense_minor"] == 15500  # $100 USD + $55 USD = $155 USD

    completeness_after = get_portfolio_fx_completeness("2026-03")
    assert completeness_after["is_complete"] is True
    assert completeness_after["pending_valuations"] == 0
    assert completeness_after["reconciled_percentage"] == 100.0
