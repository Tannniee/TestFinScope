import io
import csv
import re
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from app.backend.database.connection import get_db_connection
from app.backend.services.merchant_service import MerchantService, normalize_merchant_name

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
    def parse_date(date_str: str, date_format: Optional[str] = None) -> Optional[str]:
        """
        Parses diverse date formats into standard YYYY-MM-DD.
        Supports explicit date_format: 'auto', 'DD/MM/YYYY', 'MM/DD/YYYY', 'YYYY-MM-DD'.
        In 'auto' mode, if date is ambiguous (e.g. 01/02/2026 where both day and month <= 12 and day != month),
        raises ValueError prompting the user to select an explicit format.
        """
        if not date_str:
            return None
        cleaned = date_str.strip().split()[0]  # Strip time component if present

        mode = (date_format or "auto").strip().upper()

        if mode in ("DD/MM/YYYY", "DMY", "DD-MM-YYYY"):
            formats = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"]
            for fmt in formats:
                try:
                    return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
            return None

        if mode in ("MM/DD/YYYY", "MDY", "MM-DD-YYYY"):
            formats = ["%m/%d/%Y", "%m-%d-%Y", "%m.%d.%Y"]
            for fmt in formats:
                try:
                    return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
            return None

        if mode in ("YYYY-MM-DD", "YMD", "YYYY/MM/DD"):
            formats = ["%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"]
            for fmt in formats:
                try:
                    return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
            return None

        # Mode is 'AUTO':
        # 1. Unambiguous ISO format (Year is 4 digits first)
        iso_match = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", cleaned)
        if iso_match:
            try:
                y, m, d = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
                return datetime(y, m, d).strftime("%Y-%m-%d")
            except ValueError:
                return None

        # 2. 3 parts with 4-digit year at end: e.g. 01/02/2026 or 25-12-2026
        dmy_match = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", cleaned)
        if dmy_match:
            p1, p2, year = int(dmy_match.group(1)), int(dmy_match.group(2)), int(dmy_match.group(3))
            # If both p1 and p2 <= 12 and p1 != p2: AMBIGUOUS!
            if 1 <= p1 <= 12 and 1 <= p2 <= 12 and p1 != p2:
                raise ValueError(f"Ambiguous date '{cleaned}': could be DD/MM/YYYY or MM/DD/YYYY. Please select an explicit date format in Step 2.")
            elif p1 > 12 and 1 <= p2 <= 12:
                # Unambiguously DD/MM/YYYY (day > 12)
                try:
                    return datetime(year, p2, p1).strftime("%Y-%m-%d")
                except ValueError:
                    return None
            elif p2 > 12 and 1 <= p1 <= 12:
                # Unambiguously MM/DD/YYYY (day > 12 in second slot)
                try:
                    return datetime(year, p1, p2).strftime("%Y-%m-%d")
                except ValueError:
                    return None
            elif p1 == p2 and 1 <= p1 <= 12:
                # Same day and month e.g. 05/05/2026
                try:
                    return datetime(year, p1, p2).strftime("%Y-%m-%d")
                except ValueError:
                    return None

        # Fallback formats for auto mode
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
        Handles formats like ($123.45), -123.45, +123.45, 1.250,50 EUR, 1,250.50, 50.000 VND.
        Raises ValueError on malformed or empty numeric values.
        """
        if not amount_str or not amount_str.strip():
            raise ValueError("Amount string is empty.")

        raw = amount_str.strip()
        is_negative = False

        if raw.startswith("(") and raw.endswith(")"):
            is_negative = True
            raw = raw[1:-1].strip()
        elif raw.startswith("-"):
            is_negative = True
            raw = raw[1:].strip()
        elif "-" in raw:
            is_negative = True
            raw = raw.replace("-", "").strip()
        elif raw.startswith("+"):
            is_negative = False
            raw = raw[1:].strip()

        # Detect currency indicators
        has_vnd = bool(re.search(r'(?:vnd|vnđ|đ)', raw, re.IGNORECASE))
        has_eur = bool(re.search(r'(?:eur|€)', raw, re.IGNORECASE))

        # Remove currency symbols and letters, keeping only digits and separators
        cleaned = re.sub(r"[^\d.,]", "", raw)
        if not cleaned:
            raise ValueError(f"Unable to parse amount: '{amount_str}'")

        if has_vnd:
            # VND has no decimal minor units; dots and commas are thousand separators
            cleaned = cleaned.replace(".", "").replace(",", "")
        elif "," in cleaned and "." in cleaned:
            # Both separators present
            last_comma = cleaned.rfind(",")
            last_dot = cleaned.rfind(".")
            if last_comma > last_dot:
                # 1.250,50 EUR -> dot is thousand, comma is decimal
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                # 1,250.50 USD -> comma is thousand, dot is decimal
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned and "." not in cleaned:
            parts = cleaned.split(",")
            if len(parts) > 2:
                # e.g. 1,000,000
                cleaned = cleaned.replace(",", "")
            elif len(parts) == 2:
                # e.g. 12,50 (len=2) or 50,000 (len=3)
                if len(parts[1]) == 3 and not has_eur:
                    cleaned = cleaned.replace(",", "")
                else:
                    cleaned = cleaned.replace(",", ".")
        elif "." in cleaned and "," not in cleaned:
            parts = cleaned.split(".")
            if len(parts) > 2:
                # e.g. 1.000.000 -> thousand separators
                cleaned = cleaned.replace(".", "")
            elif len(parts) == 2:
                # e.g. 50.000 VND or 50.000 (3 digits ending)
                if len(parts[1]) == 3 and (has_vnd or has_eur or len(parts[0]) <= 3):
                    cleaned = cleaned.replace(".", "")

        try:
            val = float(cleaned)
        except ValueError:
            raise ValueError(f"Unable to parse amount: '{amount_str}'")

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

    @staticmethod
    def _build_fingerprint(
        account_id: Optional[int],
        date_str: Optional[str],
        amount_minor: int,
        tx_type: str,
        payee: str,
        desc: str = ""
    ) -> Tuple:
        """
        Creates a scoped deduplication fingerprint (AUD-004C).
        Avoids false duplicates between different payees or distinct descriptions on the same date/amount,
        while seamlessly matching records where payee or description is used as the primary identifier.
        """
        effective_merchant = (normalize_merchant_name(payee) or normalize_merchant_name(desc) or "").lower().strip()
        effective_desc = re.sub(r'\s+', ' ', (desc or payee or "").lower().strip())
        return (account_id, date_str, amount_minor, tx_type, effective_merchant, effective_desc)

    @classmethod
    def _parse_csv_row(
        cls,
        row: List[str],
        headers: List[str],
        indices: Dict[str, Optional[int]],
        existing_fingerprints: set,
        account_id: Optional[int],
        date_format: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Unified parser for a single CSV row.
        Guarantees identical normalization between preview_csv and commit_import.
        """
        errors: List[str] = []

        # 1. Date parsing
        idx_date = indices.get("date")
        raw_date = row[idx_date].strip() if idx_date is not None and idx_date < len(row) else ""
        parsed_date = None
        try:
            parsed_date = cls.parse_date(raw_date, date_format=date_format)
            if not parsed_date and raw_date:
                errors.append(f"Invalid date: '{raw_date}'")
            elif not raw_date:
                errors.append("Missing date")
        except ValueError as ve:
            errors.append(str(ve))

        # 2. Amount and Type
        idx_amt = indices.get("amount")
        idx_debit = indices.get("debit")
        idx_credit = indices.get("credit")
        amount = 0.0
        tx_type = "expense"

        try:
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
            elif idx_amt is not None and idx_amt < len(row) and row[idx_amt].strip():
                amount, tx_type = cls.parse_amount(row[idx_amt])
            else:
                errors.append("Missing amount value")
        except ValueError as ve:
            errors.append(str(ve))

        amount_minor = int(round(amount * 100))
        if amount_minor <= 0 and not errors:
            errors.append("Amount must be strictly greater than zero")

        # 3. Payee and Description
        idx_payee = indices.get("payee")
        idx_desc = indices.get("description")
        raw_payee = row[idx_payee].strip() if idx_payee is not None and idx_payee < len(row) else ""
        raw_desc = row[idx_desc].strip() if idx_desc is not None and idx_desc < len(row) else ""
        payee = raw_payee or raw_desc or "Bank Transaction"
        desc = raw_desc or payee

        # 4. Fingerprint and Duplicate status
        fp = cls._build_fingerprint(account_id, parsed_date, amount_minor, tx_type, payee, desc)
        is_duplicate = bool(parsed_date and amount_minor > 0 and fp in existing_fingerprints)
        is_valid = len(errors) == 0

        return {
            "date": parsed_date,
            "raw_date": raw_date,
            "amount": amount,
            "amount_minor": amount_minor,
            "transaction_type": tx_type,
            "payee": payee,
            "description": desc,
            "fingerprint": fp,
            "is_duplicate": is_duplicate,
            "is_valid": is_valid,
            "errors": errors
        }

    @classmethod
    def preview_csv(
        cls,
        csv_content: str,
        mapping: Optional[Dict[str, str]] = None,
        account_id: Optional[int] = None,
        date_format: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Parses CSV, suggests column mapping if missing, normalizes fields,
        and identifies duplicate transactions against the target account.
        Uses working_fingerprints to detect in-file duplicates during preview (AUD-004A).
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

        # Build existing transaction fingerprints for duplicate detection
        existing_fingerprints = set()
        if account_id:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT transaction_date, amount_minor, transaction_type, merchant_name, description
                    FROM active_transactions WHERE account_id = ?
                    """,
                    (account_id,)
                )
                for r in cur.fetchall():
                    fp = cls._build_fingerprint(
                        account_id,
                        r["transaction_date"],
                        r["amount_minor"],
                        r["transaction_type"],
                        r["merchant_name"] or "",
                        r["description"] or ""
                    )
                    existing_fingerprints.add(fp)

        # Working set for in-file duplicate detection (AUD-004A)
        working_fingerprints = set(existing_fingerprints)

        def get_col_idx(col_name: Optional[str]) -> Optional[int]:
            if not col_name:
                return None
            try:
                return headers.index(col_name)
            except ValueError:
                return None

        indices = {
            "date": get_col_idx(active_mapping.get("date")),
            "amount": get_col_idx(active_mapping.get("amount")),
            "debit": get_col_idx(active_mapping.get("debit")),
            "credit": get_col_idx(active_mapping.get("credit")),
            "payee": get_col_idx(active_mapping.get("payee")),
            "description": get_col_idx(active_mapping.get("description")),
            "category": get_col_idx(active_mapping.get("category"))
        }

        preview_rows = []
        duplicate_count = 0
        valid_count = 0
        invalid_count = 0

        for row_idx, row in enumerate(data_rows):
            parsed = cls._parse_csv_row(row, headers, indices, working_fingerprints, account_id, date_format=date_format)
            if not parsed["is_valid"]:
                invalid_count += 1
            elif parsed["is_duplicate"]:
                duplicate_count += 1
            else:
                valid_count += 1
                if parsed["fingerprint"]:
                    working_fingerprints.add(parsed["fingerprint"])

            preview_rows.append({
                "row_index": row_idx,
                "date": parsed["date"],
                "raw_date": parsed["raw_date"],
                "amount": parsed["amount"],
                "amount_minor": parsed["amount_minor"],
                "transaction_type": parsed["transaction_type"],
                "payee": parsed["payee"],
                "description": parsed["description"],
                "category_suggestion": None,
                "is_duplicate": parsed["is_duplicate"],
                "is_valid": parsed["is_valid"],
                "errors": parsed["errors"]
            })

        return {
            "headers": headers,
            "mapping": active_mapping,
            "preview_rows": preview_rows[:100],
            "total_rows": len(data_rows),
            "duplicate_count": duplicate_count,
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "date_format": date_format or "auto"
        }

    @classmethod
    def commit_import(
        cls,
        csv_content: str,
        mapping: Dict[str, str],
        account_id: int,
        deduplicate: bool = True,
        date_format: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Parses and inserts transactions atomically using unified _parse_csv_row logic.
        Auto-categorizes known payees via MerchantService and tags uncertain ones with needs_review = 1.
        """
        delimiter = cls._detect_delimiter(csv_content)
        reader = csv.reader(io.StringIO(csv_content.strip()), delimiter=delimiter)
        raw_rows = [row for row in reader if row and any(cell.strip() for cell in row)]

        if not raw_rows:
            raise ValueError("No valid rows found in CSV.")

        headers = [h.strip() for h in raw_rows[0]]
        data_rows = raw_rows[1:]

        def get_col_idx(col_name: Optional[str]) -> Optional[int]:
            if not col_name:
                return None
            try:
                return headers.index(col_name)
            except ValueError:
                return None

        indices = {
            "date": get_col_idx(mapping.get("date")),
            "amount": get_col_idx(mapping.get("amount")),
            "debit": get_col_idx(mapping.get("debit")),
            "credit": get_col_idx(mapping.get("credit")),
            "payee": get_col_idx(mapping.get("payee")),
            "description": get_col_idx(mapping.get("description")),
            "category": get_col_idx(mapping.get("category"))
        }

        existing_fingerprints = set()
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT transaction_date, amount_minor, transaction_type, merchant_name, description
                FROM active_transactions WHERE account_id = ?
                """,
                (account_id,)
            )
            for r in cur.fetchall():
                fp = cls._build_fingerprint(
                    account_id,
                    r["transaction_date"],
                    r["amount_minor"],
                    r["transaction_type"],
                    r["merchant_name"] or "",
                    r["description"] or ""
                )
                existing_fingerprints.add(fp)

            # Load default category for unassigned
            cur.execute("SELECT id FROM categories WHERE type = 'expense' ORDER BY id ASC LIMIT 1")
            default_cat_row = cur.fetchone()
            fallback_category_id = default_cat_row["id"] if default_cat_row else 1

            now_str = datetime.now().isoformat()
            imported_count = 0
            skipped_count = 0
            invalid_count = 0

            for row in data_rows:
                parsed = cls._parse_csv_row(row, headers, indices, existing_fingerprints, account_id, date_format=date_format)

                if not parsed["is_valid"]:
                    invalid_count += 1
                    continue

                if deduplicate and parsed["is_duplicate"]:
                    skipped_count += 1
                    continue

                payee = parsed["payee"]
                desc = parsed["description"]
                parsed_date = parsed["date"]
                amount_minor = parsed["amount_minor"]
                tx_type = parsed["transaction_type"]

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

                existing_fingerprints.add(parsed["fingerprint"])
                imported_count += 1

            conn.commit()

        return {
            "success": True,
            "imported_count": imported_count,
            "skipped_duplicates": skipped_count,
            "invalid_count": invalid_count,
            "total_processed": len(data_rows)
        }
