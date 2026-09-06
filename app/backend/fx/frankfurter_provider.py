"""
Frankfurter Reference Exchange Rate Provider Adapter.
Uses public Frankfurter API (European Central Bank reference rates).
Zero new external dependencies; relies strictly on standard library urllib.request.
"""

import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional
from app.backend.fx.models import FxQuote, FxProviderError


class FrankfurterProvider:
    """
    Adapter for Frankfurter API (https://api.frankfurter.dev/v1/).
    Provides daily reference exchange rates published by European Central Bank.
    """
    BASE_URL = "https://api.frankfurter.dev/v1"
    PROVIDER_NAME = "frankfurter"

    def __init__(self, base_url: Optional[str] = None, timeout: float = 4.0):
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.timeout = timeout

    def get_rate(
        self,
        base_currency: str,
        quote_currency: str,
        on_date: Optional[str] = None
    ) -> FxQuote:
        b = base_currency.strip().upper()
        q = quote_currency.strip().upper()

        if b == q:
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            eff_date = on_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            return FxQuote(
                base_currency=b,
                quote_currency=q,
                rate=Decimal("1.0"),
                rate_date=eff_date,
                provider=self.PROVIDER_NAME,
                fetched_at=now_iso,
                is_stale=False
            )

        date_path = on_date if on_date else "latest"
        url = f"{self.base_url}/{date_path}?base={b}&symbols={q}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "FinScope/1.1 (Personal Finance Analytics; +https://github.com/Tannniee/TestFinScope)",
                "Accept": "application/json"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            raise FxProviderError(f"Failed to fetch exchange rate from Frankfurter ({b}->{q}): {exc}") from exc

        rates = data.get("rates", {})
        if q not in rates:
            raise FxProviderError(f"Currency {q} not found in Frankfurter quote for base {b}")

        try:
            rate_val = Decimal(str(rates[q]))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise FxProviderError(f"Invalid rate value in Frankfurter response: {rates[q]}") from exc

        rate_date = data.get("date", on_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return FxQuote(
            base_currency=b,
            quote_currency=q,
            rate=rate_val,
            rate_date=rate_date,
            provider=self.PROVIDER_NAME,
            fetched_at=now_iso,
            is_stale=False
        )
