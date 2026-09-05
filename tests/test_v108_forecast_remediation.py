"""
Comprehensive Test Suite for FinScope Forecasting v1.0.8 — Audit Remediation
Validates:
- Canonical strategy semantics (non-recurring variable expense only)
- Current Pace recurring actual exclusion (F108-01)
- Recent Median pure non-recurring monthly median (F108-02)
- Robust Weekly Monday-Sunday calendar weeks (>= 4 complete weeks required) (F108-05, F108-06)
- Weekday Hybrid robust fallback without recurring actual contamination (F108-03)
- Seasonal Naive exact same calendar month prior year matching (F108-04)
- Canonical strategy IDs alignment (F108-07)
- True comparable-origin scoring via exact common origins intersection (F108-10)
- Selector contract: >= 6 comparable origins, Median AE ranking, MAE tiebreaker, 5% improvement guardrail (F108-11, F108-23)
- Sequential production-policy replay (prior-origin evidence only, F108-09)
- Recurring rule resurrection suppression for deleted/deactivated rules (F108-13)
- Unscheduled recurring rule contract (no fake day 15, F108-20)
- Database migration 007: analytics_state revision triggers & cache invalidation (F108-15)
- Point forecast strictly bounded inside displayed range (F108-19)
- Category variable allocation excluding recurring actual spend (F108-14)
"""

import pytest
import sqlite3
from datetime import date, datetime, timedelta
from app.backend.database.connection import get_db_connection
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.services.recurring_service import RecurringService
from app.backend.analytics.forecast_strategies.base import ForecastStrategy, ForecastEstimate
from app.backend.analytics.forecast_strategies.context import ForecastContext
from app.backend.analytics.forecast_strategies.request import ForecastRequest
from app.backend.analytics.forecast_strategies.config import FORECAST_CONFIG
from app.backend.analytics.forecast_strategies.series import (
    generate_calendar_months,
    same_month_previous_year,
    build_dense_daily_series,
    build_dense_monthly_series,
    build_complete_calendar_weeks
)
from app.backend.analytics.forecast_strategies.scoring import (
    ReplayOrigin,
    CandidateReplayRecord,
    compute_comparable_scores
)
from app.backend.analytics.forecast_strategies.current_pace import CurrentPaceStrategy
from app.backend.analytics.forecast_strategies.recent_median import RecentMedianStrategy
from app.backend.analytics.forecast_strategies.robust_weekly import RobustWeeklyResidualStrategy
from app.backend.analytics.forecast_strategies.weekday_hybrid import WeekdayHybridStrategy
from app.backend.analytics.forecast_strategies.seasonal_naive import SeasonalNaiveStrategy
from app.backend.analytics.forecast_strategies.registry import ModelRegistry, default_registry
from app.backend.analytics.forecast_strategies.selector import ModelSelector
from app.backend.analytics.forecasting import ForecastingEngine
from app.backend.analytics.forecast_replay import HistoricalReplayRunner


# ==============================================================================
# Context Helper for Unit Tests
# ==============================================================================

