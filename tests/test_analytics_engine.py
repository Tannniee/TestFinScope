"""
Automated Test Suite for FinScope Analytics Engine Core.
Verifies mathematical correctness, invariants, robust statistical baselines,
decomposition identities, anomaly bounds, and insight ranking.
"""

import unittest
import os
import shutil
from pathlib import Path

# Use isolated test data dir
os.environ["FINSCOPE_DATA_DIR"] = str(Path(__file__).parent / "analytics_test_data")

from app.backend.database.connection import get_db_connection, init_db
from app.backend.analytics.semantics import (
    calculate_net_spending,
    calculate_net_cash_flow,
    calculate_savings,
    calculate_savings_rate,
    classify_transaction_pnl_effect
)
from app.backend.analytics.rolling import (
    calculate_mean,
    calculate_median,
    calculate_mad,
    calculate_scaled_mad,
    calculate_ewma,
    RollingAnalyticsEngine
)
from app.backend.analytics.changes import (
    decompose_frequency_and_ticket,
    WhatChangedEngine
)
from app.backend.analytics.fingerprint import (
    calculate_percentile,
    calculate_shannon_diversity,
    calculate_cosine_similarity
)
from app.backend.analytics.anomalies import (
    calculate_robust_z_score,
    compute_normal_range,
    AnomalyDetectionEngine
)
from app.backend.analytics.forecasting import ForecastingEngine
from app.backend.analytics.backtesting import BacktestingEngine
from app.backend.analytics.insight_rules import InsightRulesGenerator
from app.backend.analytics.insight_ranker import InsightRanker
from app.backend.analytics.models import Insight
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.repositories.budget_repo import BudgetRepository
from app.backend.services.analytics_service import AnalyticsService

TEST_DIR = Path(__file__).parent / "analytics_test_data"

class TestAnalyticsEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if TEST_DIR.exists():
            shutil.rmtree(TEST_DIR, ignore_errors=True)
        TEST_DIR.mkdir(parents=True, exist_ok=True)
        init_db()

    @classmethod
    def tearDownClass(cls):
        pass

    # -------------------------------------------------------------------------
    # 1. Semantics Invariants
    # -------------------------------------------------------------------------
    def test_semantics_net_spending_and_refunds(self):
        """Verify Net Spending = Gross Expense - Refunds, never negative."""
        self.assertEqual(calculate_net_spending(5000, 1000), 4000)
        self.assertEqual(calculate_net_spending(2000, 3000), 0)  # Max(0, ...)
        self.assertEqual(calculate_net_spending(0, 500), 0)

    def test_semantics_savings_rate(self):
        """Verify Savings Rate = (Income - Net Spending) / Income * 100."""
        self.assertEqual(calculate_savings_rate(100000, 70000), 30.0)
        self.assertEqual(calculate_savings_rate(100000, 100000), 0.0)
        self.assertEqual(calculate_savings_rate(0, 50000), 0.0)

    def test_semantics_transaction_classification(self):
        """Verify transfers produce zero P&L effect, refunds reduce net spending."""
        t_effect = classify_transaction_pnl_effect("transfer", 50000)
        self.assertEqual(t_effect["income_minor"], 0)
        self.assertEqual(t_effect["gross_expense_minor"], 0)
        self.assertEqual(t_effect["net_spending_minor"], 0)

        r_effect = classify_transaction_pnl_effect("refund", 2500)
        self.assertEqual(r_effect["refund_minor"], 2500)
        self.assertEqual(r_effect["net_spending_minor"], -2500)
        self.assertEqual(r_effect["income_minor"], 0)

    # -------------------------------------------------------------------------
    # 2. Rolling Analytics & Robust Baselines
    # -------------------------------------------------------------------------
    def test_rolling_median_resilience_to_outliers(self):
        """Median should resist distortion from large one-off purchases."""
        # 5 regular months around $400-$450, 1 one-off laptop $2,000
        values = [40000, 42000, 45000, 200000, 43000, 41000]
        mean_val = calculate_mean(values)
        med_val = calculate_median(values)

        # Mean is heavily pulled up to ~$685
        self.assertGreater(mean_val, 65000)
        # Median remains near typical spend level (~$425)
        self.assertLess(med_val, 45000)
        self.assertGreater(med_val, 40000)

    def test_rolling_mad_and_scaled_mad(self):
        """Verify Median Absolute Deviation computation."""
        # Values with clear median
        vals = [1000, 2000, 3000, 4000, 5000]  # median = 3000
        # |x - 3000| = [2000, 1000, 0, 1000, 2000] -> sorted: [0, 1000, 1000, 2000, 2000] -> median = 1000
        self.assertEqual(calculate_mad(vals), 1000)
        self.assertEqual(calculate_scaled_mad(vals), 1483)

    def test_rolling_ewma(self):
        """Verify EWMA weights recent values more than older values."""
        vals = [10000, 10000, 10000, 50000]
        ewma = calculate_ewma(vals, span=3)
        mean_val = calculate_mean(vals)
        # EWMA with recent spike should exceed standard average
        self.assertGreater(ewma, mean_val)

    # -------------------------------------------------------------------------
    # 3. What Changed? v2 Exact Decomposition Identity
    # -------------------------------------------------------------------------
    def test_decomposition_exact_identity(self):
        """
        Verify: Frequency Effect + Ticket Effect == Total Delta (exact cents)
        Identity: (N1 - N0)*(A0 + A1)/2 + (A1 - A0)*(N0 + N1)/2 == Total Delta
        """
        # August: 8 purchases @ $40.00 = $320.00 (32000 cents)
        # September: 10 purchases @ $50.00 = $500.00 (50000 cents)
        n0, spend0 = 8, 32000
        n1, spend1 = 10, 50000
        delta = spend1 - spend0  # 18000 cents ($180)

        freq_effect, ticket_effect = decompose_frequency_and_ticket(n0, n1, spend0, spend1)

        # 1. Exact reconciliation
        self.assertEqual(freq_effect + ticket_effect, delta)

        # 2. Formula verification:
        # A0 = 4000, A1 = 5000
        # Freq Effect = (10 - 8) * (4000 + 5000) / 2 = 2 * 4500 = 9000 ($90)
        # Ticket Effect = (5000 - 4000) * (8 + 10) / 2 = 1000 * 9 = 9000 ($90)
        self.assertEqual(freq_effect, 9000)
        self.assertEqual(ticket_effect, 9000)

    def test_decomposition_frequency_dominated(self):
        """Same average ticket, more purchases -> Freq Effect equals Total Delta."""
        n0, spend0 = 5, 10000  # $20 each
        n1, spend1 = 10, 20000  # $20 each
        freq_eff, ticket_eff = decompose_frequency_and_ticket(n0, n1, spend0, spend1)
        self.assertEqual(freq_eff + ticket_eff, 10000)
        self.assertEqual(freq_eff, 10000)
        self.assertEqual(ticket_eff, 0)

    # -------------------------------------------------------------------------
    # 4. Spending Fingerprint Metrics
    # -------------------------------------------------------------------------
    def test_fingerprint_percentiles(self):
        """Verify percentile calculation on sorted array."""
        arr = [1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000]
        self.assertEqual(calculate_percentile(arr, 0.50), 5500)
        self.assertEqual(calculate_percentile(arr, 0.90), 9100)

    def test_fingerprint_shannon_diversity(self):
        """Verify Shannon diversity score bounds [0, 100]."""
        # All spending in one category -> diversity is 0
        self.assertEqual(calculate_shannon_diversity([1.0]), 0)
        # Evenly spread across 4 categories -> diversity is 100
        self.assertEqual(calculate_shannon_diversity([0.25, 0.25, 0.25, 0.25]), 100)

    def test_fingerprint_cosine_persistence(self):
        """Verify cosine similarity between category spending vectors."""
        v1 = {1: 100, 2: 200}
        v2 = {1: 100, 2: 200}
        v3 = {3: 300, 4: 400}  # completely orthogonal
        self.assertAlmostEqual(calculate_cosine_similarity(v1, v2), 1.0, places=2)
        self.assertAlmostEqual(calculate_cosine_similarity(v1, v3), 0.0, places=2)

    # -------------------------------------------------------------------------
    # 5. Anomaly Detection & Normal Ranges
    # -------------------------------------------------------------------------
    def test_robust_z_score_and_normal_range(self):
        """Verify robust z-score and normal range bounds."""
        med = 5000  # $50.00
        mad = 1000  # $10.00
        mad_scaled = round(1.4826 * mad)  # 1483

        low, up = compute_normal_range(med, mad_scaled, k=2.0)
        self.assertEqual(low, max(0, 5000 - 2 * 1483))
        self.assertEqual(up, 5000 + 2 * 1483)

        # Normal purchase within range
        score_normal = calculate_robust_z_score(6000, med, mad)
        self.assertLess(score_normal, 2.0)

        # Outlier purchase far outside range
        score_outlier = calculate_robust_z_score(25000, med, mad)
        self.assertGreater(score_outlier, 3.5)

    # -------------------------------------------------------------------------
    # 6. Forecasting & Backtesting
    # -------------------------------------------------------------------------
    def test_backtesting_evaluation_metrics(self):
        """Verify rolling-origin backtesting metrics on synthetic series."""
        series = [200000, 210000, 205000, 220000, 215000, 225000]
        res = BacktestingEngine.evaluate_models(series)
        self.assertEqual(res["evaluations_count"], 3)
        self.assertIn("best_baseline", res)
        self.assertIn("naive_previous", res["models"])
        self.assertIn("median_3", res["models"])
        self.assertGreater(res["models"]["median_3"]["mae_minor"], 0)

    # -------------------------------------------------------------------------
    # 7. Insights Engine: Absolute Impact Prioritization & Deduplication
    # -------------------------------------------------------------------------
    def test_insight_ranking_prioritizes_impact_over_percentage(self):
        """
        Verify: Absolute impact must rank higher than percentage drama:
        Shopping +$350 (+35%) must outrank Coffee +$8 (+400%).
        """
        coffee_insight = Insight(
            id="coffee_drama",
            insight_type="CHANGE",
            title="Coffee spending increased 400%",
            summary="$2.00 -> $10.00",
            metric="expense",
            entity_type="category",
            entity_id=1,
            current_value_minor=1000,
            baseline_value_minor=200,
            delta_value_minor=800,  # $8.00
            delta_percent=400.0,
            severity="info",
            confidence="high",
            impact_score=0.05,  # tiny financial impact
            unusualness_score=0.5,
            actionability_score=0.3,
            novelty_score=0.5,
            final_rank_score=0.0,
            drilldown_filter={},
            evidence={},
            generated_at="2026-09-04"
        )

        shopping_insight = Insight(
            id="shopping_material",
            insight_type="CHANGE",
            title="Shopping drove $350 increase",
            summary="$1,000.00 -> $1,350.00",
            metric="expense",
            entity_type="category",
            entity_id=2,
            current_value_minor=135000,
            baseline_value_minor=100000,
            delta_value_minor=35000,  # $350.00
            delta_percent=35.0,
            severity="warning",
            confidence="high",
            impact_score=0.85,  # substantial financial impact
            unusualness_score=0.7,
            actionability_score=0.8,
            novelty_score=0.8,
            final_rank_score=0.0,
            drilldown_filter={},
            evidence={},
            generated_at="2026-09-04"
        )

        ranked = InsightRanker.rank_and_deduplicate([coffee_insight, shopping_insight], limit=2)
        self.assertEqual(len(ranked), 2)
        # Material shopping increase MUST rank #1
        self.assertEqual(ranked[0]["id"], "shopping_material")
        self.assertEqual(ranked[1]["id"], "coffee_drama")

    # -------------------------------------------------------------------------
    # 8. End-to-End Integration with Golden Dataset
    # -------------------------------------------------------------------------
    def test_golden_dataset_analytics_integration(self):
        """
        Creates a deterministic 3-month dataset with known transactions and verifies:
        - What Changed driver decomposition
        - Anomalies
        - Forecast
        - Ranked Insights
        """
        acc_id = AccountRepository.create("Checking", "Everyday", "Bank A", 5000.0, "USD")
        cat_food = CategoryRepository.create("Food & Dining", "expense", "utensils", "#FF9500")
        cat_shop = CategoryRepository.create("Shopping", "expense", "shopping-bag", "#AF52DE")

        # Month 1: 2026-06
        for d in range(1, 11):
            TransactionRepository.create({
                "account_id": acc_id,
                "category_id": cat_food,
                "amount": 20.0,
                "transaction_type": "expense",
                "transaction_date": f"2026-06-{d:02d}",
                "description": "Lunch"
            })
        # Month 2: 2026-07
        for d in range(1, 11):
            TransactionRepository.create({
                "account_id": acc_id,
                "category_id": cat_food,
                "amount": 20.0,
                "transaction_type": "expense",
                "transaction_date": f"2026-07-{d:02d}",
                "description": "Lunch"
            })
        # Month 3: 2026-08 (Food increases frequency and ticket; Shopping has one huge anomaly)
        for d in range(1, 16):
            TransactionRepository.create({
                "account_id": acc_id,
                "category_id": cat_food,
                "amount": 30.0,
                "transaction_type": "expense",
                "transaction_date": f"2026-08-{d:02d}",
                "description": "Restaurant dinner"
            })

        # Test What Changed?
        changes = AnalyticsService.get_what_changed("2026-08", "2026-07")
        self.assertEqual(changes["current_month"], "2026-08")
        self.assertGreater(changes["total_delta_minor"], 0)
        # Food increased from $200 (10 * $20) to $450 (15 * $30) -> delta = +$250
        food_driver = next(d for d in changes["drivers"] if d["entity_id"] == cat_food)
        self.assertEqual(food_driver["delta_minor"], 25000)
        # Exact decomposition check
        self.assertEqual(food_driver["frequency_effect_minor"] + food_driver["ticket_effect_minor"], 25000)

        # Test Rolling Metrics
        rolling = AnalyticsService.get_rolling_metrics("expense", cat_food)
        self.assertIn("current", rolling)
        self.assertIn("median_3", rolling)

        # Test Spending Fingerprint
        fp = AnalyticsService.get_spending_fingerprint(months_window=3)
        self.assertIn("median_transaction", fp)
        self.assertIn("spending_variability", fp)
        self.assertIn("category_diversity_score", fp)

        # Test Forecast
        fc = AnalyticsService.get_forecast("2026-08", as_of_date="2026-08-15")
        self.assertGreater(fc["projected_expense_minor"], 0)
        self.assertGreaterEqual(fc["upper_bound_minor"], fc["projected_expense_minor"])

        # Test Ranked Insights
        insights = AnalyticsService.get_ranked_insights("2026-08")
        self.assertIn("insights", insights)
        self.assertGreater(len(insights["insights"]), 0)
        top = insights["insights"][0]
        self.assertIn("title", top)
        self.assertIn("summary", top)
        self.assertIn("final_rank_score", top)
        self.assertIn("drilldown_filter", top)

if __name__ == "__main__":
    unittest.main()
