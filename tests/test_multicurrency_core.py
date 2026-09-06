"""
Unit tests for FinScope Multi-Currency Core (Phase 1).
Verifies:
1. ISO 4217 currency metadata and catalogue.
2. Decimal-based major_to_minor and minor_to_major without float drift.
3. Zero-decimal (VND, JPY, KRW), 2-decimal (USD, EUR, AUD), and 3-decimal (KWD, BHD) currencies.
4. Money value object arithmetic, formatting, and cross-currency protection.
5. Conversion helper exactness and rounding.
"""

import pytest
from decimal import Decimal
from app.backend.domain.currencies import get_currency_meta, is_valid_currency, ACTIVE_ISO_4217_CODES
from app.backend.domain.money import Money, major_to_minor, minor_to_major, format_money, convert_money
from app.backend.domain.validators import validate_currency_code, validate_positive_amount


def test_iso_currency_catalogue():
    """Verifies that ISO catalogue correctly maps major currencies with their minor units."""
    vnd = get_currency_meta("VND")
    assert vnd.minor_unit == 0
    assert vnd.code == "VND"

    jpy = get_currency_meta("JPY")
    assert jpy.minor_unit == 0
    assert jpy.code == "JPY"

    usd = get_currency_meta("USD")
    assert usd.minor_unit == 2
    assert usd.code == "USD"

    kwd = get_currency_meta("KWD")
    assert kwd.minor_unit == 3
    assert kwd.code == "KWD"

    bhd = get_currency_meta("BHD")
    assert bhd.minor_unit == 3

    assert is_valid_currency("USD") is True
    assert is_valid_currency("VND") is True
    assert is_valid_currency("EUR") is True
    assert is_valid_currency("KWD") is True
    assert is_valid_currency("ZZZ") is False
    assert is_valid_currency("ABC") is False


def test_major_to_minor_exact_scaling():
    """Verifies that major amounts convert to integer minor units without float inaccuracy."""
    # 2 decimals (USD)
    assert major_to_minor("10.25", "USD") == 1025
    assert major_to_minor(10.25, "USD") == 1025
    assert major_to_minor(Decimal("10.25"), "USD") == 1025

    # 0 decimals (VND, JPY)
    assert major_to_minor("100000", "VND") == 100000
    assert major_to_minor(100000, "VND") == 100000
    assert major_to_minor("100,000", "VND") == 100000
    assert major_to_minor("123", "JPY") == 123

    # 3 decimals (KWD, BHD)
    assert major_to_minor("1.234", "KWD") == 1234
    assert major_to_minor("0.500", "BHD") == 500

    # Half-up rounding
    assert major_to_minor("10.255", "USD") == 1026
    assert major_to_minor("10.254", "USD") == 1025


def test_minor_to_major_exact_decimals():
    """Verifies that minor units convert back to Decimal major amounts."""
    assert minor_to_major(1025, "USD") == Decimal("10.25")
    assert minor_to_major(100000, "VND") == Decimal("100000")
    assert minor_to_major(1234, "KWD") == Decimal("1.234")


def test_money_value_object():
    """Verifies Money immutable value object properties and arithmetic."""
    m1 = Money.from_major("25.50", "USD")
    m2 = Money.from_major("10.25", "USD")
    m_vnd = Money.from_major("500000", "VND")

    assert m1.minor == 2550
    assert m1.currency == "USD"
    assert m1.to_decimal() == Decimal("25.50")
    assert m1.to_major_str() == "25.50"

    # Same currency addition/subtraction
    m_sum = m1 + m2
    assert m_sum.minor == 3575
    assert m_sum.currency == "USD"

    m_diff = m1 - m2
    assert m_diff.minor == 1525

    # Cross-currency protection
    with pytest.raises(ValueError, match="Cannot add Money with different currencies"):
        _ = m1 + m_vnd

    with pytest.raises(ValueError, match="Cannot compare Money with different currencies"):
        _ = m1 < m_vnd


def test_format_money():
    """Verifies formatting respects currency minor unit and symbol placement."""
    assert format_money(1025, "USD") == "$10.25"
    assert format_money(-1025, "USD") == "-$10.25"

    assert format_money(100000, "VND") == "100,000 ₫"
    assert format_money(123, "JPY") == "¥123"
    assert format_money(1234, "KWD") == "1.234 د.ك"

    # Without symbol
    assert format_money(100000, "VND", show_symbol=False) == "100,000 VND"
    assert format_money(1025, "USD", show_symbol=False) == "10.25 USD"


def test_convert_money():
    """Verifies exact cross-currency conversion."""
    # 10 USD to VND at 26,000 VND/USD
    # 10.00 USD * 26,000 = 260,000 VND (0 decimals -> 260000 minor)
    converted_vnd = convert_money(1000, "USD", "VND", "26000")
    assert converted_vnd == 260000

    # 260,000 VND to USD at 0.000038461538
    # 260000 * 0.000038461538 = 9.99999988 -> rounds to 10.00 USD (1000 minor)
    converted_usd = convert_money(260000, "VND", "USD", Decimal("1") / Decimal("26000"))
    assert converted_usd == 1000

    # Same currency returns exact amount unchanged
    assert convert_money(5000, "EUR", "EUR", "1.0") == 5000


def test_validation_helpers():
    """Verifies validate_currency_code and validate_positive_amount."""
    assert validate_currency_code("vnd") == "VND"
    assert validate_currency_code("USD") == "USD"
    assert validate_currency_code("kwd") == "KWD"

    with pytest.raises(ValueError, match="Invalid currency code"):
        validate_currency_code("US")

    with pytest.raises(ValueError, match="Unsupported currency"):
        validate_currency_code("ZZZ")

    # Positive amount validation with and without currency
    assert validate_positive_amount("50.00", currency="USD") == 5000
    assert validate_positive_amount("50000", currency="VND") == 50000
    assert validate_positive_amount("1.500", currency="KWD") == 1500
    assert validate_positive_amount(50.0) == 5000  # Default 2-decimal legacy fallback
