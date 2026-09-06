import os
import csv
import unittest
from pathlib import Path
from app.backend.database.connection import get_db_connection, init_db
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.services.backup_service import BackupService

class TestExportSecurity(unittest.TestCase):
    def setUp(self):
        init_db()
        with get_db_connection() as conn:
            conn.execute("DELETE FROM transactions")
            conn.execute("DELETE FROM accounts")
        self.acc_id = AccountRepository.create("Safe Account", "Everyday", "Bank A", 1000.0, "USD")
        self.cat_id = CategoryRepository.create("General", "expense", "tag", "#007AFF")

    def test_csv_injection_sanitization(self):
        """String fields starting with =, +, -, @ must be prefixed with single quote in CSV export."""
        # Insert a transaction with formula injection payloads in description and note
        tx_id = TransactionRepository.create({
            "account_id": self.acc_id,
            "category_id": self.cat_id,
            "amount": 25.50,
            "transaction_type": "expense",
            "transaction_date": "2026-09-01",
            "description": "=cmd|' /C calc'!A0",
            "note": "@SUM(1+1)"
        })

        # Also insert one with + and - in descriptions
        TransactionRepository.create({
            "account_id": self.acc_id,
            "category_id": self.cat_id,
            "amount": 10.00,
            "transaction_type": "expense",
            "transaction_date": "2026-09-02",
            "description": "+123456",
            "note": "-Important Note"
        })

        csv_path = BackupService.export_csv(month="2026-09", account_id=self.acc_id)
        self.assertTrue(os.path.exists(csv_path))

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        self.assertEqual(len(rows), 2)
        
        # Check that dangerous leading formula characters were neutralized
        calc_row = next(r for r in rows if "calc" in r["Description"])
        self.assertTrue(calc_row["Description"].startswith("'="), f"Expected '=, got {calc_row['Description']}")
        self.assertTrue(calc_row["Note"].startswith("'@"), f"Expected '@, got {calc_row['Note']}")

        plus_row = next(r for r in rows if "123456" in r["Description"])
        self.assertTrue(plus_row["Description"].startswith("'+"), f"Expected '+, got {plus_row['Description']}")
        self.assertTrue(plus_row["Note"].startswith("'-"), f"Expected '-, got {plus_row['Note']}")

        # Clean up exported CSV
        try:
            os.remove(csv_path)
        except OSError:
            pass

if __name__ == "__main__":
    unittest.main()
