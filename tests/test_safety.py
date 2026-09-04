import sys
import os
import unittest
import zipfile
import sqlite3
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Use isolated test data folder
TEST_DATA_DIR = PROJECT_ROOT / "data_safety_test"
os.environ["FINSCOPE_DATA_DIR"] = str(TEST_DATA_DIR)

from app.backend.database.connection import init_db, get_db_connection
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.services.analytics_service import AnalyticsService
from app.backend.services.backup_service import BackupService
from app.backend.services.settings_service import SettingsService

import shutil

class TestFinScopeSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FINSCOPE_DATA_DIR"] = str(TEST_DATA_DIR)
        if TEST_DATA_DIR.exists():
            shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
        TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
        init_db()
        AccountRepository.create(name="Everyday Checking", account_type="depository", opening_balance=2500.0)
        AccountRepository.create(name="High Yield Savings", account_type="depository", opening_balance=10000.0)
        AccountRepository.create(name="Credit Card", account_type="credit", opening_balance=0.0)

    def test_01_money_minor_units_exact_arithmetic(self):
        """Verifies that monetary amounts are stored as exact integer cents without float drift."""
        accounts = AccountRepository.get_all()
        categories = CategoryRepository.get_all(cat_type="expense")
        acc_id = accounts[0]["id"]
        cat_id = categories[0]["id"]

        # Insert 0.10 and 0.20
        tx1 = TransactionRepository.create({
            "account_id": acc_id,
            "category_id": cat_id,
            "merchant_name": "Test Float 1",
            "transaction_type": "expense",
            "amount": 0.10,
            "transaction_date": "2026-09-01"
        })
        tx2 = TransactionRepository.create({
            "account_id": acc_id,
            "category_id": cat_id,
            "merchant_name": "Test Float 2",
            "transaction_type": "expense",
            "amount": 0.20,
            "transaction_date": "2026-09-01"
        })

        t1 = TransactionRepository.get_by_id(tx1)
        t2 = TransactionRepository.get_by_id(tx2)

        self.assertEqual(t1["amount_minor"], 10)
        self.assertEqual(t2["amount_minor"], 20)
        self.assertEqual(t1["amount"], 0.10)
        self.assertEqual(t2["amount"], 0.20)

        # Sum in analytics
        summary = AnalyticsService.get_month_summary("2026-09")
        self.assertGreaterEqual(summary["kpis"]["expense"], 0.30)

    def test_02_double_entry_transfer_accounting(self):
        """Verifies transfers move money between accounts without distorting income/expense analytics."""
        acc1_id = AccountRepository.create("Checking A", "Everyday", "Bank A", opening_balance=1000.0)
        acc2_id = AccountRepository.create("Savings B", "Savings", "Bank B", opening_balance=0.0)

        # Record pre-transfer summary
        pre_summary = AnalyticsService.get_month_summary("2026-09")
        pre_income = pre_summary["kpis"]["income"]
        pre_expense = pre_summary["kpis"]["expense"]

        # Transfer $500 from A to B
        transfer_res = TransactionRepository.create_transfer(
            from_account_id=acc1_id,
            to_account_id=acc2_id,
            amount=500.0,
            transaction_date="2026-09-05",
            description="Relocate savings"
        )
        self.assertIn("transfer_group_id", transfer_res)

        # Verify account balances
        accounts = {a["id"]: a for a in AccountRepository.get_all()}
        self.assertEqual(accounts[acc1_id]["current_balance"], 500.0)
        self.assertEqual(accounts[acc2_id]["current_balance"], 500.0)

        # Verify analytics: Income and Expense must be completely unaffected by the transfer!
        post_summary = AnalyticsService.get_month_summary("2026-09")
        self.assertEqual(post_summary["kpis"]["income"], pre_income)
        self.assertEqual(post_summary["kpis"]["expense"], pre_expense)

        # Verify clean deletion: deleting one leg deletes the linked leg too
        leg1_id = transfer_res["outflow_tx_id"]
        TransactionRepository.delete(leg1_id)
        self.assertIsNone(TransactionRepository.get_by_id(leg1_id))
        self.assertIsNone(TransactionRepository.get_by_id(transfer_res["inflow_tx_id"]))

    def test_03_refund_financial_semantics(self):
        """Verifies that refunds offset category expenses and are not falsely counted as income."""
        accounts = AccountRepository.get_all()
        categories = CategoryRepository.get_all(cat_type="expense")
        acc_id = accounts[0]["id"]
        cat_id = categories[0]["id"]

        summary_before = AnalyticsService.get_month_summary("2026-08")
        base_expense = summary_before["kpis"]["expense"]
        base_income = summary_before["kpis"]["income"]

        # Expense of $200
        tx_exp = TransactionRepository.create({
            "account_id": acc_id,
            "category_id": cat_id,
            "merchant_name": "Department Store",
            "transaction_type": "expense",
            "amount": 200.0,
            "transaction_date": "2026-08-10"
        })

        # Refund of $80 for the item
        tx_ref = TransactionRepository.create({
            "account_id": acc_id,
            "category_id": cat_id,
            "merchant_name": "Department Store Refund",
            "transaction_type": "refund",
            "amount": 80.0,
            "transaction_date": "2026-08-12"
        })

        summary_after = AnalyticsService.get_month_summary("2026-08")

        # Income must remain completely unchanged
        self.assertEqual(summary_after["kpis"]["income"], base_income)
        # Net expense must increase by exactly 200 - 80 = 120
        self.assertAlmostEqual(summary_after["kpis"]["expense"], base_expense + 120.0, places=2)

    def test_04_sqlite_wal_backup_roundtrip(self):
        """Verifies that Connection.backup() safely captures uncheckpointed WAL records and restores them."""
        # Add a unique canary transaction in active WAL mode
        accounts = AccountRepository.get_all()
        acc_id = accounts[0]["id"]
        canary_desc = "Canary WAL Unique Test Record 998877"

        canary_id = TransactionRepository.create({
            "account_id": acc_id,
            "merchant_name": "WAL Canary Merchant",
            "transaction_type": "income",
            "amount": 1234.56,
            "transaction_date": "2026-09-02",
            "description": canary_desc
        })

        # Create verified backup
        backup_res = BackupService.create_backup()
        self.assertTrue(backup_res["success"])
        backup_path = backup_res["filepath"]

        # Verify archive contains finance.db and metadata.json
        with zipfile.ZipFile(backup_path, "r") as zf:
            self.assertIn("finance.db", zf.namelist())
            self.assertIn("metadata.json", zf.namelist())

        # Wipe canary from database
        TransactionRepository.delete(canary_id)
        self.assertIsNone(TransactionRepository.get_by_id(canary_id))

        # Restore from backup
        restore_res = BackupService.restore_backup(backup_path)
        self.assertTrue(restore_res["success"])

        # Confirm safety backup was created as a genuine zip archive
        safety_path = Path(backup_path).parent / restore_res["safety_backup"]
        self.assertTrue(safety_path.exists())
        self.assertTrue(zipfile.is_zipfile(safety_path))

        # Verify canary is 100% restored
        restored_tx = TransactionRepository.get_by_id(canary_id)
        self.assertIsNotNone(restored_tx)
        self.assertEqual(restored_tx["description"], canary_desc)
        self.assertEqual(restored_tx["amount"], 1234.56)

    def test_05_corrupt_backup_rejection(self):
        """Verifies that corrupt or invalid backup files are rejected before affecting live DB."""
        fake_backup = TEST_DATA_DIR / "backups" / "corrupted_test.financebackup"
        fake_backup.parent.mkdir(parents=True, exist_ok=True)
        with open(fake_backup, "wb") as f:
            f.write(b"NOT A VALID ZIP OR SQLITE ARCHIVE")

        with self.assertRaises(Exception):
            BackupService.restore_backup(str(fake_backup))

    def test_06_configurable_currency(self):
        """Verifies currency setting can be saved and retrieved."""
        SettingsService.set_setting("currency", "VND")
        self.assertEqual(SettingsService.get_setting("currency"), "VND")
        SettingsService.set_setting("currency", "USD")
        self.assertEqual(SettingsService.get_setting("currency"), "USD")

if __name__ == "__main__":
    unittest.main()
