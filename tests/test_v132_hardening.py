import pytest
from decimal import Decimal
from unittest.mock import patch

from app.backend.capture.service import QuickCaptureService
from app.backend.capture.parser import parse_quick_capture
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.services.analytics_service import AnalyticsService
from app.backend.services.merchant_service import MerchantService
from app.backend.database.connection import get_db_connection
from app.backend.database.migrations_runner import migration_012_confidence_normalization

# ---------------------------------------------------------------------------
# 1. Quick Capture Preview-to-Commit Hash Integrity & Tamper Rejection (P0-01, P0-02, P0-03, P0-04)
# ---------------------------------------------------------------------------

def test_qc_mandatory_hash_and_tamper_rejection(isolated_db):
    acc_id = AccountRepository.create("Cash Wallet", "cash", currency="USD")
    cat1 = CategoryRepository.create("HardeningGroceries", "expense")
    cat2 = CategoryRepository.create("HardeningEntertainment", "expense")

    preview = QuickCaptureService.preview("45.00 Supermarket #HardeningGroceries @Cash", default_account_id=acc_id)
    assert preview.can_commit is True
    valid_hash = preview.enrichment.preview_hash
    assert valid_hash != ""

    # Missing preview_hash rejected
    with pytest.raises(ValueError, match="preview_hash is required"):
        QuickCaptureService.commit({
            "raw_text": "45.00 Supermarket #HardeningGroceries @Cash",
            "account_id": acc_id
        })

    # Tampered hash rejected
    with pytest.raises(ValueError, match="Preview hash mismatch"):
        QuickCaptureService.commit({
            "raw_text": "45.00 Supermarket #HardeningGroceries @Cash",
            "account_id": acc_id,
            "preview_hash": "bad_hash_99999"
        })

    # Tampered amount rejected
    with pytest.raises(ValueError, match="Payload amount differs from verified preview"):
        QuickCaptureService.commit({
            "raw_text": "45.00 Supermarket #HardeningGroceries @Cash",
            "account_id": acc_id,
            "amount": 99.00,
            "preview_hash": valid_hash
        })

    # Tampered category rejected
    with pytest.raises(ValueError, match="Payload category differs from verified preview"):
        QuickCaptureService.commit({
            "raw_text": "45.00 Supermarket #HardeningGroceries @Cash",
            "account_id": acc_id,
            "category_id": cat2,
            "preview_hash": valid_hash
        })

    # Legitimate commit succeeds and preserves preview provenance (P0-04)
    res = QuickCaptureService.commit({
        "raw_text": "45.00 Supermarket #HardeningGroceries @Cash",
        "account_id": acc_id,
        "preview_hash": valid_hash
    })
    assert res["success"] is True
    tx = TransactionRepository.get_by_id(res["transaction_id"])
    assert tx["amount"] == 45.0
    assert tx["category_id"] == cat1
    assert tx["category_source"] == "explicit"
    assert tx["category_confidence"] == 1.0


def test_qc_ambiguous_hints_block_commit(isolated_db):
    # Setup multiple accounts matching "Bank"
    AccountRepository.create("Bank Main Checking", "checking", currency="USD")
    AccountRepository.create("Bank High Yield Savings", "savings", currency="USD")

    # Setup multiple categories matching "Shop"
    CategoryRepository.create("Online Shopping", "expense")
    CategoryRepository.create("Coffee Shop", "expense")

    # Ambiguous account hint
    preview_acc = QuickCaptureService.preview("20 lunch @Bank")
    assert preview_acc.can_commit is False
    assert any("Ambiguous account" in err for err in preview_acc.enrichment.validation_errors)

    # Ambiguous category hint
    preview_cat = QuickCaptureService.preview("20 lunch #Shop")
    assert preview_cat.can_commit is False
    assert any("Ambiguous category" in err for err in preview_cat.enrichment.validation_errors)


# ---------------------------------------------------------------------------
# 2. Authoritative Merchant Learning Boundary (P0-05)
# ---------------------------------------------------------------------------

