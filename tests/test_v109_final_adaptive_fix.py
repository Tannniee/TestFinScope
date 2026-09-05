"""
Integration tests for FinScope v1.0.9 — Final Adaptive Forecast Remediation.
Tests the contract hardening across HistoricalReplayRunner, ModelSelector,
disjoint baseline naming, expense history anchoring, and diagnostics.
"""

import pytest
from datetime import date
from app.backend.database.connection import get_db_connection
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.analytics.forecast_replay import HistoricalReplayRunner
from app.backend.analytics.forecasting import ForecastingEngine
from app.backend.analytics.backtesting import BacktestingEngine
from app.backend.analytics.forecast_strategies import (
    ModelSelector,
    IneligibleForecastStrategyError,
    IneligibleForecastStrategy,
    ForecastContext,
    FORECAST_CONFIG
)


# ==============================================================================
# 1. Replay Exposes Canonical model_scores (F109-01, Section 31)
# ==============================================================================
def test_replay_exposes_canonical_model_scores(isolated_db):
    """HistoricalReplayRunner.run_replay() must expose top-level canonical model_scores."""
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Living", "expense")

    with get_db_connection() as conn:
        cur = conn.cursor()
        for m in ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]:
            for d in [5, 12, 19, 26]:
                cur.execute("""
                    INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring)
                    VALUES (?, ?, 'expense', 20000, ? || '-' || printf('%02d', ?), 0)
                """, (acc_id, cat_id, m, d))
        conn.commit()

    replay = HistoricalReplayRunner.run_replay(account_id=acc_id, as_of_date="2026-08-01")

    assert "model_scores" in replay
    assert "comparable_origin_count" in replay
    assert replay["comparable_origin_count"] >= 0
    assert "candidate_models" in replay
    assert "baselines" in replay
    assert "production_policy" in replay

    for m_id, score in replay["model_scores"].items():
        assert score["comparable_origins"] == replay["comparable_origin_count"]
        assert "median_ae_minor" in score
        assert "mae_minor" in score
        assert "bias_minor" in score


def make_v109_context(
    target_month: str = "2026-09",
    as_of_date: str = "2026-09-15",
    completed_months: int = 8,
    elapsed_day: int = 15,
    remaining_days: int = 15,
    num_days: int = 30,
    actual_non_recurring_expense_minor: int = 100000,
    hist_monthly_non_recurring_expense: dict = None,
) -> ForecastContext:
    if hist_monthly_non_recurring_expense is None:
        hist_monthly_non_recurring_expense = {
            f"2026-{m:02d}": 200000 for m in range(1, completed_months + 1)
        }
    remaining_dates = tuple(f"{target_month}-{d:02d}" for d in range(elapsed_day + 1, num_days + 1))
    return ForecastContext(
        target_month=target_month,
        as_of_date=as_of_date,
        account_id=1,
        elapsed_day=elapsed_day,
        remaining_days=remaining_days,
        num_days=num_days,
        remaining_calendar_dates=remaining_dates,
        actual_expense_minor=actual_non_recurring_expense_minor,
        actual_income_minor=300000,
        actual_refund_minor=0,
        actual_net_spend_to_date_minor=actual_non_recurring_expense_minor,
        actual_non_recurring_expense_minor=actual_non_recurring_expense_minor,
        actual_recurring_expense_minor=0,
        upcoming_recurring_expense_minor=0,
        upcoming_recurring_income_minor=0,
        hist_monthly_non_recurring_expense=hist_monthly_non_recurring_expense,
        dense_daily_non_recurring_expense={},
        weekday_rates={w: 2000 for w in range(7)},
        weekday_sample_counts={w: 4 for w in range(7)},
        global_non_recurring_daily_rate=2000,
        actual_cat_spends_net={},
        actual_cat_non_recurring_expense={},
        historical_cat_non_recurring_expense={},
        cat_metadata={},
        upcoming_recurring_by_cat={},
        completed_months=completed_months,
        transaction_count=50
    )


