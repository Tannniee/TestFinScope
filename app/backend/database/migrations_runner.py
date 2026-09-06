import sqlite3
import logging
from pathlib import Path
from typing import List, Callable
from app.backend.config import DB_PATH

logger = logging.getLogger(__name__)

MIGRATIONS: List[tuple[int, str, Callable[[sqlite3.Connection], None]]] = []
MAX_SUPPORTED_SCHEMA_VERSION = 8

def migration(version: int, name: str):
    def decorator(fn: Callable[[sqlite3.Connection], None]):
        MIGRATIONS.append((version, name, fn))
        MIGRATIONS.sort(key=lambda m: m[0])
        return fn
    return decorator

# --- Migration Definitions ---

@migration(1, "initial_schema_with_minor_units")
def migration_001_initial_schema(conn: sqlite3.Connection):
    """
    Creates base schema storing monetary values as exact integer minor units (cents).
    """
    conn.executescript("""
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            account_type TEXT NOT NULL DEFAULT 'Everyday',
            institution TEXT DEFAULT '',
            opening_balance_minor INTEGER NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'USD',
            is_archived INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'expense',
            parent_category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            icon TEXT DEFAULT 'tag',
            color TEXT DEFAULT '#5B8CFF',
            is_archived INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS merchants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            default_category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            merchant_pattern TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            merchant_id INTEGER REFERENCES merchants(id) ON DELETE SET NULL,
            merchant_name TEXT NOT NULL DEFAULT '',
            transaction_type TEXT NOT NULL CHECK (transaction_type IN ('income', 'expense', 'transfer', 'refund', 'adjustment')),
            amount_minor INTEGER NOT NULL,
            transaction_date TEXT NOT NULL,
            transaction_time TEXT DEFAULT '12:00',
            description TEXT DEFAULT '',
            note TEXT DEFAULT '',
            is_recurring INTEGER NOT NULL DEFAULT 0,
            recurring_rule_id INTEGER,
            payment_method TEXT DEFAULT 'Card',
            essentiality TEXT NOT NULL DEFAULT 'discretionary' CHECK (essentiality IN ('essential', 'discretionary', 'savings')),
            transfer_group_id TEXT DEFAULT NULL,
            linked_transaction_id INTEGER DEFAULT NULL REFERENCES transactions(id) ON DELETE SET NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
            amount_minor INTEGER NOT NULL,
            period_type TEXT NOT NULL DEFAULT 'monthly',
            start_date TEXT NOT NULL,
            end_date TEXT,
            rollover INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(category_id, start_date)
        );

        CREATE TABLE IF NOT EXISTS recurring_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            transaction_type TEXT NOT NULL DEFAULT 'expense',
            amount_minor INTEGER NOT NULL,
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
            frequency TEXT NOT NULL DEFAULT 'monthly',
            next_due_date TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        -- Performance Indexes
        CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(transaction_date);
        CREATE INDEX IF NOT EXISTS idx_tx_category ON transactions(category_id);
        CREATE INDEX IF NOT EXISTS idx_tx_account ON transactions(account_id);
        CREATE INDEX IF NOT EXISTS idx_tx_type ON transactions(transaction_type);
        CREATE INDEX IF NOT EXISTS idx_tx_essentiality ON transactions(essentiality);
        CREATE INDEX IF NOT EXISTS idx_tx_transfer_group ON transactions(transfer_group_id);
        CREATE INDEX IF NOT EXISTS idx_budgets_period ON budgets(start_date, category_id);
    """)

