"""
Deterministic Natural Language Quick Capture Parser (EBNF-compliant).
Parses expressions like:
  "85k grab" -> 85,000 VND / USD, merchant "Grab", expense
  "+15tr salary" -> 15,000,000, merchant "Salary", income
  "50k cafe @cash #food" -> amount 50,000, merchant "Cafe", account "cash", category "food"
  "120k dinner yesterday" -> amount 120,000, merchant "Dinner", date yesterday
"""

import re
from datetime import datetime, timedelta
from typing import Optional, Tuple, List
from app.backend.capture.models import QuickCaptureParseResult

INCOME_KEYWORDS = {
    "salary", "luong", "lương", "bonus", "thuong", "thưởng",
    "interest", "lai", "lãi", "dividend", "co tuc", "cổ tức",
    "freelance", "income", "thu nhap", "thu nhập"
}

MAGNITUDES = {
    "k": 1_000,
    "m": 1_000_000,
    "tr": 1_000_000,
    "trieu": 1_000_000,
    "triệu": 1_000_000,
    "b": 1_000_000_000,
    "ty": 1_000_000_000,
    "tỷ": 1_000_000_000,
}

CURRENCY_SYMBOLS = {
    "$": "USD",
    "₫": "VND",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
}

CURRENCY_WORDS = {
    "vnd", "usd", "eur", "gbp", "jpy", "aud", "cad", "sgd", "chf"
}

