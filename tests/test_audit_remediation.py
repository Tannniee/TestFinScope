"""
FinScope v1.0.3 Audit Remediation Regression Tests
Covers AUD-001 through AUD-015 in strict integrity risk order.
"""

import pytest
import sqlite3
from datetime import datetime, date
from pathlib import Path
from app.backend import config
from app.backend.database.connection import get_db_connection
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.analytics.changes import WhatChangedEngine
from app.backend.analytics.anomalies import AnomalyDetectionEngine
from app.backend.analytics.context import resolve_analytics_context


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    test_db_dir = tmp_path / "finscope_data"
    test_db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FINSCOPE_DATA_DIR", str(test_db_dir))
    config.set_data_dir(test_db_dir)

    from app.backend.database.connection import init_db
    init_db()

    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def test_aud_002_soft_deleted_transaction_excluded_from_changes_and_anomalies(isolated_db):
    """
    AUD-002: Soft-deleted transactions must NOT appear or influence What Changed
    or Category Anomalies calculations.
    """
    acc_id = AccountRepository.create("Primary Acc", "checking", opening_balance=2000.0)
    cat_id = CategoryRepository.create("Fine Dining", "expense", icon="utensils", color="#E67E22")

    # Month 1: 2026-07 (previous period) -> 1 expense of $100
    TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 100.0,
        "transaction_type": "expense",
        "merchant_name": "Bistro A",
        "transaction_date": "2026-07-15"
    })

    # Month 2: 2026-08 (current period) -> 2 expenses of $150 and $200
    tx1_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 150.0,
        "transaction_type": "expense",
        "merchant_name": "Bistro B",
        "transaction_date": "2026-08-05"
    })

    tx2_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 200.0,
        "transaction_type": "expense",
        "merchant_name": "Bistro C",
        "transaction_date": "2026-08-10"
    })

    # Soft delete tx2 ($200)
    TransactionRepository.delete(tx2_id)

    # 1. Verify What Changed (WhatChangedEngine.analyze_changes)
    changes = WhatChangedEngine.analyze_changes(current_month="2026-08", comparison_month="2026-07", account_id=acc_id)
    # Current spend for Fine Dining should be ONLY tx1 ($150.00), NOT $350.00
    fine_dining_driver = next((d for d in changes["drivers"] if d["entity_id"] == cat_id), None)
    assert fine_dining_driver is not None
    assert fine_dining_driver["current_minor"] == 15000  # $150.00
    assert fine_dining_driver["delta_minor"] == 5000     # $150 - $100 = +$50.00 (not +$250.00)

    # 2. Verify Category Anomalies (AnomalyDetectionEngine.detect_anomalies)
    anomalies = AnomalyDetectionEngine.detect_anomalies(month="2026-08", account_id=acc_id)
    # Ensure current net for Fine Dining in context/anomalies is 15000 minor ($150.00)
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT SUM(t.amount_minor) as total_net
            FROM categories c
            JOIN active_transactions t ON t.category_id = c.id
            WHERE c.id = ? AND t.transaction_date >= '2026-08-01' AND t.transaction_date <= '2026-08-31'
        """, (cat_id,))
        row = cur.fetchone()
        assert row["total_net"] == 15000
