"""
Foreign Exchange (FX) Service.
Coordinates cached exchange rate storage, provider retrieval (Frankfurter),
historical/latest rate lookups, and exact Decimal monetary conversion.
"""

from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple
from app.backend.database.connection import get_db_connection
from app.backend.domain.currencies import get_currency_meta
from app.backend.domain.money import Money, convert_money
from app.backend.fx.models import FxQuote, FxConversion, FxProviderError, FxRateUnavailableError
from app.backend.fx.provider import FxProvider
from app.backend.fx.frankfurter_provider import FrankfurterProvider


class FxService:
    """
    Core foreign exchange orchestration service.
    """
    _default_provider: Optional[FxProvider] = None
    LATEST_CACHE_TTL_HOURS = 4

    @classmethod
    def get_provider(cls) -> FxProvider:
        if cls._default_provider is None:
            cls._default_provider = FrankfurterProvider()
        return cls._default_provider

    @classmethod
    def set_provider(cls, provider: FxProvider):
        """Allows swapping the provider (e.g. for testing or alternative vendors)."""
        cls._default_provider = provider

    @classmethod
    def get_latest_rate(
        cls,
        base_currency: str,
        quote_currency: str,
        force_refresh: bool = False
    ) -> FxQuote:
        """
        Retrieves latest available reference exchange rate for base -> quote.
        Uses cached quote if fresh (< 4 hours). Falls back to stale cached quote on network failure.
        """
        b = base_currency.strip().upper()
        q = quote_currency.strip().upper()

        if b == q:
            today_iso = date.today().isoformat()
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return FxQuote(b, q, Decimal("1.0"), today_iso, "identity", now_iso, is_stale=False)

        # 1. Check existing cached quote
        cached = cls._find_cached_rate(b, q, on_date=None)
        now_dt = datetime.now(timezone.utc)

        if cached and not force_refresh:
            try:
                fetched_dt = datetime.fromisoformat(cached.fetched_at.replace("Z", "+00:00"))
                if (now_dt - fetched_dt) < timedelta(hours=cls.LATEST_CACHE_TTL_HOURS):
                    return cached
            except Exception:
                pass

        # 2. Try fetching from provider
        try:
            quote = cls.get_provider().get_rate(b, q, on_date=None)
            cls._store_rate(quote)
            return quote
        except FxProviderError:
            # 3. Provider failed: return stale cached quote if available
            if cached:
                return FxQuote(
                    base_currency=cached.base_currency,
                    quote_currency=cached.quote_currency,
                    rate=cached.rate,
                    rate_date=cached.rate_date,
                    provider=cached.provider,
                    fetched_at=cached.fetched_at,
                    is_stale=True
                )
            raise FxRateUnavailableError(f"No exchange rate available for {b}->{q} and provider is unreachable.")

    @classmethod
    def get_historical_rate(
        cls,
        base_currency: str,
        quote_currency: str,
        on_date: str
    ) -> FxQuote:
        """
        Retrieves exchange rate on a specific historical date (YYYY-MM-DD).
        Historical rates are immutable: cached indefinitely once stored.
        Never returns a future rate for weekend or holiday lookups.
        """
        b = base_currency.strip().upper()
        q = quote_currency.strip().upper()

        if b == q:
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return FxQuote(b, q, Decimal("1.0"), on_date, "identity", now_iso, is_stale=False)

        # 1. Check cached rate in database
        cached = cls._find_cached_rate(b, q, on_date=on_date)
        if cached:
            return cached

        # 2. Fetch from provider for specific date
        try:
            quote = cls.get_provider().get_rate(b, q, on_date=on_date)
            # Ensure the provider rate is stored under requested on_date
            quote_to_store = FxQuote(
                base_currency=b,
                quote_currency=q,
                rate=quote.rate,
                rate_date=on_date,
                provider=quote.provider,
                fetched_at=quote.fetched_at,
                is_stale=False
            )
            cls._store_rate(quote_to_store, provider_rate_date=quote.rate_date)
            return quote_to_store
        except FxProviderError:
            # 3. Fallback: check nearest available past rate on or before on_date
            nearest = cls._find_nearest_past_cached_rate(b, q, on_date=on_date)
            if nearest:
                return FxQuote(
                    base_currency=nearest.base_currency,
                    quote_currency=nearest.quote_currency,
                    rate=nearest.rate,
                    rate_date=nearest.rate_date,
                    provider=nearest.provider,
                    fetched_at=nearest.fetched_at,
                    is_stale=True
                )
            raise FxRateUnavailableError(f"Historical exchange rate for {b}->{q} on {on_date} is unavailable.")

    @classmethod
    def store_manual_rate(
        cls,
        base_currency: str,
        quote_currency: str,
        rate: Decimal | str,
        on_date: Optional[str] = None
    ) -> FxQuote:
        """Stores a user-provided manual settlement rate in exchange_rates."""
        b = base_currency.strip().upper()
        q = quote_currency.strip().upper()
        d_rate = Decimal(str(rate))
        eff_date = on_date or date.today().isoformat()
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        quote = FxQuote(
            base_currency=b,
            quote_currency=q,
            rate=d_rate,
            rate_date=eff_date,
            provider="manual",
            fetched_at=now_iso,
            is_stale=False
        )
        cls._store_rate(quote)
        return quote

    @classmethod
    def convert_minor(
        cls,
        amount_minor: int,
        source_currency: str,
        target_currency: str,
        on_date: Optional[str] = None,
        manual_rate: Optional[Decimal | str] = None
    ) -> FxConversion:
        """
        Converts an integer minor amount from source_currency into target_currency.
        Returns full FxConversion details.
        """
        src = source_currency.strip().upper()
        tgt = target_currency.strip().upper()

        if src == tgt:
            today_iso = on_date or date.today().isoformat()
            return FxConversion(
                source=Money(amount_minor, src),
                target=Money(amount_minor, tgt),
                rate=Decimal("1.0"),
                rate_date=today_iso,
                provider="identity",
                is_stale=False
            )

        if manual_rate is not None:
            d_rate = Decimal(str(manual_rate))
            tgt_minor = convert_money(amount_minor, src, tgt, d_rate)
            eff_date = on_date or date.today().isoformat()
            return FxConversion(
                source=Money(amount_minor, src),
                target=Money(tgt_minor, tgt),
                rate=d_rate,
                rate_date=eff_date,
                provider="manual",
                is_stale=False
            )

        if on_date:
            quote = cls.get_historical_rate(src, tgt, on_date=on_date)
        else:
            quote = cls.get_latest_rate(src, tgt)

        tgt_minor = convert_money(amount_minor, src, tgt, quote.rate)
        return FxConversion(
            source=Money(amount_minor, src),
            target=Money(tgt_minor, tgt),
            rate=quote.rate,
            rate_date=quote.rate_date,
            provider=quote.provider,
            is_stale=quote.is_stale
        )

    # --- Internal Storage & DB Retrieval Helpers ---

    @staticmethod
    def _find_cached_rate(base: str, quote: str, on_date: Optional[str] = None) -> Optional[FxQuote]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            date_clause = "AND rate_date = ?" if on_date else ""
            params = [base, quote] + ([on_date] if on_date else [])
            cur.execute(f"""
                SELECT base_currency, quote_currency, rate, rate_date, provider, fetched_at
                FROM exchange_rates
                WHERE base_currency = ? AND quote_currency = ? {date_clause}
                ORDER BY rate_date DESC, id DESC
                LIMIT 1
            """, params)
            row = cur.fetchone()
            if row:
                return FxQuote(
                    base_currency=row["base_currency"],
                    quote_currency=row["quote_currency"],
                    rate=Decimal(row["rate"]),
                    rate_date=row["rate_date"],
                    provider=row["provider"],
                    fetched_at=row["fetched_at"],
                    is_stale=False
                )

            # Check inverse rate (quote -> base)
            inv_params = [quote, base] + ([on_date] if on_date else [])
            cur.execute(f"""
                SELECT base_currency, quote_currency, rate, rate_date, provider, fetched_at
                FROM exchange_rates
                WHERE base_currency = ? AND quote_currency = ? {date_clause}
                ORDER BY rate_date DESC, id DESC
                LIMIT 1
            """, inv_params)
            inv_row = cur.fetchone()
            if inv_row:
                inv_rate = Decimal(inv_row["rate"])
                if inv_rate > 0:
                    return FxQuote(
                        base_currency=base,
                        quote_currency=quote,
                        rate=Decimal("1") / inv_rate,
                        rate_date=inv_row["rate_date"],
                        provider=f"{inv_row['provider']}_reciprocal",
                        fetched_at=inv_row["fetched_at"],
                        is_stale=False
                    )

            return None

    @staticmethod
    def _find_nearest_past_cached_rate(base: str, quote: str, on_date: str) -> Optional[FxQuote]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT base_currency, quote_currency, rate, rate_date, provider, fetched_at
                FROM exchange_rates
                WHERE base_currency = ? AND quote_currency = ? AND rate_date <= ?
                ORDER BY rate_date DESC, id DESC
                LIMIT 1
            """, [base, quote, on_date])
            row = cur.fetchone()
            if row:
                return FxQuote(
                    base_currency=row["base_currency"],
                    quote_currency=row["quote_currency"],
                    rate=Decimal(row["rate"]),
                    rate_date=row["rate_date"],
                    provider=row["provider"],
                    fetched_at=row["fetched_at"],
                    is_stale=True
                )
            return None

    @staticmethod
    def _store_rate(quote: FxQuote, provider_rate_date: Optional[str] = None):
        with get_db_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO exchange_rates (
                    base_currency, quote_currency, rate_date, rate, provider, provider_rate_date, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [
                quote.base_currency,
                quote.quote_currency,
                quote.rate_date,
                str(quote.rate),
                quote.provider,
                provider_rate_date or quote.rate_date,
                quote.fetched_at
            ])
            conn.commit()
