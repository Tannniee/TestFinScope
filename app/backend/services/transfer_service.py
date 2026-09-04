import uuid
import logging
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime
from app.backend.database.connection import get_db_connection

logger = logging.getLogger(__name__)

class TransferService:
    """
    Dedicated lifecycle service for double-entry financial transfers.
    Guarantees that transfers always exist as atomic, paired legs with matching amounts,
    global cash flow neutrality, and transactional integrity across all lifecycle actions.
    """

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
        """Creates paired source (debit) and destination (credit) transfer records atomically."""
        if from_account_id == to_account_id:
            raise ValueError("Source and destination accounts must be different.")

        amount_minor = int(round(float(amount) * 100))
        if amount_minor <= 0:
            raise ValueError("Transfer amount must be strictly positive.")

        group_id = str(uuid.uuid4())

        with get_db_connection() as conn:
            cur = conn.cursor()

            # Verify accounts exist
            cur.execute("SELECT id, name FROM accounts WHERE id IN (?, ?)", (from_account_id, to_account_id))
            acc_names = {r["id"]: r["name"] for r in cur.fetchall()}
            if from_account_id not in acc_names or to_account_id not in acc_names:
                raise ValueError("One or both transfer accounts do not exist.")

            from_name = acc_names[from_account_id]
            to_name = acc_names[to_account_id]

            now_str = datetime.now().isoformat()

            # 1. Outflow leg (From account - Source)
            cur.execute("""
                INSERT INTO transactions (
                    account_id, merchant_name, transaction_type,
                    amount_minor, transaction_date, transaction_time, description,
                    note, payment_method, essentiality, transfer_group_id, transfer_role,
                    source, is_deleted, created_at, updated_at
                ) VALUES (?, ?, 'transfer', ?, ?, ?, ?, ?, 'Transfer', 'savings', ?, 'source', 'manual', 0, ?, ?)
            """, (
                from_account_id,
                f"Transfer to {to_name}",
                amount_minor,
                transaction_date,
                transaction_time,
                description or f"Transfer to {to_name}",
                note,
                group_id,
                now_str,
                now_str
            ))
            leg1_id = cur.lastrowid

            # 2. Inflow leg (To account - Destination)
            cur.execute("""
                INSERT INTO transactions (
                    account_id, merchant_name, transaction_type,
                    amount_minor, transaction_date, transaction_time, description,
                    note, payment_method, essentiality, transfer_group_id, transfer_role,
                    linked_transaction_id, source, is_deleted, created_at, updated_at
                ) VALUES (?, ?, 'transfer', ?, ?, ?, ?, ?, 'Transfer', 'savings', ?, 'destination', ?, 'manual', 0, ?, ?)
            """, (
                to_account_id,
                f"Transfer from {from_name}",
                amount_minor,
                transaction_date,
                transaction_time,
                description or f"Transfer from {from_name}",
                note,
                group_id,
                leg1_id,
                now_str,
                now_str
            ))
            leg2_id = cur.lastrowid

            # Cross-link leg 1 to leg 2
            cur.execute("UPDATE transactions SET linked_transaction_id = ? WHERE id = ?", (leg2_id, leg1_id))
            conn.commit()

            # Fetch created records
            cur.execute("SELECT * FROM transactions WHERE id = ?", (leg1_id,))
            source_tx = dict(cur.fetchone())
            source_tx["amount"] = round(source_tx["amount_minor"] / 100.0, 2)
            cur.execute("SELECT * FROM transactions WHERE id = ?", (leg2_id,))
            dest_tx = dict(cur.fetchone())
            dest_tx["amount"] = round(dest_tx["amount_minor"] / 100.0, 2)

            return {
                "success": True,
                "transfer_group_id": group_id,
                "outflow_tx_id": leg1_id,
                "inflow_tx_id": leg2_id,
                "outflow_id": leg1_id,
                "inflow_id": leg2_id,
                "source_transaction": source_tx,
                "destination_transaction": dest_tx
            }

    @classmethod
    def create_transfer_pair(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Convenience method accepting a dictionary payload for transfer pair creation."""
        return cls.create_transfer(
            from_account_id=data["from_account_id"],
            to_account_id=data["to_account_id"],
            amount=data["amount"],
            transaction_date=data.get("transaction_date", ""),
            transaction_time=data.get("transaction_time", "12:00"),
            description=data.get("description", "Account Transfer"),
            note=data.get("note", "")
        )

    @staticmethod
    def update_transfer(
        transfer_group_id: str,
        amount: Optional[float] = None,
        transaction_date: Optional[str] = None,
        description: Optional[str] = None,
        note: Optional[str] = None
    ) -> bool:
        """Updates both legs of a transfer atomically to preserve matching amounts and dates."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, transfer_role FROM transactions WHERE transfer_group_id = ?", (transfer_group_id,))
            legs = cur.fetchall()
            if len(legs) != 2:
                raise ValueError(f"Invalid transfer group: expected 2 legs, found {len(legs)}")

            updates: Dict[str, Any] = {"updated_at": datetime.now().isoformat()}
            if amount is not None:
                amount_minor = int(round(float(amount) * 100))
                if amount_minor <= 0:
                    raise ValueError("Transfer amount must be strictly positive.")
                updates["amount_minor"] = amount_minor
            if transaction_date:
                updates["transaction_date"] = transaction_date
            if description is not None:
                updates["description"] = description
            if note is not None:
                updates["note"] = note

            set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
            params = list(updates.values()) + [transfer_group_id]
            cur.execute(f"UPDATE transactions SET {set_clause} WHERE transfer_group_id = ?", params)
            conn.commit()
            return True

    @staticmethod
    def delete_transfer(transfer_group_id: str, hard: bool = False) -> bool:
        """Atomically soft-deletes (or hard-deletes) both legs of a transfer."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            if hard:
                cur.execute("DELETE FROM transactions WHERE transfer_group_id = ?", (transfer_group_id,))
            else:
                cur.execute("UPDATE transactions SET is_deleted = 1, updated_at = ? WHERE transfer_group_id = ?", (datetime.now().isoformat(), transfer_group_id))
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def undo_delete_transfer(transfer_group_id: str) -> bool:
        """Atomically restores both legs of a transfer."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE transactions SET is_deleted = 0, updated_at = ? WHERE transfer_group_id = ?", (datetime.now().isoformat(), transfer_group_id))
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def validate_transfer_group(transfer_group_id: str) -> Dict[str, Any]:
        """
        Validates all financial invariants for a transfer group:
        1. Exactly two legs.
        2. One source and one destination leg.
        3. Identical amounts.
        4. Different accounts.
        5. Identical dates.
        """
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM transactions WHERE transfer_group_id = ?", (transfer_group_id,))
            rows = [dict(r) for r in cur.fetchall()]

            if len(rows) != 2:
                return {"valid": False, "reason": f"Expected exactly 2 legs, found {len(rows)}"}

            leg1, leg2 = rows[0], rows[1]
            roles = {leg1["transfer_role"], leg2["transfer_role"]}
            if roles != {"source", "destination"}:
                return {"valid": False, "reason": f"Expected source and destination roles, found {roles}"}

            if leg1["amount_minor"] != leg2["amount_minor"]:
                return {"valid": False, "reason": f"Mismatched amounts: {leg1['amount_minor']} vs {leg2['amount_minor']}"}

            if leg1["account_id"] == leg2["account_id"]:
                return {"valid": False, "reason": "Source and destination accounts must not be identical"}

            if leg1["transaction_date"] != leg2["transaction_date"]:
                return {"valid": False, "reason": f"Mismatched dates: {leg1['transaction_date']} vs {leg2['transaction_date']}"}

            return {
                "valid": True,
                "amount_minor": leg1["amount_minor"],
                "source_account_id": leg1["account_id"] if leg1["transfer_role"] == "source" else leg2["account_id"],
                "destination_account_id": leg1["account_id"] if leg1["transfer_role"] == "destination" else leg2["account_id"],
                "is_deleted": bool(leg1["is_deleted"])
            }