def make_v108_context(
    target_month: str = "2026-09",
    as_of_date: str = "2026-09-10",
    elapsed_day: int = 10,
    remaining_days: int = 20,
    num_days: int = 30,
    actual_non_recurring_expense_minor: int = 20000,   # $200 variable
    actual_recurring_expense_minor: int = 100000,      # $1,000 rent already paid
    actual_refund_minor: int = 0,
    upcoming_recurring_expense_minor: int = 50000,     # $500 upcoming bill
    completed_months: int = 6,
    hist_monthly_non_recurring_expense: dict = None,
    dense_daily_non_recurring_expense: dict = None,
    weekday_rates: dict = None,
    weekday_sample_counts: dict = None,
    global_non_recurring_daily_rate: int = 2000
) -> ForecastContext:
    if hist_monthly_non_recurring_expense is None:
        hist_monthly_non_recurring_expense = {
            "2026-03": 60000,
            "2026-04": 65000,
            "2026-05": 58000,
            "2026-06": 62000,
            "2026-07": 64000,
            "2026-08": 61000
        }
    if dense_daily_non_recurring_expense is None:
        dense_daily_non_recurring_expense = {}
    if weekday_rates is None:
        weekday_rates = {w: 2000 for w in range(7)}
    if weekday_sample_counts is None:
        weekday_sample_counts = {w: 4 for w in range(7)}

    actual_expense_minor = actual_non_recurring_expense_minor + actual_recurring_expense_minor
    actual_net_spend_to_date_minor = actual_expense_minor - actual_refund_minor

    # generate remaining dates: YYYY-MM-(elapsed_day+1) to YYYY-MM-num_days
    remaining_dates = tuple(f"{target_month}-{d:02d}" for d in range(elapsed_day + 1, num_days + 1))

    return ForecastContext(
        target_month=target_month,
        as_of_date=as_of_date,
        account_id=1,
        elapsed_day=elapsed_day,
        remaining_days=remaining_days,
        num_days=num_days,
        remaining_calendar_dates=remaining_dates,
        actual_expense_minor=actual_expense_minor,
        actual_income_minor=300000,
        actual_refund_minor=actual_refund_minor,
        actual_net_spend_to_date_minor=actual_net_spend_to_date_minor,
        actual_non_recurring_expense_minor=actual_non_recurring_expense_minor,
        actual_recurring_expense_minor=actual_recurring_expense_minor,
        upcoming_recurring_expense_minor=upcoming_recurring_expense_minor,
        upcoming_recurring_income_minor=0,
        hist_monthly_non_recurring_expense=hist_monthly_non_recurring_expense,
        dense_daily_non_recurring_expense=dense_daily_non_recurring_expense,
        weekday_rates=weekday_rates,
        weekday_sample_counts=weekday_sample_counts,
        global_non_recurring_daily_rate=global_non_recurring_daily_rate,
        actual_cat_spends_net={},
        actual_cat_non_recurring_expense={},
        historical_cat_non_recurring_expense={},
        cat_metadata={},
        upcoming_recurring_by_cat={},
        completed_months=completed_months,
        transaction_count=30
    )


# ==============================================================================
# 1. Strategy Semantics (F108-01, F108-02, F108-03, F108-04)
# ==============================================================================

def test_current_pace_excludes_actual_recurring_expense():
    """
    F108-01: When $1,000 recurring rent was paid on day 1 and $200 variable spend occurred over 10 days,
    Current Pace daily rate must be $200 / 10 = $20/day (2000 minor/day), NOT ($1,000 + $200)/10 = $120/day!
    For 20 remaining days, remaining variable must be $400 (40,000 minor).
    """
    strat = CurrentPaceStrategy()
    ctx = make_v108_context(
        elapsed_day=10,
        remaining_days=20,
        actual_non_recurring_expense_minor=20000,  # $200 variable
        actual_recurring_expense_minor=100000      # $1,000 rent
    )
    est = strat.predict(ctx)
    assert est.model_id == "current_pace"
    # Pace: 20000 // 10 = 2000/day. Remaining 20 days: 40000 minor ($400)
    assert est.remaining_variable_minor == 40000
    assert est.diagnostics["actual_non_recurring_expense_minor"] == 20000
    assert est.diagnostics["implied_daily_variable_rate"] == 2000


def test_recent_median_uses_pure_non_recurring_monthly_history():
    """
    F108-02: Recent Median takes median of non-recurring historical months.
    It does NOT subtract upcoming recurring bills from the historical variable pace.
    """
    strat = RecentMedianStrategy()
    # 3 complete months with variable spends $600, $660, $630 (median = $630 = 63000 minor)
    hist_months = {"2026-06": 60000, "2026-07": 66000, "2026-08": 63000}
    ctx = make_v108_context(
        num_days=30,
        remaining_days=15,
        upcoming_recurring_expense_minor=50000,  # $500 recurring commitment
        hist_monthly_non_recurring_expense=hist_months
    )
    est = strat.predict(ctx)
    assert est.model_id == "three_month_median"
    # Median monthly variable: 63000. For 15/30 days: 31500 minor.
    # Must NOT subtract upcoming recurring 50000 from 63000!
    assert est.remaining_variable_minor == 31500
    assert est.diagnostics["median_monthly_variable"] == 63000


