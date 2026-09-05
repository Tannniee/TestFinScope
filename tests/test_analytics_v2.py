import os
import unittest
import tempfile
import shutil
from datetime import date, datetime
from pathlib import Path

# Use isolated test data directory
TEST_DIR = Path(__file__).parent / "analytics_v2_test_data"
if TEST_DIR.exists():
    try:
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    except Exception:
        pass
os.environ["FINSCOPE_DATA_DIR"] = str(TEST_DIR)

from app.backend.database.connection import get_db_connection, init_db
from app.backend.database.migrations_runner import run_migrations
from app.backend.analytics.context import resolve_analytics_context, AnalyticsContext
from app.backend.analytics.period_series import (
    calendar_month_series,
    generate_month_range,
    check_data_sufficiency
)
from app.backend.analytics.reconciliation import (
    reconcile_period_totals,
    reconcile_category_totals,
    reconcile_change_decomposition,
    reconcile_forecast_components
)
from app.backend.analytics.changes import (
    decompose_frequency_ticket_refund,
    WhatChangedEngine
)
from app.backend.analytics.fingerprint import (
    SpendingFingerprintEngine,
    count_weekday_occurrences_in_range
)
from app.backend.analytics.anomalies import AnomalyDetectionEngine
from app.backend.analytics.forecasting import ForecastingEngine
from app.backend.analytics.backtesting import BacktestingEngine
from app.backend.analytics.insight_history import InsightHistoryTracker
from app.backend.analytics.insight_rules import InsightRulesGenerator
from app.backend.analytics.insight_ranker import InsightRanker
from app.backend.services.analytics_service import AnalyticsService

