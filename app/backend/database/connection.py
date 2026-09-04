import sqlite3
import logging
from pathlib import Path
from typing import Generator
from app.backend.config import DB_PATH

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 1

DEFAULT_ACCOUNTS = [
    {"name": "Everyday Checking", "account_type": "Everyday", "institution": "Main Bank", "opening_balance": 3500.0, "currency": "USD"},
    {"name": "High Yield Savings", "account_type": "Savings", "institution": "Capital Savings", "opening_balance": 12800.0, "currency": "USD"},
    {"name": "Platinum Credit Card", "account_type": "Credit Card", "institution": "Chase", "opening_balance": -450.0, "currency": "USD"},
    {"name": "Cash Wallet", "account_type": "Cash", "institution": "Cash", "opening_balance": 220.0, "currency": "USD"},
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

from contextlib import contextmanager

@contextmanager
def get_db_connection() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(DB_PATH), timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Initializes the database schema and default records if empty."""
    schema_file = Path(__file__).resolve().parent / "schema.sql"
    with open(schema_file, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with get_db_connection() as conn:
        conn.executescript(schema_sql)

        # Check migration version
        cur = conn.cursor()
        cur.execute("SELECT MAX(version) FROM schema_migrations")
        row = cur.fetchone()
        version = row[0] if row and row[0] is not None else 0

        if version < CURRENT_SCHEMA_VERSION:
            conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (CURRENT_SCHEMA_VERSION,))

        # Seed default accounts if none exist
        cur.execute("SELECT COUNT(*) FROM accounts")
        if cur.fetchone()[0] == 0:
            for acc in DEFAULT_ACCOUNTS:
                conn.execute(
                    "INSERT INTO accounts (name, account_type, institution, opening_balance, currency) VALUES (?, ?, ?, ?, ?)",
                    (acc["name"], acc["account_type"], acc["institution"], acc["opening_balance"], acc["currency"])
                )

        # Seed default categories if none exist
        cur.execute("SELECT COUNT(*) FROM categories")
        if cur.fetchone()[0] == 0:
            for cat in DEFAULT_CATEGORIES:
                conn.execute(
                    "INSERT INTO categories (name, type, icon, color) VALUES (?, ?, ?, ?)",
                    (cat["name"], cat["type"], cat["icon"], cat["color"])
                )

        conn.commit()
    logger.info("Database initialized successfully at %s", DB_PATH)
