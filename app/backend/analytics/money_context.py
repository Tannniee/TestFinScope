"""
Canonical Money Context for FinScope Analytics V2.
Ensures every analytics module operates on explicit, consistent currency domains:
- Portfolio Scope (account_id is None): All calculations use COALESCE(base_amount_minor, amount_minor)
  and values are denominated in the configured Base / Reporting Currency.
- Account Scope (account_id is not None): Calculations use native amount_minor and the account's currency.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from app.backend.database.connection import get_db_connection
from app.backend.services.settings_service import SettingsService
from app.backend.domain.currencies import get_currency_meta
from app.backend.domain.money import minor_to_major, format_money, major_to_minor


@dataclass(frozen=True)
class AnalyticsMoneyContext:
    currency: str
    account_id: Optional[int]
    is_portfolio: bool
    amount_expr: str
    tx_amount_expr: str

    def to_major(self, minor: int) -> float:
        """Converts integer minor units to float major units respecting the context currency."""
        return float(minor_to_major(minor, self.currency))

    def to_major_decimal(self, minor: int) -> Decimal:
        """Converts integer minor units to Decimal major units respecting the context currency."""
        return minor_to_major(minor, self.currency)

    def format(self, minor: int, show_symbol: bool = True) -> str:
        """Formats integer minor units to standard display string respecting the context currency."""
        return format_money(minor, self.currency, show_symbol=show_symbol)

    def materiality_minor(self, baseline_minor: Optional[int] = None) -> int:
        """
        Returns a currency-aware materiality threshold.
        For USD/EUR (2 decimals): 5000 minor ($50.00).
        For VND/JPY (0 decimals): 100,000 minor (VND) / 5,000 minor (JPY).
        For KWD/BHD (3 decimals): 15,000 minor (15.000 KWD).
        """
        meta = get_currency_meta(self.currency)
        if meta.minor_unit == 0:
            if self.currency == "VND":
                return 500000  # ~20 USD
            return 5000        # JPY ~35 USD
        elif meta.minor_unit == 3:
            return 15000       # ~50 USD
        else:
            return 5000        # 50.00 USD/EUR/GBP


def resolve_analytics_money_context(account_id: Optional[int] = None) -> AnalyticsMoneyContext:
    """
    Resolves the canonical money context for analytics operations.
    If account_id is provided, looks up account's native currency.
    If account_id is None, uses reporting Base Currency.
    """
    base_currency = SettingsService.get_setting("currency", "USD") or "USD"
    base_currency = base_currency.strip().upper()

    if account_id is None:
        return AnalyticsMoneyContext(
            currency=base_currency,
            account_id=None,
            is_portfolio=True,
            amount_expr=f"COALESCE(base_amount_minor, CASE WHEN COALESCE(base_currency, '{base_currency}') = COALESCE((SELECT currency FROM accounts WHERE id = account_id), '{base_currency}') THEN amount_minor ELSE 0 END)",
            tx_amount_expr=f"COALESCE(t.base_amount_minor, CASE WHEN COALESCE(t.base_currency, '{base_currency}') = COALESCE((SELECT currency FROM accounts WHERE id = t.account_id), '{base_currency}') THEN t.amount_minor ELSE 0 END)"
        )

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT currency FROM accounts WHERE id = ?", (account_id,))
        row = cur.fetchone()
        acc_currency = row["currency"].strip().upper() if row and row["currency"] else base_currency

    return AnalyticsMoneyContext(
        currency=acc_currency,
        account_id=account_id,
        is_portfolio=False,
        amount_expr="amount_minor",
        tx_amount_expr="t.amount_minor"
    )


def get_portfolio_fx_completeness(month: Optional[str] = None) -> Dict[str, Any]:
    """Returns FX completeness stats for portfolio scope."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        query = """
            SELECT 
                COUNT(*) as total_txs,
                SUM(CASE WHEN a.currency <> t.base_currency THEN 1 ELSE 0 END) as foreign_txs,
                SUM(CASE WHEN a.currency <> t.base_currency AND t.base_amount_minor IS NULL THEN 1 ELSE 0 END) as pending_fx_txs
            FROM active_transactions t
            JOIN accounts a ON t.account_id = a.id
            WHERE 1=1
        """
        params = []
        if month:
            query += " AND t.transaction_date LIKE ?"
            params.append(f"{month}%")
        cur.execute(query, params)
        row = cur.fetchone()
        total = row["total_txs"] or 0
        foreign = row["foreign_txs"] or 0
        pending = row["pending_fx_txs"] or 0
        reconciled = foreign - pending
        pct = round((reconciled / foreign * 100.0) if foreign > 0 else 100.0, 1)
        return {
            "total_transactions": total,
            "foreign_transactions": foreign,
            "pending_valuations": pending,
            "reconciled_percentage": pct,
            "is_complete": pending == 0
        }

