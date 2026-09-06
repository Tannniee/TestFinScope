"""
Domain models for Foreign Exchange (FX) rates, quotes, and conversions.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from app.backend.domain.money import Money


@dataclass(frozen=True)
class FxQuote:
    """
    Represents a currency exchange rate quote.
    Formula: 1 base_currency = rate quote_currency.
    """
    base_currency: str
    quote_currency: str
    rate: Decimal
    rate_date: str
    provider: str
    fetched_at: str
    is_stale: bool = False


@dataclass(frozen=True)
class FxConversion:
    """
    Represents the result of converting Money from a source currency to a target currency.
    """
    source: Money
    target: Money
    rate: Decimal
    rate_date: str
    provider: str
    is_stale: bool = False


class FxProviderError(Exception):
    """Raised when an FX provider fails to fetch a quote or is unreachable."""
    pass


class FxRateUnavailableError(Exception):
    """Raised when no market or cached exchange rate is available for a currency pair."""
    pass
