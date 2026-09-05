"""
Automated Test Suite for FinScope CORE Engine.
Verifies Migration 002, Merchant Intelligence & Memory, Financial Semantics,
Double-Entry Transfers with Roles, Linked Refunds, Review Queue, and Non-blocking Undo Delete.
"""

import os
import shutil
import unittest
from pathlib import Path

# Use isolated test data directory
TEST_DIR = Path(__file__).parent / "core_test_data"
if TEST_DIR.exists():
    try:
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    except Exception:
        pass
os.environ["FINSCOPE_DATA_DIR"] = str(TEST_DIR)

from app.backend import config
from app.backend.database.connection import get_db_connection, init_db
from app.backend.services.merchant_service import (
    normalize_merchant_name,
    get_or_create_merchant,
    suggest_merchants,
    get_recent_payees
)
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.analytics.semantics import calculate_net_spending


class TestCoreEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if TEST_DIR.exists():
            shutil.rmtree(TEST_DIR, ignore_errors=True)
        TEST_DIR.mkdir(parents=True, exist_ok=True)
        os.environ["FINSCOPE_DATA_DIR"] = str(TEST_DIR)
        config.set_data_dir(TEST_DIR)
        init_db()
        cls.account_repo = AccountRepository()
        cls.category_repo = CategoryRepository()
        cls.tx_repo = TransactionRepository()

        # Setup seed test accounts
        cls.acc_checking_id = cls.account_repo.create("Everyday Checking", "checking", opening_balance=1000.00)
        cls.acc_savings_id = cls.account_repo.create("High Yield Savings", "savings", opening_balance=5000.00)

        # Setup seed test categories
        cls.cat_groceries_id = cls.category_repo.create("Groceries", "expense", icon="shopping-cart", color="#4CAF50")
        cls.cat_tech_id = cls.category_repo.create("Electronics & Tech", "expense", icon="laptop", color="#2196F3")

    def test_01_migration_002_schema_integrity(self):
        """Verify Migration 002 columns and system Uncategorized category."""
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Check transactions columns
            cursor.execute("PRAGMA table_info(transactions)")
            tx_cols = {row["name"] for row in cursor.fetchall()}
            self.assertIn("transfer_role", tx_cols)
            self.assertIn("refund_of_transaction_id", tx_cols)
            self.assertIn("source", tx_cols)
            self.assertIn("needs_review", tx_cols)
            self.assertIn("is_deleted", tx_cols)

            # Check merchants columns
            cursor.execute("PRAGMA table_info(merchants)")
            m_cols = {row["name"] for row in cursor.fetchall()}
            self.assertIn("preferred_account_id", m_cols)
            self.assertIn("default_essentiality", m_cols)

            # Check merchant_rules table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='merchant_rules'")
            self.assertIsNotNone(cursor.fetchone())

        # Check Uncategorized category
        uncat = self.category_repo.get_by_name("Uncategorized")
        self.assertIsNotNone(uncat)
        self.assertEqual(uncat["name"], "Uncategorized")
        self.assertEqual(uncat["type"], "expense")
        self.assertEqual(uncat["icon"], "help-circle")

    def test_02_merchant_name_normalization(self):
        """Verify merchant normalization strips store codes, cleans casing, and removes noise."""
        self.assertEqual(normalize_merchant_name("Woolworths 1245"), "Woolworths")
        self.assertEqual(normalize_merchant_name("WOOLWORTHS STORE #49"), "Woolworths")
        self.assertEqual(normalize_merchant_name("mcdonalds"), "McDonalds")
        self.assertEqual(normalize_merchant_name("UBER *EATS SYDNEY"), "Uber Eats")
        self.assertEqual(normalize_merchant_name("  Starbucks Coffee   "), "Starbucks Coffee")
        self.assertEqual(normalize_merchant_name("7-Eleven 3481"), "7-Eleven")
        self.assertEqual(normalize_merchant_name(""), "")

    def test_03_merchant_memory_and_suggestions(self):
        """Verify canonical merchant storage, smart defaults memory, and autocomplete suggestions."""
        # Record canonical merchant with defaults
        m_id = get_or_create_merchant(
            "Woolworths Store #102",
            category_id=self.cat_groceries_id,
            account_id=self.acc_checking_id,
            essentiality="essential"
        )
        self.assertGreater(m_id, 0)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name, default_category_id, preferred_account_id, default_essentiality FROM merchants WHERE id = ?", (m_id,))
            m = cursor.fetchone()
            self.assertEqual(m["name"], "Woolworths")
            self.assertEqual(m["default_category_id"], self.cat_groceries_id)
            self.assertEqual(m["preferred_account_id"], self.acc_checking_id)
            self.assertEqual(m["default_essentiality"], "essential")

        # Test suggestions autocomplete
        res = suggest_merchants("wool", limit=5)
        self.assertTrue(len(res) > 0)
        first = res[0]
        self.assertEqual(first["name"], "Woolworths")
        self.assertEqual(first["confidence"], "high")
        self.assertEqual(first["category_id"], self.cat_groceries_id)
        self.assertEqual(first["account_id"], self.acc_checking_id)

        # Also create a transaction with Woolworths so recent payees picks it up
        self.tx_repo.create({
            "account_id": self.acc_checking_id,
            "category_id": self.cat_groceries_id,
            "merchant_name": "Woolworths",
            "transaction_type": "expense",
            "amount": 55.20,
            "transaction_date": "2026-09-02",
            "description": "Weekly food"
        })

        # Test recent payees
        recent = get_recent_payees(limit=5)
        names = [r["merchant_name"] for r in recent]
        self.assertIn("Woolworths", names)

    def test_04_uncategorized_fallback_and_review_queue(self):
        """Verify fallback to Uncategorized with needs_review=1 and review resolution."""
        # Create an expense with NO category
        tx_id = self.tx_repo.create({
            "account_id": self.acc_checking_id,
            "category_id": None,
            "merchant_name": "Corner Kiosk",
            "transaction_type": "expense",
            "amount": 14.50,
            "transaction_date": "2026-09-02",
            "description": "Quick snack"
        })

        tx = self.tx_repo.get_by_id(tx_id)
        self.assertEqual(tx["needs_review"], 1)
        uncat = self.category_repo.get_by_name("Uncategorized")
        self.assertEqual(tx["category_id"], uncat["id"])

        # Verify it appears in Review Queue
        queue = self.tx_repo.get_review_queue()
        queue_ids = [item["id"] for item in queue["items"]]
        self.assertIn(tx_id, queue_ids)

        # Resolve review
        res = self.tx_repo.resolve_review(tx_id, self.cat_groceries_id, "discretionary")
        self.assertTrue(res)

        # Verify transaction updated
        updated_tx = self.tx_repo.get_by_id(tx_id)
        self.assertEqual(updated_tx["category_id"], self.cat_groceries_id)
        self.assertEqual(updated_tx["needs_review"], 0)
        self.assertEqual(updated_tx["essentiality"], "discretionary")

        # Verify it disappeared from Review Queue
        new_queue = self.tx_repo.get_review_queue()
        new_queue_ids = [item["id"] for item in new_queue["items"]]
        self.assertNotIn(tx_id, new_queue_ids)

    def test_05_double_entry_transfers_with_explicit_roles(self):
        """Verify transfers generate paired entries with 'source' and 'destination' roles."""
        trans = self.tx_repo.create_transfer(
            from_account_id=self.acc_checking_id,
            to_account_id=self.acc_savings_id,
            amount=250.00,
            transaction_date="2026-09-03",
            description="Monthly Savings Contribution"
        )

        source_leg = trans["source_transaction"]
        dest_leg = trans["destination_transaction"]

        self.assertEqual(source_leg["transfer_role"], "source")
        self.assertEqual(dest_leg["transfer_role"], "destination")
        self.assertEqual(source_leg["linked_transaction_id"], dest_leg["id"])
        self.assertEqual(dest_leg["linked_transaction_id"], source_leg["id"])
        self.assertEqual(source_leg["transfer_group_id"], dest_leg["transfer_group_id"])
        self.assertEqual(source_leg["amount"], 250.00)
        self.assertEqual(dest_leg["amount"], 250.00)

        # Verify account balances reflect transfer
        bal_checking = self.account_repo.get_balance(self.acc_checking_id)
        bal_savings = self.account_repo.get_balance(self.acc_savings_id)
        # Checking: initial 1000 - 55.20 (groceries) - 14.50 (snack) - 250 (transfer) = 680.30
        self.assertAlmostEqual(bal_checking, 680.30)
        # Savings: initial 5000 + 250 (transfer) = 5250.00
        self.assertAlmostEqual(bal_savings, 5250.00)

    def test_06_linked_refunds_and_pnl_semantics(self):
        """Verify linked refund inherits category/merchant and reduces net spending."""
        # Create an original purchase
        orig_id = self.tx_repo.create({
            "account_id": self.acc_checking_id,
            "category_id": self.cat_tech_id,
            "merchant_name": "JB Hi-Fi",
            "transaction_type": "expense",
            "amount": 120.00,
            "transaction_date": "2026-09-01",
            "description": "Wireless Headphones"
        })
        orig_tx = self.tx_repo.get_by_id(orig_id)

        # Record a partial linked refund
        refund_id = self.tx_repo.create_refund(
            original_tx_id=orig_id,
            amount=40.00,
            account_id=self.acc_checking_id,
            transaction_date="2026-09-04"
        )
        refund_tx = self.tx_repo.get_by_id(refund_id)

        self.assertEqual(refund_tx["transaction_type"], "refund")
        self.assertEqual(refund_tx["refund_of_transaction_id"], orig_id)
        self.assertEqual(refund_tx["category_id"], self.cat_tech_id)
        self.assertEqual(refund_tx["merchant_name"], "JB Hi-Fi")

        # Test Analytics semantics for net spending
        net_spent_minor = calculate_net_spending(orig_tx["amount_minor"], refund_tx["amount_minor"])
        self.assertEqual(net_spent_minor, 8000)  # $120.00 - $40.00 = $80.00

    def test_07_soft_delete_and_undo_delete_window(self):
        """Verify non-destructive soft delete, exclusion from balance, and atomic undo."""
        tx_id = self.tx_repo.create({
            "account_id": self.acc_checking_id,
            "category_id": self.cat_groceries_id,
            "merchant_name": "Coles",
            "transaction_type": "expense",
            "amount": 35.00,
            "transaction_date": "2026-09-04",
            "description": "Bakery goods"
        })

        bal_before = self.account_repo.get_balance(self.acc_checking_id)

        # Soft delete
        deleted = self.tx_repo.delete(tx_id)
        self.assertTrue(deleted)

        # Verify transaction is excluded from get_by_id and list
        self.assertIsNone(self.tx_repo.get_by_id(tx_id))
        bal_after_delete = self.account_repo.get_balance(self.acc_checking_id)
        self.assertAlmostEqual(bal_after_delete, bal_before + 35.00)

        # Undo delete
        restored = self.tx_repo.undo_delete(tx_id)
        self.assertTrue(restored)

        # Verify transaction is restored
        restored_tx = self.tx_repo.get_by_id(tx_id)
        self.assertIsNotNone(restored_tx)
        self.assertEqual(restored_tx["is_deleted"], 0)
        bal_after_undo = self.account_repo.get_balance(self.acc_checking_id)
        self.assertAlmostEqual(bal_after_undo, bal_before)


if __name__ == "__main__":
    unittest.main()
