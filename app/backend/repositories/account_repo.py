from typing import List, Dict, Any, Optional
from app.backend.database.connection import get_db_connection
from app.backend.domain.money import major_to_minor, minor_to_major
from app.backend.domain.validators import validate_currency_code


class AccountRepository:
    @staticmethod
    def get_all(include_archived: bool = False) -> List[Dict[str, Any]]:
        from app.backend.services.settings_service import SettingsService
        from app.backend.fx.service import FxService
        base_currency = SettingsService.get_setting("currency", "USD") or "USD"

        with get_db_connection() as conn:
            cur = conn.cursor()
            query = """
                SELECT 
                    a.id, a.name, a.account_type, a.institution, 
                    a.opening_balance_minor, a.currency, a.is_archived, a.created_at,
                    (
                        a.opening_balance_minor +
                        COALESCE((
                            SELECT SUM(
                                CASE 
                                    WHEN t.transaction_type = 'income' THEN t.amount_minor
                                    WHEN t.transaction_type = 'expense' THEN -t.amount_minor
                                    WHEN t.transaction_type = 'refund' THEN t.amount_minor
                                    WHEN t.transaction_type = 'transfer' AND (t.transfer_role = 'destination' OR t.description LIKE '%(Received)%') THEN t.amount_minor
                                    WHEN t.transaction_type = 'transfer' THEN -t.amount_minor
                                    WHEN t.transaction_type = 'adjustment' THEN t.amount_minor
                                    ELSE 0
                                END
                            )
                            FROM active_transactions t
                            WHERE t.account_id = a.id
                        ), 0)
                    ) as current_balance_minor
                FROM accounts a
                WHERE 1=1
            """
            if not include_archived:
                query += " AND a.is_archived = 0"
            query += " ORDER BY a.id ASC"

            cur.execute(query)
            results = []
            for row in cur.fetchall():
                acc = dict(row)
                curr = acc["currency"]
                acc["opening_balance"] = float(minor_to_major(acc["opening_balance_minor"], curr))
                acc["current_balance"] = float(minor_to_major(acc["current_balance_minor"], curr))

                # Base currency valuation
                if curr == base_currency:
                    acc["current_balance_base_minor"] = acc["current_balance_minor"]
                    acc["current_balance_base"] = acc["current_balance"]
                else:
                    try:
                        conv = FxService.convert_minor(acc["current_balance_minor"], curr, base_currency)
                        acc["current_balance_base_minor"] = conv.target.minor
                        acc["current_balance_base"] = float(conv.target.to_decimal())
                    except Exception:
                        acc["current_balance_base_minor"] = None
                        acc["current_balance_base"] = None
                results.append(acc)
            return results

    @staticmethod
    def get_by_id(account_id: int) -> Optional[Dict[str, Any]]:
        accounts = AccountRepository.get_all(include_archived=True)
        for acc in accounts:
            if acc["id"] == account_id:
                return acc
        return None

    @staticmethod
    def get_balance(account_id: int) -> float:
        acc = AccountRepository.get_by_id(account_id)
        if acc:
            return float(acc["current_balance"])
        return 0.0

    @staticmethod
    def create(name: str, account_type: str, institution: str = "", opening_balance: float = 0.0, currency: Optional[str] = None) -> int:
        if not name or not name.strip():
            raise ValueError("Account name cannot be empty.")
        from app.backend.services.settings_service import SettingsService
        base_currency = SettingsService.get_setting("currency", "USD") or "USD"

        if currency:
            target_currency = validate_currency_code(currency)
        else:
            target_currency = base_currency

        opening_minor = major_to_minor(opening_balance, target_currency)

        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO accounts (name, account_type, institution, opening_balance_minor, currency)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name.strip(), account_type, institution, opening_minor, target_currency)
            )
            conn.commit()
            return cur.lastrowid

    @staticmethod
    def update(account_id: int, **fields) -> bool:
        if "name" in fields:
            if not fields["name"] or not str(fields["name"]).strip():
                raise ValueError("Account name cannot be empty.")
            fields["name"] = str(fields["name"]).strip()

        if "currency" in fields:
            new_curr = validate_currency_code(fields["currency"])
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM transactions WHERE account_id = ?", (account_id,))
                if cur.fetchone()[0] > 0:
                    raise ValueError("Account currency cannot be changed after ledger transactions exist.")
            fields["currency"] = new_curr

        allowed = {"name", "account_type", "institution", "currency", "is_archived"}
        updates = {k: v for k, v in fields.items() if k in allowed}

        if "opening_balance" in fields:
            # Need currency to accurately scale opening balance
            acc = AccountRepository.get_by_id(account_id)
            acc_curr = fields.get("currency") or (acc["currency"] if acc else "USD")
            updates["opening_balance_minor"] = major_to_minor(fields["opening_balance"], acc_curr)

        if not updates:
            return False

        set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [account_id]

        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(f"UPDATE accounts SET {set_clause} WHERE id = ?", values)
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def delete(account_id: int) -> bool:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM accounts WHERE id = ?", (account_id,))
            if not cur.fetchone():
                return False
            cur.execute("SELECT COUNT(*) FROM transactions WHERE account_id = ?", (account_id,))
            if cur.fetchone()[0] > 0:
                cur.execute("UPDATE accounts SET is_archived = 1 WHERE id = ?", (account_id,))
            else:
                cur.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            conn.commit()
            return True
