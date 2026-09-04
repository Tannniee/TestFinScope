import os
import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Generator
from app.backend import config
from app.backend.database.migrations_runner import run_migrations

logger = logging.getLogger(__name__)

DEFAULT_ACCOUNTS = [
    {"name": "Everyday Checking", "account_type": "Everyday", "institution": "Main Bank", "opening_balance_minor": 350000, "currency": "USD"},
    {"name": "High Yield Savings", "account_type": "Savings", "institution": "Capital Savings", "opening_balance_minor": 1280000, "currency": "USD"},
    {"name": "Platinum Credit Card", "account_type": "Credit Card", "institution": "Chase", "opening_balance_minor": -45000, "currency": "USD"},
    {"name": "Cash Wallet", "account_type": "Cash", "institution": "Cash", "opening_balance_minor": 22000, "currency": "USD"},
]

DEFAULT_CATEGORIES = [
    # Expenses
    {"name": "Groceries", "type": "expense", "icon": "shopping-cart", "color": "#4DD5A5"},
    {"name": "Dining & Coffee", "type": "expense", "icon": "coffee", "color": "#FF9F43"},
    {"name": "Housing & Rent", "type": "expense", "icon": "home", "color": "#5B8CFF"},
    {"name": "Utilities & Bills", "type": "expense", "icon": "zap", "color": "#27D5D5"},
    {"name": "Transportation & Fuel", "type": "expense", "icon": "car", "color": "#C85AF4"},
    {"name": "Shopping & Tech", "type": "expense", "icon": "shopping-bag", "color": "#FF6B8A"},
    {"name": "Entertainment & Subscriptions", "type": "expense", "icon": "film", "color": "#A55EEA"},
    {"name": "Healthcare & Wellness", "type": "expense", "icon": "activity", "color": "#20BF6B"},
    {"name": "Education & Personal", "type": "expense", "icon": "book-open", "color": "#45AAF2"},
    {"name": "Travel & Holidays", "type": "expense", "icon": "compass", "color": "#FA8231"},
    {"name": "Other Expenses", "type": "expense", "icon": "more-horizontal", "color": "#778CA3"},
    # Incomes
    {"name": "Salary / Primary Job", "type": "income", "icon": "briefcase", "color": "#2ECC71"},
    {"name": "Freelance & Consulting", "type": "income", "icon": "laptop", "color": "#1ABC9C"},
    {"name": "Investments & Dividends", "type": "income", "icon": "trending-up", "color": "#3498DB"},
    {"name": "Gifts & Grants", "type": "income", "icon": "gift", "color": "#9B59B6"},
    {"name": "Other Income", "type": "income", "icon": "plus-circle", "color": "#16A085"},
    # Transfers
    {"name": "Internal Transfer", "type": "transfer", "icon": "repeat", "color": "#95A5A6"},
]

DEFAULT_SETTINGS = {
    "currency": "USD",
    "currency_symbol": "$",
    "date_format": "YYYY-MM-DD",
    "theme": "dark",
    "has_initialized": "false"
}

@contextmanager
def get_db_connection() -> Generator[sqlite3.Connection, None, None]:
    env_dir = os.environ.get("FINSCOPE_DATA_DIR")
    if env_dir and Path(env_dir) != config.DATA_DIR:
        config.set_data_dir(Path(env_dir))

    conn = sqlite3.connect(str(config.DB_PATH), timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Initializes the database schema and default records safely using migrations."""
    env_dir = os.environ.get("FINSCOPE_DATA_DIR")
    if env_dir and Path(env_dir) != config.DATA_DIR:
        config.set_data_dir(Path(env_dir))

    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with get_db_connection() as conn:
        # 1. Run migrations safely
        run_migrations(conn)

        cur = conn.cursor()

        # 2. Seed default settings if empty
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
                (k, v)
            )

        # 3. Default categories (0 fake accounts created on fresh init)
        cur.execute("SELECT COUNT(*) FROM categories WHERE name != 'Uncategorized'")
        if cur.fetchone()[0] == 0:
            for cat in DEFAULT_CATEGORIES:
                conn.execute(
                    "INSERT OR IGNORE INTO categories (name, type, icon, color) VALUES (?, ?, ?, ?)",
                    (cat["name"], cat["type"], cat["icon"], cat["color"])
                )

        conn.commit()

    logger.info("Database initialized successfully at %s", config.DB_PATH)
