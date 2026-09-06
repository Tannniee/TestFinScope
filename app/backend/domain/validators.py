import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Union, Optional
from app.backend.domain.currencies import ACTIVE_ISO_4217_CODES, is_valid_currency, CURRENCIES
from app.backend.domain.money import major_to_minor

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Exported for backward compatibility; now encompasses all active ISO 4217 currencies
SUPPORTED_CURRENCIES = ACTIVE_ISO_4217_CODES

VALID_TRANSACTION_TYPES = {"income", "expense", "transfer", "refund", "adjustment"}
VALID_RECURRING_FREQUENCIES = {"daily", "weekly", "biweekly", "monthly", "quarterly", "yearly"}
VALID_RECURRING_TRANSACTION_TYPES = {"expense", "income"}


def money_to_minor(
    value: Union[int, float, str, Decimal],
    *,
    allow_negative: bool = False,
    scale: int = 2,
    currency: Optional[str] = None
) -> int:
    """
    Central Decimal-based money converter (FSC-M17).
    Rejects non-finite (NaN, inf) values and enforces ROUND_HALF_UP.
    """
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Amount must be a valid finite number.")

    if not dec.is_finite():
        raise ValueError("Amount must be finite.")

    if not allow_negative and dec <= 0:
        raise ValueError("Amount must be greater than zero.")

    if currency:
        info = CURRENCIES.get(currency.upper())
        effective_scale = info.minor_unit if info else scale
    else:
        effective_scale = scale

    factor = Decimal(10) ** effective_scale
    return int((dec * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def validate_budget_amount(
    amount: Union[int, float, str, Decimal],
    currency: Optional[str] = None
) -> int:
    """Validates that budget amount is strictly positive and converts to minor units."""
    return validate_positive_amount(amount, "Budget amount", currency=currency)


def validate_positive_amount(
    amount: Union[int, float, str, Decimal],
    field_name: str = "Transaction amount",
    currency: Optional[str] = None
) -> int:
    """
    Validates that amount is positive (> 0) and returns integer minor units.
    Uses centralized money_to_minor for exact Decimal arithmetic and finite validation (FSC-M17).
    """
    try:
        return money_to_minor(amount, allow_negative=False, currency=currency)
    except ValueError as e:
        if "greater than zero" in str(e):
            raise ValueError(f"{field_name} must be greater than zero.")
        raise ValueError(f"{field_name} must be a valid number.")


def validate_iso_date(date_str: str, field_name: str = "Date") -> str:
    """
    Validates that date_str is a valid ISO date YYYY-MM-DD.
    """
    if not date_str or not isinstance(date_str, str):
        raise ValueError(f"Invalid {field_name}: date string is required.")

    clean_str = date_str.strip()
    try:
        parsed = datetime.strptime(clean_str, "%Y-%m-%d")
        return parsed.strftime("%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid {field_name} format: '{clean_str}'. Expected YYYY-MM-DD.")


def validate_transaction_type(tx_type: str) -> str:
    """
    Validates that tx_type is one of the supported domain transaction types.
    """
    if not tx_type or not isinstance(tx_type, str):
        raise ValueError("Transaction type is required.")

    normalized = tx_type.strip().lower()
    if normalized not in VALID_TRANSACTION_TYPES:
        raise ValueError(f"Invalid transaction type: '{tx_type}'. Must be one of: {', '.join(sorted(VALID_TRANSACTION_TYPES))}")

    return normalized


def validate_currency_code(currency: str, check_supported: bool = True) -> str:
    """
    Validates that currency is an ISO 4217 3-letter uppercase code.
    If check_supported is True, validates against active ISO 4217 currencies.
    """
    if not currency or not isinstance(currency, str):
        raise ValueError("Currency code is required.")

    code = currency.strip().upper()
    if not CURRENCY_RE.fullmatch(code):
        raise ValueError(f"Invalid currency code: '{currency}'. Must be 3 uppercase letters (e.g. USD).")

    if check_supported and not is_valid_currency(code):
        raise ValueError(f"Unsupported currency: '{code}'.")

    return code


def validate_hex_color(color: str) -> str:
    """
    Validates that color is a 6-digit hex color code (#RRGGBB).
    """
    if not color or not isinstance(color, str):
        raise ValueError("Category colour is required.")

    clean_color = color.strip()
    if not HEX_COLOR_RE.fullmatch(clean_color):
        raise ValueError(f"Invalid category colour. Expected format: #RRGGBB")

    return clean_color


def validate_recurring_frequency(frequency: str) -> str:
    """
    Validates that recurring frequency is in the allowed set.
    """
    if not frequency or not isinstance(frequency, str):
        raise ValueError("Recurring frequency is required.")

    freq = frequency.strip().lower()
    if freq not in VALID_RECURRING_FREQUENCIES:
        raise ValueError(f"Invalid recurring frequency: '{frequency}'. Must be one of: {', '.join(sorted(VALID_RECURRING_FREQUENCIES))}")

    return freq


def validate_recurring_transaction_type(tx_type: str) -> str:
    """
    Validates that recurring transaction type is strictly expense or income (FSC-M12).
    """
    if not tx_type or not isinstance(tx_type, str):
        raise ValueError("Recurring transaction type is required.")

    norm = tx_type.strip().lower()
    if norm not in VALID_RECURRING_TRANSACTION_TYPES:
        raise ValueError(f"Invalid recurring transaction type: '{tx_type}'. Must be 'expense' or 'income'.")

    return norm


def validate_month(month: str, field_name: str = "Month") -> str:
    """
    Strict YYYY-MM period validator (FSC-M19).
    Rejects malformed strings instead of silent fallback.
    """
    if not month or not isinstance(month, str):
        raise ValueError(f"{field_name} string is required.")

    clean_m = month.strip()
    if not MONTH_RE.fullmatch(clean_m):
        raise ValueError(f"Invalid {field_name} format: '{month}'. Expected YYYY-MM.")

    return clean_m


def validate_category_for_transaction(
    conn,
    category_id: Optional[int],
    tx_type: str
) -> Optional[int]:
    """
    Validates semantic compatibility between transaction type and category type (FSC-H02).
    Enforces that expense requires expense category, income requires income category,
    refund requires expense category, and archived categories cannot be newly assigned.
    """
    if category_id is None:
        return None

    cur = conn.cursor()
    cur.execute("SELECT id, type, is_archived FROM categories WHERE id = ?", (category_id,))
    row = cur.fetchone()

    if not row:
        raise ValueError(f"Category {category_id} does not exist.")

    expected = "expense" if tx_type == "refund" else tx_type
    cat_type = row["type"]

    if expected in ("expense", "income") and cat_type != expected:
        raise ValueError(f"{tx_type} transactions require a {expected} category (got '{cat_type}').")

    if row["is_archived"]:
        raise ValueError("Archived categories cannot be assigned to new transactions.")

    return category_id


def validate_budget_category(conn, category_id: int) -> int:
    """
    Validates that a budget is assigned to an existing, active, expense category (FSC-M18).
    """
    cur = conn.cursor()
    cur.execute("SELECT id, type, is_archived FROM categories WHERE id = ?", (category_id,))
    row = cur.fetchone()

    if not row:
        raise ValueError(f"Category {category_id} does not exist.")

    if row["type"] != "expense":
        raise ValueError(f"Budget categories must be expense categories, not '{row['type']}'.")

    if row["is_archived"]:
        raise ValueError("Archived categories cannot have active budgets.")

    return category_id
