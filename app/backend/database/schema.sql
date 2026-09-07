-- FinScope Database Schema — Reference Contract
-- NOTE: The migration scripts in app/backend/database/migrations_runner.py are the
-- authoritative source of truth for runtime database structure and constraints.
-- This file serves as the clean reference contract for fresh schema generation and documentation.
-- Monetary values stored strictly as exact integer minor units (e.g. cents)

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
    type TEXT NOT NULL DEFAULT 'expense', -- 'expense', 'income', 'transfer'
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
    amount_minor INTEGER NOT NULL, -- Integer cents/minor units (e.g. 5240 = $52.40)
    transaction_date TEXT NOT NULL, -- YYYY-MM-DD
    transaction_time TEXT DEFAULT '12:00', -- HH:MM
    description TEXT DEFAULT '',
    note TEXT DEFAULT '',
    is_recurring INTEGER NOT NULL DEFAULT 0,
    recurring_rule_id INTEGER,
    payment_method TEXT DEFAULT 'Card',
    essentiality TEXT NOT NULL DEFAULT 'unknown' CHECK (essentiality IN ('unknown', 'essential', 'discretionary', 'savings')),
    transfer_group_id TEXT DEFAULT NULL, -- Links legs of double-entry transfers
    transfer_role TEXT CHECK (transfer_role IS NULL OR transfer_role IN ('source', 'destination')),
    linked_transaction_id INTEGER DEFAULT NULL REFERENCES transactions(id) ON DELETE SET NULL,
    refund_of_transaction_id INTEGER DEFAULT NULL REFERENCES transactions(id) ON DELETE SET NULL,
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'csv_import', 'recurring_generated', 'adjustment')),
    capture_method TEXT NOT NULL DEFAULT 'manual_form',
    category_source TEXT DEFAULT 'manual',
    category_confidence REAL DEFAULT 1.0,
    essentiality_source TEXT DEFAULT 'manual',
    essentiality_confidence REAL DEFAULT 1.0,
    review_reason TEXT,
    parser_version TEXT,
    needs_review INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    raw_merchant_name TEXT DEFAULT '',
    original_currency TEXT,
    original_amount_minor INTEGER,
    base_currency TEXT,
    base_amount_minor INTEGER,
    fx_rate_to_base TEXT,
    fx_rate_date TEXT,
    fx_rate_source TEXT,
    fx_status TEXT NOT NULL DEFAULT 'not_required',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS import_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    header_signature TEXT NOT NULL UNIQUE,
    delimiter TEXT NOT NULL DEFAULT ',',
    has_header INTEGER NOT NULL DEFAULT 1,
    date_format TEXT,
    column_mapping_json TEXT NOT NULL,
    category_rules_json TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    amount_minor INTEGER NOT NULL,
    period_type TEXT NOT NULL DEFAULT 'monthly',
    start_date TEXT NOT NULL, -- YYYY-MM format
    end_date TEXT,
    rollover INTEGER NOT NULL DEFAULT 0,
    currency TEXT DEFAULT NULL,
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
    currency TEXT DEFAULT NULL,
    original_currency TEXT DEFAULT NULL,
    original_amount_minor INTEGER DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recurring_rule_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    transaction_type TEXT NOT NULL DEFAULT 'expense',
    amount_minor INTEGER NOT NULL,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    frequency TEXT NOT NULL DEFAULT 'monthly',
    next_due_date TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    change_type TEXT NOT NULL DEFAULT 'created',
    currency TEXT DEFAULT NULL,
    original_currency TEXT DEFAULT NULL,
    original_amount_minor INTEGER DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rrv_rule_id ON recurring_rule_versions(rule_id);
CREATE INDEX IF NOT EXISTS idx_rrv_validity ON recurring_rule_versions(valid_from, valid_to);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(transaction_date);
CREATE INDEX IF NOT EXISTS idx_tx_category ON transactions(category_id);
CREATE INDEX IF NOT EXISTS idx_tx_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_tx_type ON transactions(transaction_type);
CREATE INDEX IF NOT EXISTS idx_tx_essentiality ON transactions(essentiality);
CREATE INDEX IF NOT EXISTS idx_tx_transfer_group ON transactions(transfer_group_id);
CREATE INDEX IF NOT EXISTS idx_budgets_period ON budgets(start_date, category_id);

-- Canonical Active Transactions View (Excludes soft-deleted records)
CREATE VIEW IF NOT EXISTS active_transactions AS
SELECT *
FROM transactions
WHERE is_deleted = 0;

-- Automatic sync triggers
CREATE TRIGGER IF NOT EXISTS trg_recurring_rules_insert
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

CREATE TRIGGER IF NOT EXISTS trg_recurring_rules_update
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

CREATE TRIGGER IF NOT EXISTS trg_recurring_rules_delete
AFTER DELETE ON recurring_rules
BEGIN
    UPDATE recurring_rule_versions
    SET valid_to = date('now'), change_type = 'deleted'
    WHERE rule_id = OLD.id AND valid_to IS NULL;
END;

-- Analytics State Revision Tracking for Replay Cache Freshness (Migration 007)
CREATE TABLE IF NOT EXISTS analytics_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    revision INTEGER NOT NULL DEFAULT 0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO analytics_state (id, revision)
VALUES (1, 0);

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

-- Multi-Currency Exchange Rates Storage (Migration 008)
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
CREATE INDEX IF NOT EXISTS idx_tx_merchant_id ON transactions(merchant_id);
CREATE INDEX IF NOT EXISTS idx_tx_review_account ON transactions(needs_review, account_id, transaction_date);
