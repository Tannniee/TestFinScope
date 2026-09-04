import io
import csv
import re
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from app.backend.database.connection import get_db_connection
from app.backend.services.merchant_service import MerchantService

logger = logging.getLogger(__name__)

class ImportService:
    """
    Bank CSV Import Engine.
    Provides intelligent column auto-detection, date and currency normalization,
    duplicate detection, merchant memory auto-categorization, and atomic batch insertion.
    """

    @staticmethod
    def _detect_delimiter(sample_text: str) -> str:
        """Detects delimiter from first few lines."""
        for line in sample_text.splitlines()[:5]:
            if line.count(",") > 1:
                return ","
            if line.count(";") > 1:
                return ";"
            if line.count("\t") > 1:
                return "\t"
        return ","

    @staticmethod
    def parse_date(date_str: str) -> Optional[str]:
        """Parses diverse date formats into standard YYYY-MM-DD."""
        if not date_str:
            return None
        cleaned = date_str.strip().split()[0]  # Strip time component if present
        formats = [
            "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y",
            "%m/%d/%Y", "%m-%d-%Y", "%d.%m.%Y", "%Y.%m.%d"
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(cleaned, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None

    @staticmethod
    def parse_amount(amount_str: str) -> Tuple[float, str]:
        """
        Parses amount string into float and transaction type ('expense' or 'income').
        Handles formats like ($123.45), -123.45, +123.45, 123,45 EUR, 50.000 VND.
        """
        if not amount_str:
            return 0.0, "expense"
        raw = amount_str.strip()
        is_negative = False

        if raw.startswith("(") and raw.endswith(")"):
            is_negative = True
            raw = raw[1:-1]
        elif "-" in raw:
            is_negative = True
            raw = raw.replace("-", "")

        # Remove currency symbols and non-numeric except . and ,
        raw = re.sub(r"[^\d.,]", "", raw)
        if not raw:
            return 0.0, "expense"

        # Handle European decimal comma (e.g. 1.250,50 -> 1250.50)
        if "," in raw and "." in raw:
            if raw.rfind(",") > raw.rfind("."):
                raw = raw.replace(".", "").replace(",", ".")
            else:
                raw = raw.replace(",", "")
        elif "," in raw and "." not in raw:
            # Could be decimal comma like 12,50 or thousand sep 12,000
            parts = raw.split(",")
            if len(parts) == 2 and len(parts[1]) <= 2:
                raw = raw.replace(",", ".")
            else:
                raw = raw.replace(",", "")

        try:
            val = float(raw)
        except ValueError:
            val = 0.0

        if is_negative:
            return abs(val), "expense"
        return abs(val), "income" if val > 0 else "expense"

    @classmethod
    def auto_detect_mapping(cls, headers: List[str]) -> Dict[str, str]:
        """Infers mapping of CSV columns to FinScope transaction fields."""
        mapping: Dict[str, str] = {
            "date": "",
            "amount": "",
            "payee": "",
            "description": "",
            "category": "",
            "debit": "",
            "credit": ""
        }

        lower_headers = [h.strip().lower() for h in headers]

        for idx, h in enumerate(lower_headers):
            orig = headers[idx]
            # Date
            if not mapping["date"] and any(k in h for k in ["date", "trans date", "posting date", "ngày", "ngay"]):
                mapping["date"] = orig
            # Amount
            elif not mapping["amount"] and any(k in h for k in ["amount", "số tiền", "so tien", "value", "net"]):
                mapping["amount"] = orig
            # Debit / Outflow
            elif not mapping["debit"] and any(k in h for k in ["debit", "outflow", "chi"]):
                mapping["debit"] = orig
            # Credit / Inflow
            elif not mapping["credit"] and any(k in h for k in ["credit", "inflow", "thu"]):
                mapping["credit"] = orig
            # Payee / Merchant
            elif not mapping["payee"] and any(k in h for k in ["merchant", "payee", "party", "beneficiary", "đối tác", "doi tac"]):
                mapping["payee"] = orig
            # Description / Narrative / Memo
            elif not mapping["description"] and any(k in h for k in ["description", "narrative", "memo", "details", "nội dung", "noi dung"]):
                mapping["description"] = orig
            # Category
            elif not mapping["category"] and any(k in h for k in ["category", "danh mục", "danh muc"]):
                mapping["category"] = orig

        # Fallback: if no payee but description exists, set payee = description
        if not mapping["payee"] and mapping["description"]:
            mapping["payee"] = mapping["description"]

        return mapping

    @classmethod
    def preview_csv(
        cls,
        csv_content: str,
        mapping: Optional[Dict[str, str]] = None,
        account_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Parses CSV, suggests column mapping if missing, normalizes fields,
        and identifies duplicate transactions against the target account.
        """
        if not csv_content or not csv_content.strip():
            raise ValueError("CSV content is empty.")

        delimiter = cls._detect_delimiter(csv_content)
        reader = csv.reader(io.StringIO(csv_content.strip()), delimiter=delimiter)
        raw_rows = [row for row in reader if row and any(cell.strip() for cell in row)]

        if not raw_rows:
            raise ValueError("No valid rows found in CSV.")

        headers = [h.strip() for h in raw_rows[0]]
        data_rows = raw_rows[1:]

        active_mapping = mapping if mapping and any(mapping.values()) else cls.auto_detect_mapping(headers)

        # Build existing transaction set for duplicate detection
        existing_txs = set()
        if account_id:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT transaction_date, amount_minor FROM active_transactions WHERE account_id = ?",
                    (account_id,)
                )
                for r in cur.fetchall():
                    existing_txs.add((r["transaction_date"], r["amount_minor"]))

        date_col = active_mapping.get("date")
        amount_col = active_mapping.get("amount")
        debit_col = active_mapping.get("debit")
        credit_col = active_mapping.get("credit")
        payee_col = active_mapping.get("payee")
        desc_col = active_mapping.get("description")
        cat_col = active_mapping.get("category")

        def get_col_idx(col_name: Optional[str]) -> Optional[int]:
            if not col_name:
                return None
            try:
                return headers.index(col_name)
            except ValueError:
                return None

        idx_date = get_col_idx(date_col)
        idx_amt = get_col_idx(amount_col)
        idx_debit = get_col_idx(debit_col)
        idx_credit = get_col_idx(credit_col)
        idx_payee = get_col_idx(payee_col)
        idx_desc = get_col_idx(desc_col)
        idx_cat = get_col_idx(cat_col)

        preview_rows = []
        duplicate_count = 0
        valid_count = 0

        for row_idx, row in enumerate(data_rows):
            # Extract date
            raw_date = row[idx_date] if idx_date is not None and idx_date < len(row) else ""
            parsed_date = cls.parse_date(raw_date) or datetime.now().strftime("%Y-%m-%d")

            # Extract amount and type
            amount = 0.0
            tx_type = "expense"

            if idx_debit is not None and idx_debit < len(row) and row[idx_debit].strip():
                val, _ = cls.parse_amount(row[idx_debit])
                if val > 0:
                    amount = val
                    tx_type = "expense"
            elif idx_credit is not None and idx_credit < len(row) and row[idx_credit].strip():
                val, _ = cls.parse_amount(row[idx_credit])
                if val > 0:
                    amount = val
                    tx_type = "income"
            elif idx_amt is not None and idx_amt < len(row):
                amount, tx_type = cls.parse_amount(row[idx_amt])

            amount_minor = int(round(amount * 100))

            # Extract payee and description
            raw_payee = row[idx_payee].strip() if idx_payee is not None and idx_payee < len(row) else ""
            raw_desc = row[idx_desc].strip() if idx_desc is not None and idx_desc < len(row) else ""
            payee = raw_payee or raw_desc or "Bank Transaction"
            desc = raw_desc or payee

            # Duplicate check
            is_dup = (parsed_date, amount_minor) in existing_txs
            if is_dup:
                duplicate_count += 1
            elif amount_minor > 0:
                valid_count += 1

            preview_rows.append({
                "row_index": row_idx,
                "date": parsed_date,
                "amount": amount,
                "amount_minor": amount_minor,
                "transaction_type": tx_type,
                "payee": payee,
                "description": desc,
                "category_suggestion": None,
                "is_duplicate": is_dup
            })

        return {
            "headers": headers,
            "mapping": active_mapping,
            "preview_rows": preview_rows[:100],
            "total_rows": len(data_rows),
            "duplicate_count": duplicate_count,
            "valid_count": valid_count
        }

    @classmethod
    def commit_import(
        cls,
        csv_content: str,
        mapping: Dict[str, str],
        account_id: int,
        deduplicate: bool = True
    ) -> Dict[str, Any]:
        """
        Parses and inserts transactions atomically. Auto-categorizes known payees
        via MerchantService and tags uncertain ones with needs_review = 1.
        """
        preview = cls.preview_csv(csv_content, mapping, account_id=account_id)
        rows_to_insert = preview["preview_rows"]

        # Parse ALL rows from CSV for the actual commit
        delimiter = cls._detect_delimiter(csv_content)
        reader = csv.reader(io.StringIO(csv_content.strip()), delimiter=delimiter)
        raw_rows = [row for row in reader if row and any(cell.strip() for cell in row)]
        headers = [h.strip() for h in raw_rows[0]]
        data_rows = raw_rows[1:]

        def get_col_idx(col_name: Optional[str]) -> Optional[int]:
            if not col_name:
                return None
            try:
                return headers.index(col_name)
            except ValueError:
                return None

        idx_date = get_col_idx(mapping.get("date"))
        idx_amt = get_col_idx(mapping.get("amount"))
        idx_debit = get_col_idx(mapping.get("debit"))
        idx_credit = get_col_idx(mapping.get("credit"))
        idx_payee = get_col_idx(mapping.get("payee"))
        idx_desc = get_col_idx(mapping.get("description"))

        existing_txs = set()
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT transaction_date, amount_minor FROM active_transactions WHERE account_id = ?",
                (account_id,)
            )
            for r in cur.fetchall():
                existing_txs.add((r["transaction_date"], r["amount_minor"]))

            # Load default category for unassigned
            cur.execute("SELECT id FROM categories WHERE type = 'expense' ORDER BY id ASC LIMIT 1")
            default_cat_row = cur.fetchone()
            fallback_category_id = default_cat_row["id"] if default_cat_row else 1

            now_str = datetime.now().isoformat()
            imported_count = 0
            skipped_count = 0

            for row in data_rows:
                raw_date = row[idx_date] if idx_date is not None and idx_date < len(row) else ""
                parsed_date = cls.parse_date(raw_date) or datetime.now().strftime("%Y-%m-%d")

                amount = 0.0
                tx_type = "expense"

                if idx_debit is not None and idx_debit < len(row) and row[idx_debit].strip():
                    val, _ = cls.parse_amount(row[idx_debit])
                    if val > 0:
                        amount = val
                        tx_type = "expense"
                elif idx_credit is not None and idx_credit < len(row) and row[idx_credit].strip():
                    val, _ = cls.parse_amount(row[idx_credit])
                    if val > 0:
                        amount = val
                        tx_type = "income"
                elif idx_amt is not None and idx_amt < len(row):
                    amount, tx_type = cls.parse_amount(row[idx_amt])

                amount_minor = int(round(amount * 100))
                if amount_minor <= 0:
                    continue

                if deduplicate and (parsed_date, amount_minor) in existing_txs:
                    skipped_count += 1
                    continue

                raw_payee = row[idx_payee].strip() if idx_payee is not None and idx_payee < len(row) else ""
                raw_desc = row[idx_desc].strip() if idx_desc is not None and idx_desc < len(row) else ""
                payee = raw_payee or raw_desc or "Bank Transaction"
                desc = raw_desc or payee

                # Merchant memory lookup
                cur.execute("SELECT default_category_id, default_essentiality FROM merchants WHERE name = ? COLLATE NOCASE", (payee,))
                m_row = cur.fetchone()

                category_id = m_row["default_category_id"] if m_row and m_row["default_category_id"] else fallback_category_id
                essentiality = m_row["default_essentiality"] if m_row and m_row["default_essentiality"] else "discretionary"
                needs_review = 0 if (m_row and m_row["default_category_id"]) else 1

                cur.execute("""
                    INSERT INTO transactions (
                        account_id, category_id, merchant_name, transaction_type,
                        amount_minor, transaction_date, transaction_time, description,
                        note, essentiality, payment_method, source, needs_review,
                        is_deleted, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, '12:00', ?, '', ?, 'Bank Import', 'csv_import', ?, 0, ?, ?)
                """, (
                    account_id,
                    category_id,
                    payee,
                    tx_type,
                    amount_minor,
                    parsed_date,
                    desc,
                    essentiality,
                    needs_review,
                    now_str,
                    now_str
                ))

                existing_txs.add((parsed_date, amount_minor))
                imported_count += 1

            conn.commit()

        return {
            "success": True,
            "imported_count": imported_count,
            "skipped_duplicates": skipped_count,
            "total_processed": len(data_rows)
        }