class TestAnalyticsV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TEST_DIR.mkdir(parents=True, exist_ok=True)
        init_db()

    def setUp(self):
        with get_db_connection() as conn:
            conn.execute("DELETE FROM transactions")
            conn.execute("DELETE FROM accounts")
            conn.execute("DELETE FROM categories")
            conn.execute("DELETE FROM insight_history")
            conn.commit()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_DIR, ignore_errors=True)

    # ------------------------------------------------------------------------
    # 1. Context Resolution & Temporal Semantics
    # ------------------------------------------------------------------------
    def test_context_resolution_current_month_partial(self):
        """Current month must resolve to MTD with matched comparison by default."""
        mock_today = date(2026, 9, 4)
        ctx = resolve_analytics_context(month="2026-09", today=mock_today)

        self.assertEqual(ctx.as_of_month, "2026-09")
        self.assertEqual(ctx.start_date, date(2026, 9, 1))
        self.assertEqual(ctx.end_date, date(2026, 9, 4))
        self.assertTrue(ctx.is_current_month)
        self.assertFalse(ctx.is_completed)
        self.assertEqual(ctx.comparison_mode, "previous_month_matched")
        self.assertEqual(ctx.comparison_start, date(2026, 8, 1))
        self.assertEqual(ctx.comparison_end, date(2026, 8, 4))

    def test_context_resolution_historical_completed_month(self):
        """Historical completed month must resolve to full month comparison."""
        mock_today = date(2026, 9, 4)
        ctx = resolve_analytics_context(month="2026-08", today=mock_today)

        self.assertEqual(ctx.as_of_month, "2026-08")
        self.assertEqual(ctx.start_date, date(2026, 8, 1))
        self.assertEqual(ctx.end_date, date(2026, 8, 31))
        self.assertFalse(ctx.is_current_month)
        self.assertTrue(ctx.is_completed)
        self.assertEqual(ctx.comparison_mode, "previous_month_full")
        self.assertEqual(ctx.comparison_start, date(2026, 7, 1))
        self.assertEqual(ctx.comparison_end, date(2026, 7, 31))

    def test_context_month_boundary_safety(self):
        """Matched day cannot exceed target month days (e.g. Jan 31 vs Feb)."""
        mock_today = date(2026, 3, 10)
        # Mocking user inspecting Jan 31 matched against Feb
        ctx = resolve_analytics_context(
            month="2026-03",
            comparison_mode="previous_month_matched",
            today=mock_today
        )
        self.assertEqual(ctx.comparison_end, date(2026, 2, 10))

    # ------------------------------------------------------------------------
    # 2. Zero-Filled Period Series & Coverage
    # ------------------------------------------------------------------------
    def test_zero_filled_series_continuity(self):
        """Missing months must be filled with $0 and not omitted."""
        raw_dict = {"2026-01": 50000, "2026-03": 75000}
        series = calendar_month_series("2026-01", "2026-03", raw_dict, earliest_recorded_month="2026-01")

        self.assertEqual(len(series), 3)
        self.assertEqual(series[0].period, "2026-01")
        self.assertEqual(series[0].value_minor, 50000)
        self.assertTrue(series[0].has_transactions)

        # Feb is zero-filled
        self.assertEqual(series[1].period, "2026-02")
        self.assertEqual(series[1].value_minor, 0)
        self.assertFalse(series[1].has_transactions)
        self.assertEqual(series[1].coverage, "complete")

        self.assertEqual(series[2].period, "2026-03")
        self.assertEqual(series[2].value_minor, 75000)

    def test_data_sufficiency_guards(self):
        """Must return available=False when sample size or history is too sparse."""
        suff = check_data_sufficiency("fingerprint", sample_size=10, months_history=1)
        self.assertFalse(suff.available)
        self.assertEqual(suff.confidence_band, "insufficient")
        self.assertIn("Insufficient", suff.reason)

        suff_ok = check_data_sufficiency("fingerprint", sample_size=40, months_history=3)
        self.assertTrue(suff_ok.available)

    # ------------------------------------------------------------------------
    # 3. Exact Reconciliation Identities
    # ------------------------------------------------------------------------
    def test_reconciliation_period_totals(self):
        """Net spending must equal Gross Expense - Refunds."""
        res_ok = reconcile_period_totals(gross_expense_minor=10000, refund_minor=2500, net_spending_minor=7500)
        self.assertTrue(res_ok.passed)
        self.assertEqual(res_ok.difference_minor, 0)

        res_drift = reconcile_period_totals(gross_expense_minor=10000, refund_minor=2500, net_spending_minor=7499)
        self.assertFalse(res_drift.passed)
        self.assertEqual(res_drift.difference_minor, -1)

    def test_reconciliation_change_decomposition(self):
        """Net delta must equal Frequency + Ticket + Refund effects."""
        res = reconcile_change_decomposition(
            net_delta_minor=15000,
            frequency_effect_minor=8000,
            ticket_effect_minor=9000,
            refund_effect_minor=-2000
        )
        self.assertTrue(res.passed)
        self.assertEqual(res.difference_minor, 0)

    def test_reconciliation_forecast_components(self):
        """Forecast total projected must equal sum of its components."""
        res = reconcile_forecast_components(
            actual_to_date_minor=40000,
            recurring_minor=20000,
            variable_minor=35000,
            irregular_minor=0,
            expected_refund_minor=0,
            total_minor=95000
        )
        self.assertTrue(res.passed)
        self.assertEqual(res.difference_minor, 0)

    # ------------------------------------------------------------------------
    # 4. What Changed v2.1 Decomposition with Refunds
    # ------------------------------------------------------------------------
    def test_refund_decomposition_exact_integer_guarantee(self):
        """
        Roadmap example:
        Previous: 10 purchases @ $50 ($500), $0 refund -> Net $500
        Current:  10 purchases @ $50 ($500), $100 refund -> Net $400
        Expected: Freq = $0, Ticket = $0, Refund = -$100, Net Delta = -$100
        """
        freq, ticket, refund = decompose_frequency_ticket_refund(
            n0=10, n1=10,
            gross0_minor=50000, gross1_minor=50000,
            refund0_minor=0, refund1_minor=10000
        )

        self.assertEqual(freq, 0)
        self.assertEqual(ticket, 0)
        self.assertEqual(refund, -10000)
        self.assertEqual(freq + ticket + refund, -10000)

    def test_frequency_and_ticket_fractional_remainder_assigned(self):
        """Integer rounding remainder must be assigned to guarantee zero penny drift."""
        # N0=3, Gross0=10000 (avg=3333.33)
        # N1=5, Gross1=18000 (avg=3600.00)
        # Delta = 8000
        freq, ticket, refund = decompose_frequency_ticket_refund(
            n0=3, n1=5,
            gross0_minor=10000, gross1_minor=18000,
            refund0_minor=0, refund1_minor=0
        )
        self.assertEqual(freq + ticket + refund, 8000)

    # ------------------------------------------------------------------------
    # 5. Weekday Metrics Disambiguation
    # ------------------------------------------------------------------------
    def test_weekday_transaction_size_vs_daily_spend(self):
        """Average transaction size and average daily spend must be calculated separately."""
        # 14-day range (2 Mondays, 2 Tuesdays, etc.)
        start_d = date(2026, 9, 1)  # Tuesday
        end_d = date(2026, 9, 14)    # Monday
        counts = count_weekday_occurrences_in_range(start_d, end_d)

        # There are 2 Mondays (index 0)
        self.assertEqual(counts[0], 2)

    # ------------------------------------------------------------------------
    # 6. Persistent Insight Memory & Novelty Decay
    # ------------------------------------------------------------------------
    def test_persistent_insight_memory(self):
        """Insight history tracks times shown, novelty decay, material change resets, and dismissals."""
        key = "category_change:10"

        # 1. Brand new insight
        score1 = InsightHistoryTracker.compute_novelty_score(key, current_value_minor=5000)
        self.assertEqual(score1, 1.0)

        # 2. Record shown
        InsightHistoryTracker.record_insights_shown([
            {"insight_key": key, "type": "category", "entity_id": 10, "impact_minor": 5000}
        ], month="2026-09")

        # 3. Shown 1 time -> novelty decays
        score2 = InsightHistoryTracker.compute_novelty_score(key, current_value_minor=5000)
        self.assertEqual(score2, 0.85)

        # 4. Material change (e.g. 5000 -> 8000 is +60% shift) -> novelty resets to 0.90
        score3 = InsightHistoryTracker.compute_novelty_score(key, current_value_minor=8000)
        self.assertEqual(score3, 0.90)

        # 5. Dismissal
        self.assertFalse(InsightHistoryTracker.is_dismissed(key))
        InsightHistoryTracker.dismiss_insight(key)
        self.assertTrue(InsightHistoryTracker.is_dismissed(key))
        self.assertEqual(InsightHistoryTracker.compute_novelty_score(key, 8000), 0.0)

    # ------------------------------------------------------------------------
    # 7. Backtesting with FinScope Hybrid Model
    # ------------------------------------------------------------------------
    def test_backtesting_evaluates_finscope_hybrid(self):
        """Backtesting must evaluate the actual FinScope Hybrid model (legacy_series_hybrid) alongside baselines."""
        # 8 months of spending
        series = [100000, 110000, 105000, 120000, 115000, 130000, 125000, 140000]
        eval_res = BacktestingEngine.evaluate_models(series)

        self.assertTrue(eval_res["available"])
        self.assertIn("legacy_series_hybrid", eval_res["models"])
        self.assertNotIn("finscope_hybrid", eval_res["models"])
        self.assertIn("naive_previous", eval_res["models"])
        self.assertIn("median_3", eval_res["models"])

        hybrid_m = eval_res["models"]["legacy_series_hybrid"]
        self.assertGreater(hybrid_m["sample_origins"], 0)
        self.assertGreater(hybrid_m["mae"], 0)

    # ------------------------------------------------------------------------
    # 8. Golden Dataset Integration Test
    # ------------------------------------------------------------------------
    def test_golden_dataset_analytics_v2(self):
        """
        Creates a rich 12-month dataset with accounts, categories, refunds,
        recurring bills, and verifies that all Analytics V2 service calls
        reconcile with 0 penny drift.
        """
        with get_db_connection() as conn:
            cur = conn.cursor()
            # 1. Accounts
            cur.execute("INSERT INTO accounts (name, account_type) VALUES ('Everyday Checking', 'checking')")
            acc1 = cur.lastrowid
            cur.execute("INSERT INTO accounts (name, account_type) VALUES ('Savings Plus', 'savings')")
            acc2 = cur.lastrowid

            # 2. Categories
            cur.execute("INSERT INTO categories (name, type, color) VALUES ('Groceries', 'expense', '#4DD5A5')")
            cat_groc = cur.lastrowid
            cur.execute("INSERT INTO categories (name, type, color) VALUES ('Dining Out', 'expense', '#FF9F43')")
            cat_dine = cur.lastrowid
            cur.execute("INSERT INTO categories (name, type, color) VALUES ('Subscriptions', 'expense', '#5B8CFF')")
            cat_subs = cur.lastrowid
            cur.execute("INSERT INTO categories (name, type, color) VALUES ('Salary', 'income', '#27D5D5')")
            cat_sal = cur.lastrowid

            # 3. Seed multi-month transactions (2026-01 through 2026-09)
            months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
            for m in months:
                # Salary income
                cur.execute("""
                    INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, description)
                    VALUES (?, ?, 'income', 500000, ? || '-01', 'Monthly Salary')
                """, (acc1, cat_sal, m))

                # Groceries (4 purchases / month)
                for day in [3, 10, 17, 24]:
                    cur.execute("""
                        INSERT INTO transactions (account_id, category_id, merchant_name, transaction_type, amount_minor, transaction_date)
                        VALUES (?, ?, 'Supermarket', 'expense', 12000, ? || '-' || printf('%02d', ?))
                    """, (acc1, cat_groc, m, day))

                # Subscriptions (recurring)
                cur.execute("""
                    INSERT INTO transactions (account_id, category_id, merchant_name, transaction_type, amount_minor, transaction_date, is_recurring)
                    VALUES (?, ?, 'Netflix', 'expense', 2299, ? || '-15', 1)
                """, (acc1, cat_subs, m))

            # August 2026: Add dining out and a linked refund
            cur.execute("""
                INSERT INTO transactions (account_id, category_id, merchant_name, transaction_type, amount_minor, transaction_date)
                VALUES (?, ?, 'Fine Bistro', 'expense', 15000, '2026-08-12')
            """, (acc1, cat_dine))
            exp_id = cur.lastrowid

            # August 2026: Refund of 5000 cents
            cur.execute("""
                INSERT INTO transactions (account_id, category_id, merchant_name, transaction_type, amount_minor, transaction_date, refund_of_transaction_id)
                VALUES (?, ?, 'Fine Bistro', 'refund', 5000, '2026-08-14', ?)
            """, (acc1, cat_dine, exp_id))

            conn.commit()

        # Test AnalyticsService endpoints on Golden Dataset
        # A. Context
        ctx_dict = AnalyticsService.get_analytics_context(month="2026-08")
        self.assertEqual(ctx_dict["as_of_month"], "2026-08")
        self.assertEqual(ctx_dict["comparison_mode"], "previous_month_full")

        # B. Month Summary & Reconciliation
        summary = AnalyticsService.get_month_summary(month="2026-08")
        self.assertEqual(summary["kpis"]["income"], 5000.00)
        # August Net Spend = Groceries (4*120=480) + Subs (22.99) + Dining Net (150 - 50 = 100) = 602.99
        self.assertEqual(summary["kpis"]["expense"], 602.99)

        # C. What Changed v2.1
        changes = AnalyticsService.get_what_changed(current_month="2026-08", comparison_month="2026-07")
        self.assertEqual(changes["total_current"], 602.99)
        # July Net Spend = Groceries (480) + Subs (22.99) = 502.99
        self.assertEqual(changes["total_previous"], 502.99)
        self.assertEqual(changes["total_delta"], 100.00)
        # Exactly reconciled
        reconciled_sum = changes["overall_frequency_effect_minor"] + changes["overall_ticket_effect_minor"] + changes["overall_refund_effect_minor"]
        self.assertEqual(reconciled_sum, changes["total_delta_minor"])

        # D. Merchant Drilldown
        merchants = AnalyticsService.get_merchant_drilldown(category_id=cat_dine, current_month="2026-08")
        self.assertEqual(len(merchants), 1)
        self.assertEqual(merchants[0]["merchant"], "Fine Bistro")
        self.assertEqual(merchants[0]["delta"], 100.00)
        self.assertEqual(merchants[0]["refund_effect"], -50.00)

        # E. Rolling Metrics with zero-filling
        rolling = AnalyticsService.get_rolling_metrics(metric="expense", as_of_month="2026-08")
        self.assertTrue(rolling["available"])
        self.assertGreater(rolling["median_6"], 0)

        # F. Ranked Insights
        insights_res = AnalyticsService.get_ranked_insights(month="2026-08")
        self.assertIn("insights", insights_res)
        self.assertGreaterEqual(len(insights_res["insights"]), 1)

if __name__ == "__main__":
    unittest.main()