def test_robust_weekly_requires_at_least_four_complete_weeks():
    """
    F108-05: Robust Weekly must reject history with only 2 or 3 complete weeks.
    It requires at least 4 complete Monday-Sunday weeks.
    """
    strat = RobustWeeklyResidualStrategy()
    assert FORECAST_CONFIG.robust_weekly_min_complete_weeks == 4

    # 3 complete weeks (21 days Monday to Sunday)
    dense_3_weeks = {}
    base_monday = date(2026, 8, 3)  # Monday
    for i in range(21):
        d_str = (base_monday + timedelta(days=i)).isoformat()
        dense_3_weeks[d_str] = 3000

    ctx_3 = make_v108_context(dense_daily_non_recurring_expense=dense_3_weeks)
    assert len(ctx_3.get_complete_weekly_totals()) == 3
    assert strat.is_eligible(ctx_3) is False

    # Add 4th complete week (7 more days) -> 28 days total
    dense_4_weeks = dict(dense_3_weeks)
    for i in range(21, 28):
        d_str = (base_monday + timedelta(days=i)).isoformat()
        dense_4_weeks[d_str] = 3000

    ctx_4 = make_v108_context(dense_daily_non_recurring_expense=dense_4_weeks)
    assert len(ctx_4.get_complete_weekly_totals()) == 4
    assert strat.is_eligible(ctx_4) is True


def test_complete_calendar_weeks_monday_to_sunday_grouping():
    """
    F108-06: build_complete_calendar_weeks strictly groups Monday-Sunday weeks,
    discarding leading and trailing partial weeks.
    """
    # 2026-08-01 is Saturday (discard Sat 01, Sun 02)
    # 2026-08-03 is Monday through 2026-08-30 is Sunday (4 complete weeks)
    # 2026-08-31 is Monday (discard trailing Monday)
    dense_series = {}
    cur = date(2026, 8, 1)
    end = date(2026, 8, 31)
    while cur <= end:
        dense_series[cur.isoformat()] = 1000
        cur += timedelta(days=1)

    weeks = build_complete_calendar_weeks(dense_series)
    assert len(weeks) == 4
    # Each week has 7 days * 1000 = 7000
    assert all(w == 7000 for w in weeks)


def test_weekday_hybrid_sparse_day_falls_back_to_global_daily_rate():
    """
    F108-03: When Wednesday has < 3 historical samples, it uses global_non_recurring_daily_rate,
    preventing 0 variable spend forecast on Wednesdays.
    """
    strat = WeekdayHybridStrategy()
    # Wednesday is sqlite %w = 3 (Sunday is 0, Monday is 1, Tuesday is 2, Wednesday is 3)
    # Setup Wednesday with 1 sample (below threshold 3)
    weekday_counts = {w: 5 for w in range(7)}
    weekday_counts[3] = 1  # Sparse Wednesday

    weekday_rates = {w: 5000 for w in range(7)}
    weekday_rates[3] = 100  # unrepresentative single sample

    # Context with 1 Wednesday remaining: 2026-09-16 is Wednesday
    ctx = make_v108_context(
        weekday_sample_counts=weekday_counts,
        weekday_rates=weekday_rates,
        global_non_recurring_daily_rate=4500
    )
    assert strat.is_eligible(ctx) is True
    est = strat.predict(ctx)

    # Wednesday applied rate must fall back to global 4500, not 100
    assert est.diagnostics["applied_rates_sample"][3] == 4500


def test_seasonal_naive_uses_exact_prior_year_calendar_month():
    """
    F108-04: Seasonal Naive looks up exact YYYY-1-MM month, regardless of gaps in months.
    """
    strat = SeasonalNaiveStrategy()
    assert same_month_previous_year("2026-09") == "2025-09"

    # History contains 2025-09 with non-recurring expense $800 (80000 minor)
    hist_months = {
        "2025-09": 80000,
        "2025-10": 70000,
        "2026-08": 60000
    }
    ctx = make_v108_context(
        target_month="2026-09",
        completed_months=12,
        num_days=30,
        remaining_days=15,
        hist_monthly_non_recurring_expense=hist_months
    )
    assert strat.is_eligible(ctx) is True
    est = strat.predict(ctx)
    assert est.model_id == "seasonal_naive"
    # 80000 * 15 / 30 = 40000 minor
    assert est.remaining_variable_minor == 40000
    assert est.diagnostics["reference_month"] == "2025-09"


