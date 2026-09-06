import unittest
import threading
import time
from app.backend.analytics.forecast_replay import LRUCache
from app.backend.database.maintenance import MaintenanceCoordinator
from app.backend.database.connection import get_db_connection, init_db
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.services.transfer_service import TransferService
from app.backend.domain.validators import validate_category_for_transaction

class TestV121Remediation(unittest.TestCase):
    def setUp(self):
        init_db()
        with get_db_connection() as conn:
            conn.execute("DELETE FROM transactions")
            conn.execute("DELETE FROM accounts")
            conn.execute("DELETE FROM categories WHERE id > 20")

    def test_lru_cache_composition_eviction_and_order(self):
        """PR 1: LRUCache correctly bounds capacity and maintains LRU order via composition."""
        cache = LRUCache(maxsize=3)
        cache["k1"] = "v1"
        cache["k2"] = "v2"
        cache["k3"] = "v3"
        self.assertEqual(len(cache), 3)

        # Access k1 to make it most recently used
        val = cache.get("k1")
        self.assertEqual(val, "v1")

        # Insert k4 -> should evict k2 (the oldest)
        cache["k4"] = "v4"
        self.assertEqual(len(cache), 3)
        self.assertIn("k1", cache)
        self.assertNotIn("k2", cache)
        self.assertIn("k3", cache)
        self.assertIn("k4", cache)

        # Deletion works
        del cache["k3"]
        self.assertEqual(len(cache), 2)
        self.assertNotIn("k3", cache)

        # Clear works
        cache.clear()
        self.assertEqual(len(cache), 0)

    def test_maintenance_coordinator_exclusive_concurrency(self):
        """PR 2: Multiple concurrent exclusive tasks cannot run simultaneously and recover cleanly."""
        mc = MaintenanceCoordinator()
        execution_trace = []

        def task(name, delay):
            with mc.exclusive():
                execution_trace.append(f"{name}_start")
                time.sleep(delay)
                execution_trace.append(f"{name}_end")

        t1 = threading.Thread(target=task, args=("task1", 0.04))
        t2 = threading.Thread(target=task, args=("task2", 0.02))

        t1.start()
        time.sleep(0.005)
        t2.start()

        t1.join()
        t2.join()

        # Task 1 must finish before task 2 starts
        self.assertIn("task1_start", execution_trace)
        self.assertIn("task1_end", execution_trace)
        self.assertIn("task2_start", execution_trace)
        self.assertIn("task2_end", execution_trace)
        self.assertTrue(
            execution_trace.index("task1_end") < execution_trace.index("task2_start"),
            f"Execution trace violated exclusivity: {execution_trace}"
        )
        self.assertFalse(mc.is_maintenance)

    def test_transfer_pair_hydration_in_get_by_id(self):
        """PR 4 & V121-M03: get_by_id on either transfer leg hydrates linked account and amount."""
        acc_from = AccountRepository.create("Checking", "Everyday", "Bank A", 500.0, "USD")
        acc_to = AccountRepository.create("Savings", "Savings", "Bank B", 1000.0, "USD")

        res = TransferService.create_transfer(
            from_account_id=acc_from,
            to_account_id=acc_to,
            amount=150.0,
            transaction_date="2026-09-02",
            description="Monthly savings"
        )
        source_id = res["source_transaction"]["id"]
        dest_id = res["destination_transaction"]["id"]

        # Fetch source leg
        tx_source = TransactionRepository.get_by_id(source_id)
        self.assertIsNotNone(tx_source)
        self.assertEqual(tx_source["transfer_role"], "source")
        self.assertEqual(tx_source["account_id"], acc_from)
        self.assertEqual(tx_source["linked_account_id"], acc_to)
        self.assertEqual(tx_source["linked_account_name"], "Savings")
        self.assertEqual(tx_source["from_account_id"], acc_from)
        self.assertEqual(tx_source["to_account_id"], acc_to)
        self.assertEqual(tx_source["destination_amount"], 150.0)

        # Fetch destination leg
        tx_dest = TransactionRepository.get_by_id(dest_id)
        self.assertIsNotNone(tx_dest)
        self.assertEqual(tx_dest["transfer_role"], "destination")
        self.assertEqual(tx_dest["account_id"], acc_to)
        self.assertEqual(tx_dest["linked_account_id"], acc_from)
        self.assertEqual(tx_dest["linked_account_name"], "Checking")
        self.assertEqual(tx_dest["from_account_id"], acc_from)
        self.assertEqual(tx_dest["to_account_id"], acc_to)
        self.assertEqual(tx_dest["destination_amount"], 150.0)

    def test_category_type_compatibility_validation(self):
        """PR 7: Category type matching is enforced strictly for expense, income, and refund."""
        exp_cat = CategoryRepository.create("Groceries", "expense", "cart", "#FF0000")
        inc_cat = CategoryRepository.create("Freelance", "income", "briefcase", "#00FF00")

        with get_db_connection() as conn:
            # Expense transaction with expense category: OK
            cat = validate_category_for_transaction(conn, exp_cat, "expense")
            self.assertEqual(cat, exp_cat)

            # Income transaction with income category: OK
            cat = validate_category_for_transaction(conn, inc_cat, "income")
            self.assertEqual(cat, inc_cat)

            # Refund transaction with expense category: OK
            cat = validate_category_for_transaction(conn, exp_cat, "refund")
            self.assertEqual(cat, exp_cat)

            # Expense transaction with income category: REJECT
            with self.assertRaises(ValueError) as cm:
                validate_category_for_transaction(conn, inc_cat, "expense")
            self.assertIn("expense transactions require a expense category", str(cm.exception))

            # Income transaction with expense category: REJECT
            with self.assertRaises(ValueError) as cm:
                validate_category_for_transaction(conn, exp_cat, "income")
            self.assertIn("income transactions require a income category", str(cm.exception))

            # Refund transaction with income category: REJECT
            with self.assertRaises(ValueError) as cm:
                validate_category_for_transaction(conn, inc_cat, "refund")
            self.assertIn("refund transactions require a expense category", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
