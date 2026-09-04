from typing import List, Dict, Any, Optional
from datetime import datetime
from app.backend.database.connection import get_db_connection

class TransactionRepository:
    @staticmethod
    def get_all(
        month: Optional[str] = None, # e.g. "2026-09"
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        account_id: Optional[int] = None,
        category_id: Optional[int] = None,
        transaction_type: Optional[str] = None,
        essentiality: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            query = """
                SELECT 
                    t.*,
                    a.name as account_name,
                    c.name as category_name,
                    c.color as category_color,
                    c.icon as category_icon
                FROM transactions t
                LEFT JOIN accounts a ON t.account_id = a.id
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE 1=1
            """
            params = []

            if month:
                query += " AND t.transaction_date LIKE ?"
                params.append(f"{month}%")
            if start_date:
                query += " AND t.transaction_date >= ?"
                params.append(start_date)
            if end_date:
                query += " AND t.transaction_date <= ?"
                params.append(end_date)
            if account_id:
                query += " AND t.account_id = ?"
                params.append(account_id)
            if category_id:
                query += " AND t.category_id = ?"
                params.append(category_id)
            if transaction_type:
                query += " AND t.transaction_type = ?"
                params.append(transaction_type)
            if essentiality:
                query += " AND t.essentiality = ?"
                params.append(essentiality)
            if search:
                query += " AND (t.merchant_name LIKE ? OR t.description LIKE ? OR t.note LIKE ?)"
                term = f"%{search}%"
                params.extend([term, term, term])

            # Get total count
            count_query = f"SELECT COUNT(*) FROM ({query}) as count_sub"
            cur.execute(count_query, params)
            total_count = cur.fetchone()[0]

            # Append ordering and pagination
            query += " ORDER BY t.transaction_date DESC, t.transaction_time DESC, t.id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cur.execute(query, params)
            items = [dict(row) for row in cur.fetchall()]

            return {
                "items": items,
                "total": total_count,
                "limit": limit,
                "offset": offset
            }

    @staticmethod
    def get_by_id(tx_id: int) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    t.*,
                    a.name as account_name,
                    c.name as category_name,
                    c.color as category_color,
                    c.icon as category_icon
                FROM transactions t
                LEFT JOIN accounts a ON t.account_id = a.id
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE t.id = ?
            """, (tx_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    @staticmethod
    def create(data: Dict[str, Any]) -> int:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO transactions (
                    account_id, category_id, merchant_name, transaction_type,
                    amount, transaction_date, transaction_time, description,
                    note, is_recurring, payment_method, essentiality
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["account_id"],
                data.get("category_id"),
                data.get("merchant_name", ""),
                data["transaction_type"],
                float(data["amount"]),
                data["transaction_date"],
                data.get("transaction_time", "12:00"),
                data.get("description", ""),
                data.get("note", ""),
                1 if data.get("is_recurring") else 0,
                data.get("payment_method", "Card"),
                data.get("essentiality", "discretionary")
            ))
            conn.commit()
            return cur.lastrowid

    @staticmethod
    def update(tx_id: int, data: Dict[str, Any]) -> bool:
        allowed = {
            "account_id", "category_id", "merchant_name", "transaction_type",
            "amount", "transaction_date", "transaction_time", "description",
            "note", "is_recurring", "payment_method", "essentiality"
        }
        updates = {k: v for k, v in data.items() if k in allowed}
        if not updates:
            return False

        if "amount" in updates:
            updates["amount"] = float(updates["amount"])
        if "is_recurring" in updates:
            updates["is_recurring"] = 1 if updates["is_recurring"] else 0

        updates["updated_at"] = datetime.now().isoformat()
        set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [tx_id]

        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(f"UPDATE transactions SET {set_clause} WHERE id = ?", values)
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def delete(tx_id: int) -> bool:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def duplicate(tx_id: int) -> Optional[int]:
        original = TransactionRepository.get_by_id(tx_id)
        if not original:
            return None
        clone = dict(original)
        clone.pop("id", None)
        clone.pop("created_at", None)
        clone.pop("updated_at", None)
        clone.pop("account_name", None)
        clone.pop("category_name", None)
        clone.pop("category_color", None)
        clone.pop("category_icon", None)
        clone["description"] = f"{clone.get('description', '')} (Copy)".strip()
        return TransactionRepository.create(clone)