@migration(2, "core_relationships_and_merchants")
def migration_002_core_relationships_and_merchants(conn: sqlite3.Connection):
    """
    Extends transactions with transfer_role, refund_of_transaction_id, source,
    needs_review, and soft-delete support for non-blocking Undo.
    Extends merchants with preferred_account_id, default_essentiality, and merchant_rules.
    Ensures Uncategorized system category exists.
    """
    # Helper to check if column exists before altering
    def column_exists(table: str, col: str) -> bool:
        cur = conn.execute(f"PRAGMA table_info({table})")
        return any(row[1] == col for row in cur.fetchall())

    # 1. Update transactions columns
    if not column_exists("transactions", "transfer_role"):
        conn.execute("ALTER TABLE transactions ADD COLUMN transfer_role TEXT DEFAULT NULL;")
    if not column_exists("transactions", "refund_of_transaction_id"):
        conn.execute("ALTER TABLE transactions ADD COLUMN refund_of_transaction_id INTEGER DEFAULT NULL REFERENCES transactions(id) ON DELETE SET NULL;")
    if not column_exists("transactions", "source"):
        conn.execute("ALTER TABLE transactions ADD COLUMN source TEXT NOT NULL DEFAULT 'manual';")
    if not column_exists("transactions", "needs_review"):
        conn.execute("ALTER TABLE transactions ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 0;")
    if not column_exists("transactions", "is_deleted"):
        conn.execute("ALTER TABLE transactions ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0;")

    # 2. Update merchants columns
    if not column_exists("merchants", "preferred_account_id"):
        conn.execute("ALTER TABLE merchants ADD COLUMN preferred_account_id INTEGER DEFAULT NULL REFERENCES accounts(id) ON DELETE SET NULL;")
    if not column_exists("merchants", "default_essentiality"):
        conn.execute("ALTER TABLE merchants ADD COLUMN default_essentiality TEXT DEFAULT 'discretionary';")

    # 3. Create merchant_rules table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS merchant_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT NOT NULL UNIQUE,
            merchant_id INTEGER REFERENCES merchants(id) ON DELETE CASCADE,
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 4. Create Uncategorized system category
    cur = conn.execute("SELECT id FROM categories WHERE name = 'Uncategorized'")
    if not cur.fetchone():
        conn.execute("""
            INSERT INTO categories (name, type, icon, color)
            VALUES ('Uncategorized', 'expense', 'help-circle', '#8E8E93')
        """)

    # 5. Indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_review ON transactions(needs_review);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_refund_of ON transactions(refund_of_transaction_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_is_deleted ON transactions(is_deleted);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_merchants_name ON merchants(name);")