# ==============================================================================
# 2. Critical Test: All-Origin Winner vs Common-Origin Winner (F109-01, Section 32)
# ==============================================================================
def test_all_origin_vs_common_origin_winner_inversion():
    """
    When Model A has lower all-origin error across disparate sample counts,
    but Model B wins across the exact common origins,
    ModelSelector must choose Model B based exclusively on model_scores.
    """
    ctx = make_v109_context(completed_months=8)

    # Inverted replay payload:
    # In candidate_models (all origins), current_pace has lower MAE (100 vs 200).
    # In model_scores (exact common origins), weekday_hybrid has lower Median AE (150 vs 300).
    replay_payload = {
        "available": True,
        "ranking_metric": "median_absolute_error",
        "minimum_comparable_origins": 6,
        "comparable_origin_count": 8,
        "model_scores": {
            "current_pace": {
                "model_id": "current_pace",
                "comparable_origins": 8,
                "median_ae_minor": 30000,
                "mae_minor": 32000,
                "bias_minor": 1000
            },
            "weekday_hybrid": {
                "model_id": "weekday_hybrid",
                "comparable_origins": 8,
                "median_ae_minor": 15000,
                "mae_minor": 18000,
                "bias_minor": -500
            }
        },
        "candidate_models": {
            "current_pace": {
                "name": "current_pace",
                "sample_origins": 24,
                "median_ae_minor": 10000,
                "mae_minor": 12000
            },
            "weekday_hybrid": {
                "name": "weekday_hybrid",
                "sample_origins": 8,
                "median_ae_minor": 20000,
                "mae_minor": 22000
            }
        }
    }

    selector = ModelSelector()
    selected_strategy, reason = selector.select(ctx, replay_scores=replay_payload)

    # Must select weekday_hybrid because model_scores has lowest Median AE on comparable origins
    assert selected_strategy.id == "weekday_hybrid"
    assert "lowest Median AE on comparable origins" in reason


# ==============================================================================
# 3. Critical Test: Global Comparable Threshold Gating (F109-02, Section 33)
# ==============================================================================
def test_global_comparable_threshold_gates_adaptive_selection():
    """
    If comparable_origin_count < 6, adaptive selection must NOT occur,
    even if individual candidate_models have large sample counts.
    """
    ctx = make_v109_context(completed_months=8)

    replay_payload = {
        "available": True,
        "comparable_origin_count": 0,
        "model_scores": {},
        "candidate_models": {
            "robust_weekly": {
                "name": "robust_weekly",
                "sample_origins": 20,
                "median_ae_minor": 100,
                "mae_minor": 150
            }
        }
    }

    selector = ModelSelector()
    strategy, reason = selector.select(ctx, replay_scores=replay_payload)

    # Must fall back deterministically (e.g. weekday_hybrid under mature history)
    assert not reason.startswith("Adaptive replay selection")
    assert strategy.id in ("weekday_hybrid", "recent_median", "current_pace")


# ==============================================================================
# 4. Critical Test: No Sample-Origin Fallback (F109-01, Section 34)
# ==============================================================================
def test_no_sample_origin_fallback_for_comparable_selection():
    """
    If a model has comparable_origins = 5 and sample_origins = 30,
    it must NOT be considered for adaptive selection (5 < 6).
    """
    ctx = make_v109_context(completed_months=8)

    replay_payload = {
        "available": True,
        "comparable_origin_count": 5,
        "model_scores": {
            "robust_weekly": {
                "model_id": "robust_weekly",
                "comparable_origins": 5,
                "sample_origins": 30,
                "median_ae_minor": 5000,
                "mae_minor": 6000,
                "bias_minor": 0
            }
        }
    }

    selector = ModelSelector()
    strategy, reason = selector.select(ctx, replay_scores=replay_payload)

    # Gating check: comparable_origin_count 5 < 6 -> fallback
    assert not reason.startswith("Adaptive replay selection")


