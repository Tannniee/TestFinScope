"""
Transaction Repository for FinScope CORE.
Handles structured transaction persistence, exact integer minor units,
double-entry transfers with transfer_roles, linked refunds,
soft-delete for undo recovery, and review queue resolution.
"""

import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime
from app.backend.database.connection import get_db_connection
from app.backend.services.merchant_service import MerchantService, normalize_merchant_name

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
        needs_review: Optional[bool] = None,
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
                    t.transfer_group_id, t.transfer_role, t.linked_transaction_id,
                    t.refund_of_transaction_id, t.source, t.needs_review,
                    t.created_at, t.updated_at,
                    a.name as account_name,
                    c.name as category_name,
                    c.color as category_color,
                    c.icon as category_icon
                FROM transactions t
                LEFT JOIN accounts a ON t.account_id = a.id
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE t.is_deleted = 0
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
            if needs_review is not None:
                query += " AND t.needs_review = ?"
                params.append(1 if needs_review else 0)
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
    def get_by_id(tx_id: int, include_deleted: bool = False) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            query = """
                SELECT 
                    t.id, t.account_id, t.category_id, t.merchant_id, t.merchant_name,
                    t.transaction_type, t.amount_minor,
                    ROUND(CAST(t.amount_minor AS REAL) / 100.0, 2) as amount,
                    t.transaction_date, t.transaction_time, t.description, t.note,
                    t.is_recurring, t.recurring_rule_id, t.payment_method, t.essentiality,
                    t.transfer_group_id, t.transfer_role, t.linked_transaction_id,
                    t.refund_of_transaction_id, t.source, t.needs_review, t.is_deleted,
                    t.created_at, t.updated_at,
                    a.name as account_name,
                    c.name as category_name,
                    c.color as category_color,
                    c.icon as category_icon
                FROM transactions t
                LEFT JOIN accounts a ON t.account_id = a.id
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE t.id = ?
            """
            if not include_deleted:
                query += " AND t.is_deleted = 0"
            cur.execute(query, (tx_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    @staticmethod
    def create(data: Dict[str, Any]) -> int:
        amount_minor = int(round(float(data["amount"]) * 100))
        tx_type = data["transaction_type"]
        category_id = data.get("category_id")
        raw_merchant = data.get("merchant_name", "")
        clean_merchant = normalize_merchant_name(raw_merchant)
        needs_review = 1 if data.get("needs_review") else 0

        # Smart Merchant Resolution & Auto-learning
        merchant_id = None
        if clean_merchant:
            merchant_id = MerchantService.get_or_create_merchant(
                clean_merchant,
                category_id=category_id,
                account_id=data.get("account_id"),
                essentiality=data.get("essentiality")
            )

        with get_db_connection() as conn:
            cur = conn.cursor()

            # Handle Uncategorized for expense if category is missing
            if tx_type == "expense" and not category_id:
                cur.execute("SELECT id FROM categories WHERE name = 'Uncategorized'")
                uncat_row = cur.fetchone()
                if uncat_row:
                    category_id = uncat_row["id"]
                    needs_review = 1

            cur.execute("""
                INSERT INTO transactions (
                    account_id, category_id, merchant_id, merchant_name, transaction_type,
                    amount_minor, transaction_date, transaction_time, description,
                    note, is_recurring, payment_method, essentiality,
                    transfer_group_id, transfer_role, linked_transaction_id,
                    refund_of_transaction_id, source, needs_review, is_deleted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                data["account_id"],
                category_id,
                merchant_id,
                clean_merchant or raw_merchant,
                tx_type,
                amount_minor,
                data["transaction_date"],
                data.get("transaction_time", "12:00"),
                data.get("description", "") or clean_merchant,
                data.get("note", ""),
                1 if data.get("is_recurring") else 0,
                data.get("payment_method", "Card"),
                data.get("essentiality", "discretionary"),
                data.get("transfer_group_id"),
                data.get("transfer_role"),
                data.get("linked_transaction_id"),
                data.get("refund_of_transaction_id"),
                data.get("source", "manual"),
                needs_review
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
        Creates proper double-entry transfer records linked via transfer_group_id
        with explicit transfer_roles: 'source' (debit) and 'destination' (credit).
        """
        if from_account_id == to_account_id:
            raise ValueError("Source and destination accounts must be different.")

        amount_minor = int(round(float(amount) * 100))
        group_id = str(uuid.uuid4())

        with get_db_connection() as conn:
            cur = conn.cursor()

            cur.execute("SELECT id, name FROM accounts WHERE id IN (?, ?)", (from_account_id, to_account_id))
            acc_names = {r["id"]: r["name"] for r in cur.fetchall()}
            from_name = acc_names.get(from_account_id, "Account")
            to_name = acc_names.get(to_account_id, "Account")

            # Outflow leg (From account - Source)
            cur.execute("""
                INSERT INTO transactions (
                    account_id, merchant_name, transaction_type,
                    amount_minor, transaction_date, transaction_time, description,
                    note, payment_method, essentiality, transfer_group_id, transfer_role,
                    source, is_deleted
                ) VALUES (?, ?, 'transfer', ?, ?, ?, ?, ?, 'Transfer', 'savings', ?, 'source', 'manual', 0)
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

            # Inflow leg (To account - Destination)
            cur.execute("""
                INSERT INTO transactions (
                    account_id, merchant_name, transaction_type,
                    amount_minor, transaction_date, transaction_time, description,
                    note, payment_method, essentiality, transfer_group_id, transfer_role,
                    linked_transaction_id, source, is_deleted
                ) VALUES (?, ?, 'transfer', ?, ?, ?, ?, ?, 'Transfer', 'savings', ?, 'destination', ?, 'manual', 0)
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

            cur.execute("UPDATE transactions SET linked_transaction_id = ? WHERE id = ?", (leg2_id, leg1_id))
            conn.commit()

            return {
                "transfer_group_id": group_id,
                "outflow_tx_id": leg1_id,
                "inflow_tx_id": leg2_id,
                "source_transaction": TransactionRepository.get_by_id(leg1_id),
                "destination_transaction": TransactionRepository.get_by_id(leg2_id)
            }

    @staticmethod
    def create_refund(
        original_tx_id: int,
        amount: float,
        transaction_date: str,
        account_id: Optional[int] = None,
        note: str = ""
    ) -> int:
        """
        Creates a refund linked to an original expense transaction.
        Inherits category, merchant, and essentiality from the original.
        """
        orig = TransactionRepository.get_by_id(original_tx_id)
        if not orig:
            raise ValueError(f"Original transaction {original_tx_id} not found.")

        target_acc_id = account_id or orig["account_id"]
        merchant_name = orig.get("merchant_name", "")
        desc = f"Refund: {orig.get('description', merchant_name)}"

        refund_data = {
            "account_id": target_acc_id,
            "category_id": orig["category_id"],
            "merchant_name": merchant_name,
            "transaction_type": "refund",
            "amount": amount,
            "transaction_date": transaction_date,
            "transaction_time": datetime.now().strftime("%H:%M"),
            "description": desc,
            "note": note,
            "essentiality": orig.get("essentiality", "discretionary"),
            "refund_of_transaction_id": original_tx_id,
            "source": "manual"
        }
        return TransactionRepository.create(refund_data)

    @staticmethod
    def update(tx_id: int, data: Dict[str, Any]) -> bool:
        allowed = {
            "account_id", "category_id", "merchant_name", "transaction_type",
            "transaction_date", "transaction_time", "description",
            "note", "is_recurring", "payment_method", "essentiality",
            "needs_review"
        }
        updates = {k: v for k, v in data.items() if k in allowed}
        if not updates:
            return False

        if "amount" in data:
            updates["amount_minor"] = int(round(float(data["amount"]) * 100))
        if "is_recurring" in updates:
            updates["is_recurring"] = 1 if updates["is_recurring"] else 0
        if "merchant_name" in updates:
            updates["merchant_name"] = normalize_merchant_name(updates["merchant_name"])

        updates["updated_at"] = datetime.now().isoformat()
        set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [tx_id]

        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(f"UPDATE transactions SET {set_clause} WHERE id = ?", values)
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def delete(tx_id: int, hard: bool = False) -> bool:
        """
        By default, soft-deletes (is_deleted = 1) allowing 5-second Undo recovery.
        If part of a transfer group, operates atomically on both legs.
        """
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT transfer_group_id FROM transactions WHERE id = ?", (tx_id,))
            row = cur.fetchone()

            if hard:
                if row and row["transfer_group_id"]:
                    cur.execute("DELETE FROM transactions WHERE transfer_group_id = ?", (row["transfer_group_id"],))
                else:
                    cur.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
            else:
                if row and row["transfer_group_id"]:
                    cur.execute("UPDATE transactions SET is_deleted = 1 WHERE transfer_group_id = ?", (row["transfer_group_id"],))
                else:
                    cur.execute("UPDATE transactions SET is_deleted = 1 WHERE id = ?", (tx_id,))

            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def undo_delete(tx_id: int) -> bool:
        """Restores a soft-deleted transaction or transfer group."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT transfer_group_id FROM transactions WHERE id = ?", (tx_id,))
            row = cur.fetchone()
            if row and row["transfer_group_id"]:
                cur.execute("UPDATE transactions SET is_deleted = 0 WHERE transfer_group_id = ?", (row["transfer_group_id"],))
            else:
                cur.execute("UPDATE transactions SET is_deleted = 0 WHERE id = ?", (tx_id,))
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def get_review_queue(limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """Returns transactions that require review (e.g. Uncategorized or flagged)."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    t.id, t.account_id, t.category_id, t.merchant_name, t.amount_minor,
                    ROUND(CAST(t.amount_minor AS REAL) / 100.0, 2) as amount,
                    t.transaction_date, t.description, t.essentiality,
                    a.name as account_name,
                    c.name as category_name, c.color as category_color, c.icon as category_icon
                FROM transactions t
                LEFT JOIN accounts a ON t.account_id = a.id
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE (t.needs_review = 1 OR c.name = 'Uncategorized')
                  AND t.is_deleted = 0
                ORDER BY t.transaction_date DESC, t.id DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))
            items = [dict(r) for r in cur.fetchall()]

            cur.execute("""
                SELECT COUNT(*) FROM transactions t
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE (t.needs_review = 1 OR c.name = 'Uncategorized')
                  AND t.is_deleted = 0
            """)
            total = cur.fetchone()[0]

            return {
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset
            }

    @staticmethod
    def resolve_review(tx_id: int, category_id: int, merchant_name: Optional[str] = None) -> bool:
        """Sets category, clears review flag, and teaches MerchantService."""
        tx = TransactionRepository.get_by_id(tx_id)
        if not tx:
            return False

        effective_merchant = normalize_merchant_name(merchant_name or tx.get("merchant_name", ""))
        if effective_merchant:
            MerchantService.get_or_create_merchant(
                effective_merchant,
                category_id=category_id,
                account_id=tx.get("account_id")
            )

        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE transactions 
                SET category_id = ?, needs_review = 0, merchant_name = ?
                WHERE id = ?
            """, (category_id, effective_merchant or tx.get("merchant_name", ""), tx_id))
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
        clone.pop("transfer_role", None)
        clone.pop("linked_transaction_id", None)
        clone["description"] = f"{clone.get('description', '')} (Copy)".strip()
        return TransactionRepository.create(clone)
