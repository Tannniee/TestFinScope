from typing import List, Dict, Any, Optional
from app.backend.database.connection import get_db_connection

class AccountRepository:
    @staticmethod
    def get_all(include_archived: bool = False) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            query = """
                SELECT 
                    a.id, a.name, a.account_type, a.institution, 
                    a.opening_balance_minor, a.currency, a.is_archived, a.created_at,
                    ROUND(CAST(a.opening_balance_minor AS REAL) / 100.0, 2) as opening_balance,
                    (
                        ROUND(CAST(a.opening_balance_minor AS REAL) / 100.0, 2) +
                        COALESCE((
                            SELECT SUM(
                                CASE 
                                    WHEN t.transaction_type = 'income' THEN CAST(t.amount_minor AS REAL) / 100.0
                                    WHEN t.transaction_type = 'expense' THEN -CAST(t.amount_minor AS REAL) / 100.0
                                    WHEN t.transaction_type = 'refund' THEN CAST(t.amount_minor AS REAL) / 100.0
                                    WHEN t.transaction_type = 'transfer' AND (t.transfer_role = 'destination' OR t.description LIKE '%(Received)%') THEN CAST(t.amount_minor AS REAL) / 100.0
                                    WHEN t.transaction_type = 'transfer' THEN -CAST(t.amount_minor AS REAL) / 100.0
                                    WHEN t.transaction_type = 'adjustment' THEN CAST(t.amount_minor AS REAL) / 100.0
                                    ELSE 0.0
                                END
                            )
                            FROM active_transactions t
                            WHERE t.account_id = a.id
                        ), 0.0)
                    ) as current_balance
                FROM accounts a
                WHERE 1=1
            """
            if not include_archived:
                query += " AND a.is_archived = 0"
            query += " ORDER BY a.id ASC"

            cur.execute(query)
            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def get_by_id(account_id: int) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    a.id, a.name, a.account_type, a.institution, 
                    a.opening_balance_minor, a.currency, a.is_archived, a.created_at,
                    ROUND(CAST(a.opening_balance_minor AS REAL) / 100.0, 2) as opening_balance
                FROM accounts a
                WHERE a.id = ?
            """, (account_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_balance(account_id: int) -> float:
        accounts = AccountRepository.get_all(include_archived=True)
        for acc in accounts:
            if acc["id"] == account_id:
                return float(acc["current_balance"])
        return 0.0

    @staticmethod
    def create(name: str, account_type: str, institution: str = "", opening_balance: float = 0.0, currency: str = "USD") -> int:
        opening_minor = int(round(float(opening_balance) * 100))
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO accounts (name, account_type, institution, opening_balance_minor, currency)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, account_type, institution, opening_minor, currency)
            )
            conn.commit()
            return cur.lastrowid

    @staticmethod
    def update(account_id: int, **fields) -> bool:
        allowed = {"name", "account_type", "institution", "currency", "is_archived"}
        updates = {k: v for k, v in fields.items() if k in allowed}

        if "opening_balance" in fields:
            updates["opening_balance_minor"] = int(round(float(fields["opening_balance"]) * 100))

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
            cur.execute("SELECT COUNT(*) FROM transactions WHERE account_id = ?", (account_id,))
            if cur.fetchone()[0] > 0:
                cur.execute("UPDATE accounts SET is_archived = 1 WHERE id = ?", (account_id,))
            else:
                cur.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            conn.commit()
            return True