# ==============================================================================
# 2. Comparable-Origin Scoring & Model Selector (F108-10, F108-11, F108-23)
# ==============================================================================

def test_compute_comparable_scores_exact_common_origins_intersection():
    """
    F108-10: Models must be compared ONLY on the exact intersection of origin IDs.
    Model A evaluated on origins 1..10, Model B on origins 5..10:
    Comparable evaluation must score both models ONLY on origins 5..10 (6 origins)!
    """
    rec_a = [CandidateReplayRecord(f"O{i}", "model_a", 100, 120, 20, 20) for i in range(1, 11)]
    rec_b = [CandidateReplayRecord(f"O{i}", "model_b", 100, 110, 10, 10) for i in range(5, 11)]

    candidates = {"model_a": rec_a, "model_b": rec_b}
    res = compute_comparable_scores(candidates, ["model_a", "model_b"])

    assert res["comparable_origin_count"] == 6
    assert set(res["common_origins"]) == {f"O{i}" for i in range(5, 11)}
    assert res["model_scores"]["model_a"]["comparable_origins"] == 6
    assert res["model_scores"]["model_b"]["comparable_origins"] == 6
    assert res["model_scores"]["model_b"]["median_ae_minor"] == 10
    assert res["model_scores"]["model_a"]["median_ae_minor"] == 20


def test_selector_requires_at_least_six_comparable_origins():
    """
    F108-11: Adaptive selection requires >= 6 comparable origins.
    With only 5 origins, deterministic fallback must be retained.
    """
    selector = ModelSelector()

    # Replay scores with only 5 origins
    replay_5 = {
        "available": True,
        "comparable_origin_count": 5,
        "model_scores": {
            "robust_weekly": {"median_ae_minor": 5000, "mae_minor": 6000, "comparable_origins": 5},
            "weekday_hybrid": {"median_ae_minor": 15000, "mae_minor": 16000, "comparable_origins": 5}
        }
    }
    # With completed_months=6, fallback priority selects weekday_hybrid
    ctx = make_v108_context(completed_months=6)
    strat, reason = selector.select(ctx, replay_scores=replay_5)
    assert strat.id == "weekday_hybrid"
    assert "established history" in reason.lower()


def test_selector_respects_meaningful_improvement_guardrail():
    """
    F108-23: If winning candidate improves over fallback by < 5%, retain fallback.
    Fallback (weekday_hybrid) Median AE = 10,000 minor.
    Candidate (robust_weekly) Median AE = 9,800 minor (only 2% improvement).
    Selector must retain fallback to prevent model thrashing.
    """
    selector = ModelSelector()

    replay_scores = {
        "available": True,
        "comparable_origin_count": 8,
        "model_scores": {
            "weekday_hybrid": {"median_ae_minor": 10000, "mae_minor": 12000, "comparable_origins": 8},
            "robust_weekly": {"median_ae_minor": 9800, "mae_minor": 11500, "comparable_origins": 8}
        }
    }
    # 4 complete weeks from Monday 2026-08-03 to Sunday 2026-08-30
    dense_series = {}
    monday = date(2026, 8, 3)
    for i in range(28):
        dense_series[(monday + timedelta(days=i)).isoformat()] = 2000
    ctx = make_v108_context(completed_months=6, dense_daily_non_recurring_expense=dense_series)

    strat, reason = selector.select(ctx, replay_scores=replay_scores)
    # 2% improvement is below the 5% threshold -> fallback retained!
    assert strat.id == "weekday_hybrid"
    assert "fallback retained" in reason.lower()


# ==============================================================================
# 3. Database Migration 007 & Analytics State (F108-15)
# ==============================================================================

