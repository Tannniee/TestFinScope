import sqlite3
import pytest
from app.backend.database.migrations_runner import (
    migration_001_initial_schema,
    migration_002_core_relationships_and_merchants,
    migration_003_analytics_v2_insight_history,
    migration_004_core_v2_active_transactions_view,
    migration_005_enforce_table_constraints,
)

def _setup_v4_database(conn: sqlite3.Connection):
    """Sets up a database migrated through version 4 with test transactions."""
    migration_001_initial_schema(conn)
    migration_002_core_relationships_and_merchants(conn)
    migration_003_analytics_v2_insight_history(conn)
    migration_004_core_v2_active_transactions_view(conn)
    conn.execute("INSERT INTO schema_migrations (version, name) VALUES (1, 'initial'), (2, 'core'), (3, 'v2'), (4, 'v4')")
    
    # Insert test account
    conn.execute("INSERT INTO accounts (id, name, account_type) VALUES (1, 'Checking', 'Everyday')")
    for i in range(10):
        conn.execute("""
            INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, description)
            VALUES (1, 1, 'expense', ?, '2026-05-01', ?)
        """, ((i + 1) * 1000, f"Tx {i}"))
    conn.commit()


class FailingConnectionProxy:
    def __init__(self, conn, fail_on_sql: str):
        self._conn = conn
        self._fail_on_sql = fail_on_sql

    def execute(self, sql, *args, **kwargs):
        if self._fail_on_sql in sql:
            raise sqlite3.OperationalError(f"Injected failure on: {self._fail_on_sql}")
        return self._conn.execute(sql, *args, **kwargs)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def cursor(self):
        return self._conn.cursor()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_migration_005_normal_execution():
    """FSC-C02: Migration 005 executes cleanly and preserves all rows and views."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _setup_v4_database(conn)

    migration_005_enforce_table_constraints(conn)

    # Check row count
    cnt = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert cnt == 10

    # Check active_transactions view works
    v_cnt = conn.execute("SELECT COUNT(*) FROM active_transactions").fetchone()[0]
    assert v_cnt == 10

    # Check foreign keys
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    fk_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert len(fk_issues) == 0
    conn.close()


def test_migration_005_rollback_on_failure_leaves_db_intact():
    """
    FSC-C02: If a failure occurs during migration 005 (e.g. injected error),
    the transaction rolls back and the original transactions table and view remain completely intact.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _setup_v4_database(conn)

    proxy = FailingConnectionProxy(conn, fail_on_sql="DROP TABLE transactions")

    with pytest.raises(sqlite3.OperationalError, match="Injected failure"):
        migration_005_enforce_table_constraints(proxy)

    # Verify that original transactions table is intact and has 10 rows
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 10
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()
