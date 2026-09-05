import sqlite3
import logging
from pathlib import Path
from typing import List, Callable
from app.backend.config import DB_PATH

logger = logging.getLogger(__name__)

MIGRATIONS: List[tuple[int, str, Callable[[sqlite3.Connection], None]]] = []
MAX_SUPPORTED_SCHEMA_VERSION = 6

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
