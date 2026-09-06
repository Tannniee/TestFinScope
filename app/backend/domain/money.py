"""
Exact Money Domain Value Object and Arithmetic Helpers for FinScope.
Uses Python Decimal for all conversions with explicit rounding to prevent floating-point inaccuracy.
Never assumes 2 decimal minor units.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Union
from app.backend.domain.currencies import get_currency_meta, CurrencyMeta


@dataclass(frozen=True)
class Money:
    """
    Exact monetary amount represented in integer minor units (e.g. cents, pence, dong).
    Immutable value object.
    """
    minor: int
    currency: str

    def __post_init__(self):
        if not isinstance(self.minor, int):
            raise TypeError(f"Money minor amount must be an integer, got {type(self.minor).__name__}")
        if not self.currency or not isinstance(self.currency, str):
            raise ValueError("Money currency must be a non-empty string.")
        # Normalize currency code uppercase
        object.__setattr__(self, "currency", self.currency.strip().upper())

    @classmethod
    def from_major(cls, value: Union[str, int, float, Decimal], currency: str) -> "Money":
        """Creates a Money instance from major units (e.g. '10.25' USD -> Money(1025, 'USD'))."""
        minor = major_to_minor(value, currency)
        return cls(minor=minor, currency=currency)

    @classmethod
    def zero(cls, currency: str) -> "Money":
        """Returns zero Money in the specified currency."""
        return cls(minor=0, currency=currency)

    @property
    def meta(self) -> CurrencyMeta:
        return get_currency_meta(self.currency)

    def to_decimal(self) -> Decimal:
        """Converts integer minor amount into Decimal major units."""
        return minor_to_major(self.minor, self.currency)

    def to_major_str(self) -> str:
        """Returns major amount formatted as string with exact decimals according to currency."""
        dec = self.to_decimal()
        decimals = self.meta.minor_unit
        if decimals == 0:
            return f"{int(dec)}"
        return f"{dec:.{decimals}f}"

    def format(self, show_symbol: bool = True) -> str:
        return format_money(self.minor, self.currency, show_symbol=show_symbol)

    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(f"Cannot add Money with different currencies: '{self.currency}' and '{other.currency}'. Convert first.")
        return Money(minor=self.minor + other.minor, currency=self.currency)

    def __sub__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(f"Cannot subtract Money with different currencies: '{self.currency}' and '{other.currency}'. Convert first.")
        return Money(minor=self.minor - other.minor, currency=self.currency)

    def __neg__(self) -> "Money":
        return Money(minor=-self.minor, currency=self.currency)

    def __lt__(self, other: "Money") -> bool:
        if not isinstance(other, Money) or self.currency != other.currency:
            raise ValueError(f"Cannot compare Money with different currencies: '{self.currency}' and '{getattr(other, 'currency', None)}'")
        return self.minor < other.minor

    def __le__(self, other: "Money") -> bool:
        if not isinstance(other, Money) or self.currency != other.currency:
            raise ValueError(f"Cannot compare Money with different currencies: '{self.currency}' and '{getattr(other, 'currency', None)}'")
        return self.minor <= other.minor

    def __gt__(self, other: "Money") -> bool:
        if not isinstance(other, Money) or self.currency != other.currency:
            raise ValueError(f"Cannot compare Money with different currencies: '{self.currency}' and '{getattr(other, 'currency', None)}'")
        return self.minor > other.minor

    def __ge__(self, other: "Money") -> bool:
        if not isinstance(other, Money) or self.currency != other.currency:
            raise ValueError(f"Cannot compare Money with different currencies: '{self.currency}' and '{getattr(other, 'currency', None)}'")
        return self.minor >= other.minor


def major_to_minor(value: Union[str, int, float, Decimal], currency: str) -> int:
    """
    Converts major monetary units into integer minor units using currency minor_unit exponent.
    Uses Decimal with ROUND_HALF_UP to ensure bit-exact financial precision.
    Examples:
      major_to_minor("10.25", "USD") -> 1025
      major_to_minor("100000", "VND") -> 100000
      major_to_minor("123", "JPY") -> 123
      major_to_minor("1.234", "KWD") -> 1234
    """
    meta = get_currency_meta(currency)
    scale = Decimal(10) ** meta.minor_unit

    try:
        amount = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid monetary amount: '{value}'") from exc

    minor = (amount * scale).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(minor)


def minor_to_major(minor: int, currency: str) -> Decimal:
    """
    Converts integer minor units into Decimal major units using currency minor_unit exponent.
    Examples:
      minor_to_major(1025, "USD") -> Decimal("10.25")
      minor_to_major(100000, "VND") -> Decimal("100000")
      minor_to_major(1234, "KWD") -> Decimal("1.234")
    """
    if not isinstance(minor, int):
        raise TypeError(f"minor must be an int, got {type(minor).__name__}")
    meta = get_currency_meta(currency)
    scale = Decimal(10) ** meta.minor_unit
    return Decimal(minor) / scale


def format_money(minor: int, currency: str, show_symbol: bool = True) -> str:
    """
    Standard canonical money formatter for FinScope.
    Correctly respects currency decimal exponent and locale digit grouping.
    """
    meta = get_currency_meta(currency)
    dec = minor_to_major(minor, currency)
    decimals = meta.minor_unit

    is_negative = dec < 0
    abs_dec = abs(dec)

    if decimals == 0:
        formatted_num = f"{int(abs_dec):,}"
    else:
        formatted_num = f"{abs_dec:,.{decimals}f}"

    prefix = "-" if is_negative else ""

    if not show_symbol:
        return f"{prefix}{formatted_num} {meta.code}"

    # Standard symbol placement
    symbol = meta.symbol or meta.code
    if symbol in ("$", "€", "£", "¥", "₩", "₹", "₱", "฿"):
        return f"{prefix}{symbol}{formatted_num}"
    else:
        return f"{prefix}{formatted_num} {symbol}"


def convert_money(
    amount_minor: int,
    from_currency: str,
    to_currency: str,
    rate_quote_per_base: Union[Decimal, str, float]
) -> int:
    """
    Converts amount_minor in from_currency to to_currency using rate:
    rate = 1 from_currency = rate to_currency.
    Uses exact Decimal arithmetic and rounds to target currency's minor units.
    """
    if from_currency.upper() == to_currency.upper():
        return amount_minor

    try:
        d_rate = Decimal(str(rate_quote_per_base).strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid FX rate: '{rate_quote_per_base}'") from exc

    if d_rate <= 0:
        raise ValueError(f"FX rate must be strictly positive, got {d_rate}")

    from_major = minor_to_major(amount_minor, from_currency)
    to_major = from_major * d_rate
    return major_to_minor(to_major, to_currency)
