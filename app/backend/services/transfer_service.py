import uuid
import logging
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime
from app.backend.database.connection import get_db_connection

from app.backend.domain.money import major_to_minor, minor_to_major
from app.backend.domain.validators import validate_iso_date, validate_positive_amount
from app.backend.services.settings_service import SettingsService
from app.backend.fx.service import FxService

logger = logging.getLogger(__name__)

class TransferService:
    """
    Dedicated lifecycle service for double-entry financial transfers.
    Guarantees that transfers always exist as atomic, paired legs with matching amounts,
    global cash flow neutrality, and transactional integrity across all lifecycle actions.
    Supports cross-currency transfers with exact multi-currency and FX valuations.
    """

    @staticmethod
    def create_transfer_in_conn(
        conn,
        from_account_id: int,
        to_account_id: int,
        amount: float,
        transaction_date: str,
        transaction_time: str = "12:00",
        description: str = "Account Transfer",
        note: str = "",
        to_amount: Optional[float] = None
    ) -> Dict[str, Any]:
        """Creates paired source (debit) and destination (credit) transfer records on an active connection."""
        if from_account_id == to_account_id:
            raise ValueError("Source and destination accounts must be different.")

        cur = conn.cursor()

        # Verify accounts exist and fetch currencies
        cur.execute("SELECT id, name, currency FROM accounts WHERE id IN (?, ?)", (from_account_id, to_account_id))
        acc_rows = {r["id"]: dict(r) for r in cur.fetchall()}
        if from_account_id not in acc_rows or to_account_id not in acc_rows:
            raise ValueError("One or both transfer accounts do not exist.")

        from_acc = acc_rows[from_account_id]
        to_acc = acc_rows[to_account_id]
        from_curr = from_acc["currency"] or "USD"
        to_curr = to_acc["currency"] or "USD"
        base_curr = SettingsService.get_setting("currency", "USD") or "USD"

        clean_date = validate_iso_date(transaction_date, "Transfer transaction date")
        from_amount_minor = validate_positive_amount(amount, "Transfer amount", currency=from_curr)

        if from_curr == to_curr:
            to_amount_minor = from_amount_minor
        else:
            if to_amount is not None:
                to_amount_minor = validate_positive_amount(to_amount, "Destination transfer amount", currency=to_curr)
            else:
                conv = FxService.convert_minor(from_amount_minor, from_curr, to_curr, on_date=clean_date)
                to_amount_minor = conv.target.minor

        # Base currency valuations for leg 1 (source leg)
        if from_curr == base_curr:
            from_base_minor = from_amount_minor
            from_fx_rate = "1.0"
            from_fx_date = clean_date
            from_fx_source = "identity"
            from_fx_status = "not_required"
        else:
            conv_fb = FxService.convert_minor(from_amount_minor, from_curr, base_curr, on_date=clean_date)
            from_base_minor = conv_fb.target.minor
            from_fx_rate = str(conv_fb.rate)
            from_fx_date = conv_fb.rate_date
            from_fx_source = conv_fb.provider
            from_fx_status = "market_estimate"

        # Base currency valuations for leg 2 (destination leg)
        if to_curr == base_curr:
            to_base_minor = to_amount_minor
            to_fx_rate = "1.0"
            to_fx_date = clean_date
            to_fx_source = "identity"
            to_fx_status = "not_required"
        else:
            conv_tb = FxService.convert_minor(to_amount_minor, to_curr, base_curr, on_date=clean_date)
            to_base_minor = conv_tb.target.minor
            to_fx_rate = str(conv_tb.rate)
            to_fx_date = conv_tb.rate_date
            to_fx_source = conv_tb.provider
            to_fx_status = "market_estimate"

        group_id = str(uuid.uuid4())
        from_name = from_acc["name"]
        to_name = to_acc["name"]
        now_str = datetime.now().isoformat()

        # 1. Outflow leg (From account - Source)
        cur.execute("""
            INSERT INTO transactions (
                account_id, merchant_name, transaction_type,
                amount_minor, transaction_date, transaction_time, description,
                note, payment_method, essentiality, transfer_group_id, transfer_role,
                source, is_deleted, created_at, updated_at,
                original_currency, original_amount_minor,
                base_currency, base_amount_minor,
                fx_rate_to_base, fx_rate_date, fx_rate_source, fx_status
            ) VALUES (?, ?, 'transfer', ?, ?, ?, ?, ?, 'Transfer', 'savings', ?, 'source', 'manual', 0, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            from_account_id,
            f"Transfer to {to_name}",
            from_amount_minor,
            clean_date,
            transaction_time,
            description or f"Transfer to {to_name}",
            note,
            group_id,
            now_str,
            now_str,
            from_curr,
            from_amount_minor,
            base_curr,
            from_base_minor,
            from_fx_rate,
            from_fx_date,
            from_fx_source,
            from_fx_status
        ))
        leg1_id = cur.lastrowid

        # 2. Inflow leg (To account - Destination)
        cur.execute("""
            INSERT INTO transactions (
                account_id, merchant_name, transaction_type,
                amount_minor, transaction_date, transaction_time, description,
                note, payment_method, essentiality, transfer_group_id, transfer_role,
                linked_transaction_id, source, is_deleted, created_at, updated_at,
                original_currency, original_amount_minor,
                base_currency, base_amount_minor,
                fx_rate_to_base, fx_rate_date, fx_rate_source, fx_status
            ) VALUES (?, ?, 'transfer', ?, ?, ?, ?, ?, 'Transfer', 'savings', ?, 'destination', ?, 'manual', 0, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            to_account_id,
            f"Transfer from {from_name}",
            to_amount_minor,
            clean_date,
            transaction_time,
            description or f"Transfer from {from_name}",
            note,
            group_id,
            leg1_id,
            now_str,
            now_str,
            from_curr,
            from_amount_minor,
            base_curr,
            to_base_minor,
            to_fx_rate,
            to_fx_date,
            to_fx_source,
            to_fx_status
        ))
        leg2_id = cur.lastrowid

        # Cross-link leg 1 to leg 2
        cur.execute("UPDATE transactions SET linked_transaction_id = ? WHERE id = ?", (leg2_id, leg1_id))

        # Fetch created records
        cur.execute("SELECT * FROM transactions WHERE id = ?", (leg1_id,))
        source_tx = dict(cur.fetchone())
        source_tx["amount"] = float(minor_to_major(source_tx["amount_minor"], from_curr))
        cur.execute("SELECT * FROM transactions WHERE id = ?", (leg2_id,))
        dest_tx = dict(cur.fetchone())
        dest_tx["amount"] = float(minor_to_major(dest_tx["amount_minor"], to_curr))

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

    @staticmethod
    def create_transfer(
        from_account_id: int,
        to_account_id: int,
        amount: float,
        transaction_date: str,
        transaction_time: str = "12:00",
        description: str = "Account Transfer",
        note: str = "",
        to_amount: Optional[float] = None
    ) -> Dict[str, Any]:
        """Creates paired source (debit) and destination (credit) transfer records atomically."""
        with get_db_connection() as conn:
            res = TransferService.create_transfer_in_conn(
                conn=conn,
                from_account_id=from_account_id,
                to_account_id=to_account_id,
                amount=amount,
                transaction_date=transaction_date,
                transaction_time=transaction_time,
                description=description,
                note=note,
                to_amount=to_amount
            )
            conn.commit()
            return res

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
            note=data.get("note", ""),
            to_amount=data.get("to_amount") or data.get("destination_amount")
        )

    @staticmethod
    def _load_transfer_pair(cur, transfer_group_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Loads and strictly validates a transfer pair from SQLite (FSC-M08).
        Requires:
        - Exactly 2 rows
        - Both transaction_type == 'transfer'
        - Same transfer_group_id
        - Roles == {'source', 'destination'}
        - Cross-linked IDs (leg1.linked_id == leg2.id and vice versa)
        - Same deletion state (is_deleted must match)
        Returns (source_leg, destination_leg).
        Raises ValueError if corrupted or invalid.
        """
        cur.execute("SELECT * FROM transactions WHERE transfer_group_id = ?", (transfer_group_id,))
        legs = [dict(r) for r in cur.fetchall()]
        if len(legs) != 2:
            raise ValueError(f"Invalid transfer group '{transfer_group_id}': expected exactly 2 legs, found {len(legs)}.")

        for leg in legs:
            if leg["transaction_type"] != "transfer":
                raise ValueError(f"Corrupted transfer leg {leg['id']}: type is '{leg['transaction_type']}', expected 'transfer'.")

        leg_roles = {leg["transfer_role"] for leg in legs}
        if leg_roles != {"source", "destination"}:
            raise ValueError(f"Invalid transfer roles for group '{transfer_group_id}': expected {{'source', 'destination'}}, got {leg_roles}.")

        source_leg = next(l for l in legs if l["transfer_role"] == "source")
        dest_leg = next(l for l in legs if l["transfer_role"] == "destination")

        if source_leg.get("linked_transaction_id") != dest_leg["id"] or dest_leg.get("linked_transaction_id") != source_leg["id"]:
            raise ValueError(f"Corrupted transfer pair '{transfer_group_id}': transfer legs are not properly cross-linked.")

        if source_leg["is_deleted"] != dest_leg["is_deleted"]:
            raise ValueError(f"Inconsistent deletion state in transfer group '{transfer_group_id}': source is_deleted={source_leg['is_deleted']}, dest is_deleted={dest_leg['is_deleted']}.")

        return source_leg, dest_leg

    @staticmethod
    def update_transfer(
        transfer_group_id: Optional[str] = None,
        tx_id: Optional[int] = None,
        from_account_id: Optional[int] = None,
        to_account_id: Optional[int] = None,
        amount: Optional[float] = None,
        to_amount: Optional[float] = None,
        transaction_date: Optional[str] = None,
        transaction_time: Optional[str] = None,
        description: Optional[str] = None,
        note: Optional[str] = None
    ) -> bool:
        """Updates both legs of a transfer atomically to preserve matching amounts, dates, and accounts."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            if not transfer_group_id and tx_id is not None:
                cur.execute("SELECT transfer_group_id FROM transactions WHERE id = ?", (tx_id,))
                row = cur.fetchone()
                if not row or not row["transfer_group_id"]:
                    raise ValueError(f"Transaction {tx_id} is not part of a transfer.")
                transfer_group_id = row["transfer_group_id"]

            if not transfer_group_id:
                raise ValueError("Either transfer_group_id or tx_id must be provided.")

            source_leg, dest_leg = TransferService._load_transfer_pair(cur, transfer_group_id)

            # Resolve accounts
            new_from_acc = from_account_id if from_account_id is not None else source_leg["account_id"]
            new_to_acc = to_account_id if to_account_id is not None else dest_leg["account_id"]

            if new_from_acc == new_to_acc:
                raise ValueError("Source and destination accounts must be different.")

            cur.execute("SELECT id, name, currency FROM accounts WHERE id IN (?, ?)", (new_from_acc, new_to_acc))
            acc_map = {r["id"]: dict(r) for r in cur.fetchall()}
            if new_from_acc not in acc_map or new_to_acc not in acc_map:
                raise ValueError("One or both transfer accounts do not exist.")

            from_acc = acc_map[new_from_acc]
            to_acc = acc_map[new_to_acc]
            from_curr = from_acc["currency"] or "USD"
            to_curr = to_acc["currency"] or "USD"
            base_curr = SettingsService.get_setting("currency", "USD") or "USD"

            clean_date = validate_iso_date(transaction_date, "Transfer transaction date") if transaction_date is not None else source_leg["transaction_date"]

            if amount is not None:
                from_minor = validate_positive_amount(amount, "Transfer amount", currency=from_curr)
            else:
                from_minor = source_leg["amount_minor"]

            if from_curr == to_curr:
                to_minor = from_minor
            else:
                if to_amount is not None:
                    to_minor = validate_positive_amount(to_amount, "Destination transfer amount", currency=to_curr)
                elif amount is not None:
                    conv = FxService.convert_minor(from_minor, from_curr, to_curr, on_date=clean_date)
                    to_minor = conv.target.minor
                else:
                    to_minor = dest_leg["amount_minor"]

            # Source leg base valuation
            if from_curr == base_curr:
                from_base_minor = from_minor
                from_fx_rate = "1.0"
                from_fx_date = clean_date
                from_fx_source = "identity"
                from_fx_status = "not_required"
            else:
                conv_fb = FxService.convert_minor(from_minor, from_curr, base_curr, on_date=clean_date)
                from_base_minor = conv_fb.target.minor
                from_fx_rate = str(conv_fb.rate)
                from_fx_date = conv_fb.rate_date
                from_fx_source = conv_fb.provider
                from_fx_status = "market_estimate"

            # Destination leg base valuation
            if to_curr == base_curr:
                to_base_minor = to_minor
                to_fx_rate = "1.0"
                to_fx_date = clean_date
                to_fx_source = "identity"
                to_fx_status = "not_required"
            else:
                conv_tb = FxService.convert_minor(to_minor, to_curr, base_curr, on_date=clean_date)
                to_base_minor = conv_tb.target.minor
                to_fx_rate = str(conv_tb.rate)
                to_fx_date = conv_tb.rate_date
                to_fx_source = conv_tb.provider
                to_fx_status = "market_estimate"

            now_str = datetime.now().isoformat()
            from_name = from_acc["name"]
            to_name = to_acc["name"]

            # Update source leg
            cur.execute("""
                UPDATE transactions 
                SET account_id = ?,
                    merchant_name = ?,
                    description = COALESCE(?, description),
                    amount_minor = ?,
                    transaction_date = ?,
                    transaction_time = COALESCE(?, transaction_time),
                    note = COALESCE(?, note),
                    original_currency = ?,
                    original_amount_minor = ?,
                    base_currency = ?,
                    base_amount_minor = ?,
                    fx_rate_to_base = ?,
                    fx_rate_date = ?,
                    fx_rate_source = ?,
                    fx_status = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                new_from_acc,
                f"Transfer to {to_name}",
                description,
                from_minor,
                clean_date,
                transaction_time,
                note,
                from_curr,
                from_minor,
                base_curr,
                from_base_minor,
                from_fx_rate,
                from_fx_date,
                from_fx_source,
                from_fx_status,
                now_str,
                source_leg["id"]
            ))

            # Update destination leg
            cur.execute("""
                UPDATE transactions 
                SET account_id = ?,
                    merchant_name = ?,
                    description = COALESCE(?, description),
                    amount_minor = ?,
                    transaction_date = ?,
                    transaction_time = COALESCE(?, transaction_time),
                    note = COALESCE(?, note),
                    original_currency = ?,
                    original_amount_minor = ?,
                    base_currency = ?,
                    base_amount_minor = ?,
                    fx_rate_to_base = ?,
                    fx_rate_date = ?,
                    fx_rate_source = ?,
                    fx_status = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                new_to_acc,
                f"Transfer from {from_name}",
                description,
                to_minor,
                clean_date,
                transaction_time,
                note,
                from_curr,
                from_minor,
                base_curr,
                to_base_minor,
                to_fx_rate,
                to_fx_date,
                to_fx_source,
                to_fx_status,
                now_str,
                dest_leg["id"]
            ))

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
        3. Identical amounts for same-currency, positive amounts for cross-currency.
        4. Different accounts.
        5. Identical dates.
        """
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT t.*, a.currency as account_currency
                FROM transactions t
                LEFT JOIN accounts a ON t.account_id = a.id
                WHERE t.transfer_group_id = ?
            """, (transfer_group_id,))
            rows = [dict(r) for r in cur.fetchall()]

            if len(rows) != 2:
                return {"valid": False, "reason": f"Expected exactly 2 legs, found {len(rows)}"}

            leg1, leg2 = rows[0], rows[1]
            roles = {leg1["transfer_role"], leg2["transfer_role"]}
            if roles != {"source", "destination"}:
                return {"valid": False, "reason": f"Expected source and destination roles, found {roles}"}

            c1 = leg1.get("account_currency") or "USD"
            c2 = leg2.get("account_currency") or "USD"

            if c1 == c2:
                if leg1["amount_minor"] != leg2["amount_minor"]:
                    return {"valid": False, "reason": f"Mismatched amounts: {leg1['amount_minor']} vs {leg2['amount_minor']}"}
            else:
                if leg1["amount_minor"] <= 0 or leg2["amount_minor"] <= 0:
                    return {"valid": False, "reason": f"Non-positive transfer amounts: {leg1['amount_minor']} / {leg2['amount_minor']}"}

            if leg1["account_id"] == leg2["account_id"]:
                return {"valid": False, "reason": "Source and destination accounts must not be identical"}

            if leg1["transaction_date"] != leg2["transaction_date"]:
                return {"valid": False, "reason": f"Mismatched dates: {leg1['transaction_date']} vs {leg2['transaction_date']}"}

            if leg1.get("linked_transaction_id") != leg2["id"] or leg2.get("linked_transaction_id") != leg1["id"]:
                return {"valid": False, "reason": "Transfers must be cross-linked via linked_transaction_id"}

            if leg1["is_deleted"] != leg2["is_deleted"]:
                return {"valid": False, "reason": f"Inconsistent deletion state: {leg1['is_deleted']} vs {leg2['is_deleted']}"}

            return {
                "valid": True,
                "amount_minor": leg1["amount_minor"],
                "source_account_id": leg1["account_id"] if leg1["transfer_role"] == "source" else leg2["account_id"],
                "destination_account_id": leg1["account_id"] if leg1["transfer_role"] == "destination" else leg2["account_id"],
                "is_deleted": bool(leg1["is_deleted"])
            }

    @staticmethod
    def validate_all_transfer_groups(include_deleted: bool = False) -> Dict[str, Any]:
        """
        Validates that all transfer transactions in the database strictly adhere to invariants:
        1. No orphan transfers (transfers without transfer_group_id or with transfer_role NULL).
        2. Every transfer group has exactly 2 legs: one source, one destination.
        3. Identical amount_minor, identical transaction_date.
        4. Different accounts.
        5. Properly cross-linked via linked_transaction_id.
        """
        with get_db_connection() as conn:
            cur = conn.cursor()

            # Check 1: Transfers with missing group or missing role
            cur.execute("""
                SELECT id, account_id, transfer_group_id, transfer_role
                FROM transactions
                WHERE transaction_type = 'transfer'
                  AND (transfer_group_id IS NULL OR transfer_group_id = '' OR transfer_role IS NULL)
                  AND (is_deleted = 0 OR ?)
            """, (1 if include_deleted else 0,))
            orphans = [dict(r) for r in cur.fetchall()]

            # Check 2: Group integrity
            cur.execute("""
                SELECT DISTINCT transfer_group_id
                FROM transactions
                WHERE transaction_type = 'transfer' AND transfer_group_id IS NOT NULL AND transfer_group_id != ''
                  AND (is_deleted = 0 OR ?)
            """, (1 if include_deleted else 0,))
            groups = [r["transfer_group_id"] for r in cur.fetchall()]

            invalid_groups = []
            for gid in groups:
                res = TransferService.validate_transfer_group(gid)
                if not res["valid"]:
                    invalid_groups.append({"group_id": gid, "reason": res["reason"]})

            is_valid = (len(orphans) == 0 and len(invalid_groups) == 0)
            return {
                "valid": is_valid,
                "total_groups": len(groups),
                "orphan_count": len(orphans),
                "orphan_transactions": orphans,
                "invalid_groups": invalid_groups
            }

