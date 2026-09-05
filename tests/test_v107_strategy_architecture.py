"""
Unit and Integration Test Suite for FinScope Forecasting v1.0.7
Validates Strategy Pattern Architecture, Robust Weekly Residual Model,
Model Registry, and Replay-Driven Adaptive Selection.
"""

import pytest
from datetime import date, datetime, timedelta
from app.backend.database.connection import get_db_connection
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository
from app.backend.analytics.forecasting import ForecastingEngine

from app.backend.analytics.forecast_replay import HistoricalReplayRunner
from app.backend.analytics.forecast_strategies import (
    ForecastContext,
    ForecastEstimate,
    ForecastStrategy,
    CurrentPaceStrategy,
    RecentMedianStrategy,
    RobustWeeklyResidualStrategy,
    WeekdayHybridStrategy,
    SeasonalNaiveStrategy,
    ModelRegistry,
    default_registry,
    ModelSelector
)


# ==============================================================================
# Helper to build mock ForecastContext for isolated strategy testing
# ==============================================================================

def make_context(
    target_month: str = "2026-09",
    as_of_date: str = "2026-09-10",
    elapsed_day: int = 10,
    remaining_days: int = 20,
    num_days: int = 30,
    actual_net_spend_to_date: int = 100000,
    upcoming_recurring_minor: int = 20000,
    completed_months: int = 4,
    hist_monthly_spends: list = None,
    dense_daily_non_recurring: dict = None,
    weekday_avg_minor: dict = None,
    replay_mode: bool = False,
    forced_method: str = None
) -> ForecastContext:
    if hist_monthly_spends is None:
        hist_monthly_spends = [150000, 160000, 155000, 165000]
    if dense_daily_non_recurring is None:
        dense_daily_non_recurring = {}
    if weekday_avg_minor is None:
        weekday_avg_minor = {i: 5000 for i in range(7)}

    # Convert hist_monthly_spends to continuous dictionary ending in prior month
    hist_months_dict = {}
    y, m = map(int, target_month.split("-"))
    cur_m = date(y, m, 1)
    for idx, amt in enumerate(reversed(hist_monthly_spends)):
        # Month idx + 1 prior to target_month
        pm = cur_m - timedelta(days=28 * (idx + 1))
        pm_str = f"{pm.year:04d}-{pm.month:02d}"
        hist_months_dict[pm_str] = amt

    # Ensure reference month for seasonal naive exists if >= 12 months
    if len(hist_monthly_spends) >= 12:
        hist_months_dict[f"{y - 1:04d}-{m:02d}"] = hist_monthly_spends[0]

    remaining_dates = tuple(f"{target_month}-{d:02d}" for d in range(elapsed_day + 1, num_days + 1))

    return ForecastContext(
        target_month=target_month,
        as_of_date=as_of_date,
        account_id=1,
        elapsed_day=elapsed_day,
        remaining_days=remaining_days,
        num_days=num_days,
        remaining_calendar_dates=remaining_dates,
        actual_expense_minor=actual_net_spend_to_date,
        actual_income_minor=300000,
        actual_refund_minor=0,
        actual_net_spend_to_date_minor=actual_net_spend_to_date,
        actual_non_recurring_expense_minor=actual_net_spend_to_date,
        actual_recurring_expense_minor=0,
        upcoming_recurring_expense_minor=upcoming_recurring_minor,
        upcoming_recurring_income_minor=0,
        hist_monthly_non_recurring_expense=hist_months_dict,
        dense_daily_non_recurring_expense=dense_daily_non_recurring,
        weekday_rates=weekday_avg_minor,
        weekday_sample_counts={i: 4 for i in range(7)},
        global_non_recurring_daily_rate=5000,
        actual_cat_spends_net={},
        actual_cat_non_recurring_expense={},
        historical_cat_non_recurring_expense={},
        cat_metadata={},
        upcoming_recurring_by_cat={},
        completed_months=completed_months,
        transaction_count=25
    )


# ==============================================================================
# Group 1: Strategy Pattern Architecture & Model Registry
# ==============================================================================

