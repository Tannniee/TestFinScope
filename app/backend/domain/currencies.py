"""
ISO 4217 Currency Catalogue & Metadata for FinScope Multi-Currency Foundation.
Contains active ISO 4217 currency definitions with exact minor units (decimals),
numeric codes, names, and symbol definitions.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Set


@dataclass(frozen=True)
class CurrencyMeta:
    code: str
    numeric_code: str
    minor_unit: int
    name: str
    symbol: str = ""


# Canonical ISO 4217 Active Currency Catalogue
# minor_unit specifies decimal exponent (e.g. 2 -> 100 minor per major, 0 -> 1 minor per major, 3 -> 1000 minor per major)
_CURRENCIES_LIST = [
    # Zero minor unit (0 decimals)
    CurrencyMeta("VND", "704", 0, "Vietnamese Dong", "₫"),
    CurrencyMeta("JPY", "392", 0, "Japanese Yen", "¥"),
    CurrencyMeta("KRW", "410", 0, "South Korean Won", "₩"),
    CurrencyMeta("CLP", "152", 0, "Chilean Peso", "$"),
    CurrencyMeta("ISK", "352", 0, "Icelandic Króna", "kr"),
    CurrencyMeta("PYG", "600", 0, "Paraguayan Guaraní", "₲"),
    CurrencyMeta("RWF", "646", 0, "Rwandan Franc", "FRw"),
    CurrencyMeta("UGX", "800", 0, "Ugandan Shilling", "USh"),
    CurrencyMeta("VUV", "548", 0, "Vanuatu Vatu", "VT"),
    CurrencyMeta("BIF", "108", 0, "Burundian Franc", "FBu"),
    CurrencyMeta("DJF", "262", 0, "Djiboutian Franc", "Fdj"),
    CurrencyMeta("GNF", "324", 0, "Guinean Franc", "FG"),
    CurrencyMeta("KMF", "174", 0, "Comorian Franc", "CF"),
    CurrencyMeta("XOF", "952", 0, "West African CFA Franc", "CFA"),
    CurrencyMeta("XAF", "950", 0, "Central African CFA Franc", "FCFA"),
    CurrencyMeta("XPF", "953", 0, "CFP Franc", "₣"),

    # Three minor units (3 decimals)
    CurrencyMeta("BHD", "048", 3, "Bahraini Dinar", ".د.ب"),
    CurrencyMeta("IQD", "368", 3, "Iraqi Dinar", "ع.د"),
    CurrencyMeta("JOD", "400", 3, "Jordanian Dinar", "د.ا"),
    CurrencyMeta("KWD", "414", 3, "Kuwaiti Dinar", "د.ك"),
    CurrencyMeta("LYD", "434", 3, "Libyan Dinar", "ل.د"),
    CurrencyMeta("OMR", "512", 3, "Omani Rial", "ر.ع."),
    CurrencyMeta("TND", "788", 3, "Tunisian Dinar", "د.ت"),

    # Standard Two minor units (2 decimals)
    CurrencyMeta("USD", "840", 2, "United States Dollar", "$"),
    CurrencyMeta("EUR", "978", 2, "Euro", "€"),
    CurrencyMeta("GBP", "826", 2, "British Pound Sterling", "£"),
    CurrencyMeta("AUD", "036", 2, "Australian Dollar", "A$"),
    CurrencyMeta("CAD", "124", 2, "Canadian Dollar", "C$"),
    CurrencyMeta("CHF", "756", 2, "Swiss Franc", "CHF"),
    CurrencyMeta("CNY", "156", 2, "Chinese Yuan", "¥"),
    CurrencyMeta("SGD", "702", 2, "Singapore Dollar", "S$"),
    CurrencyMeta("HKD", "344", 2, "Hong Kong Dollar", "HK$"),
    CurrencyMeta("NZD", "554", 2, "New Zealand Dollar", "NZ$"),
    CurrencyMeta("SEK", "752", 2, "Swedish Krona", "kr"),
    CurrencyMeta("NOK", "578", 2, "Norwegian Krone", "kr"),
    CurrencyMeta("DKK", "208", 2, "Danish Krone", "kr"),
    CurrencyMeta("PLN", "985", 2, "Polish Zloty", "zł"),
    CurrencyMeta("CZK", "203", 2, "Czech Koruna", "Kč"),
    CurrencyMeta("HUF", "348", 2, "Hungarian Forint", "Ft"),
    CurrencyMeta("ILS", "376", 2, "Israeli New Shekel", "₪"),
    CurrencyMeta("INR", "356", 2, "Indian Rupee", "₹"),
    CurrencyMeta("BRL", "986", 2, "Brazilian Real", "R$"),
    CurrencyMeta("ZAR", "710", 2, "South African Rand", "R"),
    CurrencyMeta("MXN", "484", 2, "Mexican Peso", "$"),
    CurrencyMeta("TWD", "901", 2, "New Taiwan Dollar", "NT$"),
    CurrencyMeta("THB", "764", 2, "Thai Baht", "฿"),
    CurrencyMeta("MYR", "458", 2, "Malaysian Ringgit", "RM"),
    CurrencyMeta("IDR", "360", 2, "Indonesian Rupiah", "Rp"),
    CurrencyMeta("PHP", "608", 2, "Philippine Peso", "₱"),
    CurrencyMeta("AED", "784", 2, "United Arab Emirates Dirham", "د.إ"),
    CurrencyMeta("SAR", "682", 2, "Saudi Riyal", "ر.س"),
    CurrencyMeta("QAR", "634", 2, "Qatari Riyal", "ر.ق"),
    CurrencyMeta("TRY", "949", 2, "Turkish Lira", "₺"),
    CurrencyMeta("ARS", "032", 2, "Argentine Peso", "$"),
    CurrencyMeta("COP", "170", 2, "Colombian Peso", "$"),
    CurrencyMeta("PEN", "604", 2, "Peruvian Sol", "S/"),
    CurrencyMeta("EGP", "818", 2, "Egyptian Pound", "E£"),
    CurrencyMeta("PKR", "586", 2, "Pakistani Rupee", "₨"),
    CurrencyMeta("BDT", "050", 2, "Bangladeshi Taka", "৳"),
    CurrencyMeta("LKR", "144", 2, "Sri Lankan Rupee", "Rs"),
    CurrencyMeta("NGN", "566", 2, "Nigerian Naira", "₦"),
    CurrencyMeta("KES", "404", 2, "Kenyan Shilling", "KSh"),
    CurrencyMeta("GHS", "936", 2, "Ghanaian Cedi", "GH₵"),
    CurrencyMeta("MAD", "504", 2, "Moroccan Dirham", "MAD"),
    CurrencyMeta("RON", "946", 2, "Romanian Leu", "lei"),
    CurrencyMeta("BGN", "975", 2, "Bulgarian Lev", "лв"),
    CurrencyMeta("HRK", "191", 2, "Croatian Kuna", "kn"),
    CurrencyMeta("RSD", "941", 2, "Serbian Dinar", "дин."),
    CurrencyMeta("UAH", "980", 2, "Ukrainian Hryvnia", "₴"),
    CurrencyMeta("KZT", "398", 2, "Kazakhstani Tenge", "₸"),
    CurrencyMeta("AZN", "944", 2, "Azerbaijani Manat", "₼"),
    CurrencyMeta("GEL", "981", 2, "Georgian Lari", "₾"),
]

ISO_4217_CATALOGUE: Dict[str, CurrencyMeta] = {c.code: c for c in _CURRENCIES_LIST}
CURRENCIES: Dict[str, CurrencyMeta] = ISO_4217_CATALOGUE
ACTIVE_ISO_4217_CODES: Set[str] = set(ISO_4217_CATALOGUE.keys())


def get_currency_meta(currency_code: str) -> CurrencyMeta:
    """
    Retrieves metadata for an ISO 4217 currency code.
    If the 3-letter uppercase code is valid ISO format but uncatalogued,
    provides a standard 2-decimal fallback CurrencyMeta.
    """
    if not currency_code or not isinstance(currency_code, str):
        raise ValueError("Currency code must be a non-empty string.")
    
    code = currency_code.strip().upper()
    if code in ISO_4217_CATALOGUE:
        return ISO_4217_CATALOGUE[code]
    
    # Check general 3-letter ISO 4217 format
    if len(code) == 3 and code.isalpha():
        # Extensible default for rare/newer ISO 4217 currencies: 2 minor units
        return CurrencyMeta(code=code, numeric_code="000", minor_unit=2, name=f"Currency {code}", symbol=code)
    
    raise ValueError(f"Invalid ISO 4217 currency code: '{currency_code}'")


def is_valid_currency(currency_code: str) -> bool:
    """Checks if a currency code is a valid 3-letter uppercase active ISO 4217 code."""
    if not currency_code or not isinstance(currency_code, str):
        return False
    code = currency_code.strip().upper()
    return code in ACTIVE_ISO_4217_CODES
