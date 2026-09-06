"""
Financial Integrity Service for FinScope CORE.
Provides automated diagnostic checks for financial invariants:
1. Orphan or asymmetric transfer legs
2. Cross-transfer currency and balance discrepancies
3. Over-refunded original expense transactions
4. Missing base currency valuations on active transactions
5. Category budget denomination consistency with Base/Reporting Currency
"""

from typing import Dict, Any, List, Optional
import sqlite3
from app.backend.database.connection import get_db_connection
from app.backend.services.settings_service import SettingsService


class IntegrityService:
    @staticmethod
    def run_diagnostics(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
        """
        Executes lightweight, read-only financial invariant checks.
        Can run within an existing connection or open a new one.
        """
        if conn is not None:
            return IntegrityService._check_all(conn)

        with get_db_connection() as c:
            return IntegrityService._check_all(c)

    @staticmethod
    def _check_all(conn: sqlite3.Connection) -> Dict[str, Any]:
        cur = conn.cursor()
        issues: List[str] = []

        # 1. Check for Orphan or Malformed Transfers
        cur.execute("""
            SELECT transfer_group_id, COUNT(*) as cnt
            FROM transactions
            WHERE transaction_type = 'transfer' AND is_deleted = 0
            GROUP BY transfer_group_id
            HAVING cnt != 2 OR transfer_group_id IS NULL
        """)
        orphan_groups = [r[0] for r in cur.fetchall()]
        if orphan_groups:
            issues.append(f"Found {len(orphan_groups)} transfer group(s) with asymmetric or orphan legs.")

        # 2. Check Same-Currency Transfer Amount Discrepancy
        cur.execute("""
            SELECT t1.transfer_group_id, t1.amount_minor, t2.amount_minor, a1.currency, a2.currency
            FROM transactions t1
            JOIN transactions t2 ON t1.transfer_group_id = t2.transfer_group_id AND t1.id < t2.id
            JOIN accounts a1 ON t1.account_id = a1.id
            JOIN accounts a2 ON t2.account_id = a2.id
            WHERE t1.transaction_type = 'transfer' AND t2.transaction_type = 'transfer'
              AND t1.is_deleted = 0 AND t2.is_deleted = 0
              AND a1.currency = a2.currency
              AND t1.amount_minor != t2.amount_minor
        """)
        mismatched_transfers = cur.fetchall()
        if mismatched_transfers:
            issues.append(f"Found {len(mismatched_transfers)} same-currency transfer(s) with differing leg amounts.")

        # 3. Check Over-Refunded Expense Transactions
        cur.execute("""
            SELECT orig.id,
                   COALESCE(orig.original_amount_minor, orig.amount_minor) AS orig_minor,
                   SUM(COALESCE(ref.original_amount_minor, ref.amount_minor)) AS total_refunded_minor
            FROM transactions orig
            JOIN transactions ref ON ref.refund_of_transaction_id = orig.id
            WHERE orig.is_deleted = 0 AND ref.is_deleted = 0 AND ref.transaction_type = 'refund'
            GROUP BY orig.id
            HAVING total_refunded_minor > orig_minor
        """)
        over_refunded = cur.fetchall()
        if over_refunded:
            issues.append(f"Found {len(over_refunded)} expense transaction(s) with cumulative refunds exceeding original amount.")

        # 4. Check Missing Base Currency Valuations on Active Transactions
        cur.execute("""
            SELECT COUNT(*)
            FROM transactions
            WHERE is_deleted = 0
              AND (base_amount_minor IS NULL OR base_currency IS NULL OR base_currency = '')
        """)
        missing_base_count = cur.fetchone()[0]
        if missing_base_count > 0:
            issues.append(f"Found {missing_base_count} active transaction(s) missing base currency valuation.")

        # 5. Check Budget Currency Consistency
        base_currency = SettingsService.get_setting("currency", "USD") or "USD"
        cur.execute("""
            SELECT COUNT(*)
            FROM budgets
            WHERE currency IS NOT NULL AND currency != ?
        """, (base_currency,))
        inconsistent_budgets = cur.fetchone()[0]
        if inconsistent_budgets > 0:
            issues.append(f"Found {inconsistent_budgets} category budget(s) denominated in non-base currency ({base_currency}).")

        is_healthy = len(issues) == 0

        return {
            "is_healthy": is_healthy,
            "issues_count": len(issues),
            "issues": issues,
            "details": {
                "orphan_transfer_groups": len(orphan_groups),
                "mismatched_transfers": len(mismatched_transfers),
                "over_refunded_transactions": len(over_refunded),
                "missing_base_valuations": missing_base_count,
                "inconsistent_budgets": inconsistent_budgets
            }
        }
