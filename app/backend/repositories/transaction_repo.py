"""
Transaction Repository for FinScope CORE.
Handles structured transaction persistence, exact integer minor units,
double-entry transfers with transfer_roles, linked refunds,
soft-delete for undo recovery, and review queue resolution.
"""

import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime
from decimal import Decimal
from app.backend.database.connection import get_db_connection
from app.backend.domain.money import major_to_minor, minor_to_major, format_money
from app.backend.domain.validators import (
    validate_positive_amount,
    validate_iso_date,
    validate_transaction_type,
    validate_currency_code
)
from app.backend.services.merchant_service import MerchantService, normalize_merchant_name
from app.backend.repositories.account_repo import AccountRepository
from app.backend.services.settings_service import SettingsService
from app.backend.fx.service import FxService


def _hydrate_transaction_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Hydrates raw SQL transaction row with exact Decimal major amounts and multi-currency formatting."""
    tx = dict(row)
    acct_curr = tx.get("account_currency") or tx.get("base_currency") or "USD"
    orig_curr = tx.get("original_currency") or acct_curr
    base_curr = tx.get("base_currency") or "USD"

    tx["currency"] = acct_curr
    tx["amount"] = float(minor_to_major(tx["amount_minor"], acct_curr))

    orig_minor = tx["original_amount_minor"] if tx.get("original_amount_minor") is not None else tx["amount_minor"]
    tx["original_amount_minor"] = orig_minor
    tx["original_currency"] = orig_curr
    tx["original_amount"] = float(minor_to_major(orig_minor, orig_curr))

    if tx.get("base_amount_minor") is not None:
        base_minor = tx["base_amount_minor"]
        tx["base_amount_minor"] = base_minor
        tx["base_currency"] = base_curr
        tx["base_amount"] = float(minor_to_major(base_minor, base_curr))
        tx["formatted_base_amount"] = format_money(base_minor, base_curr)
    elif acct_curr == base_curr:
        base_minor = tx["amount_minor"]
        tx["base_amount_minor"] = base_minor
        tx["base_currency"] = base_curr
        tx["base_amount"] = float(minor_to_major(base_minor, base_curr))
        tx["formatted_base_amount"] = format_money(base_minor, base_curr)
    else:
        tx["base_amount_minor"] = None
        tx["base_currency"] = base_curr
        tx["base_amount"] = None
        tx["formatted_base_amount"] = "Pending"

    tx["formatted_amount"] = format_money(tx["amount_minor"], acct_curr)
    tx["formatted_original_amount"] = format_money(orig_minor, orig_curr)

    return tx


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
                    t.raw_merchant_name, t.capture_method, t.category_source, t.category_confidence,
                    t.essentiality_source, t.essentiality_confidence, t.review_reason, t.parser_version,
                    t.transaction_type, t.amount_minor,
                    t.transaction_date, t.transaction_time, t.description, t.note,
                    t.is_recurring, t.recurring_rule_id, t.payment_method, t.essentiality,
                    t.transfer_group_id, t.transfer_role, t.linked_transaction_id,
                    t.refund_of_transaction_id, t.source, t.needs_review,
                    t.original_currency, t.original_amount_minor,
                    t.base_currency, t.base_amount_minor,
                    t.fx_rate_to_base, t.fx_rate_date, t.fx_rate_source, t.fx_status,
                    t.created_at, t.updated_at,
                    a.name as account_name,
                    a.currency as account_currency,
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
            items = [_hydrate_transaction_row(row) for row in cur.fetchall()]

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
                    t.raw_merchant_name, t.capture_method, t.category_source, t.category_confidence,
                    t.essentiality_source, t.essentiality_confidence, t.review_reason, t.parser_version,
                    t.transaction_type, t.amount_minor,
                    t.transaction_date, t.transaction_time, t.description, t.note,
                    t.is_recurring, t.recurring_rule_id, t.payment_method, t.essentiality,
                    t.transfer_group_id, t.transfer_role, t.linked_transaction_id,
                    t.refund_of_transaction_id, t.source, t.needs_review, t.is_deleted,
                    t.original_currency, t.original_amount_minor,
                    t.base_currency, t.base_amount_minor,
                    t.fx_rate_to_base, t.fx_rate_date, t.fx_rate_source, t.fx_status,
                    t.created_at, t.updated_at,
                    a.name as account_name,
                    a.currency as account_currency,
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
            if not row:
                return None
            res = _hydrate_transaction_row(row)

            # Hydrate paired transfer leg if this is a transfer
            if res.get("transfer_group_id") or res.get("linked_transaction_id"):
                linked_id = res.get("linked_transaction_id")
                group_id = res.get("transfer_group_id")
                if linked_id:
                    cur.execute("""
                        SELECT t.id, t.account_id, t.amount_minor, t.transfer_role,
                               a.name as account_name, a.currency as account_currency
                        FROM transactions t
                        LEFT JOIN accounts a ON t.account_id = a.id
                        WHERE t.id = ?
                    """, (linked_id,))
                elif group_id:
                    cur.execute("""
                        SELECT t.id, t.account_id, t.amount_minor, t.transfer_role,
                               a.name as account_name, a.currency as account_currency
                        FROM transactions t
                        LEFT JOIN accounts a ON t.account_id = a.id
                        WHERE t.transfer_group_id = ? AND t.id != ?
                    """, (group_id, tx_id))
                else:
                    linked_row = None

                linked_row = cur.fetchone() if (linked_id or group_id) else None
                if linked_row:
                    linked_curr = linked_row["account_currency"] or "USD"
                    linked_amt = float(minor_to_major(linked_row["amount_minor"], linked_curr))
                    res["linked_account_id"] = linked_row["account_id"]
                    res["linked_account_name"] = linked_row["account_name"]
                    res["linked_account_currency"] = linked_curr
                    res["linked_amount_minor"] = linked_row["amount_minor"]
                    res["linked_amount"] = linked_amt

                    if res.get("transfer_role") == "source":
                        res["from_account_id"] = res["account_id"]
                        res["to_account_id"] = linked_row["account_id"]
                        res["destination_amount"] = linked_amt
                    elif res.get("transfer_role") == "destination":
                        res["from_account_id"] = linked_row["account_id"]
                        res["to_account_id"] = res["account_id"]
                        res["destination_amount"] = res.get("amount")
                        res["source_amount"] = linked_amt

            return res

    @staticmethod
    def create(data: Dict[str, Any]) -> int:
        tx_type = validate_transaction_type(data["transaction_type"])
        if tx_type == "transfer":
            raise ValueError("Transfers must be created through TransferService.")
        if tx_type == "refund":
            raise ValueError("Refunds must be created through create_refund().")

        account_id = data["account_id"]
        account = AccountRepository.get_by_id(account_id)
        account_currency = account["currency"] if account else "USD"
        base_currency = SettingsService.get_setting("currency", "USD") or "USD"

        raw_orig_curr = data.get("original_currency") or data.get("currency")
        original_currency = validate_currency_code(raw_orig_curr) if raw_orig_curr else account_currency
        clean_date = validate_iso_date(data["transaction_date"], "Transaction date")

        # Multi-currency amount resolution (Section 47 / MC-005)
        if original_currency == account_currency:
            amount_val = data.get("amount") if data.get("amount") is not None else data.get("original_amount")
            if tx_type != "adjustment":
                amount_minor = validate_positive_amount(amount_val, "Transaction amount", currency=account_currency)
            else:
                amount_minor = major_to_minor(amount_val, account_currency)

            original_amount_minor = amount_minor
            if account_currency == base_currency:
                base_amount_minor = amount_minor
                fx_status = "not_required"
                fx_rate_to_base = "1.0"
                fx_rate_date = clean_date
                fx_rate_source = "identity"
            else:
                # Foreign account ledger (e.g. USD account when base is VND)
                # Local cached conversion only (zero network calls)
                conv = FxService.try_convert_cached_minor(amount_minor, account_currency, base_currency, on_date=clean_date)
                if conv:
                    base_amount_minor = conv.target.minor
                    fx_status = "market_estimate"
                    fx_rate_to_base = str(conv.rate)
                    fx_rate_date = conv.rate_date
                    fx_rate_source = conv.provider
                else:
                    base_amount_minor = None
                    fx_status = "pending"
                    fx_rate_to_base = None
                    fx_rate_date = None
                    fx_rate_source = None
        else:
            # Foreign merchant purchase on account (e.g. 10 USD on VND account)
            orig_val = data.get("original_amount") if data.get("original_amount") is not None else data.get("amount")
            original_amount_minor = validate_positive_amount(orig_val, "Original amount", currency=original_currency)

            conv_acct = None
            if data.get("settlement_amount") is not None:
                amount_minor = validate_positive_amount(data["settlement_amount"], "Settlement amount", currency=account_currency)
                fx_status = "user_settlement"
            elif data.get("amount") is not None and data.get("original_amount") is not None and data.get("amount") != data.get("original_amount"):
                amount_minor = validate_positive_amount(data["amount"], "Settlement amount", currency=account_currency)
                fx_status = "user_settlement"
            else:
                conv_acct = FxService.try_convert_cached_minor(original_amount_minor, original_currency, account_currency, on_date=clean_date)
                if conv_acct is not None:
                    amount_minor = conv_acct.target.minor
                    fx_status = "market_estimate"
                else:
                    if data.get("settlement_amount") is None and ("amount" not in data or data.get("amount") == orig_val):
                        raise ValueError(
                            f"Cross-currency transaction ({original_currency} on {account_currency} account) "
                            f"requires a settlement amount or an existing cached exchange rate."
                        )
                    amount_minor = validate_positive_amount(data["amount"], "Settlement amount", currency=account_currency)
                    fx_status = "user_settlement"

            if account_currency == base_currency:
                base_amount_minor = amount_minor
                if conv_acct is not None:
                    fx_rate_to_base = str(conv_acct.rate)
                    fx_rate_date = conv_acct.rate_date
                    fx_rate_source = conv_acct.provider
                else:
                    orig_maj = minor_to_major(original_amount_minor, original_currency)
                    base_maj = minor_to_major(base_amount_minor, base_currency)
                    fx_rate_to_base = str(base_maj / orig_maj) if orig_maj > 0 else "1.0"
                    fx_rate_date = clean_date
                    fx_rate_source = "user_settlement"
            else:
                conv_base = FxService.try_convert_cached_minor(amount_minor, account_currency, base_currency, on_date=clean_date)
                if conv_base:
                    base_amount_minor = conv_base.target.minor
                    fx_rate_to_base = str(conv_base.rate)
                    fx_rate_date = conv_base.rate_date
                    fx_rate_source = conv_base.provider
                    if fx_status != "user_settlement":
                        fx_status = "market_estimate"
                else:
                    base_amount_minor = None
                    fx_status = "pending"
                    fx_rate_to_base = None
                    fx_rate_date = None
                    fx_rate_source = None

        category_id = data.get("category_id")
        raw_merchant = data.get("raw_merchant_name") or data.get("merchant_name", "")
        clean_merchant = normalize_merchant_name(raw_merchant)
        needs_review = 1 if data.get("needs_review") else 0
        review_reason = data.get("review_reason")
        capture_method = data.get("capture_method", "modal")
        category_source = data.get("category_source", "user")
        category_confidence = data.get("category_confidence")
        raw_ess = data.get("essentiality")
        if not raw_ess:
            essentiality = "unknown"
            essentiality_source = data.get("essentiality_source", "fallback")
            essentiality_confidence = data.get("essentiality_confidence", 0.0)
        else:
            essentiality = raw_ess
            essentiality_source = data.get("essentiality_source", "user")
            essentiality_confidence = data.get("essentiality_confidence", 1.0 if essentiality_source == "user" else 0.0)
        parser_version = data.get("parser_version")

        with get_db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.cursor()

                merchant_id = None
                if clean_merchant:
                    merchant_id = MerchantService.get_or_create_merchant_in_conn(
                        conn,
                        clean_merchant,
                        category_id=category_id,
                        account_id=account_id,
                        essentiality=data.get("essentiality")
                    )

                # Handle Uncategorized for expense if category is missing
                if tx_type == "expense" and not category_id:
                    cur.execute("SELECT id FROM categories WHERE name = 'Uncategorized'")
                    uncat_row = cur.fetchone()
                    if uncat_row:
                        category_id = uncat_row["id"]
                        needs_review = 1
                        if not review_reason:
                            review_reason = "uncategorized"

                from app.backend.domain.validators import validate_category_for_transaction
                category_id = validate_category_for_transaction(conn, category_id, tx_type)

                cur.execute("""
                    INSERT INTO transactions (
                        account_id, category_id, merchant_id, merchant_name, raw_merchant_name,
                        transaction_type, amount_minor, transaction_date, transaction_time,
                        description, note, is_recurring, payment_method, essentiality,
                        transfer_group_id, transfer_role, linked_transaction_id,
                        refund_of_transaction_id, source, needs_review, review_reason,
                        capture_method, category_source, category_confidence,
                        essentiality_source, essentiality_confidence, parser_version,
                        is_deleted, original_currency, original_amount_minor,
                        base_currency, base_amount_minor,
                        fx_rate_to_base, fx_rate_date, fx_rate_source, fx_status
                    ) VALUES (
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?,
                        0, ?, ?,
                        ?, ?,
                        ?, ?, ?, ?
                    )
                """, (
                    account_id,
                    category_id,
                    merchant_id,
                    clean_merchant or raw_merchant,
                    raw_merchant,
                    tx_type,
                    amount_minor,
                    clean_date,
                    data.get("transaction_time", "12:00"),
                    data.get("description", "") or clean_merchant,
                    data.get("note", ""),
                    1 if data.get("is_recurring") else 0,
                    data.get("payment_method", "Card"),
                    essentiality,
                    data.get("transfer_group_id"),
                    data.get("transfer_role"),
                    data.get("linked_transaction_id"),
                    data.get("refund_of_transaction_id"),
                    data.get("source", "manual"),
                    needs_review,
                    review_reason,
                    capture_method,
                    category_source,
                    category_confidence,
                    essentiality_source,
                    essentiality_confidence,
                    parser_version,
                    original_currency,
                    original_amount_minor,
                    base_currency,
                    base_amount_minor,
                    fx_rate_to_base,
                    fx_rate_date,
                    fx_rate_source,
                    fx_status
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
        note: str = "",
        to_amount: Optional[float] = None
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
            note=note,
            to_amount=to_amount
        )

    @staticmethod
    def create_refund(
        original_tx_id: Optional[int] = None,
        amount: float = 0.0,
        transaction_date: str = "",
        account_id: Optional[int] = None,
        note: str = "",
        *,
        parent_tx_id: Optional[int] = None,
        orig_tx_id: Optional[int] = None
    ) -> int:
        """
        Creates a refund linked to an original expense transaction atomically under BEGIN IMMEDIATE.
        Enforces:
        1. Original transaction exists and is an expense.
        2. Refund amount is strictly positive and evaluated in the parent's original purchase currency.
        3. Cumulative active refunds do not exceed the parent's original purchase amount.
        4. Settlement amount into target account is correctly converted via FX.
        """
        target_orig_id = parent_tx_id or orig_tx_id or original_tx_id
        if not target_orig_id:
            raise ValueError("Original transaction ID is required for a linked refund.")

        from app.backend.domain.validators import validate_positive_amount, validate_iso_date
        clean_date = validate_iso_date(transaction_date, "Refund transaction date")

        # 1. Pre-fetch original transaction and account currencies before transaction lock
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM transactions WHERE id = ?", (target_orig_id,))
            orig = cur.fetchone()
            if not orig:
                raise ValueError(f"Original transaction {target_orig_id} not found.")

            if orig["transaction_type"] != "expense":
                raise ValueError(f"Cannot refund a transaction of type '{orig['transaction_type']}'; only expenses can be refunded.")

            target_acc_id = account_id or orig["account_id"]
            cur.execute("SELECT currency FROM accounts WHERE id = ?", (orig["account_id"],))
            orig_acc_row = cur.fetchone()
            orig_acc_curr = orig_acc_row["currency"] if orig_acc_row else "USD"

            cur.execute("SELECT currency FROM accounts WHERE id = ?", (target_acc_id,))
            target_acc_row = cur.fetchone()
            target_acc_curr = target_acc_row["currency"] if target_acc_row else orig_acc_curr

        base_currency = SettingsService.get_setting("currency", "USD") or "USD"
        orig_dict = dict(orig)
        orig_purchase_curr = orig_dict.get("original_currency") or orig_acc_curr
        orig_total_minor = orig_dict.get("original_amount_minor") if orig_dict.get("original_amount_minor") is not None else orig_dict["amount_minor"]

        # Validate amount in the parent's original purchase currency
        refund_original_minor = validate_positive_amount(amount, "Refund amount", currency=orig_purchase_curr)

        # 2. Resolve multi-currency and FX valuations:
        # Original refund amount (in orig_purchase_curr) -> settlement in target account -> base/reporting currency
        if target_acc_curr == orig_purchase_curr:
            target_amount_minor = refund_original_minor
        else:
            conv_target = FxService.try_convert_cached_minor(refund_original_minor, orig_purchase_curr, target_acc_curr, on_date=clean_date)
            if not conv_target:
                raise ValueError(f"Exchange rate from {orig_purchase_curr} to {target_acc_curr} is not cached.")
            target_amount_minor = conv_target.target.minor

        if target_acc_curr == base_currency:
            base_amount_minor = target_amount_minor
            fx_rate_to_base = "1.0"
            fx_rate_date = clean_date
            fx_rate_source = "identity"
            fx_status = "not_required"
        else:
            conv_base = FxService.try_convert_cached_minor(target_amount_minor, target_acc_curr, base_currency, on_date=clean_date)
            if conv_base:
                base_amount_minor = conv_base.target.minor
                fx_rate_to_base = str(conv_base.rate)
                fx_rate_date = conv_base.rate_date
                fx_rate_source = conv_base.provider
                fx_status = "market_estimate"
            else:
                base_amount_minor = None
                fx_rate_to_base = None
                fx_rate_date = None
                fx_rate_source = None
                fx_status = "pending"

        merchant_name = orig["merchant_name"] or ""
        desc = f"Refund: {orig['description'] or merchant_name}"

        # 3. Atomically enforce cumulative balance limit and insert refund record
        with get_db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT COALESCE(SUM(COALESCE(original_amount_minor, amount_minor)), 0)
                    FROM active_transactions
                    WHERE refund_of_transaction_id = ? AND transaction_type = 'refund'
                """, (target_orig_id,))
                existing_refunded_minor = cur.fetchone()[0]

                remaining_refundable_minor = orig_total_minor - existing_refunded_minor
                if refund_original_minor > remaining_refundable_minor:
                    err_str = (
                        f"Refund amount of {format_money(refund_original_minor, orig_purchase_curr)} exceeds remaining refundable balance of {format_money(remaining_refundable_minor, orig_purchase_curr)} "
                        f"(Original: {format_money(orig_total_minor, orig_purchase_curr)}, Prior Refunds: {format_money(existing_refunded_minor, orig_purchase_curr)})."
                    )
                    raise ValueError(err_str)

                cur.execute("""
                    INSERT INTO transactions (
                        account_id, category_id, merchant_id, merchant_name, transaction_type,
                        amount_minor, transaction_date, transaction_time, description,
                        note, is_recurring, payment_method, essentiality,
                        transfer_group_id, transfer_role, linked_transaction_id,
                        refund_of_transaction_id, source, needs_review, is_deleted,
                        original_currency, original_amount_minor,
                        base_currency, base_amount_minor,
                        fx_rate_to_base, fx_rate_date, fx_rate_source, fx_status
                    ) VALUES (
                        ?, ?, ?, ?, 'refund', ?, ?, ?, ?, ?, 0, ?, ?, NULL, NULL, NULL, ?, 'manual', 0, 0,
                        ?, ?, ?, ?, ?, ?, ?, ?
                    )
                """, (
                    target_acc_id,
                    orig["category_id"],
                    orig["merchant_id"],
                    merchant_name,
                    target_amount_minor,
                    clean_date,
                    datetime.now().strftime("%H:%M"),
                    desc,
                    note,
                    orig["payment_method"] or "Card",
                    orig["essentiality"] or "discretionary",
                    target_orig_id,
                    orig_purchase_curr,
                    refund_original_minor,
                    base_currency,
                    base_amount_minor,
                    fx_rate_to_base,
                    fx_rate_date,
                    fx_rate_source,
                    fx_status
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
        Updates an existing refund transaction atomically under BEGIN IMMEDIATE.
        Recalculates FX conversions and validates cumulative bounds against original parent in purchase currency.
        """
        from app.backend.domain.validators import validate_positive_amount, validate_iso_date

        # 1. Pre-fetch before transaction lock
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,))
            orig_refund = cur.fetchone()
            if not orig_refund:
                raise ValueError(f"Refund transaction {tx_id} not found.")
            if orig_refund["transaction_type"] != "refund":
                raise ValueError(f"Transaction {tx_id} is not a refund.")

            ref_dict = dict(orig_refund)
            clean_date = validate_iso_date(transaction_date, "Refund transaction date") if transaction_date else ref_dict["transaction_date"]
            target_acc_id = account_id if account_id is not None else ref_dict["account_id"]
            cur.execute("SELECT currency FROM accounts WHERE id = ?", (target_acc_id,))
            target_row = cur.fetchone()
            target_acc_curr = target_row["currency"] if target_row else "USD"

            parent_id = ref_dict.get("refund_of_transaction_id")
            parent_acc_curr = target_acc_curr
            parent_orig_curr = ref_dict.get("original_currency") or target_acc_curr
            parent_tx = None
            if parent_id:
                cur.execute("SELECT * FROM transactions WHERE id = ?", (parent_id,))
                parent_tx = cur.fetchone()
                if parent_tx:
                    p_dict = dict(parent_tx)
                    cur.execute("SELECT currency FROM accounts WHERE id = ?", (p_dict["account_id"],))
                    p_row = cur.fetchone()
                    parent_acc_curr = p_row["currency"] if p_row else "USD"
                    parent_orig_curr = p_dict.get("original_currency") or parent_acc_curr

        base_currency = SettingsService.get_setting("currency", "USD") or "USD"

        if amount is not None:
            new_original_minor = validate_positive_amount(amount, "Refund amount", currency=parent_orig_curr)
        else:
            new_original_minor = ref_dict.get("original_amount_minor") if ref_dict.get("original_amount_minor") is not None else ref_dict["amount_minor"]

        # 2. Resolve FX valuations: parent_orig_curr -> target_acc_curr -> base_currency
        if target_acc_curr == parent_orig_curr:
            target_amount_minor = new_original_minor
        else:
            conv_target = FxService.try_convert_cached_minor(new_original_minor, parent_orig_curr, target_acc_curr, on_date=clean_date)
            if not conv_target:
                raise ValueError(f"Exchange rate from {parent_orig_curr} to {target_acc_curr} is not cached.")
            target_amount_minor = conv_target.target.minor

        if target_acc_curr == base_currency:
            base_amount_minor = target_amount_minor
            fx_rate_to_base = "1.0"
            fx_rate_date = clean_date
            fx_rate_source = "identity"
            fx_status = "not_required"
        else:
            conv_base = FxService.try_convert_cached_minor(target_amount_minor, target_acc_curr, base_currency, on_date=clean_date)
            if conv_base:
                base_amount_minor = conv_base.target.minor
                fx_rate_to_base = str(conv_base.rate)
                fx_rate_date = conv_base.rate_date
                fx_rate_source = conv_base.provider
                fx_status = "market_estimate"
            else:
                base_amount_minor = None
                fx_rate_to_base = None
                fx_rate_date = None
                fx_rate_source = None
                fx_status = "pending"

        # 3. Atomically check bounds and update
        with get_db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.cursor()
                if parent_id and parent_tx:
                    cur.execute("""
                        SELECT COALESCE(SUM(COALESCE(original_amount_minor, amount_minor)), 0)
                        FROM active_transactions
                        WHERE refund_of_transaction_id = ? AND transaction_type = 'refund' AND id != ?
                    """, (parent_id, tx_id))
                    other_refunds = cur.fetchone()[0]

                    p_dict = dict(parent_tx)
                    parent_total_minor = p_dict.get("original_amount_minor") if p_dict.get("original_amount_minor") is not None else p_dict["amount_minor"]
                    remaining = parent_total_minor - other_refunds
                    if new_original_minor > remaining:
                        err_str = f"Updated refund amount of {format_money(new_original_minor, parent_orig_curr)} exceeds remaining refundable balance of {format_money(remaining, parent_orig_curr)}."
                        raise ValueError(err_str)

                updates: Dict[str, Any] = {
                    "amount_minor": target_amount_minor,
                    "original_amount_minor": new_original_minor,
                    "original_currency": parent_orig_curr,
                    "base_currency": base_currency,
                    "base_amount_minor": base_amount_minor,
                    "fx_rate_to_base": fx_rate_to_base,
                    "fx_rate_date": fx_rate_date,
                    "fx_rate_source": fx_rate_source,
                    "fx_status": fx_status,
                    "updated_at": datetime.now().isoformat()
                }
                if transaction_date:
                    updates["transaction_date"] = clean_date
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
    def get_refundable_info(tx_id: int) -> Dict[str, Any]:
        """
        Returns refund status and remaining refundable balance in the transaction's original purchase currency.
        """
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Transaction {tx_id} not found.")
            tx = dict(row)

            cur.execute("SELECT currency FROM accounts WHERE id = ?", (tx["account_id"],))
            acc_row = cur.fetchone()
            orig_curr = (tx.get("original_currency") or (acc_row["currency"] if acc_row else "USD")) or "USD"
            orig_amount_minor = tx.get("original_amount_minor") if tx.get("original_amount_minor") is not None else tx["amount_minor"]

            cur.execute("""
                SELECT COALESCE(SUM(COALESCE(original_amount_minor, amount_minor)), 0)
                FROM active_transactions
                WHERE refund_of_transaction_id = ? AND transaction_type = 'refund'
            """, (tx_id,))
            refunded_minor = cur.fetchone()[0]
            remaining_minor = max(0, orig_amount_minor - refunded_minor)

            return {
                "transaction_id": tx_id,
                "original_currency": orig_curr,
                "original_amount_minor": orig_amount_minor,
                "original_amount": float(minor_to_major(orig_amount_minor, orig_curr)),
                "refunded_amount_minor": refunded_minor,
                "refunded_amount": float(minor_to_major(refunded_minor, orig_curr)),
                "remaining_refundable_minor": remaining_minor,
                "remaining_refundable": float(minor_to_major(remaining_minor, orig_curr)),
                "can_refund": remaining_minor > 0 and tx["transaction_type"] == "expense",
                "is_expense": tx["transaction_type"] == "expense"
            }

    @staticmethod
    def _update_fields(tx_id: int, data: Dict[str, Any]) -> bool:
        """
        Low-level persistence method for updating transaction fields in SQLite.
        """
        from app.backend.domain.validators import (
            validate_positive_amount,
            validate_iso_date,
            validate_transaction_type
        )
        allowed = {
            "account_id", "category_id", "merchant_name", "merchant_id", "transaction_type",
            "amount_minor",
            "transaction_date", "transaction_time", "description",
            "note", "is_recurring", "payment_method", "essentiality",
            "needs_review", "review_reason", "raw_merchant_name",
            "capture_method", "category_source", "category_confidence",
            "essentiality_source", "essentiality_confidence", "parser_version",
            "original_currency", "original_amount_minor",
            "base_currency", "base_amount_minor",
            "fx_rate_to_base", "fx_rate_date", "fx_rate_source", "fx_status"
        }
        updates: Dict[str, Any] = {}

        if "transaction_type" in data:
            data["transaction_type"] = validate_transaction_type(data["transaction_type"])

        if "transaction_date" in data:
            data["transaction_date"] = validate_iso_date(data["transaction_date"], "Transaction date")

        if "amount_minor" in data:
            updates["amount_minor"] = int(data["amount_minor"])
        elif "amount" in data:
            eff_type = data.get("transaction_type")
            if not eff_type:
                with get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT transaction_type FROM transactions WHERE id = ?", (tx_id,))
                    row = cur.fetchone()
                    if row:
                        eff_type = row["transaction_type"]
            if eff_type == "adjustment":
                updates["amount_minor"] = major_to_minor(data["amount"])
            else:
                updates["amount_minor"] = validate_positive_amount(data["amount"], "Transaction amount")

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
        - Recomputes exact multi-currency and FX valuations if amounts, dates, or accounts change.
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

        eff_type = data.get("transaction_type") or existing.get("transaction_type")
        eff_cat_id = data["category_id"] if "category_id" in data else existing.get("category_id")
        if "category_id" in data or "transaction_type" in data:
            with get_db_connection() as conn:
                from app.backend.domain.validators import validate_category_for_transaction
                validate_category_for_transaction(conn, eff_cat_id, eff_type)

        target_acc_id = data.get("account_id", existing["account_id"])
        account = AccountRepository.get_by_id(target_acc_id)
        account_currency = account["currency"] if account else "USD"
        base_currency = SettingsService.get_setting("currency", "USD") or "USD"

        # Check if amount or currencies or date need re-evaluating
        has_amount_change = any(k in data for k in ["amount", "amount_minor", "original_amount", "original_amount_minor", "settlement_amount"])
        has_context_change = ("account_id" in data) or ("transaction_date" in data) or ("original_currency" in data)

        data_copy = dict(data)

        if has_amount_change or has_context_change:
            clean_date = validate_iso_date(data_copy.get("transaction_date", existing["transaction_date"]), "Transaction date")
            orig_curr_in = data_copy.get("original_currency")
            original_currency = validate_currency_code(orig_curr_in) if orig_curr_in else (existing.get("original_currency") or account_currency)
            eff_type = validate_transaction_type(data_copy.get("transaction_type", existing["transaction_type"]))

            if original_currency == account_currency:
                if "amount" in data_copy:
                    amt_val = data_copy["amount"]
                    if eff_type != "adjustment":
                        amount_minor = validate_positive_amount(amt_val, "Transaction amount", currency=account_currency)
                    else:
                        amount_minor = major_to_minor(amt_val, account_currency)
                elif "amount_minor" in data_copy:
                    amt_minor = int(data_copy["amount_minor"])
                    if eff_type != "adjustment" and amt_minor <= 0:
                        raise ValueError("Transaction amount must be greater than zero.")
                    amount_minor = amt_minor
                elif "original_amount" in data_copy:
                    amount_minor = validate_positive_amount(data_copy["original_amount"], "Transaction amount", currency=account_currency)
                else:
                    amount_minor = existing["amount_minor"]

                original_amount_minor = amount_minor
                if account_currency == base_currency:
                    base_amount_minor = amount_minor
                    fx_status = "not_required"
                    fx_rate_to_base = "1.0"
                    fx_rate_date = clean_date
                    fx_rate_source = "identity"
                else:
                    conv = FxService.try_convert_cached_minor(amount_minor, account_currency, base_currency, on_date=clean_date)
                    if conv:
                        base_amount_minor = conv.target.minor
                        fx_status = "market_estimate"
                        fx_rate_to_base = str(conv.rate)
                        fx_rate_date = conv.rate_date
                        fx_rate_source = conv.provider
                    else:
                        base_amount_minor = None
                        fx_status = "pending"
                        fx_rate_to_base = None
                        fx_rate_date = None
                        fx_rate_source = None
            else:
                if "original_amount" in data_copy:
                    original_amount_minor = validate_positive_amount(data_copy["original_amount"], "Original amount", currency=original_currency)
                elif "original_amount_minor" in data_copy:
                    orig_minor = int(data_copy["original_amount_minor"])
                    if orig_minor <= 0:
                        raise ValueError("Transaction amount must be greater than zero.")
                    original_amount_minor = orig_minor
                elif "amount" in data_copy and data_copy.get("settlement_amount") is None:
                    original_amount_minor = validate_positive_amount(data_copy["amount"], "Original amount", currency=original_currency)
                else:
                    original_amount_minor = existing.get("original_amount_minor") or existing["amount_minor"]

                conv_acct = None
                if data_copy.get("settlement_amount") is not None:
                    amount_minor = validate_positive_amount(data_copy["settlement_amount"], "Settlement amount", currency=account_currency)
                    fx_status = "user_settlement"
                elif "amount" in data_copy and "original_amount" in data_copy and data_copy.get("amount") != data_copy.get("original_amount"):
                    amount_minor = validate_positive_amount(data_copy["amount"], "Settlement amount", currency=account_currency)
                    fx_status = "user_settlement"
                elif "amount_minor" in data_copy and "original_amount_minor" in data_copy:
                    amount_minor = int(data_copy["amount_minor"])
                    fx_status = "user_settlement"
                else:
                    conv_acct = FxService.try_convert_cached_minor(original_amount_minor, original_currency, account_currency, on_date=clean_date)
                    if conv_acct is not None:
                        amount_minor = conv_acct.target.minor
                        fx_status = "market_estimate"
                    else:
                        if data_copy.get("settlement_amount") is None and ("amount" not in data_copy or data_copy.get("amount") == data_copy.get("original_amount")):
                            raise ValueError(
                                f"Cross-currency transaction ({original_currency} on {account_currency} account) "
                                f"requires a settlement amount or an existing cached exchange rate."
                            )
                        amount_minor = validate_positive_amount(data_copy["amount"], "Settlement amount", currency=account_currency)
                        fx_status = "user_settlement"

                if account_currency == base_currency:
                    base_amount_minor = amount_minor
                    if conv_acct is not None:
                        fx_rate_to_base = str(conv_acct.rate)
                        fx_rate_date = conv_acct.rate_date
                        fx_rate_source = conv_acct.provider
                    else:
                        orig_maj = minor_to_major(original_amount_minor, original_currency)
                        base_maj = minor_to_major(base_amount_minor, base_currency)
                        fx_rate_to_base = str(base_maj / orig_maj) if orig_maj > 0 else "1.0"
                        fx_rate_date = clean_date
                        fx_rate_source = "user_settlement"
                else:
                    conv_base = FxService.try_convert_cached_minor(amount_minor, account_currency, base_currency, on_date=clean_date)
                    if conv_base:
                        base_amount_minor = conv_base.target.minor
                        fx_rate_to_base = str(conv_base.rate)
                        fx_rate_date = conv_base.rate_date
                        fx_rate_source = conv_base.provider
                        if fx_status != "user_settlement":
                            fx_status = "market_estimate"
                    else:
                        base_amount_minor = None
                        fx_status = "pending"
                        fx_rate_to_base = None
                        fx_rate_date = None
                        fx_rate_source = None

            data_copy["amount_minor"] = amount_minor
            data_copy["original_currency"] = original_currency
            data_copy["original_amount_minor"] = original_amount_minor
            data_copy["base_currency"] = base_currency
            data_copy["base_amount_minor"] = base_amount_minor
            data_copy["fx_rate_to_base"] = fx_rate_to_base
            data_copy["fx_rate_date"] = fx_rate_date
            data_copy["fx_rate_source"] = fx_rate_source
            data_copy["fx_status"] = fx_status

        # If merchant_name is changing, ensure merchant record is created or updated
        if "merchant_name" in data_copy:
            clean_merch = normalize_merchant_name(data_copy["merchant_name"])
            if clean_merch:
                data_copy["merchant_id"] = MerchantService.get_or_create_merchant(
                    clean_merch,
                    category_id=data_copy.get("category_id", existing.get("category_id")),
                    account_id=target_acc_id,
                    essentiality=data_copy.get("essentiality", existing.get("essentiality"))
                )

        return TransactionRepository._update_fields(tx_id, data_copy)

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
    def get_review_queue(limit: int = 50, offset: int = 0, account_id: Optional[int] = None) -> Dict[str, Any]:
        """Returns transactions that require review (e.g. Uncategorized or flagged), optionally filtered by account."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            query = """
                SELECT 
                    t.id, t.account_id, t.category_id, t.merchant_id, t.merchant_name,
                    t.raw_merchant_name, t.capture_method, t.category_source, t.category_confidence,
                    t.essentiality_source, t.essentiality_confidence, t.review_reason, t.parser_version,
                    t.amount_minor, t.transaction_date, t.transaction_time, t.description, t.note,
                    t.transaction_type, t.is_recurring, t.payment_method, t.essentiality,
                    t.transfer_group_id, t.transfer_role, t.linked_transaction_id,
                    t.refund_of_transaction_id, t.source, t.needs_review, t.is_deleted,
                    t.original_currency, t.original_amount_minor,
                    t.base_currency, t.base_amount_minor,
                    t.fx_rate_to_base, t.fx_rate_date, t.fx_rate_source, t.fx_status,
                    a.name as account_name, a.currency as account_currency,
                    c.name as category_name, c.color as category_color, c.icon as category_icon
                FROM active_transactions t
                LEFT JOIN accounts a ON t.account_id = a.id
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE (t.needs_review = 1 OR c.name = 'Uncategorized')
            """
            count_query = """
                SELECT COUNT(*) FROM active_transactions t
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE (t.needs_review = 1 OR c.name = 'Uncategorized')
            """
            params: List[Any] = []
            count_params: List[Any] = []
            if account_id is not None:
                query += " AND t.account_id = ?"
                count_query += " AND t.account_id = ?"
                params.append(account_id)
                count_params.append(account_id)

            query += " ORDER BY t.transaction_date DESC, t.id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cur.execute(query, params)
            items = [_hydrate_transaction_row(dict(r)) for r in cur.fetchall()]

            cur.execute(count_query, count_params)
            total = cur.fetchone()[0]

            return {
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset
            }

    @staticmethod
    def resolve_review(
        tx_id: int,
        category_id: int,
        merchant_name: Optional[str] = None,
        essentiality: Optional[str] = None
    ) -> bool:
        """Sets category, clears review flag, and authoritatively re-learns merchant defaults atomically (P0-04, P0-05)."""
        # Handle positional ambiguity where 3rd param is essentiality ("essential", "discretionary", "savings")
        if merchant_name in ("essential", "discretionary", "savings", "unknown") and essentiality is None:
            essentiality = merchant_name
            merchant_name = None

        with get_db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.cursor()
                cur.execute("SELECT id, account_id, merchant_name, essentiality FROM transactions WHERE id = ? AND is_deleted = 0", (tx_id,))
                tx = cur.fetchone()
                if not tx:
                    return False

                effective_merchant = normalize_merchant_name(merchant_name or tx["merchant_name"] or "")
                target_essentiality = essentiality or tx["essentiality"] or "discretionary"

                if effective_merchant:
                    MerchantService.learn_defaults_in_conn(
                        conn,
                        effective_merchant,
                        category_id=category_id,
                        account_id=tx["account_id"],
                        essentiality=target_essentiality,
                        overwrite=True
                    )

                cur.execute("""
                    UPDATE transactions 
                    SET category_id = ?, 
                        needs_review = 0, 
                        review_reason = NULL,
                        category_source = 'review_confirmed',
                        category_confidence = 1.0,
                        essentiality = ?,
                        essentiality_source = 'review_confirmed',
                        essentiality_confidence = 1.0,
                        merchant_name = ?
                    WHERE id = ?
                """, (category_id, target_essentiality, effective_merchant or tx["merchant_name"] or "", tx_id))
                updated = cur.rowcount > 0
                conn.commit()
                return updated
            except Exception:
                conn.rollback()
                raise

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
