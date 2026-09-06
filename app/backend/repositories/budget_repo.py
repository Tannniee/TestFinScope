from typing import List, Dict, Any, Optional
from app.backend.database.connection import get_db_connection
from app.backend.domain.money import major_to_minor, minor_to_major, format_money
from app.backend.services.settings_service import SettingsService
from app.backend.repositories.account_repo import AccountRepository

class BudgetRepository:
    @staticmethod
    def get_by_month(month: str, account_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Returns all budgets for a given month (YYYY-MM), joined with actual net expense spend
        (expenses minus refunds), normalized to reporting base currency or account currency.
        """
        from app.backend.domain.validators import validate_month
        validate_month(month)
        base_currency = SettingsService.get_setting("currency", "USD") or "USD"
        filter_currency = base_currency
        if account_id:
            acc = AccountRepository.get_by_id(account_id)
            if acc and acc.get("currency"):
                filter_currency = acc["currency"]

        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND t.account_id = ?" if account_id else ""
            params = [month, f"{month}%"] + ([account_id] if account_id else [])

            # Category budgets are denominated in Reporting/Base Currency.
            # Spend (whether portfolio or account-scoped) must be evaluated in that same currency to allow valid comparison.
            amt_col = "COALESCE(t.base_amount_minor, t.amount_minor)"

            cur.execute(f"""
                SELECT 
                    b.id,
                    b.category_id,
                    b.amount_minor,
                    b.currency as budget_currency,
                    b.start_date,
                    c.name as category_name,
                    c.color as category_color,
                    c.icon as category_icon,
                    COALESCE(
                        SUM(
                            CASE 
                                WHEN t.transaction_type = 'expense' THEN {amt_col}
                                WHEN t.transaction_type = 'refund' THEN -{amt_col}
                                ELSE 0
                            END
                        ), 0
                    ) as spent_minor
                FROM categories c
                LEFT JOIN budgets b ON b.category_id = c.id AND b.start_date = ?
                LEFT JOIN active_transactions t ON t.category_id = c.id 
                    AND t.transaction_type IN ('expense', 'refund')
                    AND t.transaction_date LIKE ? {acc_clause}
                WHERE c.type = 'expense' AND c.is_archived = 0
                GROUP BY c.id, b.id
                ORDER BY b.amount_minor DESC, c.name ASC
            """, params)
            rows = cur.fetchall()

            result = []
            for r in rows:
                item = dict(r)
                b_curr = item.get("budget_currency") or base_currency
                item["currency"] = b_curr
                spent_min = item.pop("spent_minor", 0) or 0
                b_min = item.get("amount_minor")

                if b_min is not None:
                    item["budget_amount"] = float(minor_to_major(b_min, b_curr))
                    item["formatted_budget_amount"] = format_money(b_min, b_curr)
                else:
                    item["budget_amount"] = None
                    item["formatted_budget_amount"] = None

                item["spent_amount"] = float(minor_to_major(spent_min, b_curr))
                item["formatted_spent_amount"] = format_money(spent_min, b_curr)
                result.append(item)

            return result

    @staticmethod
    def set_budget(category_id: int, month: str, amount: float, currency: Optional[str] = None) -> int:
        from app.backend.domain.validators import validate_budget_amount, validate_month, validate_budget_category
        validate_month(month)
        base_currency = SettingsService.get_setting("currency", "USD") or "USD"
        eff_currency = currency or base_currency
        amount_minor = validate_budget_amount(amount, currency=eff_currency)

        with get_db_connection() as conn:
            validate_budget_category(conn, category_id)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO budgets (category_id, start_date, amount_minor, period_type, currency)
                VALUES (?, ?, ?, 'monthly', ?)
                ON CONFLICT(category_id, start_date) DO UPDATE SET
                    amount_minor = excluded.amount_minor,
                    currency = excluded.currency
            """, (category_id, month, amount_minor, eff_currency))
            conn.commit()
            return cur.lastrowid

    @staticmethod
    def delete_budget(budget_id: int) -> bool:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM budgets WHERE id = ?", (budget_id,))
            conn.commit()
            return cur.rowcount > 0