def test_registry_contains_all_v107_strategies():
    """Registry must include all 5 canonical FinScope statistical models."""
    registry = default_registry
    models = registry.list_models()
    model_ids = {m.id for m in models}

    assert "current_pace" in model_ids
    assert "three_month_median" in model_ids
    assert "robust_weekly" in model_ids
    assert "weekday_hybrid" in model_ids
    assert "seasonal_naive" in model_ids


def test_registry_eligibility_filtering():
    """Registry correctly filters eligible models based on history and context."""
    registry = default_registry

    # Low history (1 month)
    ctx_low = make_context(completed_months=1, hist_monthly_spends=[100000])
    eligible_low = {s.id for s in registry.get_eligible(ctx_low)}
    assert "current_pace" in eligible_low
    assert "three_month_median" not in eligible_low
    assert "seasonal_naive" not in eligible_low

    # Mature history (14 months)
    ctx_high = make_context(completed_months=14, hist_monthly_spends=[100000] * 14)
    eligible_high = {s.id for s in registry.get_eligible(ctx_high)}
    assert "current_pace" in eligible_high
    assert "three_month_median" in eligible_high
    assert "weekday_hybrid" in eligible_high
    assert "seasonal_naive" in eligible_high


# ==============================================================================
# Group 2: Individual Strategy Predictions
# ==============================================================================

def test_current_pace_strategy_prediction():
    """Current pace extrapolates daily run-rate across remaining days."""
    strat = CurrentPaceStrategy()
    ctx = make_context(
        elapsed_day=10,
        remaining_days=20,
        actual_net_spend_to_date=100000  # $1,000 -> $100/day
    )
    est = strat.predict(ctx)
    assert est.model_id == "current_pace"
    assert est.remaining_variable_minor == 200000  # 20 days * $100 = $2,000
    assert est.diagnostics["implied_daily_variable_rate"] == 10000


def test_current_pace_day_zero_safeguard():
    """At day 0, pace must be safely 0 without division by zero."""
    strat = CurrentPaceStrategy()
    ctx = make_context(elapsed_day=0, remaining_days=30, actual_net_spend_to_date=0)
    est = strat.predict(ctx)
    assert est.remaining_variable_minor == 0
    assert est.diagnostics["implied_daily_variable_rate"] == 0


def test_recent_median_strategy_prediction():
    """F108-02: Recent median uses pure non-recurring median and prorates by remaining days."""
    strat = RecentMedianStrategy()
    ctx = make_context(
        num_days=30,
        remaining_days=15,
        hist_monthly_spends=[120000, 140000, 160000],  # median = 140000
        upcoming_recurring_minor=20000
    )
    est = strat.predict(ctx)
    assert est.model_id == "three_month_median"
    # Pure non-recurring median: 140000 * (15 / 30) = 70000
    assert est.remaining_variable_minor == 70000
    assert est.diagnostics["median_monthly_variable"] == 140000


def test_seasonal_naive_strategy_requires_12_months():
    """Seasonal naive is only eligible when >= 12 months of history exist."""
    strat = SeasonalNaiveStrategy()
    ctx_11 = make_context(completed_months=11, hist_monthly_spends=[100000] * 11)
    assert strat.is_eligible(ctx_11) is False

    ctx_12 = make_context(completed_months=12, hist_monthly_spends=[150000] + [100000] * 11)
    assert strat.is_eligible(ctx_12) is True
    est = strat.predict(ctx_12)
    assert est.model_id == "seasonal_naive"
    # Spend in reference month (2025-09) was 150000, prorated for 20/30 days = 100000
    assert est.remaining_variable_minor == 100000


# ==============================================================================
# Group 3: Robust Weekly Residual Strategy
# ==============================================================================