def test_merchant_learning_boundary_infer_does_not_train(isolated_db):
    acc_id = AccountRepository.create("Main", "checking", currency="USD")
    cat_id = CategoryRepository.create("Dining", "expense")

    # Create transaction with inferred / fallback category source
    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 30.0,
        "merchant_name": "Mysterious Cafe",
        "transaction_type": "expense",
        "transaction_date": "2026-09-01",
        "category_source": "rules_keyword",
        "essentiality": "unknown",
        "essentiality_source": "fallback"
    })
    assert tx_id > 0

    with get_db_connection() as conn:
        row = conn.execute("SELECT default_category_id, default_essentiality FROM merchants WHERE name = 'Mysterious Cafe'").fetchone()
        assert row is not None
        # Must create bare identity WITHOUT setting default_category_id (P0-05)
        assert row["default_category_id"] is None
        assert row["default_essentiality"] == "unknown"


def test_merchant_learning_boundary_authoritative_trains(isolated_db):
    acc_id = AccountRepository.create("Main", "checking", currency="USD")
    cat_id = CategoryRepository.create("AuthoritativeGroceries", "expense")

    # Create transaction with authoritative source (explicit or manual)
    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 60.0,
        "merchant_name": "Target Store",
        "transaction_type": "expense",
        "transaction_date": "2026-09-01",
        "category_source": "explicit",
        "essentiality": "essential",
        "essentiality_source": "explicit"
    })
    assert tx_id > 0

    with get_db_connection() as conn:
        row = conn.execute("SELECT default_category_id, default_essentiality FROM merchants WHERE name = 'Target Store'").fetchone()
        assert row is not None
        assert row["default_category_id"] == cat_id
        assert row["default_essentiality"] == "essential"


# ---------------------------------------------------------------------------
# 3. Review Queue Category-Only Resolve & Validation (P1-01, P1-02)
# ---------------------------------------------------------------------------

def test_resolve_review_validates_category_type(isolated_db):
    acc_id = AccountRepository.create("Main", "checking", currency="USD")
    exp_cat = CategoryRepository.create("Dining", "expense")
    inc_cat = CategoryRepository.create("Salary", "income")

    # Create expense transaction needing review
    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": exp_cat,
        "amount": 25.0,
        "merchant_name": "Corner Bakery",
        "transaction_type": "expense",
        "transaction_date": "2026-09-01",
        "needs_review": 1,
        "review_reason": "low_confidence_suggestion"
    })

    # Attempt to resolve review with an income category should fail server-side (P1-01)
    with pytest.raises(ValueError, match="expense transactions require a expense category"):
        TransactionRepository.resolve_review(tx_id, inc_cat)


def test_resolve_review_category_only_preserves_unknown_essentiality(isolated_db):
    acc_id = AccountRepository.create("Main", "checking", currency="USD")
    exp_cat1 = CategoryRepository.create("Dining", "expense")
    exp_cat2 = CategoryRepository.create("Groceries", "expense")

    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": exp_cat1,
        "amount": 40.0,
        "merchant_name": "Trader Joe",
        "transaction_type": "expense",
        "transaction_date": "2026-09-01",
        "essentiality": "unknown",
        "essentiality_source": "fallback",
        "needs_review": 1,
        "review_reason": "uncategorized"
    })

    # Resolve category only (no essentiality provided)
    TransactionRepository.resolve_review(tx_id, exp_cat2)

    tx = TransactionRepository.get_by_id(tx_id)
    assert tx["category_id"] == exp_cat2
    assert tx["category_source"] == "review_confirmed"
    assert tx["category_confidence"] == 1.0
    assert tx["needs_review"] == 0

    # Essentiality remains unchanged and not falsely marked review_confirmed (P1-02)
    assert tx["essentiality"] == "unknown"
    assert tx["essentiality_source"] == "fallback"
    assert tx["essentiality_confidence"] == 0.0

    # Merchant should learn category, but NOT essentiality
    with get_db_connection() as conn:
        row = conn.execute("SELECT default_category_id, default_essentiality FROM merchants WHERE name = 'Trader Joe'").fetchone()
        assert row["default_category_id"] == exp_cat2
        assert row["default_essentiality"] == "unknown"


