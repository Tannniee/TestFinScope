"""
Provider interface Protocol for external foreign exchange data providers.
"""

from typing import Protocol, Optional
from app.backend.fx.models import FxQuote


class FxProvider(Protocol):
    """
    Protocol definition for foreign exchange rate providers (e.g. Frankfurter, European Central Bank, etc.).
    """
    def get_rate(
        self,
        base_currency: str,
        quote_currency: str,
        on_date: Optional[str] = None
    ) -> FxQuote:
        """
        Retrieves exchange rate for base_currency -> quote_currency.
        If on_date is None, returns the latest available rate.
        If on_date is specified (YYYY-MM-DD), returns rate valid on or before that date (never in future).
        """
        ...