# ==============================================================================
# 5. Critical Test: Disjoint Candidate vs Baseline IDs (F109-03, Section 35 & 36)
# ==============================================================================
def test_candidate_models_and_baselines_are_disjoint(isolated_db):
    """
    Candidate current_pace and baseline current_pace must NOT collide.
    Baselines must be prefixed with baseline_*.
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Living", "expense")

    with get_db_connection() as conn:
        cur = conn.cursor()
        for m in ["2026-04", "2026-05", "2026-06", "2026-07"]:
            for d in [5, 12, 19, 26]:
                cur.execute("""
                    INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring)
                    VALUES (?, ?, 'expense', 25000, ? || '-' || printf('%02d', ?), 0)
                """, (acc_id, cat_id, m, d))
        conn.commit()

    replay = HistoricalReplayRunner.run_replay(account_id=acc_id, as_of_date="2026-08-01")

    assert "current_pace" in replay["candidate_models"]
    assert "baseline_current_pace" in replay["baselines"]
    assert "current_pace" not in replay["baselines"]

    candidate_ids = set(replay["candidate_models"].keys())
    baseline_ids = set(replay["baselines"].keys())
    assert candidate_ids.isdisjoint(baseline_ids), f"Collision detected: {candidate_ids & baseline_ids}"

    # Verify merged backward-compatibility map preserves candidate current_pace
    assert replay["models"]["current_pace"]["name"] == "current_pace"


# ==============================================================================
# 6. Test: Selector Reads model_scores Only (F109-01, Section 37)
# ==============================================================================
def test_selector_reads_model_scores_only():
    """
    Ensure the live selector queries model_scores and ignores candidate_models
    for the adaptive ranking calculation.
    """
    ctx = make_v109_context(completed_months=8)

    replay_payload = {
        "available": True,
        "comparable_origin_count": 9,
        "model_scores": {
            "weekday_hybrid": {
                "model_id": "weekday_hybrid",
                "comparable_origins": 9,
                "median_ae_minor": 12000,
                "mae_minor": 15000,
                "bias_minor": 0
            },
            "robust_weekly": {
                "model_id": "robust_weekly",
                "comparable_origins": 9,
                "median_ae_minor": 25000,
                "mae_minor": 28000,
                "bias_minor": 0
            }
        },
        "candidate_models": {
            "robust_weekly": {
                "name": "robust_weekly",
                "sample_origins": 18,
                "median_ae_minor": 5000,
                "mae_minor": 6000
            },
            "weekday_hybrid": {
                "name": "weekday_hybrid",
                "sample_origins": 18,
                "median_ae_minor": 30000,
                "mae_minor": 35000
            }
        }
    }

    selector = ModelSelector()
    strategy, reason = selector.select(ctx, replay_scores=replay_payload)
    assert strategy.id == "weekday_hybrid"


# ==============================================================================
# 7. Test: Expense Replay Start Anchors on Expense Activity (F109-06, Section 38)
# ==============================================================================
def test_expense_replay_start_anchors_on_expense_activity(isolated_db):
    """
    An initial income-only period must NOT create artificial historical expense months.
    Replay history starts from the first expense/refund transaction.
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_inc = CategoryRepository.create("Salary", "income")
    cat_exp = CategoryRepository.create("Living", "expense")

    with get_db_connection() as conn:
        cur = conn.cursor()
        # Jan & Feb: Income only
        cur.execute("""
            INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring)
            VALUES (?, ?, 'income', 500000, '2026-01-15', 1)
        """, (acc_id, cat_inc))
        cur.execute("""
            INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring)
            VALUES (?, ?, 'income', 500000, '2026-02-15', 1)
        """, (acc_id, cat_inc))

        # March: First expense
        cur.execute("""
            INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring)
            VALUES (?, ?, 'expense', 20000, '2026-03-10', 0)
        """, (acc_id, cat_exp))

        # April: Zero expense (income only)
        cur.execute("""
            INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring)
            VALUES (?, ?, 'income', 500000, '2026-04-15', 1)
        """, (acc_id, cat_inc))

        # May: Expense
        cur.execute("""
            INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring)
            VALUES (?, ?, 'expense', 30000, '2026-05-10', 0)
        """, (acc_id, cat_exp))

        conn.commit()

    completed_months = HistoricalReplayRunner.get_completed_historical_months(
        account_id=acc_id,
        as_of_date="2026-06-01"
    )

    # First expense was in 2026-03. Completed months before 2026-06 must be:
    # 2026-03, 2026-04 (zero-filled), 2026-05.
    # Jan and Feb must NOT be included!
    assert "2026-01" not in completed_months
    assert "2026-02" not in completed_months
    assert completed_months == ["2026-03", "2026-04", "2026-05"]


