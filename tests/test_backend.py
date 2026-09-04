import sys
import os
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Use a test database
os.environ["FINSCOPE_DATA_DIR"] = str(PROJECT_ROOT / "data_test")

from app.backend.database.connection import init_db, get_db_connection
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.repositories.budget_repo import BudgetRepository
from app.backend.services.analytics_service import AnalyticsService
from app.backend.services.budget_service import BudgetService
import shutil
from app.backend.services.backup_service import BackupService
from app.backend.services.sample_data import seed_sample_data
from app.backend.api.handler import ApiHandler

class TestFinScopeBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_dir = PROJECT_ROOT / "data_test"
        os.environ["FINSCOPE_DATA_DIR"] = str(test_dir)
        if test_dir.exists():
            shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        init_db()
        seed_sample_data()

    def test_01_default_accounts_and_categories(self):
        accounts = AccountRepository.get_all()
        self.assertGreaterEqual(len(accounts), 3)
        categories = CategoryRepository.get_all()
        self.assertGreaterEqual(len(categories), 10)

    def test_02_transaction_crud(self):
        accounts = AccountRepository.get_all()
        categories = CategoryRepository.get_all(cat_type="expense")
        acc_id = accounts[0]["id"]
        cat_id = categories[0]["id"]

        # Create
        tx_id = TransactionRepository.create({
            "account_id": acc_id,
            "category_id": cat_id,
            "merchant_name": "Test Supermarket",
            "transaction_type": "expense",
            "amount": 75.50,
            "transaction_date": "2026-09-04",
            "description": "Weekly grocery shopping",
            "essentiality": "essential"
        })
        self.assertIsNotNone(tx_id)

        # Read
        tx = TransactionRepository.get_by_id(tx_id)
        self.assertIsNotNone(tx)
        self.assertEqual(tx["merchant_name"], "Test Supermarket")
        self.assertEqual(tx["amount"], 75.50)

        # Update
        updated = TransactionRepository.update(tx_id, {"amount": 85.00, "note": "Updated with receipt"})
        self.assertTrue(updated)
        tx_after = TransactionRepository.get_by_id(tx_id)
        self.assertEqual(tx_after["amount"], 85.00)

        # Duplicate
        dup_id = TransactionRepository.duplicate(tx_id)
        self.assertIsNotNone(dup_id)
        dup_tx = TransactionRepository.get_by_id(dup_id)
        self.assertIn("(Copy)", dup_tx["description"])

        # Delete duplicate
        deleted = TransactionRepository.delete(dup_id)
        self.assertTrue(deleted)

    def test_03_sample_data_and_analytics(self):
        # Seed realistic data
        res = seed_sample_data(clear_existing=True)
        self.assertTrue(res["success"])

        # Test Analytics Month Summary
        summary = AnalyticsService.get_month_summary("2026-09")
        self.assertIn("kpis", summary)
        self.assertGreater(summary["kpis"]["income"], 0)
        self.assertGreater(summary["kpis"]["expense"], 0)
        self.assertIn("trend", summary)
        self.assertIn("categories", summary)

        # Test Calendar Data
        cal = AnalyticsService.get_calendar_data("2026-09")
        self.assertIn("days", cal)
        self.assertGreater(len(cal["days"]), 0)

        # Test Deep Dive
        deep_dive = AnalyticsService.get_analytics_deep_dive("2026-09")
        self.assertIn("variance", deep_dive)
        self.assertIn("weekday", deep_dive)
        self.assertIn("cumulative", deep_dive)
        self.assertIn("merchants", deep_dive)
        self.assertEqual(len(deep_dive["weekday"]), 7)

    def test_04_budget_service(self):
        status = BudgetService.get_monthly_budget_status("2026-09")
        self.assertIn("summary", status)
        self.assertIn("items", status)
        self.assertGreater(len(status["items"]), 0)
        self.assertIn("consumed_pct", status["summary"])

    def test_05_backup_and_export(self):
        backup_res = BackupService.create_backup()
        self.assertTrue(backup_res["success"])
        self.assertTrue(os.path.exists(backup_res["filepath"]))

        csv_path = BackupService.export_csv()
        self.assertTrue(os.path.exists(csv_path))

        health = BackupService.get_storage_health()
        self.assertEqual(health["status"], "Healthy")
        self.assertGreater(health["transaction_count"], 0)

if __name__ == "__main__":
    unittest.main()