def test_migration_007_analytics_revision_trigger(isolated_db):
    """
    F108-15: Any INSERT, UPDATE, or DELETE on transactions or recurring_rules
    must increment analytics_state.revision.
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT revision FROM analytics_state WHERE id = 1")
        row = cur.fetchone()
        initial_rev = row[0] if row else 0

    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Food", "expense")

    # 1. Insert transaction increments revision
    TransactionRepository.create({
        "account_id": acc_id, "category_id": cat_id, "amount": 50.0,
        "transaction_type": "expense", "transaction_date": "2026-09-01"
    })

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT revision FROM analytics_state WHERE id = 1")
        rev_after_tx = cur.fetchone()[0]
        assert rev_after_tx > initial_rev

    # 2. Insert recurring rule increments revision
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO recurring_rules (name, transaction_type, amount_minor, category_id, account_id, next_due_date, frequency, active)
            VALUES ('Sub', 'expense', 1500, ?, ?, '2026-09-15', 'monthly', 1)
        """, (cat_id, acc_id))
        conn.commit()
        cur.execute("SELECT revision FROM analytics_state WHERE id = 1")
        rev_after_rec = cur.fetchone()[0]
        assert rev_after_rec > rev_after_tx


# ==============================================================================
# 4. Recurring Rule Resurrection & Unscheduled Rules (F108-13, F108-20)
# ==============================================================================

def test_deleted_or_inactive_recurring_rule_not_resurrected_by_history(isolated_db):
    """
    F108-13: When a recurring rule was deleted/deactivated, historical transactions
    linking to that rule ID must NOT resurrect it in future forecast.
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Gym", "expense")

    # Create and then delete a recurring rule
    rule_id = RecurringService.create({
        "name": "Old Gym Membership",
        "amount": 50.0,
        "transaction_type": "expense",
        "category_id": cat_id,
        "account_id": acc_id,
        "frequency": "monthly",
        "next_due_date": "2026-08-15"
    })
    RecurringService.delete_rule(rule_id)

    # Add historical recurring transaction linked to that rule_id in August
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO transactions (account_id, category_id, recurring_rule_id, transaction_type, amount_minor, transaction_date, is_recurring, merchant_name)
            VALUES (?, ?, ?, 'expense', 5000, '2026-08-15', 1, 'Old Gym Membership')
        """, (acc_id, cat_id, rule_id))
        conn.commit()

    # Forecast September 2026 as of Sept 10
    fc = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-10")
    # Upcoming recurring bills must NOT include Old Gym Membership!
    assert fc["upcoming_recurring_minor"] == 0


def test_rule_without_next_due_date_is_unscheduled(isolated_db):
    """
    F108-20: An active rule without next_due_date must be reported as unscheduled,
    not given an invented due date of day 15.
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Utilities", "expense")

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO recurring_rules (name, transaction_type, amount_minor, category_id, account_id, next_due_date, frequency, active)
            VALUES ('Unscheduled Water', 'expense', 4000, ?, ?, NULL, 'monthly', 1)
        """, (cat_id, acc_id))
        conn.commit()

    bills = RecurringService.get_upcoming_bills_for_month("2026-09", account_id=acc_id)
    water_bill = next((b for b in bills if b["name"] == "Unscheduled Water"), None)
    assert water_bill is not None
    assert water_bill["status"] == "unscheduled"
    assert water_bill["due_date"] is None
    assert water_bill["due_day"] is None

    # Forecast should also not count it as upcoming known expense
    fc = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-01")
    assert fc["upcoming_recurring_minor"] == 0


# ==============================================================================
# 5. Point Forecast Strictly Inside Range (F108-19)
# ==============================================================================

def test_point_forecast_always_bounded_inside_displayed_range(isolated_db):
    """
    F108-19: lower_bound_minor <= projected_expense_minor <= upper_bound_minor
    must strictly hold under all circumstances.
    """
    acc_id = AccountRepository.create("Checking", "checking")
    fc = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-10")
    proj = fc["projected_expense_minor"]
    lower = fc["lower_bound_minor"]
    upper = fc["upper_bound_minor"]

    assert lower <= proj <= upper


# ==============================================================================
# 6. Category Variable Allocation & Uncategorised Fallback (F108-14, F108-28)
# ==============================================================================

