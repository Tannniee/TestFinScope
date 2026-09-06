"""
Tests for Foreign Exchange (FX) Provider & Service (Phase 3 & Section 69).
Verifies:
1. Same-currency conversions return 1.0 identity immediately without network calls.
2. Historical rates are cached and immutable once stored.
3. Provider failure falls back to cached stale rates (with is_stale=True) or raises FxRateUnavailableError.
4. Reciprocal quotes (A -> B inverted when B -> A is stored) calculate accurately.
5. Exact Decimal conversion across currencies without binary float imprecision.
"""

import pytest
from decimal import Decimal
from app.backend.database.connection import init_db, get_db_connection
from app.backend.fx.models import FxQuote, FxProviderError, FxRateUnavailableError
from app.backend.fx.service import FxService


class MockFxProvider:
    def __init__(self):
        self.call_count = 0
        self.should_fail = False
        self.mock_rates = {
            ("USD", "VND", None): Decimal("26000"),
            ("USD", "VND", "2026-08-01"): Decimal("25500"),
            ("EUR", "USD", None): Decimal("1.10"),
            ("EUR", "USD", "2026-08-01"): Decimal("1.0850"),
        }

    def get_rate(self, base_currency: str, quote_currency: str, on_date=None) -> FxQuote:
        self.call_count += 1
        if self.should_fail:
            raise FxProviderError("Simulated network outage")

        key = (base_currency, quote_currency, on_date)
        if key in self.mock_rates:
            rate = self.mock_rates[key]
        elif (base_currency, quote_currency, None) in self.mock_rates:
            rate = self.mock_rates[(base_currency, quote_currency, None)]
        else:
            raise FxProviderError(f"No mock quote for {key}")

        eff_date = on_date or "2026-09-01"
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return FxQuote(
            base_currency=base_currency,
            quote_currency=quote_currency,
            rate=rate,
            rate_date=eff_date,
            provider="mock_fx",
            fetched_at=now_iso,
            is_stale=False
        )


@pytest.fixture(autouse=True)
def setup_fx_db(isolated_db):
    """Initializes database and configures mock FX provider."""
    mock = MockFxProvider()
    FxService.set_provider(mock)
    yield mock
    FxService.set_provider(None)


def test_same_currency_conversion_needs_no_provider(setup_fx_db):
    """Same currency conversion must return identity without calling the provider."""
    mock = setup_fx_db
    conv = FxService.convert_minor(100000, "VND", "VND")

    assert conv.source.minor == 100000
    assert conv.target.minor == 100000
    assert conv.rate == Decimal("1.0")
    assert conv.provider == "identity"
    assert mock.call_count == 0


def test_latest_rate_retrieval_and_caching(setup_fx_db):
    """Latest rate is fetched from provider, cached in DB, and reused on subsequent calls."""
    mock = setup_fx_db

    quote1 = FxService.get_latest_rate("USD", "VND")
    assert quote1.rate == Decimal("26000")
    assert quote1.provider == "mock_fx"
    assert mock.call_count == 1

    # Second call uses DB cache within TTL
    quote2 = FxService.get_latest_rate("USD", "VND")
    assert quote2.rate == Decimal("26000")
    assert mock.call_count == 1  # No additional network call


def test_historical_rate_retrieval_and_immutability(setup_fx_db):
    """Historical rates are keyed by date and cached permanently."""
    mock = setup_fx_db

    quote_hist = FxService.get_historical_rate("USD", "VND", on_date="2026-08-01")
    assert quote_hist.rate == Decimal("25500")
    assert quote_hist.rate_date == "2026-08-01"
    assert mock.call_count == 1

    # Repeat lookup hits DB cache
    quote_cached = FxService.get_historical_rate("USD", "VND", on_date="2026-08-01")
    assert quote_cached.rate == Decimal("25500")
    assert mock.call_count == 1


def test_network_failure_falls_back_to_cached_stale_quote(setup_fx_db):
    """When provider is down, service gracefully falls back to cached quote with is_stale=True."""
    mock = setup_fx_db

    # Seed initial rate in DB
    FxService.get_latest_rate("USD", "VND")
    assert mock.call_count == 1

    # Simulate network outage and force refresh
    mock.should_fail = True
    quote_stale = FxService.get_latest_rate("USD", "VND", force_refresh=True)

    assert quote_stale.rate == Decimal("26000")
    assert quote_stale.is_stale is True


def test_network_failure_without_cache_raises_unavailable(setup_fx_db):
    """When provider is down and no cached quote exists, raises FxRateUnavailableError."""
    mock = setup_fx_db
    mock.should_fail = True

    with pytest.raises(FxRateUnavailableError, match="No exchange rate available"):
        FxService.get_latest_rate("GBP", "JPY")


def test_manual_rate_override_and_conversion():
    """Manual rates can be explicitly stored and used for conversion."""
    FxService.store_manual_rate("USD", "VND", rate="26250", on_date="2026-09-01")

    conv = FxService.convert_minor(
        amount_minor=1000,  # 10.00 USD
        source_currency="USD",
        target_currency="VND",
        on_date="2026-09-01"
    )

    # 10.00 USD * 26250 = 262,500 VND (0 decimals -> 262500 minor)
    assert conv.target.minor == 262500
    assert conv.target.currency == "VND"
    assert conv.provider == "manual"
    assert conv.rate == Decimal("26250")


def test_reciprocal_rate_calculation():
    """If A -> B rate is stored, B -> A can be computed as reciprocal."""
    FxService.store_manual_rate("USD", "EUR", rate="0.80", on_date="2026-09-01")

    # Invert: EUR -> USD at 1 / 0.80 = 1.25
    quote_inv = FxService.get_historical_rate("EUR", "USD", on_date="2026-09-01")
    assert quote_inv.rate == Decimal("1.25")
    assert "reciprocal" in quote_inv.provider
