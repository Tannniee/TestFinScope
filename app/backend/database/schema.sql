-- FinScope Database Schema — Production Edition
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
    essentiality TEXT NOT NULL DEFAULT 'discretionary' CHECK (essentiality IN ('essential', 'discretionary', 'savings')),
    transfer_group_id TEXT DEFAULT NULL, -- Links legs of double-entry transfers
    transfer_role TEXT CHECK (transfer_role IN ('source', 'destination')),
    linked_transaction_id INTEGER DEFAULT NULL REFERENCES transactions(id) ON DELETE SET NULL,
    refund_of_transaction_id INTEGER DEFAULT NULL REFERENCES transactions(id) ON DELETE SET NULL,
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'csv_import', 'recurring_generated', 'adjustment')),
    needs_review INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0,
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
