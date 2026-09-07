import pytest
from app.backend.capture.parser import parse_quick_capture

def test_parse_simple_expense_with_magnitude():
    res = parse_quick_capture("85k grab", reference_date="2026-03-01")
    assert res.amount == 85000.0
    assert res.transaction_type == "expense"
    assert res.merchant_raw == "grab"
    assert res.date_str == "2026-03-01"
    assert not res.parse_errors

def test_parse_income_with_plus_and_tr():
    res = parse_quick_capture("+15tr salary", reference_date="2026-03-01")
    assert res.amount == 15000000.0
    assert res.transaction_type == "income"
    assert res.merchant_raw == "salary"
    assert res.date_str == "2026-03-01"
    assert not res.parse_errors

def test_parse_income_keyword_detection():
    res = parse_quick_capture("10m lương công ty", reference_date="2026-03-01")
    assert res.amount == 10000000.0
    assert res.transaction_type == "income"
    assert res.merchant_raw == "lương công ty"
    assert not res.parse_errors

def test_parse_decimal_and_currency_symbol():
    res = parse_quick_capture("$25.50 taxi lunch", reference_date="2026-03-01")
    assert res.amount == 25.50
    assert res.currency == "USD"
    assert res.transaction_type == "expense"
    assert res.merchant_raw == "taxi lunch"
    assert not res.parse_errors

def test_parse_account_and_category_hints():
    res = parse_quick_capture("50k cafe highland @cash #dining", reference_date="2026-03-01")
    assert res.amount == 50000.0
    assert res.account_hint == "cash"
    assert res.category_hint == "dining"
    assert res.merchant_raw == "cafe highland"
    assert not res.parse_errors

def test_parse_yesterday_date():
    res = parse_quick_capture("120k hotpot yesterday", reference_date="2026-03-05")
    assert res.amount == 120000.0
    assert res.date_str == "2026-03-04"
    assert res.merchant_raw == "hotpot"

def test_parse_explicit_date_dm():
    res = parse_quick_capture("300k supermarket 15/03", reference_date="2026-01-01")
    assert res.amount == 300000.0
    assert res.date_str == "2026-03-15"
    assert res.merchant_raw == "supermarket"

def test_parse_vietnamese_magnitudes():
    res_b = parse_quick_capture("2.5 tỷ condo", reference_date="2026-03-01")
    assert res_b.amount == 2500000000.0
    assert res_b.merchant_raw == "condo"

    res_tr = parse_quick_capture("1.5tr shoes", reference_date="2026-03-01")
    assert res_tr.amount == 1500000.0
    assert res_tr.merchant_raw == "shoes"

def test_parse_empty_or_invalid():
    res_empty = parse_quick_capture("")
    assert "Input is empty" in res_empty.parse_errors

    res_no_amt = parse_quick_capture("just a plain text")
    assert "No valid amount detected." in res_no_amt.parse_errors