# ---------------------------------------------------------------------------
# 4. Offline Account Loading & Portfolio FX Completeness (P0-06, P1-06)
# ---------------------------------------------------------------------------

def test_account_repo_get_all_offline_zero_network(isolated_db):
    AccountRepository.create("USD Account", "checking", currency="USD")
    AccountRepository.create("EUR Account", "checking", currency="EUR")

    # Mock FxService.convert_minor to ensure network conversion is never invoked by get_all()
    with patch("app.backend.fx.service.FxService.convert_minor") as mock_convert:
        accounts = AccountRepository.get_all()
        assert len(accounts) == 2
        mock_convert.assert_not_called()


def test_portfolio_fx_completeness_disclosure(isolated_db):
    acc_id = AccountRepository.create("EUR Account", "checking", currency="EUR")
    cat_id = CategoryRepository.create("Tech", "expense")

    # Create transaction in foreign currency without cached rate to trigger pending FX
    TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 100.0,
        "original_currency": "EUR",
        "currency": "EUR",
        "merchant_name": "Software GmbH",
        "transaction_type": "expense",
        "transaction_date": "2026-09-02"
    })

    # Summary without account_id (portfolio-wide) should include fx_completeness
    summary = AnalyticsService.get_month_summary("2026-09", account_id=None)
    assert "fx_completeness" in summary
    completeness = summary["fx_completeness"]
    assert completeness["is_complete"] is False
    assert completeness["pending_valuations"] >= 1
    assert completeness["foreign_transactions"] >= 1


# ---------------------------------------------------------------------------
# 5. Currency Token Parsing: 3-Decimal & 0-Decimal Currencies (P1-05)
# ---------------------------------------------------------------------------

def test_parser_three_decimal_and_zero_decimal_currencies():
    # 3-decimal currencies: KWD, BHD, OMR, TND
    p1 = parse_quick_capture("1.234 KWD dining")
    assert p1.amount == 1.234
    assert p1.currency == "KWD"

    p2 = parse_quick_capture("1,234.567 BHD electronics")
    assert p2.amount == 1234.567
    assert p2.currency == "BHD"

    # 0-decimal currencies: VND, JPY
    p3 = parse_quick_capture("100.000 VND coffee")
    assert p3.amount == 100000.0
    assert p3.currency == "VND"

    p4 = parse_quick_capture("100,000 VND coffee")
    assert p4.amount == 100000.0
    assert p4.currency == "VND"

    # Standard 2-decimal currencies: USD, EUR
    p5 = parse_quick_capture("12.34 USD groceries")
    assert p5.amount == 12.34
    assert p5.currency == "USD"


# ---------------------------------------------------------------------------
# 6. Migration 012: Confidence Normalization (P1-07)
# ---------------------------------------------------------------------------

def test_migration_012_normalizes_legacy_confidence(isolated_db):
    acc_id = AccountRepository.create("Migrate Wallet", "cash", currency="USD")
    with get_db_connection() as conn:
        # Insert legacy rows with >1.0 confidence (e.g. 85.0 and 100.0)
        conn.execute("""
            INSERT INTO transactions (
                account_id, amount_minor, base_currency, original_currency,
                transaction_type, transaction_date, capture_method,
                category_confidence, essentiality_confidence
            ) VALUES (
                ?, 100000, 'USD', 'USD',
                'expense', '2026-09-01', 'quick_capture',
                85.0, 100.0
            )
        """, (acc_id,))
        conn.commit()

        # Run migration 012
        migration_012_confidence_normalization(conn)
        conn.commit()

        row = conn.execute("SELECT category_confidence, essentiality_confidence FROM transactions WHERE amount_minor = 100000").fetchone()
        assert row is not None
        assert abs(row["category_confidence"] - 0.85) < 1e-4
        assert abs(row["essentiality_confidence"] - 1.0) < 1e-4