def test_robust_weekly_residual_outlier_resistance():
    """
    Validates that a massive single-day outlier spike in Week 1 does NOT distort
    the median weekly estimator, unlike mean or current pace.
    """
    strat = RobustWeeklyResidualStrategy()

    # Generate 4 complete Monday-Sunday weeks (28 days) of dense daily non-recurring expenses
    # 2026-08-03 is Monday
    dense_series = {}
    base_date = date(2026, 8, 3)

    for i in range(28):
        cur_d = base_date + timedelta(days=i)
        d_str = cur_d.isoformat()
        dense_series[d_str] = 3000

    # Week 1 day 0 (Monday Aug 3): inject extreme one-off $1,000 appliance purchase (100,000 minor)
    first_day_str = base_date.isoformat()
    dense_series[first_day_str] = 100000

    ctx = make_context(
        num_days=30,
        remaining_days=10,
        dense_daily_non_recurring=dense_series
    )

    weekly_totals = ctx.get_complete_weekly_totals(max_weeks=4)
    assert len(weekly_totals) == 4

    # Week 1: 100000 + 6*3000 = 118000
    # Weeks 2, 3, 4: 7*3000 = 21000 each
    assert 118000 in weekly_totals
    assert weekly_totals.count(21000) == 3

    # Median weekly total must be 21000 (the 118000 spike is completely rejected!)
    est = strat.predict(ctx)
    assert est.model_id == "robust_weekly"
    assert est.diagnostics["median_weekly_minor"] == 21000

    # Remaining 10 days variable spend: round(21000 * 10 / 7) = 30000
    assert est.remaining_variable_minor == 30000


# ==============================================================================
# Group 4: Model Selector (Fallback vs Adaptive Replay Selection)
# ==============================================================================

def test_model_selector_deterministic_fallback():
    """Without replay evidence, ModelSelector adheres to deterministic configured fallback priority."""
    selector = ModelSelector()

    # Low history (1 month) -> current_pace is only eligible
    ctx_1 = make_context(completed_months=1)
    s1, r1 = selector.select(ctx_1)
    assert s1.id == "current_pace"

    # 3 months with daily weekday history -> weekday_hybrid is eligible and highest priority
    ctx_3 = make_context(completed_months=3)
    s2, r2 = selector.select(ctx_3)
    assert s2.id == "weekday_hybrid"

    # 3 months without daily weekday history -> three_month_median wins fallback
    empty_counts = {i: 0 for i in range(7)}
    ctx_sparse = ForecastContext(
        target_month="2026-09",
        as_of_date="2026-09-10",
        account_id=1,
        elapsed_day=10,
        remaining_days=20,
        num_days=30,
        remaining_calendar_dates=tuple(f"2026-09-{d:02d}" for d in range(11, 31)),
        actual_expense_minor=100000,
        actual_income_minor=300000,
        actual_refund_minor=0,
        actual_net_spend_to_date_minor=100000,
        actual_non_recurring_expense_minor=100000,
        actual_recurring_expense_minor=0,
        upcoming_recurring_expense_minor=20000,
        upcoming_recurring_income_minor=0,
        hist_monthly_non_recurring_expense={"2026-06": 50000, "2026-07": 60000, "2026-08": 55000},
        dense_daily_non_recurring_expense={},
        weekday_rates=empty_counts,
        weekday_sample_counts=empty_counts,
        global_non_recurring_daily_rate=0,
        actual_cat_spends_net={},
        actual_cat_non_recurring_expense={},
        historical_cat_non_recurring_expense={},
        cat_metadata={},
        upcoming_recurring_by_cat={},
        completed_months=3,
        transaction_count=25
    )
    s_sparse, r_sparse = selector.select(ctx_sparse)
    assert s_sparse.id == "three_month_median"


def test_model_selector_forced_override():
    """Forced method takes precedence if eligible."""
    selector = ModelSelector()
    ctx = make_context(completed_months=6)
    s, r = selector.select(ctx, forced_method="weekday_hybrid")
    assert s.id == "weekday_hybrid"


