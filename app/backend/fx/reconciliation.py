"""
Offline-First FX Reconciliation Service for FinScope CORE (WP-06 / P0-09).
Reconciles transactions with fx_status in ('pending', 'pending_revaluation')
once connectivity or historical exchange rates become available.
"""

from datetime import datetime
from typing import Dict, Any, List
from app.backend.database.connection import get_db_connection
from app.backend.fx.service import FxService
from app.backend.services.settings_service import SettingsService

class FxReconciliationService:
    @staticmethod
    def reconcile_pending_fx(limit: int = 200) -> Dict[str, Any]:
        """
        Scans for transactions pending FX valuation and calculates exact base_amount_minor.
        """
        reconciled_count = 0
        failed_count = 0

        # Step 1: Read pending rows and immediately release connection/lock (P1-24)
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    t.id, t.amount_minor, t.transaction_date, t.original_amount_minor,
                    t.original_currency, t.base_currency, t.fx_status,
                    a.currency as account_currency
                FROM transactions t
                JOIN accounts a ON t.account_id = a.id
                WHERE t.is_deleted = 0
                  AND (
                      t.fx_status IN ('pending', 'pending_revaluation')
                      OR (t.base_amount_minor IS NULL AND a.currency <> t.base_currency)
                  )
                ORDER BY t.transaction_date DESC, t.id DESC
                LIMIT ?
            """, (limit,))
            pending_rows = [dict(r) for r in cur.fetchall()]

        # Step 2: Compute valuations outside of database lock
        updates = []
        default_base = SettingsService.get_setting("currency", "USD") or "USD"
        now_iso = datetime.now().isoformat()

        for row in pending_rows:
            tx_id = row["id"]
            acct_curr = row["account_currency"]
            base_curr = row["base_currency"] or default_base
            amt_minor = row["amount_minor"]
            tx_date = row["transaction_date"]

            if acct_curr == base_curr:
                updates.append({
                    "id": tx_id,
                    "base_amount_minor": amt_minor,
                    "fx_status": "not_required",
                    "fx_rate_to_base": "1.0",
                    "fx_rate_date": tx_date,
                    "fx_rate_source": "identity",
                    "updated_at": now_iso
                })
                reconciled_count += 1
                continue

            try:
                conv = FxService.convert_minor(amt_minor, acct_curr, base_curr, on_date=tx_date)
                updates.append({
                    "id": tx_id,
                    "base_amount_minor": conv.target.minor,
                    "fx_status": "market_estimate",
                    "fx_rate_to_base": str(conv.rate),
                    "fx_rate_date": conv.rate_date,
                    "fx_rate_source": conv.provider,
                    "updated_at": now_iso
                })
                reconciled_count += 1
            except Exception:
                failed_count += 1

        # Step 3: Fast atomic write transaction
        if updates:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.executemany("""
                    UPDATE transactions
                    SET base_amount_minor = :base_amount_minor,
                        fx_status = :fx_status,
                        fx_rate_to_base = :fx_rate_to_base,
                        fx_rate_date = :fx_rate_date,
                        fx_rate_source = :fx_rate_source,
                        updated_at = :updated_at
                    WHERE id = :id
                """, updates)
                conn.commit()

        # Step 4: Check remaining count
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM transactions t
                JOIN accounts a ON t.account_id = a.id
                WHERE t.is_deleted = 0
                  AND (
                      t.fx_status IN ('pending', 'pending_revaluation')
                      OR (t.base_amount_minor IS NULL AND a.currency <> t.base_currency)
                  )
            """)
            remaining_pending = cur.fetchone()[0]

        return {
            "reconciled": reconciled_count,
            "failed": failed_count,
            "remaining_pending": remaining_pending
        }