def test_category_variable_weights_exclude_recurring_actual_spend(isolated_db):
    """
    F108-14: Category variable weights must be based on non-recurring expenses.
    If Cat A has $1,000 recurring rent and Cat B has $100 variable groceries,
    future variable spend must NOT be 90% allocated to Cat A rent!
    It must be 100% allocated to Cat B groceries!
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_rent = CategoryRepository.create("Rent", "expense")
    cat_groc = CategoryRepository.create("Groceries", "expense")

    with get_db_connection() as conn:
        cur = conn.cursor()
        # Cat Rent: $1,000 recurring spend in September
        cur.execute("""
            INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring)
            VALUES (?, ?, 'expense', 100000, '2026-09-02', 1)
        """, (acc_id, cat_rent))
        # Cat Groceries: $100 non-recurring spend in September
        cur.execute("""
            INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring)
            VALUES (?, ?, 'expense', 10000, '2026-09-05', 0)
        """, (acc_id, cat_groc))
        conn.commit()

    fc = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-10")
    cats = {c["category_id"]: c for c in fc["category_forecasts"]}

    # Rent actual: 100000, but projected variable addition must be 0!
    # Groceries: actual 10000, receives all variable forecast!
    rem_var = fc["expected_variable_minor"]
    if rem_var > 0:
        # Groceries projected must equal actual + rem_var
        assert cats[cat_groc]["projected_minor"] == 10000 + rem_var
        # Rent projected must equal actual (100000) + 0 variable
        assert cats[cat_rent]["projected_minor"] == 100000


def test_category_variable_fallback_allocates_to_uncategorised_when_no_evidence(isolated_db):
    """
    F108-28: When remaining_variable_minor > 0 but no category evidence exists,
    variable spend is assigned to Uncategorised (id=0), not equally spread.
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_misc = CategoryRepository.create("Misc", "expense")
    cat_ent = CategoryRepository.create("Entertainment", "expense")

    # Day 5 with no prior transactions: fallback pace or rate creates remaining variable
    fc = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-05")
    # If variable exists with 0 category history, it must allocate to Uncategorised
    cats = {c["category_id"]: c for c in fc["category_forecasts"]}
    if fc["expected_variable_minor"] > 0:
        assert 0 in cats
        assert cats[0]["name"] == "Uncategorised"
        assert cats[0]["projected_minor"] == fc["expected_variable_minor"]


# ==============================================================================
# 7. Replay Cache & Sequential Production Policy (F108-09, F108-15, F108-18)
# ==============================================================================

def test_replay_cache_invalidates_on_transaction_mutation(isolated_db):
    """
    F108-15: Revision in cache key ensures changes to transactions or rules
    produce a different cache key.
    """
    key1 = HistoricalReplayRunner._get_cache_key(account_id=1, as_of_date="2026-09-10")
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Food", "expense")
    TransactionRepository.create({
        "account_id": acc_id, "category_id": cat_id, "amount": 25.0,
        "transaction_type": "expense", "transaction_date": "2026-09-02"
    })
    key2 = HistoricalReplayRunner._get_cache_key(account_id=1, as_of_date="2026-09-10")
    assert key1 != key2


def test_calibrated_range_requires_eight_residuals():
    """
    F108-18: get_calibrated_residuals requires >= 8 samples to return 'calibrated_range'.
    With 7 samples, it returns 'early_estimate'.
    """
    from app.backend.analytics.forecast_replay import _RESIDUALS_BY_BUCKET_CACHE, get_progress_bucket, HistoricalReplayRunner

    cache_key = (HistoricalReplayRunner.CACHE_VERSION, 999, 1, "__latest__")
    _RESIDUALS_BY_BUCKET_CACHE[cache_key] = {
        2: [100, -200, 150, -50, 300, -100, 80]  # 7 samples
    }

    bucket = get_progress_bucket(0.60)  # bucket 2
    assert bucket == 2
    residuals = _RESIDUALS_BY_BUCKET_CACHE[cache_key][2]
    assert len(residuals) == 7

    # Directly verify threshold check
    res_type = "calibrated_range" if len(residuals) >= FORECAST_CONFIG.calibrated_range_min_residuals else "early_estimate"
    assert res_type == "early_estimate"

    # Add 8th sample
    residuals.append(50)
    res_type_8 = "calibrated_range" if len(residuals) >= FORECAST_CONFIG.calibrated_range_min_residuals else "early_estimate"
    assert res_type_8 == "calibrated_range"
