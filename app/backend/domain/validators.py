import re
from datetime import datetime
from typing import Union

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

SUPPORTED_CURRENCIES = {"USD", "VND", "AUD", "EUR", "GBP", "JPY", "SGD", "CAD"}

VALID_TRANSACTION_TYPES = {"income", "expense", "transfer", "refund", "adjustment"}
VALID_RECURRING_FREQUENCIES = {"daily", "weekly", "biweekly", "monthly", "quarterly", "yearly"}


def validate_positive_amount(amount: Union[int, float], field_name: str = "Transaction amount") -> int:
    """
    Validates that amount is positive (> 0) and returns integer minor units (cents).
    """
    try:
        val = float(amount)
    except (ValueError, TypeError):
        raise ValueError(f"{field_name} must be a valid number.")

    if val <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")

    return int(round(val * 100))


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
    If check_supported is True, validates against FinScope supported currencies.
    """
    if not currency or not isinstance(currency, str):
        raise ValueError("Currency code is required.")

    code = currency.strip().upper()
    if not CURRENCY_RE.fullmatch(code):
        raise ValueError(f"Invalid currency code: '{currency}'. Must be 3 uppercase letters (e.g. USD).")

    if check_supported and code not in SUPPORTED_CURRENCIES:
        raise ValueError(f"Unsupported currency: '{code}'. Supported currencies: {', '.join(sorted(SUPPORTED_CURRENCIES))}")

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


def validate_budget_amount(amount: Union[int, float]) -> int:
    """
    Validates that a budget amount is positive (> 0) and returns minor units.
    """
    try:
        val = float(amount)
    except (ValueError, TypeError):
        raise ValueError("Budget amount must be a valid number.")

    if val <= 0:
        raise ValueError("Budget amount must be greater than zero.")

    return int(round(val * 100))
