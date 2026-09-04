from typing import List, Dict, Any, Optional
from app.backend.database.connection import get_db_connection

class AccountRepository:
    @staticmethod
    def get_all(include_archived: bool = False) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            if include_archived:
                cur.execute("SELECT * FROM accounts ORDER BY id ASC")
            else:
                cur.execute("SELECT * FROM accounts WHERE is_archived = 0 ORDER BY id ASC")
            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def get_by_id(account_id: int) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    @staticmethod
    def create(name: str, account_type: str, institution: str = "", opening_balance: float = 0.0, currency: str = "USD") -> int:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO accounts (name, account_type, institution, opening_balance, currency)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, account_type, institution, opening_balance, currency)
            )
            conn.commit()
            return cur.lastrowid

    @staticmethod
    def update(account_id: int, **fields) -> bool:
        allowed = {"name", "account_type", "institution", "opening_balance", "currency", "is_archived"}
        updates = {k: v for k, v in fields.items() if k in allowed}
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
            # Check if has transactions
            cur.execute("SELECT COUNT(*) FROM transactions WHERE account_id = ?", (account_id,))
            if cur.fetchone()[0] > 0:
                # Soft delete
                cur.execute("UPDATE accounts SET is_archived = 1 WHERE id = ?", (account_id,))
            else:
                cur.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            conn.commit()
            return True