def parse_quick_capture(text: str, reference_date: Optional[str] = None) -> QuickCaptureParseResult:
    """
    Deterministically parses a single-line quick capture query into structured tokens.
    """
    raw_text = (text or "").strip()
    if not raw_text:
        return QuickCaptureParseResult(raw_text="", parse_errors=["Input is empty"])

    tokens = raw_text.split()
    remaining_tokens: List[str] = []
    errors: List[str] = []

    account_hint: Optional[str] = None
    category_hint: Optional[str] = None
    date_str: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    tx_type: Optional[str] = None

    # Reference today
    ref_dt = datetime.strptime(reference_date, "%Y-%m-%d") if reference_date else datetime.now()

    i = 0
    while i < len(tokens):
        token = tokens[i]

        # 1. Account hint: @account
        if token.startswith("@") and len(token) > 1:
            account_hint = token[1:].strip()
            i += 1
            continue

        # 2. Category hint: #category
        if token.startswith("#") and len(token) > 1:
            category_hint = token[1:].strip()
            i += 1
            continue

        # 3. Date expressions: today, yesterday, hom nay, hom qua, YYYY-MM-DD, DD/MM
        lower_token = token.lower()
        if lower_token in ("today", "homnay", "hôm nay"):
            date_str = ref_dt.strftime("%Y-%m-%d")
            i += 1
            continue
        if lower_token in ("yesterday", "homqua", "hôm qua"):
            date_str = (ref_dt - timedelta(days=1)).strftime("%Y-%m-%d")
            i += 1
            continue
        # Two-word date expressions check: "hom nay" / "hom qua"
        if i + 1 < len(tokens):
            two_word = f"{lower_token} {tokens[i+1].lower()}"
            if two_word in ("hom nay", "hôm nay"):
                date_str = ref_dt.strftime("%Y-%m-%d")
                i += 2
                continue
            if two_word in ("hom qua", "hôm qua"):
                date_str = (ref_dt - timedelta(days=1)).strftime("%Y-%m-%d")
                i += 2
                continue

        # ISO date check: 2026-03-01
        if re.match(r"^\d{4}-\d{2}-\d{2}$", token):
            try:
                datetime.strptime(token, "%Y-%m-%d")
                date_str = token
                i += 1
                continue
            except ValueError:
                pass

        # DD/MM check: e.g. 15/03 or 15/3 or 15/03/2026
        dm_match = re.match(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$", token)
        if dm_match:
            d = int(dm_match.group(1))
            m = int(dm_match.group(2))
            y = int(dm_match.group(3)) if dm_match.group(3) else ref_dt.year
            if y < 100:
                y += 2000
            try:
                dt = datetime(y, m, d)
                date_str = dt.strftime("%Y-%m-%d")
                i += 1
                continue
            except ValueError:
                pass

        # 4. Amount parsing
        parsed_amt, parsed_curr, parsed_type = _try_parse_amount_token(token)
        if parsed_amt is not None and amount is None:
            # Check if next token is a standalone magnitude token (e.g. "2.5 tỷ", "15 tr")
            if i + 1 < len(tokens):
                next_tok = tokens[i+1].lower()
                if next_tok in MAGNITUDES:
                    parsed_amt = round(parsed_amt * MAGNITUDES[next_tok], 4)
                    i += 1

            amount = parsed_amt
            if parsed_curr:
                currency = parsed_curr
            if parsed_type:
                tx_type = parsed_type

            # Look ahead for currency token if not yet set
            if currency is None and i + 1 < len(tokens):
                next_tok = tokens[i+1].lower()
                if next_tok in CURRENCY_WORDS:
                    currency = next_tok.upper()
                    i += 1
                elif next_tok in CURRENCY_SYMBOLS:
                    currency = CURRENCY_SYMBOLS[next_tok]
                    i += 1
            i += 1
            continue

        remaining_tokens.append(token)
        i += 1

    # If date was not given, default to today
    if not date_str:
        date_str = ref_dt.strftime("%Y-%m-%d")

    # Merchant description from remaining tokens
    merchant_raw = " ".join(remaining_tokens).strip() if remaining_tokens else ""

    # Determine transaction type if not explicitly set by sign
    if tx_type is None:
        # Check merchant words against known income keywords
        merchant_lower = merchant_raw.lower()
        words = re.split(r"[\s,.-]+", merchant_lower)
        if any(w in INCOME_KEYWORDS for w in words):
            tx_type = "income"
        else:
            tx_type = "expense"

    if amount is None:
        errors.append("No valid amount detected.")

    return QuickCaptureParseResult(
        raw_text=raw_text,
        amount=amount,
        currency=currency,
        transaction_type=tx_type,
        merchant_raw=merchant_raw or "Quick Expense",
        account_hint=account_hint,
        category_hint=category_hint,
        date_str=date_str,
        parser_version="qc_v1",
        parse_errors=errors
    )


def _try_parse_amount_token(tok: str) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    """
    Attempts to parse a token as an amount.
    Returns (amount, currency, tx_type).
    """
    token = tok.strip()
    if not token:
        return None, None, None

    explicit_type: Optional[str] = None
    if token.startswith("+"):
        explicit_type = "income"
        token = token[1:]
    elif token.startswith("-"):
        explicit_type = "expense"
        token = token[1:]

    if not token:
        return None, None, None

    detected_currency: Optional[str] = None

    # Prefix currency symbol: $50, ₫100k
    if token[0] in CURRENCY_SYMBOLS:
        detected_currency = CURRENCY_SYMBOLS[token[0]]
        token = token[1:]
    # Prefix currency code: USD50
    for c in ("USD", "VND", "EUR", "GBP", "JPY"):
        if token.upper().startswith(c) and len(token) > len(c) and (token[len(c)].isdigit() or token[len(c)] in ('.', ',')):
            detected_currency = c
            token = token[len(c):]
            break

    # Suffix currency symbol: 50$, 100₫
    if token and token[-1] in CURRENCY_SYMBOLS:
        detected_currency = CURRENCY_SYMBOLS[token[-1]]
        token = token[:-1]

    # Suffix currency code: 50usd, 100vnd
    for c in ("USD", "VND", "EUR", "GBP", "JPY", "AUD", "CAD", "SGD"):
        if token.upper().endswith(c) and len(token) > len(c) and token[-len(c)-1].isdigit():
            detected_currency = c
            token = token[:-len(c)]
            break

    # Check magnitude suffix: k, m, tr, trieu, triệu, b, ty, tỷ
    multiplier = 1.0
    token_lower = token.lower()
    for mag_str, mag_val in sorted(MAGNITUDES.items(), key=lambda x: -len(x[0])):
        if token_lower.endswith(mag_str):
            num_part = token[:-len(mag_str)]
            # If remaining is a valid number, we found magnitude
            if _is_number_like(num_part):
                multiplier = float(mag_val)
                token = num_part
                break

    # Parse numeric part
    # Handle European / Vietnamese number formats (e.g. 100.000 or 100,000 or 15.5)
    clean_num = _normalize_number_string(token)
    if clean_num is None:
        return None, None, None

    try:
        val = float(clean_num) * multiplier
        if val < 0:
            return None, None, None
        return round(val, 4), detected_currency, explicit_type
    except (ValueError, OverflowError):
        return None, None, None


def _is_number_like(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    # Replace dots and commas
    cleaned = s.replace(".", "").replace(",", "")
    return cleaned.isdigit()


def _normalize_number_string(s: str) -> Optional[str]:
    """
    Normalizes number string with dots or commas into standard float string.
    E.g.:
      "85" -> "85"
      "85.5" -> "85.5"
      "85,5" -> "85.5"
      "100.000" -> "100000" (if 3 digits after dot, standard VND thousand separator)
      "1,000.50" -> "1000.50"
      "1.000,50" -> "1000.50"
    """
    s = s.strip()
    if not s:
        return None

    # If both '.' and ',' present
    if "." in s and "," in s:
        last_dot = s.rfind(".")
        last_comma = s.rfind(",")
        if last_dot > last_comma:
            # 1,000.50 format
            s = s.replace(",", "")
        else:
            # 1.000,50 format
            s = s.replace(".", "").replace(",", ".")
        return s

    # Only comma
    if "," in s:
        parts = s.split(",")
        # If exactly 3 digits after comma and nothing else, e.g. "100,000"
        if len(parts) == 2 and len(parts[1]) == 3 and int(parts[1]) >= 0:
            # Ambiguous: could be 100,000 or 100.000. If magnitude is >= 100, usually thousands
            return parts[0] + parts[1]
        elif len(parts) > 2:
            return "".join(parts)
        else:
            return s.replace(",", ".")

    # Only dot
    if "." in s:
        parts = s.split(".")
        # If parts after dot are all 3 digits, e.g. "100.000" or "1.000.000"
        if len(parts) >= 2 and all(len(p) == 3 for p in parts[1:]):
            return "".join(parts)
        elif len(parts) == 2:
            # e.g. 85.5 or 12.34
            return s

    if s.isdigit():
        return s

    return None
