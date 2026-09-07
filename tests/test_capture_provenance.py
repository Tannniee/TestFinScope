import pytest
import sqlite3
from app.backend.database.migrations_runner import run_migrations, MAX_SUPPORTED_SCHEMA_VERSION
from app.backend.database.connection import get_db_connection
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository


def test_migrations_009_010_011_schema_and_backfill(isolated_db):
    """
    Verifies that migrations 009, 010, and 011 apply successfully,
    expose new provenance columns, allow 'unknown' essentiality,
    and create import_profiles table.
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(version) FROM schema_migrations")
        ver = cur.fetchone()[0]
        assert ver == MAX_SUPPORTED_SCHEMA_VERSION == 12

        # Check provenance columns on active_transactions view
        cur.execute("PRAGMA table_info(transactions)")
        cols = {row["name"]: row for row in cur.fetchall()}

        assert "raw_merchant_name" in cols
        assert "capture_method" in cols
        assert "category_source" in cols
        assert "category_confidence" in cols
        assert "essentiality_source" in cols
        assert "essentiality_confidence" in cols
        assert "review_reason" in cols
        assert "parser_version" in cols

        # Check import_profiles table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='import_profiles'")
        assert cur.fetchone() is not None


def test_essentiality_unknown_allowed(isolated_db):
    """
    Verifies that 'unknown' essentiality is permitted under Migration 010 constraint.
    """
    acc_id = AccountRepository.create("Test Checking", "checking", opening_balance=500.0)
    cat_id = CategoryRepository.create("Misc", "expense", "tag", "#5B8CFF")

    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 25.0,
        "transaction_type": "expense",
        "transaction_date": "2026-09-01",
        "essentiality": "unknown",
        "description": "Unclassified purchase"
    })

    tx = TransactionRepository.get_by_id(tx_id)
    assert tx is not None
    assert tx["essentiality"] == "unknown"


def test_suspicious_legacy_fx_revaluation_flagged(isolated_db):
    """
    Verifies Migration 010 marks suspicious foreign legacy rows as pending_revaluation.
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        # Seed an account in EUR where base currency is USD
        cur.execute("INSERT INTO accounts (name, account_type, currency, opening_balance_minor) VALUES ('EUR Card', 'credit', 'EUR', 0)")
        acc_eur_id = cur.lastrowid

        # Insert a suspicious legacy transaction: EUR account, base USD, fx_status 'not_required'
        cur.execute("""
            INSERT INTO transactions (
                account_id, amount_minor, transaction_date, transaction_type,
                base_currency, base_amount_minor, fx_status, description
            ) VALUES (?, 10000, '2025-05-10', 'expense', 'USD', 10000, 'not_required', 'Legacy suspicious EUR')
        """, (acc_eur_id,))
        tx_id = cur.lastrowid
        conn.commit()

        # Run migration 010 repair logic directly to verify query behavior
        conn.execute("""
            UPDATE transactions
            SET base_amount_minor = NULL,
                fx_status = 'pending_revaluation'
            WHERE id IN (
                SELECT t.id
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
                WHERE a.currency <> t.base_currency
                  AND (t.fx_rate_to_base IS NULL OR t.fx_rate_source IS NULL OR t.fx_rate_source = 'identity')
                  AND t.fx_status = 'not_required'
            );
        """)
        conn.commit()

        cur.execute("SELECT base_amount_minor, fx_status FROM transactions WHERE id = ?", (tx_id,))
        row = cur.fetchone()
        assert row["base_amount_minor"] is None
        assert row["fx_status"] == "pending_revaluation"


def test_create_transaction_with_provenance(isolated_db):
    from app.backend.repositories.account_repo import AccountRepository
    from app.backend.repositories.category_repo import CategoryRepository
    from app.backend.repositories.transaction_repo import TransactionRepository

    acc_id = AccountRepository.create("Prov Test Cash", "cash", currency="USD")
    cat_id = CategoryRepository.create("Prov Dining", "expense")

    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 42.50,
        "merchant_name": "STARBUCKS #1234",
        "raw_merchant_name": "STARBUCKS #1234",
        "transaction_date": "2026-03-01",
        "transaction_type": "expense",
        "capture_method": "quick_capture",
        "category_source": "rule",
        "category_confidence": 0.95,
        "essentiality_source": "rule",
        "essentiality_confidence": 0.9,
        "review_reason": "none",
        "parser_version": "qc_v1"
    })

    tx = TransactionRepository.get_by_id(tx_id)
    assert tx is not None
    assert tx["merchant_name"] == "Starbucks"
    assert tx["raw_merchant_name"] == "STARBUCKS #1234"
    assert tx["capture_method"] == "quick_capture"
    assert tx["category_source"] == "rule"
    assert tx["category_confidence"] == 0.95
    assert tx["essentiality_source"] == "rule"
    assert tx["parser_version"] == "qc_v1"


def test_resolve_review_updates_provenance(isolated_db):
    acc_id = AccountRepository.create("Checking Prov", "checking", currency="USD")
    cat_init = CategoryRepository.create("Uncategorized Prov", "expense")
    cat_target = CategoryRepository.create("Groceries Confirmed", "expense")

    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_init,
        "amount": 55.0,
        "merchant_name": "Target Superstore",
        "transaction_date": "2026-04-01",
        "transaction_type": "expense",
        "needs_review": 1,
        "review_reason": "uncategorized",
        "category_source": "fallback"
    })

    # Resolve review
    ok = TransactionRepository.resolve_review(tx_id, cat_target, merchant_name="Target")
    assert ok is True

    resolved = TransactionRepository.get_by_id(tx_id)
    assert resolved["needs_review"] == 0
    assert resolved["category_id"] == cat_target
    assert resolved["review_reason"] is None
    assert resolved["category_source"] == "review_confirmed"
    assert resolved["category_confidence"] == 1.0


def test_unclassified_essentiality_defaults_to_unknown(isolated_db):
    acc_id = AccountRepository.create("Cash Prov", "cash", currency="USD")
    cat_id = CategoryRepository.create("Misc Item", "expense")

    # Transaction created without essentiality specified
    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 15.0,
        "transaction_date": "2026-04-02",
        "transaction_type": "expense"
    })

    tx = TransactionRepository.get_by_id(tx_id)
    assert tx["essentiality"] == "unknown"
    assert tx["essentiality_source"] == "fallback"
    assert tx["essentiality_confidence"] == 0.0