# ==============================================================================
# 8. Test: Forced Ineligible Candidate Raises Exception (F109-08, Section 39)
# ==============================================================================
def test_forced_ineligible_candidate_raises_ineligible_exception(isolated_db):
    """
    Forcing an ineligible strategy (e.g. seasonal_naive with only 3 months of history)
    must raise IneligibleForecastStrategyError rather than returning an invalid prediction.
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Living", "expense")

    with get_db_connection() as conn:
        cur = conn.cursor()
        for m in ["2026-05", "2026-06", "2026-07"]:
            cur.execute("""
                INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring)
                VALUES (?, ?, 'expense', 50000, ? || '-10', 0)
            """, (acc_id, cat_id, m))
        conn.commit()

    # seasonal_naive requires >= 12 months history
    with pytest.raises((IneligibleForecastStrategyError, IneligibleForecastStrategy)):
        ForecastingEngine.forecast_month(
            month="2026-08",
            account_id=acc_id,
            as_of_date="2026-08-15",
            forced_method="seasonal_naive"
        )


# ==============================================================================
# 9. Test: Production Policy Is Not A Candidate (F109-05, Section 42)
# ==============================================================================
def test_production_policy_is_not_candidate(isolated_db):
    """
    production_policy must be separate from candidate_models and model_scores.
    It represents the historical system performance benchmark.
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Living", "expense")

    with get_db_connection() as conn:
        cur = conn.cursor()
        for m in ["2026-04", "2026-05", "2026-06", "2026-07"]:
            for d in [5, 12, 19, 26]:
                cur.execute("""
                    INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring)
                    VALUES (?, ?, 'expense', 25000, ? || '-' || printf('%02d', ?), 0)
                """, (acc_id, cat_id, m, d))
        conn.commit()

    replay = HistoricalReplayRunner.run_replay(account_id=acc_id, as_of_date="2026-08-01")

    assert "production_policy" not in replay["candidate_models"]
    assert "production_policy" not in replay["model_scores"]
    assert "production_policy" in replay
    assert replay["best_candidate"] != "production_policy"


# ==============================================================================
# 10. Test: Legacy Hybrid Hidden From Backtest Models (F109-10, Section 43)
# ==============================================================================
def test_legacy_hybrid_hidden_from_backtest_models():
    """
    BacktestingEngine.evaluate_models() exposes legacy_series_hybrid
    and does not expose duplicate finscope_hybrid to avoid confusion.
    """
    series = [100000, 110000, 105000, 120000, 115000, 130000]
    res = BacktestingEngine.evaluate_models(series)

    assert res["available"] is True
    assert "legacy_series_hybrid" in res["models"]
    assert "finscope_hybrid" not in res["models"]


# ==============================================================================
# 11. Test: Forecasting Diagnostics Selection Evidence (Section 29)
# ==============================================================================
def test_forecasting_diagnostics_selection_evidence(isolated_db):
    """
    Forecast diagnostics must expose selection_evidence, comparable_origin_count,
    ranking_metric, and confidence_error_source.
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Living", "expense")

    with get_db_connection() as conn:
        cur = conn.cursor()
        for m in ["2026-04", "2026-05", "2026-06", "2026-07"]:
            for d in [5, 12, 19, 26]:
                cur.execute("""
                    INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring)
                    VALUES (?, ?, 'expense', 25000, ? || '-' || printf('%02d', ?), 0)
                """, (acc_id, cat_id, m, d))
        conn.commit()

    fc = ForecastingEngine.forecast_month(
        month="2026-08",
        account_id=acc_id,
        as_of_date="2026-08-15"
    )

    diag = fc.get("diagnostics", {})
    assert "selection_evidence" in diag
    assert diag["selection_evidence"] in ("comparable_replay", "fallback", "forced")
    assert "comparable_origin_count" in diag
    assert diag["ranking_metric"] == "median_absolute_error"
    assert "confidence_error_source" in diag