@migration(3, "analytics_v2_insight_history")
def migration_003_analytics_v2_insight_history(conn: sqlite3.Connection):
    """
    Creates insight_history table to persist seen insights, novelty decay,
    material change resets, and user dismissals.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS insight_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            insight_key TEXT UNIQUE NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            times_shown INTEGER NOT NULL DEFAULT 1,
            last_value_minor INTEGER NOT NULL DEFAULT 0,
            last_rank INTEGER NOT NULL DEFAULT 0,
            dismissed INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_insight_key ON insight_history(insight_key);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_insight_dismissed ON insight_history(dismissed);")

@migration(4, "core_v2_active_transactions_view")
def migration_004_core_v2_active_transactions_view(conn: sqlite3.Connection):
    """
    Creates canonical active_transactions view to ensure all reporting, analytics,
    budgets, and exports deterministically exclude soft-deleted transactions.
    """
    conn.execute("""
        CREATE VIEW IF NOT EXISTS active_transactions AS
        SELECT *
        FROM transactions
        WHERE is_deleted = 0;
    """)

@migration(5, "enforce_table_constraints")
def migration_005_enforce_table_constraints(conn: sqlite3.Connection):
    """
    Rebuilds transactions table with explicit CHECK constraints on transfer_role and source,
    aligning the runtime database with schema.sql.
    """
    conn.executescript("""
        PRAGMA foreign_keys = OFF;

        CREATE TABLE IF NOT EXISTS transactions_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            merchant_id INTEGER REFERENCES merchants(id) ON DELETE SET NULL,
            merchant_name TEXT NOT NULL DEFAULT '',
            transaction_type TEXT NOT NULL CHECK (transaction_type IN ('income', 'expense', 'transfer', 'refund', 'adjustment')),
            amount_minor INTEGER NOT NULL,
            transaction_date TEXT NOT NULL,
            transaction_time TEXT DEFAULT '12:00',
            description TEXT DEFAULT '',
            note TEXT DEFAULT '',
            is_recurring INTEGER NOT NULL DEFAULT 0,
            recurring_rule_id INTEGER,
            payment_method TEXT DEFAULT 'Card',
            essentiality TEXT NOT NULL DEFAULT 'discretionary' CHECK (essentiality IN ('essential', 'discretionary', 'savings')),
            transfer_group_id TEXT DEFAULT NULL,
            transfer_role TEXT CHECK (transfer_role IS NULL OR transfer_role IN ('source', 'destination')),
            linked_transaction_id INTEGER DEFAULT NULL REFERENCES transactions(id) ON DELETE SET NULL,
            refund_of_transaction_id INTEGER DEFAULT NULL REFERENCES transactions(id) ON DELETE SET NULL,
            source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'csv_import', 'recurring_generated', 'adjustment')),
            needs_review INTEGER NOT NULL DEFAULT 0,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        INSERT INTO transactions_new (
            id, account_id, category_id, merchant_id, merchant_name, transaction_type,
            amount_minor, transaction_date, transaction_time, description, note,
            is_recurring, recurring_rule_id, payment_method, essentiality,
            transfer_group_id, transfer_role, linked_transaction_id,
            refund_of_transaction_id, source, needs_review, is_deleted,
            created_at, updated_at
        )
        SELECT
            id, account_id, category_id, merchant_id, merchant_name, transaction_type,
            amount_minor, transaction_date, transaction_time, description, note,
            is_recurring, recurring_rule_id, payment_method, essentiality,
            transfer_group_id, transfer_role, linked_transaction_id,
            refund_of_transaction_id, source, needs_review, is_deleted,
            created_at, updated_at
        FROM transactions;

        DROP VIEW IF EXISTS active_transactions;
        DROP TABLE transactions;
        ALTER TABLE transactions_new RENAME TO transactions;

        PRAGMA foreign_keys = ON;

        CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(transaction_date);
        CREATE INDEX IF NOT EXISTS idx_tx_category ON transactions(category_id);
        CREATE INDEX IF NOT EXISTS idx_tx_account ON transactions(account_id);
        CREATE INDEX IF NOT EXISTS idx_tx_type ON transactions(transaction_type);
        CREATE INDEX IF NOT EXISTS idx_tx_essentiality ON transactions(essentiality);
        CREATE INDEX IF NOT EXISTS idx_tx_transfer_group ON transactions(transfer_group_id);
        CREATE INDEX IF NOT EXISTS idx_tx_review ON transactions(needs_review);
        CREATE INDEX IF NOT EXISTS idx_tx_refund_of ON transactions(refund_of_transaction_id);
        CREATE INDEX IF NOT EXISTS idx_tx_is_deleted ON transactions(is_deleted);

        CREATE VIEW IF NOT EXISTS active_transactions AS
        SELECT *
        FROM transactions
        WHERE is_deleted = 0;
    """)

@migration(6, "recurring_rule_point_in_time_versioning")
def migration_006_recurring_rule_versioning(conn: sqlite3.Connection):
    """
    Creates recurring_rule_versions table and triggers to enable point-in-time
    anti-leakage historical replay of recurring commitments.
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS recurring_rule_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            transaction_type TEXT NOT NULL DEFAULT 'expense',
            amount_minor INTEGER NOT NULL,
            category_id INTEGER,
            account_id INTEGER,
            frequency TEXT NOT NULL DEFAULT 'monthly',
            next_due_date TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            valid_from TEXT NOT NULL,
            valid_to TEXT,
            change_type TEXT NOT NULL DEFAULT 'created',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_rrv_rule_id ON recurring_rule_versions(rule_id);
        CREATE INDEX IF NOT EXISTS idx_rrv_validity ON recurring_rule_versions(valid_from, valid_to);

        -- Seed initial version for existing rules
        INSERT INTO recurring_rule_versions (
            rule_id, name, transaction_type, amount_minor, category_id,
            account_id, frequency, next_due_date, active, valid_from, valid_to, change_type
        )
        SELECT 
            id, name, transaction_type, amount_minor, category_id,
            account_id, frequency, next_due_date, active,
            COALESCE(created_at, date('now')), NULL, 'created'
        FROM recurring_rules
        WHERE id NOT IN (SELECT DISTINCT rule_id FROM recurring_rule_versions);

        -- Automatic sync triggers
        CREATE TRIGGER IF NOT EXISTS trg_recurring_rules_insert
        AFTER INSERT ON recurring_rules
        BEGIN
            INSERT INTO recurring_rule_versions (
                rule_id, name, transaction_type, amount_minor, category_id,
                account_id, frequency, next_due_date, active, valid_from, valid_to, change_type
            ) VALUES (
                NEW.id, NEW.name, NEW.transaction_type, NEW.amount_minor, NEW.category_id,
                NEW.account_id, NEW.frequency, NEW.next_due_date, NEW.active,
                COALESCE(NEW.created_at, date('now')), NULL, 'created'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS trg_recurring_rules_update
        AFTER UPDATE ON recurring_rules
        BEGIN
            UPDATE recurring_rule_versions
            SET valid_to = date('now')
            WHERE rule_id = OLD.id AND valid_to IS NULL;

            INSERT INTO recurring_rule_versions (
                rule_id, name, transaction_type, amount_minor, category_id,
                account_id, frequency, next_due_date, active, valid_from, valid_to, change_type
            ) VALUES (
                NEW.id, NEW.name, NEW.transaction_type, NEW.amount_minor, NEW.category_id,
                NEW.account_id, NEW.frequency, NEW.next_due_date, NEW.active,
                date('now'), NULL, 'updated'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS trg_recurring_rules_delete
        AFTER DELETE ON recurring_rules
        BEGIN
            UPDATE recurring_rule_versions
            SET valid_to = date('now'), change_type = 'deleted'
            WHERE rule_id = OLD.id AND valid_to IS NULL;
        END;
    """)

@migration(7, "analytics_revision_tracking")
def migration_007_analytics_revision_tracking(conn: sqlite3.Connection):
    """
    Creates analytics_state table and automatic mutation triggers on transactions
    and recurring_rules to enable deterministic replay cache invalidation (F108-15).
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS analytics_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            revision INTEGER NOT NULL DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        INSERT OR IGNORE INTO analytics_state (id, revision)
        VALUES (1, 0);

        -- Transaction mutation triggers
        CREATE TRIGGER IF NOT EXISTS trg_analytics_state_tx_insert
        AFTER INSERT ON transactions
        BEGIN
            UPDATE analytics_state SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = 1;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_analytics_state_tx_update
        AFTER UPDATE ON transactions
        BEGIN
            UPDATE analytics_state SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = 1;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_analytics_state_tx_delete
        AFTER DELETE ON transactions
        BEGIN
            UPDATE analytics_state SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = 1;
        END;

        -- Recurring rules mutation triggers
        CREATE TRIGGER IF NOT EXISTS trg_analytics_state_rec_insert
        AFTER INSERT ON recurring_rules
        BEGIN
            UPDATE analytics_state SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = 1;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_analytics_state_rec_update
        AFTER UPDATE ON recurring_rules
        BEGIN
            UPDATE analytics_state SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = 1;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_analytics_state_rec_delete
        AFTER DELETE ON recurring_rules
        BEGIN
            UPDATE analytics_state SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = 1;
        END;
    """)


def _add_column_if_not_exists(conn: sqlite3.Connection, table: str, column_def: str):
    col_name = column_def.split()[0]
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cur.fetchall()]
    if col_name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")


@migration(8, "multi_currency_foundation")
def migration_008_multi_currency_foundation(conn: sqlite3.Connection):
    """
    Migration 008: Multi-Currency Foundation (F110 / MC-Phase 2)
    - Adds original_currency, original_amount_minor, base_currency, base_amount_minor,
      fx_rate_to_base, fx_rate_date, fx_rate_source, fx_status to transactions.
    - Adds currency to budgets and recurring_rules.
    - Adds exchange_rates table with revision tracking on analytics_state.
    - Updates triggers and recreates active_transactions view.
    - Repairs legacy zero-decimal data (VND, JPY) if needed.
    - Backfills existing transactions to self-describing multi-currency state.
    """
    # 1. Add columns to transactions
    _add_column_if_not_exists(conn, "transactions", "original_currency TEXT")
    _add_column_if_not_exists(conn, "transactions", "original_amount_minor INTEGER")
    _add_column_if_not_exists(conn, "transactions", "base_currency TEXT")
    _add_column_if_not_exists(conn, "transactions", "base_amount_minor INTEGER")
    _add_column_if_not_exists(conn, "transactions", "fx_rate_to_base TEXT")
    _add_column_if_not_exists(conn, "transactions", "fx_rate_date TEXT")
    _add_column_if_not_exists(conn, "transactions", "fx_rate_source TEXT")
    _add_column_if_not_exists(conn, "transactions", "fx_status TEXT NOT NULL DEFAULT 'not_required'")

    # 2. Add columns to budgets
    _add_column_if_not_exists(conn, "budgets", "currency TEXT DEFAULT NULL")

    # 3. Add columns to recurring_rules and versions
    _add_column_if_not_exists(conn, "recurring_rules", "currency TEXT DEFAULT NULL")
    _add_column_if_not_exists(conn, "recurring_rules", "original_currency TEXT DEFAULT NULL")
    _add_column_if_not_exists(conn, "recurring_rules", "original_amount_minor INTEGER DEFAULT NULL")

    _add_column_if_not_exists(conn, "recurring_rule_versions", "currency TEXT DEFAULT NULL")
    _add_column_if_not_exists(conn, "recurring_rule_versions", "original_currency TEXT DEFAULT NULL")
    _add_column_if_not_exists(conn, "recurring_rule_versions", "original_amount_minor INTEGER DEFAULT NULL")

    # 4. Create exchange_rates table and triggers
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS exchange_rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_currency TEXT NOT NULL,
            quote_currency TEXT NOT NULL,
            rate_date TEXT NOT NULL,
            rate TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_rate_date TEXT,
            fetched_at TEXT NOT NULL,
            UNIQUE(base_currency, quote_currency, rate_date, provider)
        );

        CREATE INDEX IF NOT EXISTS idx_exchange_rates_lookup ON exchange_rates(base_currency, quote_currency, rate_date);

        CREATE TRIGGER IF NOT EXISTS trg_analytics_state_fx_insert
        AFTER INSERT ON exchange_rates
        BEGIN
            UPDATE analytics_state SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = 1;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_analytics_state_fx_update
        AFTER UPDATE ON exchange_rates
        BEGIN
            UPDATE analytics_state SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = 1;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_analytics_state_fx_delete
        AFTER DELETE ON exchange_rates
        BEGIN
            UPDATE analytics_state SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = 1;
        END;

        -- Recreate active_transactions view to expose new columns
        DROP VIEW IF EXISTS active_transactions;
        CREATE VIEW active_transactions AS
        SELECT *
        FROM transactions
        WHERE is_deleted = 0;

        -- Update recurring rule version triggers to include currency columns
        DROP TRIGGER IF EXISTS trg_recurring_rules_insert;
        CREATE TRIGGER trg_recurring_rules_insert
        AFTER INSERT ON recurring_rules
        BEGIN
            INSERT INTO recurring_rule_versions (
                rule_id, name, transaction_type, amount_minor, category_id,
                account_id, frequency, next_due_date, active, valid_from, valid_to, change_type,
                currency, original_currency, original_amount_minor
            ) VALUES (
                NEW.id, NEW.name, NEW.transaction_type, NEW.amount_minor, NEW.category_id,
                NEW.account_id, NEW.frequency, NEW.next_due_date, NEW.active,
                COALESCE(NEW.created_at, date('now')), NULL, 'created',
                NEW.currency, NEW.original_currency, NEW.original_amount_minor
            );
        END;

        DROP TRIGGER IF EXISTS trg_recurring_rules_update;
        CREATE TRIGGER trg_recurring_rules_update
        AFTER UPDATE ON recurring_rules
        BEGIN
            UPDATE recurring_rule_versions
            SET valid_to = date('now')
            WHERE rule_id = OLD.id AND valid_to IS NULL;

            INSERT INTO recurring_rule_versions (
                rule_id, name, transaction_type, amount_minor, category_id,
                account_id, frequency, next_due_date, active, valid_from, valid_to, change_type,
                currency, original_currency, original_amount_minor
            ) VALUES (
                NEW.id, NEW.name, NEW.transaction_type, NEW.amount_minor, NEW.category_id,
                NEW.account_id, NEW.frequency, NEW.next_due_date, NEW.active,
                date('now'), NULL, 'updated',
                NEW.currency, NEW.original_currency, NEW.original_amount_minor
            );
        END;
    """)

    # 5. Data repair for legacy zero-decimal currencies (VND, JPY)
    cur = conn.cursor()
    cur.execute("SELECT value FROM app_settings WHERE key = 'currency'")
    row = cur.fetchone()
    base_curr = row[0].strip().upper() if row and row[0] else "USD"

    if base_curr in ("VND", "JPY"):
        for tbl, col in [
            ("transactions", "amount_minor"),
            ("accounts", "opening_balance_minor"),
            ("budgets", "amount_minor"),
            ("recurring_rules", "amount_minor"),
            ("recurring_rule_versions", "amount_minor"),
        ]:
            cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {col} % 100 != 0")
            bad_count = cur.fetchone()[0]
            if bad_count > 0:
                raise ValueError(
                    f"Legacy zero-decimal migration safety check failed: "
                    f"{bad_count} records in {tbl}.{col} are not divisible by 100."
                )
            conn.execute(f"UPDATE {tbl} SET {col} = {col} / 100")

    # 6. Backfill transactions with multi-currency fields
    conn.execute("""
        UPDATE transactions
        SET 
            original_currency = COALESCE(
                original_currency,
                (SELECT currency FROM accounts WHERE accounts.id = transactions.account_id),
                ?
            ),
            original_amount_minor = COALESCE(original_amount_minor, amount_minor),
            base_currency = COALESCE(base_currency, ?),
            base_amount_minor = COALESCE(base_amount_minor, amount_minor),
            fx_status = COALESCE(fx_status, 'not_required')
        WHERE base_currency IS NULL OR original_currency IS NULL
    """, (base_curr, base_curr))

    # 7. Backfill recurring rules & versions
    conn.execute("""
        UPDATE recurring_rules
        SET
            currency = COALESCE(
                currency,
                (SELECT currency FROM accounts WHERE accounts.id = recurring_rules.account_id),
                ?
            ),
            original_currency = COALESCE(original_currency, currency, ?),
            original_amount_minor = COALESCE(original_amount_minor, amount_minor)
        WHERE currency IS NULL
    """, (base_curr, base_curr))

    conn.execute("""
        UPDATE recurring_rule_versions
        SET
            currency = COALESCE(
                currency,
                (SELECT currency FROM accounts WHERE accounts.id = recurring_rule_versions.account_id),
                ?
            ),
            original_currency = COALESCE(original_currency, currency, ?),
            original_amount_minor = COALESCE(original_amount_minor, amount_minor)
        WHERE currency IS NULL
    """, (base_curr, base_curr))

    # 8. Backfill budgets
    conn.execute("""
        UPDATE budgets
        SET currency = COALESCE(currency, ?)
        WHERE currency IS NULL
    """, (base_curr,))


def run_migrations(conn: sqlite3.Connection):
    """Executes any pending migrations safely."""
    # Ensure migration table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur = conn.cursor()
    cur.execute("SELECT MAX(version) FROM schema_migrations")
    row = cur.fetchone()
    current_version = row[0] if row and row[0] is not None else 0

    for version, name, migration_fn in MIGRATIONS:
        if version > current_version:
            logger.info("Applying database migration %03d: %s...", version, name)
            try:
                migration_fn(conn)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                    (version, name)
                )
                conn.commit()
                logger.info("Migration %03d applied successfully.", version)
            except Exception as e:
                conn.rollback()
                logger.error("Migration %03d failed: %s", version, e)
                raise
