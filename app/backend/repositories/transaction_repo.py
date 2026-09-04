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
                FROM active_transactions t
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
        tx_type = data["transaction_type"]
        if tx_type == "transfer":
            raise ValueError("Transfers must be created through TransferService.")

        amount_minor = int(round(float(data["amount"]) * 100))
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

        # Invariant: Prevent over-refunding in create
        if tx_type == "refund" and data.get("refund_of_transaction_id"):
            orig_id = data["refund_of_transaction_id"]
            orig = TransactionRepository.get_by_id(orig_id)
            if orig:
                with get_db_connection() as check_conn:
                    check_cur = check_conn.cursor()
                    check_cur.execute("""
                        SELECT COALESCE(SUM(amount_minor), 0)
                        FROM active_transactions
                        WHERE refund_of_transaction_id = ? AND transaction_type = 'refund'
                    """, (orig_id,))
                    existing_refunded_minor = check_cur.fetchone()[0]
                remaining_minor = orig["amount_minor"] - existing_refunded_minor
                if amount_minor > remaining_minor:
                    raise ValueError(
                        f"Cumulative refunds exceed original expense amount (Remaining: ${remaining_minor / 100:.2f}, Attempted: ${amount_minor / 100:.2f})."
                    )

        with get_db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.cursor()

                # Re-validate refund bounds inside transaction lock if refund
                if tx_type == "refund" and data.get("refund_of_transaction_id"):
                    orig_id = data["refund_of_transaction_id"]
                    cur.execute("SELECT * FROM transactions WHERE id = ?", (orig_id,))
                    locked_orig = cur.fetchone()
                    if locked_orig:
                        if locked_orig["transaction_type"] != "expense":
                            raise ValueError(f"Cannot refund a transaction of type '{locked_orig['transaction_type']}'; only expenses can be refunded.")
                        cur.execute("""
                            SELECT COALESCE(SUM(amount_minor), 0)
                            FROM active_transactions
                            WHERE refund_of_transaction_id = ? AND transaction_type = 'refund'
                        """, (orig_id,))
                        locked_existing = cur.fetchone()[0]
                        locked_remaining = locked_orig["amount_minor"] - locked_existing
                        if amount_minor > locked_remaining:
                            raise ValueError(
                                f"Cumulative refunds exceed original expense amount (Remaining: ${locked_remaining / 100:.2f}, Attempted: ${amount_minor / 100:.2f})."
                            )

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
                new_id = cur.lastrowid
                conn.commit()
                return new_id
            except Exception:
                conn.rollback()
                raise

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
        """Creates proper double-entry transfer records using TransferService."""
        from app.backend.services.transfer_service import TransferService
        return TransferService.create_transfer(
            from_account_id=from_account_id,
            to_account_id=to_account_id,
            amount=amount,
            transaction_date=transaction_date,
            transaction_time=transaction_time,
            description=description,
            note=note
        )

    @staticmethod
    def create_refund(
        original_tx_id: int,
        amount: float,
        transaction_date: str,
        account_id: Optional[int] = None,
        note: str = ""
    ) -> int:
        """
        Creates a refund linked to an original expense transaction atomically under BEGIN IMMEDIATE.
        Enforces:
        1. Original transaction exists.
        2. Original transaction is an expense.
        3. Refund amount is strictly positive.
        4. Cumulative active refunds do not exceed the original expense amount.
        """
        refund_minor = int(round(float(amount) * 100))
        if refund_minor <= 0:
            raise ValueError("Refund amount must be strictly positive.")

        with get_db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM transactions WHERE id = ?", (original_tx_id,))
                orig = cur.fetchone()
                if not orig:
                    raise ValueError(f"Original transaction {original_tx_id} not found.")

                if orig["transaction_type"] != "expense":
                    raise ValueError(f"Cannot refund a transaction of type '{orig['transaction_type']}'; only expenses can be refunded.")

                # Check cumulative refund limit against active transactions
                cur.execute("""
                    SELECT COALESCE(SUM(amount_minor), 0)
                    FROM active_transactions
                    WHERE refund_of_transaction_id = ? AND transaction_type = 'refund'
                """, (original_tx_id,))
                existing_refunded_minor = cur.fetchone()[0]

                remaining_refundable_minor = orig["amount_minor"] - existing_refunded_minor
                if refund_minor > remaining_refundable_minor:
                    raise ValueError(
                        f"Refund amount of ${refund_minor / 100:.2f} exceeds remaining refundable balance of ${remaining_refundable_minor / 100:.2f} "
                        f"(Original: ${orig['amount_minor'] / 100:.2f}, Prior Refunds: ${existing_refunded_minor / 100:.2f})."
                    )

                target_acc_id = account_id or orig["account_id"]
                merchant_name = orig["merchant_name"] or ""
                desc = f"Refund: {orig['description'] or merchant_name}"

                cur.execute("""
                    INSERT INTO transactions (
                        account_id, category_id, merchant_id, merchant_name, transaction_type,
                        amount_minor, transaction_date, transaction_time, description,
                        note, is_recurring, payment_method, essentiality,
                        transfer_group_id, transfer_role, linked_transaction_id,
                        refund_of_transaction_id, source, needs_review, is_deleted
                    ) VALUES (?, ?, ?, ?, 'refund', ?, ?, ?, ?, ?, 0, ?, ?, NULL, NULL, NULL, ?, 'manual', 0, 0)
                """, (
                    target_acc_id,
                    orig["category_id"],
                    orig["merchant_id"],
                    merchant_name,
                    refund_minor,
                    transaction_date,
                    datetime.now().strftime("%H:%M"),
                    desc,
                    note,
                    orig["payment_method"] or "Card",
                    orig["essentiality"] or "discretionary",
                    original_tx_id
                ))
                new_id = cur.lastrowid
                conn.commit()
                return new_id
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def update_refund(
        tx_id: int,
        amount: Optional[float] = None,
        transaction_date: Optional[str] = None,
        note: Optional[str] = None,
        account_id: Optional[int] = None
    ) -> bool:
        """
        Updates an existing refund transaction atomically under BEGIN IMMEDIATE,
        enforcing that the updated amount does not cause total cumulative refunds
        to exceed the original expense.
        """
        with get_db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,))
                orig_refund = cur.fetchone()
                if not orig_refund:
                    raise ValueError(f"Refund transaction {tx_id} not found.")
                if orig_refund["transaction_type"] != "refund":
                    raise ValueError(f"Transaction {tx_id} is not a refund.")

                new_amount_minor = int(round(float(amount) * 100)) if amount is not None else orig_refund["amount_minor"]
                if new_amount_minor <= 0:
                    raise ValueError("Refund amount must be strictly positive.")

                parent_id = orig_refund["refund_of_transaction_id"]
                if parent_id:
                    cur.execute("SELECT * FROM transactions WHERE id = ?", (parent_id,))
                    parent_tx = cur.fetchone()
                    if parent_tx:
                        cur.execute("""
                            SELECT COALESCE(SUM(amount_minor), 0)
                            FROM active_transactions
                            WHERE refund_of_transaction_id = ? AND transaction_type = 'refund' AND id != ?
                        """, (parent_id, tx_id))
                        other_refunds = cur.fetchone()[0]

                        remaining = parent_tx["amount_minor"] - other_refunds
                        if new_amount_minor > remaining:
                            raise ValueError(
                                f"Updated refund amount of ${new_amount_minor / 100:.2f} exceeds remaining refundable balance of ${remaining / 100:.2f}."
                            )

                updates: Dict[str, Any] = {"amount_minor": new_amount_minor, "updated_at": datetime.now().isoformat()}
                if transaction_date:
                    updates["transaction_date"] = transaction_date
                if note is not None:
                    updates["note"] = note
                if account_id is not None:
                    updates["account_id"] = account_id

                set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
                values = list(updates.values()) + [tx_id]
                cur.execute(f"UPDATE transactions SET {set_clause} WHERE id = ?", values)
                conn.commit()
                return cur.rowcount > 0
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _update_fields(tx_id: int, data: Dict[str, Any]) -> bool:
        """
        Low-level persistence method for updating transaction fields in SQLite.
        """
        allowed = {
            "account_id", "category_id", "merchant_name", "transaction_type",
            "transaction_date", "transaction_time", "description",
            "note", "is_recurring", "payment_method", "essentiality",
            "needs_review"
        }
        updates: Dict[str, Any] = {}

        # Normalize amount or amount_minor first
        if "amount_minor" in data:
            updates["amount_minor"] = int(data["amount_minor"])
        elif "amount" in data:
            updates["amount_minor"] = int(round(float(data["amount"]) * 100))

        for k in allowed:
            if k in data:
                updates[k] = data[k]

        if not updates:
            return False

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
    def update(tx_id: int, data: Dict[str, Any]) -> bool:
        """
        Public generic transaction update.
        Enforces domain invariants:
        - Transfers must be updated through TransferService.update_transfer()
        - Refunds must be updated through TransactionRepository.update_refund()
        - Prevents converting standard transactions to/from specialised types (transfer, refund)
        """
        existing = TransactionRepository.get_by_id(tx_id)
        if not existing:
            return False

        existing_type = existing.get("transaction_type")
        if existing_type == "transfer":
            raise ValueError("Transfers must be updated through TransferService.update_transfer().")
        if existing_type == "refund":
            raise ValueError("Refunds must be updated through TransactionRepository.update_refund().")

        new_type = data.get("transaction_type")
        if new_type in ("transfer", "refund"):
            raise ValueError(f"Cannot convert a standard transaction into a specialised {new_type}.")

        return TransactionRepository._update_fields(tx_id, data)

    @staticmethod
    def delete(tx_id: int, hard: bool = False) -> bool:
        """
        By default, soft-deletes (is_deleted = 1) allowing 5-second Undo recovery.
        If part of a transfer group, operates atomically on both legs via TransferService.
        """
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT transfer_group_id FROM transactions WHERE id = ?", (tx_id,))
            row = cur.fetchone()

            if row and row["transfer_group_id"]:
                from app.backend.services.transfer_service import TransferService
                return TransferService.delete_transfer(row["transfer_group_id"], hard=hard)

            if hard:
                cur.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
            else:
                cur.execute("UPDATE transactions SET is_deleted = 1, updated_at = ? WHERE id = ?", (datetime.now().isoformat(), tx_id))
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
                from app.backend.services.transfer_service import TransferService
                return TransferService.undo_delete_transfer(row["transfer_group_id"])

            cur.execute("UPDATE transactions SET is_deleted = 0, updated_at = ? WHERE id = ?", (datetime.now().isoformat(), tx_id))
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
                FROM active_transactions t
                LEFT JOIN accounts a ON t.account_id = a.id
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE (t.needs_review = 1 OR c.name = 'Uncategorized')
                ORDER BY t.transaction_date DESC, t.id DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))
            items = [dict(r) for r in cur.fetchall()]

            cur.execute("""
                SELECT COUNT(*) FROM active_transactions t
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE (t.needs_review = 1 OR c.name = 'Uncategorized')
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
        if original.get("transaction_type") == "transfer":
            raise ValueError("Transfer transactions cannot be duplicated individually.")
        if original.get("transaction_type") == "refund":
            raise ValueError("Refund transactions cannot be duplicated individually.")
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
