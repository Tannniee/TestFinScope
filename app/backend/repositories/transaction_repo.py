import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime
from app.backend.database.connection import get_db_connection

class TransactionRepository:
    @staticmethod
    def get_all(
        month: Optional[str] = None,
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
                    t.id, t.account_id, t.category_id, t.merchant_id, t.merchant_name,
                    t.transaction_type, t.amount_minor,
                    ROUND(CAST(t.amount_minor AS REAL) / 100.0, 2) as amount,
                    t.transaction_date, t.transaction_time, t.description, t.note,
                    t.is_recurring, t.recurring_rule_id, t.payment_method, t.essentiality,
                    t.transfer_group_id, t.linked_transaction_id,
                    t.created_at, t.updated_at,
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

            count_query = f"SELECT COUNT(*) FROM ({query}) as count_sub"
            cur.execute(count_query, params)
            total_count = cur.fetchone()[0]

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
                    t.id, t.account_id, t.category_id, t.merchant_id, t.merchant_name,
                    t.transaction_type, t.amount_minor,
                    ROUND(CAST(t.amount_minor AS REAL) / 100.0, 2) as amount,
                    t.transaction_date, t.transaction_time, t.description, t.note,
                    t.is_recurring, t.recurring_rule_id, t.payment_method, t.essentiality,
                    t.transfer_group_id, t.linked_transaction_id,
                    t.created_at, t.updated_at,
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
        amount_minor = int(round(float(data["amount"]) * 100))
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO transactions (
                    account_id, category_id, merchant_name, transaction_type,
                    amount_minor, transaction_date, transaction_time, description,
                    note, is_recurring, payment_method, essentiality,
                    transfer_group_id, linked_transaction_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["account_id"],
                data.get("category_id"),
                data.get("merchant_name", ""),
                data["transaction_type"],
                amount_minor,
                data["transaction_date"],
                data.get("transaction_time", "12:00"),
                data.get("description", ""),
                data.get("note", ""),
                1 if data.get("is_recurring") else 0,
                data.get("payment_method", "Card"),
                data.get("essentiality", "discretionary"),
                data.get("transfer_group_id"),
                data.get("linked_transaction_id")
            ))
            conn.commit()
            return cur.lastrowid

    @staticmethod
    def create_transfer(
        from_account_id: int,
        to_account_id: int,
        amount: float,
        transaction_date: str,
        transaction_time: str = "12:00",
        description: str = "Account Transfer",
        note: str = ""
    ) -> Dict[str, Any]:
        """
        Creates proper double-entry transfer records linked via transfer_group_id.
        Leg 1: Outflow from source account (Debit)
        Leg 2: Inflow into destination account (Credit)
        """
        if from_account_id == to_account_id:
            raise ValueError("Source and destination accounts must be different.")

        amount_minor = int(round(float(amount) * 100))
        group_id = str(uuid.uuid4())

        with get_db_connection() as conn:
            cur = conn.cursor()

            # Fetch account names
            cur.execute("SELECT id, name FROM accounts WHERE id IN (?, ?)", (from_account_id, to_account_id))
            acc_names = {r["id"]: r["name"] for r in cur.fetchall()}
            from_name = acc_names.get(from_account_id, "Account")
            to_name = acc_names.get(to_account_id, "Account")

            # Outflow leg (From account)
            cur.execute("""
                INSERT INTO transactions (
                    account_id, merchant_name, transaction_type,
                    amount_minor, transaction_date, transaction_time, description,
                    note, payment_method, essentiality, transfer_group_id
                ) VALUES (?, ?, 'transfer', ?, ?, ?, ?, ?, 'Transfer', 'savings', ?)
            """, (
                from_account_id,
                f"Transfer to {to_name}",
                amount_minor,
                transaction_date,
                transaction_time,
                description or f"Transfer to {to_name}",
                note,
                group_id
            ))
            leg1_id = cur.lastrowid

            # Inflow leg (To account)
            cur.execute("""
                INSERT INTO transactions (
                    account_id, merchant_name, transaction_type,
                    amount_minor, transaction_date, transaction_time, description,
                    note, payment_method, essentiality, transfer_group_id, linked_transaction_id
                ) VALUES (?, ?, 'transfer', ?, ?, ?, ?, ?, 'Transfer', 'savings', ?, ?)
            """, (
                to_account_id,
                f"Transfer from {from_name}",
                amount_minor,
                transaction_date,
                transaction_time,
                f"{description or 'Transfer'} (Received)",
                note,
                group_id,
                leg1_id
            ))
            leg2_id = cur.lastrowid

            # Link leg 1 back to leg 2
            cur.execute("UPDATE transactions SET linked_transaction_id = ? WHERE id = ?", (leg2_id, leg1_id))
            conn.commit()

            return {
                "transfer_group_id": group_id,
                "outflow_tx_id": leg1_id,
                "inflow_tx_id": leg2_id
            }

    @staticmethod
    def update(tx_id: int, data: Dict[str, Any]) -> bool:
        allowed = {
            "account_id", "category_id", "merchant_name", "transaction_type",
            "transaction_date", "transaction_time", "description",
            "note", "is_recurring", "payment_method", "essentiality"
        }
        updates = {k: v for k, v in data.items() if k in allowed}
        if not updates:
            return False

        if "amount" in data:
            updates["amount_minor"] = int(round(float(data["amount"]) * 100))
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
        """Deletes transaction and cleanly deletes linked transfer legs if part of a transfer group."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT transfer_group_id FROM transactions WHERE id = ?", (tx_id,))
            row = cur.fetchone()
            if row and row["transfer_group_id"]:
                cur.execute("DELETE FROM transactions WHERE transfer_group_id = ?", (row["transfer_group_id"],))
            else:
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
        clone.pop("transfer_group_id", None)
        clone.pop("linked_transaction_id", None)
        clone["description"] = f"{clone.get('description', '')} (Copy)".strip()
        return TransactionRepository.create(clone)