def test_model_selector_adaptive_replay_selection():
    """
    When historical replay provides empirical error evidence with sufficient comparable origins,
    ModelSelector chooses the strategy with lowest Median AE on common origins.
    """
    selector = ModelSelector()

    mock_replay_scores = {
        "available": True,
        "comparable_origin_count": 12,
        "models": {
            "weekday_hybrid": {
                "comparable_origins": 12,
                "median_ae_minor": 45000,
                "mae_minor": 50000
            },
            "robust_weekly": {
                "comparable_origins": 12,
                "median_ae_minor": 18000,  # Best performer
                "mae_minor": 22000
            },
            "current_pace": {
                "comparable_origins": 12,
                "median_ae_minor": 60000,
                "mae_minor": 65000
            }
        }
    }

    # Context with 4 complete Monday-Sunday weeks (2026-08-03 to 2026-08-30)
    dense_series = {}
    base_monday = date(2026, 8, 3)
    for i in range(28):
        dense_series[(base_monday + timedelta(days=i)).isoformat()] = 2000

    ctx = make_context(
        completed_months=8,
        dense_daily_non_recurring=dense_series
    )

    s, reason = selector.select(ctx, replay_scores=mock_replay_scores)
    assert s.id == "robust_weekly"
    assert "adaptive replay selection" in reason.lower()
    assert "18000" in reason


# ==============================================================================
# Group 5: End-to-End Engine Integration with v1.0.7
# ==============================================================================

def test_engine_forecast_month_integrates_strategy_architecture(isolated_db):
    """
    ForecastingEngine.forecast_month end-to-end integration:
    - Queries actuals, expands recurring rules, resolves strategy via selector,
    - Reconciles categories, zero penny drift invariant holds.
    """
    acc_id = AccountRepository.create("Main Checking", "checking")
    cat_food = CategoryRepository.create("Food", "expense")
    cat_rent = CategoryRepository.create("Rent", "expense")

    # Add transactions in target month (September 2026) up to Sept 10
    TransactionRepository.create({
        "account_id": acc_id, "category_id": cat_food, "amount": 150.0,
        "transaction_type": "expense", "transaction_date": "2026-09-05"
    })
    # Refund of $20 in food
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring)
            VALUES (?, ?, 'refund', 2000, '2026-09-08', 0)
        """, (acc_id, cat_food))
        # Recurring rule: Rent $500 on Sept 15
        cur.execute("""
            INSERT INTO recurring_rules (name, transaction_type, amount_minor, category_id, account_id, next_due_date, frequency, active)
            VALUES ('Apartment Rent', 'expense', 50000, ?, ?, '2026-09-15', 'monthly', 1)
        """, (cat_rent, acc_id))
        conn.commit()



    # Run forecast
    res = ForecastingEngine.forecast_month(
        month="2026-09",
        account_id=acc_id,
        as_of_date="2026-09-10"
    )

    # Core invariant: actual + recurring + variable - refund == projected
    assert res["actual_spent_to_date_minor"] == 13000  # $150 - $20 = $130
    assert res["upcoming_recurring_minor"] == 50000  # $500
    assert res["projected_expense_minor"] == (
        res["actual_spent_to_date_minor"] +
        res["upcoming_recurring_minor"] +
        res["expected_variable_minor"]
    )


    # Model metadata present
    assert "model_method" in res
    assert "method" in res
    assert "selection_reason" in res["diagnostics"]
    assert res["diagnostics"]["selected_method"] == res["model_method"]



def test_replay_runner_evaluates_robust_weekly_candidate(isolated_db):
    """
    HistoricalReplayRunner must evaluate robust_weekly alongside production_policy and hybrid.
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Living", "expense")

    # Seed 3 historical months
    months_data = [
        ("2025-01", 1000.0),
        ("2025-02", 1100.0),
        ("2025-03", 1050.0)
    ]
    for m, amt in months_data:
        TransactionRepository.create({
            "account_id": acc_id, "category_id": cat_id, "amount": amt,
            "transaction_type": "expense", "transaction_date": f"{m}-10"
        })

    replay_res = HistoricalReplayRunner.run_replay(account_id=acc_id, as_of_date="2025-04-01")
    assert replay_res["available"] is True
    models = replay_res["models"]

    # All candidate models must be evaluated
    assert "production_policy" in models
    assert "finscope_hybrid" in models
    assert "robust_weekly" in models
    assert "current_pace" in models
    assert models["robust_weekly"]["sample_origins"] > 0
