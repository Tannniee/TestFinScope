import unittest
from datetime import date
from app.backend.database.connection import get_db_connection, init_db
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.analytics.changes import WhatChangedEngine
from app.backend.analytics.forecasting import ForecastingEngine
from app.backend.analytics.fingerprint import SpendingFingerprintEngine
from app.backend.analytics.anomalies import AnomalyDetectionEngine

class TestArchiveInvarianceAndAnalyticsHardening(unittest.TestCase):
    def setUp(self):
        init_db()
        with get_db_connection() as conn:
            conn.execute("DELETE FROM transactions")
            conn.execute("DELETE FROM accounts")
        self.acc_id = AccountRepository.create("Checking", "Everyday", "Bank A", 10000.0, "USD")

    def test_archived_category_preservation_in_changes(self):
        """Categories that are archived but have transactions in the periods must not be dropped."""
        cat_id = CategoryRepository.create("Legacy Subscriptions", "expense", "film", "#FF3B30")
        
        # Add spending in comparison month
        TransactionRepository.create({
            "account_id": self.acc_id,
            "category_id": cat_id,
            "amount": 50.0,
            "transaction_type": "expense",
            "transaction_date": "2026-07-10",
            "description": "Old streaming service"
        })
        # Add spending in current month
        TransactionRepository.create({
            "account_id": self.acc_id,
            "category_id": cat_id,
            "amount": 20.0,
            "transaction_type": "expense",
            "transaction_date": "2026-08-10",
            "description": "Old streaming service reduced"
        })

        # Archive the category
        with get_db_connection() as conn:
            conn.execute("UPDATE categories SET is_archived = 1 WHERE id = ?", [cat_id])

        # Analyze changes between 2026-08 and 2026-07
        changes = WhatChangedEngine.analyze_changes("2026-08", "2026-07")
        driver_cat_ids = [d["entity_id"] for d in changes["drivers"]]
        self.assertIn(cat_id, driver_cat_ids)

        # Category forecasts reconciliation must also retain this archived category
        fc = ForecastingEngine.forecast_month("2026-08", as_of_date="2026-08-15")
        fc_cat_ids = [c["category_id"] for c in fc["category_forecasts"]]
        self.assertIn(cat_id, fc_cat_ids)

    def test_fingerprint_sufficiency_enforcement(self):
        """Fingerprint returns available=False when sample size is insufficient."""
        cat_id = CategoryRepository.create("Dining", "expense", "utensils", "#FF9500")
        # Add only 5 transactions (threshold is 30)
        for i in range(1, 6):
            TransactionRepository.create({
                "account_id": self.acc_id,
                "category_id": cat_id,
                "amount": 15.0,
                "transaction_type": "expense",
                "transaction_date": f"2026-08-{i:02d}",
                "description": f"Snack {i}"
            })
        
        fp = SpendingFingerprintEngine.generate_fingerprint(months_window=6, account_id=self.acc_id, as_of_month="2026-08")
        self.assertFalse(fp["available"])
        self.assertEqual(fp["data_sufficiency"]["available"], False)
        self.assertIn("Insufficient", fp["data_sufficiency"]["reason"])

    def test_anomaly_overall_baseline_fallback(self):
        """Transactions without merchant or category baseline fall back to overall baseline."""
        # Create 25 historical transactions of ~$10 across various categories
        cat1 = CategoryRepository.create("Cat A", "expense", "tag", "#34C759")
        cat2 = CategoryRepository.create("Cat B", "expense", "tag", "#5856D6")

        for m in ["2026-06", "2026-07"]:
            for d in range(1, 13):
                TransactionRepository.create({
                    "account_id": self.acc_id,
                    "category_id": cat1 if d % 2 == 0 else cat2,
                    "amount": 10.0,
                    "transaction_type": "expense",
                    "transaction_date": f"{m}-{d:02d}",
                    "description": f"Item {m}-{d}"
                })

        # In current month 2026-08, create a transaction with an uncategorized merchant with no prior history
        # but a huge amount ($500 vs usual $10)
        new_cat = CategoryRepository.create("New Cat Without History", "expense", "tag", "#AF52DE")
        tx_id = TransactionRepository.create({
            "account_id": self.acc_id,
            "category_id": new_cat,
            "amount": 500.0,
            "transaction_type": "expense",
            "transaction_date": "2026-08-05",
            "description": "One-off Mega Expense"
        })

        anomalies = AnomalyDetectionEngine.detect_anomalies("2026-08", account_id=self.acc_id)
        # Should detect the anomaly using overall baseline
        found = [a for a in anomalies if a["entity_id"] == tx_id]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["anomaly_type"], "transaction_amount")
        self.assertIn("overall typical spending", found[0]["explanation"])

if __name__ == "__main__":
    unittest.main()
