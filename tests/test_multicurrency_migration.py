"""
Tests for Migration 008 — Multi-Currency Foundation & Legacy Data Repair (Phase 2).
Verifies:
1. Migration 008 applies on existing databases without error.
2. Legacy USD data backfills base_currency, original_currency, base_amount_minor, fx_status.
3. Legacy VND/JPY data correctly rescales by dividing 100.
4. Non-divisible legacy amounts raise ValueError rather than corrupting data.
5. Exchange rates table and analytics revision bump triggers work properly.
"""

import sqlite3
import pytest
from app.backend.database.migrations_runner import run_migrations, MIGRATIONS


def test_migration_008_backfills_usd_data(tmp_path):
    """Verifies that existing USD transactions receive multi-currency backfill fields."""
    db_file = tmp_path / "test_usd.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row

    # Apply migrations 1 through 7
    for ver, name, fn in MIGRATIONS:
        if ver <= 7:
            fn(conn)
            conn.execute("INSERT INTO schema_migrations (version, name) VALUES (?, ?)", (ver, name))
    conn.commit()

    # Insert pre-migration USD data
    conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('currency', 'USD')")
    conn.execute("INSERT INTO accounts (id, name, currency, opening_balance_minor) VALUES (1, 'Checking', 'USD', 10000)")
    conn.execute("""
        INSERT INTO transactions (id, account_id, transaction_type, amount_minor, transaction_date, description)
        VALUES (1, 1, 'expense', 2550, '2026-09-01', 'Coffee')
    """)
    conn.execute("""
        INSERT INTO recurring_rules (id, account_id, name, transaction_type, amount_minor, frequency, next_due_date)
        VALUES (1, 1, 'Internet', 'expense', 5000, 'monthly', '2026-09-15')
    """)
    conn.commit()

    # Run migration 8
    run_migrations(conn)

    cur = conn.cursor()
    cur.execute("SELECT * FROM transactions WHERE id = 1")
    tx = dict(cur.fetchone())

    assert tx["amount_minor"] == 2550
    assert tx["original_currency"] == "USD"
    assert tx["original_amount_minor"] == 2550
    assert tx["base_currency"] == "USD"
    assert tx["base_amount_minor"] == 2550
    assert tx["fx_status"] == "not_required"

    # Recurring rule
    cur.execute("SELECT * FROM recurring_rules WHERE id = 1")
    rule = dict(cur.fetchone())
    assert rule["currency"] == "USD"
    assert rule["original_currency"] == "USD"
    assert rule["original_amount_minor"] == 5000

    conn.close()


def test_migration_008_repairs_legacy_vnd_data(tmp_path):
    """Verifies that legacy zero-decimal VND data entered under *100 bug is rescaled (/100)."""
    db_file = tmp_path / "test_vnd.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row

    # Apply migrations 1 through 7
    for ver, name, fn in MIGRATIONS:
        if ver <= 7:
            fn(conn)
            conn.execute("INSERT INTO schema_migrations (version, name) VALUES (?, ?)", (ver, name))
    conn.commit()

    # Pre-migration VND data where 100,000 VND was wrongly multiplied by 100 -> 10,000,000
    conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('currency', 'VND')")
    conn.execute("INSERT INTO accounts (id, name, currency, opening_balance_minor) VALUES (1, 'VCB', 'VND', 500000000)")  # 5,000,000 VND * 100
    conn.execute("""
        INSERT INTO transactions (id, account_id, transaction_type, amount_minor, transaction_date, description)
        VALUES (1, 1, 'expense', 10000000, '2026-09-01', 'Dinner')
    """)
    conn.commit()

    # Run migration 8
    run_migrations(conn)

    cur = conn.cursor()
    cur.execute("SELECT * FROM transactions WHERE id = 1")
    tx = dict(cur.fetchone())

    # Correct rescaled amount: 100,000 VND (0 decimals -> 100,000 minor)
    assert tx["amount_minor"] == 100000
    assert tx["original_amount_minor"] == 100000
    assert tx["base_amount_minor"] == 100000
    assert tx["original_currency"] == "VND"
    assert tx["base_currency"] == "VND"

    # Account opening balance rescaled: 5,000,000
    cur.execute("SELECT opening_balance_minor FROM accounts WHERE id = 1")
    acc = cur.fetchone()
    assert acc["opening_balance_minor"] == 5000000

    conn.close()


def test_migration_008_rejects_non_divisible_legacy_vnd_amounts(tmp_path):
    """Safety assertion: if a legacy zero-decimal amount is not cleanly divisible by 100, migration halts."""
    db_file = tmp_path / "test_corrupt.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row

    # Apply migrations 1 through 7
    for ver, name, fn in MIGRATIONS:
        if ver <= 7:
            fn(conn)
            conn.execute("INSERT INTO schema_migrations (version, name) VALUES (?, ?)", (ver, name))
    conn.commit()

    conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('currency', 'VND')")
    conn.execute("INSERT INTO accounts (id, name, currency, opening_balance_minor) VALUES (1, 'VCB', 'VND', 1000)")
    # Corrupt amount: 10000050 (not divisible by 100)
    conn.execute("""
        INSERT INTO transactions (id, account_id, transaction_type, amount_minor, transaction_date, description)
        VALUES (1, 1, 'expense', 10000050, '2026-09-01', 'Odd cents')
    """)
    conn.commit()

    with pytest.raises(ValueError, match="Legacy zero-decimal migration safety check failed"):
        run_migrations(conn)

    conn.close()


def test_exchange_rates_table_and_revision_trigger(tmp_path):
    """Verifies exchange_rates inserts increment analytics_state.revision."""
    db_file = tmp_path / "test_fx_trigger.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row

    run_migrations(conn)

    cur = conn.cursor()
    cur.execute("SELECT revision FROM analytics_state WHERE id = 1")
    initial_rev = cur.fetchone()["revision"]

    conn.execute("""
        INSERT INTO exchange_rates (base_currency, quote_currency, rate_date, rate, provider, fetched_at)
        VALUES ('USD', 'VND', '2026-09-01', '26060', 'frankfurter', '2026-09-05T10:00:00')
    """)
    conn.commit()

    cur.execute("SELECT revision FROM analytics_state WHERE id = 1")
    new_rev = cur.fetchone()["revision"]
    assert new_rev == initial_rev + 1

    conn.close()
