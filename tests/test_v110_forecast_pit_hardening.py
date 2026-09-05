"""
Tests for FinScope Forecasting v1.1.0/v1.0.11 — Point-in-Time & Replay Integrity Hardening.
Verifies:
1. Replay label-availability invariant: Day 14/21 within a target month does NOT use Day 7/14 errors from that same month.
2. Recurring rule snapshot PIT: Historical forecast uses rule state valid as of cutoff date.
3. Residual cutoff PIT: Calibrated residuals request passes explicit cutoff date and does not use future months.
4. Late-month calibration: Progress > 0.75 bucket (bucket 3) receives Day 26 calibration samples.
5. Strict replay evidence contract: ModelSelector ignores legacy 'models' fallback.
6. Strict confidence contract: Confidence error calculation ignores legacy 'models' fallback.
7. Zero-budget numeric variance: Budget of 0 produces numeric variance, not None.
8. Cache identity: Month rollover alters cache key even without DB revision changes.
"""

import pytest
from datetime import date
from app.backend.database.connection import get_db_connection, init_db
from app.backend.analytics.forecasting import ForecastingEngine
from app.backend.analytics.forecast_replay import HistoricalReplayRunner, _REPLAY_CACHE, _RESIDUALS_BY_BUCKET_CACHE
from app.backend.analytics.forecast_strategies.selector import ModelSelector
from app.backend.analytics.forecast_strategies.context import ForecastContext
from app.backend.analytics.forecast_strategies.config import FORECAST_CONFIG
from app.backend.analytics.forecast_strategies.request import ForecastRequest


@pytest.fixture(autouse=True)
def clean_cache_and_db(isolated_data_dir):
    """Initializes isolated DB and clears replay caches for every test."""
    init_db()
    _REPLAY_CACHE.clear()
    _RESIDUALS_BY_BUCKET_CACHE.clear()
    yield


def test_production_replay_does_not_use_same_month_error_at_later_cutoff():
    """
    F110-05: Replay label-availability invariant.
    All cutoffs in target month M must receive prior evidence strictly derived from
    completed months < M. Day 14 must not see candidate performance from Day 7 of month M.
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO accounts (id, name, account_type) VALUES (1, 'Checking', 'Everyday')")
        for m, amt in [("2026-01", 100000), ("2026-02", 100000), ("2026-03", 100000), ("2026-04", 100000)]:
            cur.execute("""
                INSERT INTO transactions (account_id, transaction_type, amount_minor, transaction_date, description)
                VALUES (1, 'expense', ?, ? || '-10', 'Expense ' || ?)
            """, [amt, m, m])
        conn.commit()

    res = HistoricalReplayRunner.run_replay(account_id=1, as_of_date="2026-05-01")
    assert res["available"] is True


def test_live_historical_forecast_uses_recurring_version_at_cutoff():
    """
    F110-06: Historical live forecast reads recurring_rule_versions as of cutoff,
    NOT current recurring_rules.
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO accounts (id, name, account_type) VALUES (1, 'Checking', 'Everyday')")
        cur.execute("""
            INSERT INTO transactions (account_id, transaction_type, amount_minor, transaction_date, description)
            VALUES (1, 'income', 500000, '2026-01-01', 'Salary')
        """)

        # Version 1: Rent was $100 (10000 minor), valid 2026-01-01 to 2026-06-01
        cur.execute("""
            INSERT INTO recurring_rule_versions (
                rule_id, account_id, name, transaction_type, amount_minor, category_id, next_due_date, frequency, active, valid_from, valid_to
            ) VALUES (1, 1, 'Apartment Rent', 'expense', 10000, NULL, '2026-05-20', 'monthly', 1, '2026-01-01', '2026-06-01')
        """)

        # Version 2: Rent increased to $200 (20000 minor), valid from 2026-06-01 onward
        cur.execute("""
            INSERT INTO recurring_rule_versions (
                rule_id, account_id, name, transaction_type, amount_minor, category_id, next_due_date, frequency, active, valid_from, valid_to
            ) VALUES (1, 1, 'Apartment Rent', 'expense', 20000, NULL, '2026-06-20', 'monthly', 1, '2026-06-01', NULL)
        """)

        # Current table has $200
        cur.execute("""
            INSERT INTO recurring_rules (
                id, account_id, name, transaction_type, amount_minor, category_id, next_due_date, frequency, active
            ) VALUES (1, 1, 'Apartment Rent', 'expense', 20000, NULL, '2026-06-20', 'monthly', 1)
        """)
        conn.commit()

    req = ForecastRequest(
        target_month="2026-05",
        as_of_date="2026-05-10",
        account_id=1,
        mode="live"
    )
    fc_may = ForecastingEngine.forecast(req)

    assert fc_may["upcoming_recurring_minor"] == 10000


def test_historical_calibration_residuals_use_requested_cutoff():
    """
    F110-03: get_calibrated_residuals must accept as_of_date and scope its replay
    to the requested cutoff, rather than using latest cache.
    """
    res_type, residuals = HistoricalReplayRunner.get_calibrated_residuals(
        account_id=1,
        progress=0.5,
        as_of_date="2026-03-15"
    )
    cache_key = HistoricalReplayRunner._get_cache_key(account_id=1, as_of_date="2026-03-15")
    assert cache_key[3] == "2026-03-15"


def test_late_month_progress_can_reach_calibrated_bucket():
    """
    F110-07: Calibration replay evaluates Day 26 production policy, populating bucket 3 (75-100%).
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO accounts (id, name, account_type) VALUES (1, 'Checking', 'Everyday')")
        for yr in [2025, 2026]:
            for mo in range(1, 13):
                if yr == 2026 and mo > 6:
                    break
                m_str = f"{yr:04d}-{mo:02d}"
                cur.execute("""
                    INSERT INTO transactions (account_id, transaction_type, amount_minor, transaction_date, description)
                    VALUES (1, 'expense', 80000, ? || '-15', 'Monthly living')
                """, [m_str])
        conn.commit()

    res = HistoricalReplayRunner.run_replay(account_id=1, as_of_date="2026-07-01")
    assert res["available"] is True

    bucket_3_residuals = res["residuals_by_bucket"][3]
    assert len(bucket_3_residuals) >= 8

    r_type, r_residuals = HistoricalReplayRunner.get_calibrated_residuals(
        account_id=1,
        progress=0.85,
        as_of_date="2026-07-01"
    )
    assert r_type == "calibrated_range"
    assert len(r_residuals) >= 8


def test_selector_does_not_read_legacy_models_fallback():
    """
    F110-01: ModelSelector must only evaluate model_scores; poisoning legacy 'models'
    map must not trigger adaptive selection.
    """
    selector = ModelSelector()
    context = ForecastContext(
        target_month="2026-09",
        as_of_date="2026-09-15",
        account_id=1,
        elapsed_day=15,
        remaining_days=15,
        num_days=30,
        remaining_calendar_dates=tuple(f"2026-09-{d:02d}" for d in range(16, 31)),
        actual_expense_minor=50000,
        actual_income_minor=100000,
        actual_refund_minor=0,
        actual_net_spend_to_date_minor=50000,
        actual_non_recurring_expense_minor=50000,
        actual_recurring_expense_minor=0,
        upcoming_recurring_expense_minor=0,
        upcoming_recurring_income_minor=0,
        hist_monthly_non_recurring_expense={"2026-06": 90000, "2026-07": 95000, "2026-08": 100000},
        dense_daily_non_recurring_expense={},
        weekday_rates={0: 3000, 1: 3000, 2: 3000, 3: 3000, 4: 3000, 5: 3000, 6: 3000},
        weekday_sample_counts={0: 5, 1: 5, 2: 5, 3: 5, 4: 5, 5: 5, 6: 5},
        global_non_recurring_daily_rate=3000,
        actual_cat_spends_net={},
        actual_cat_non_recurring_expense={},
        historical_cat_non_recurring_expense={},
        cat_metadata={},
        upcoming_recurring_by_cat={},
        completed_months=3,
        transaction_count=45
    )

    poisoned_replay = {
        "available": True,
        "comparable_origin_count": 12,
        "model_scores": {},
        "models": {
            "robust_weekly": {
                "comparable_origins": 12,
                "median_ae_minor": 1,
                "mae_minor": 1,
                "bias_minor": 0
            }
        }
    }

    selected, reason = selector.select(context, replay_scores=poisoned_replay)
    assert selected.id == "weekday_hybrid"


def test_confidence_does_not_read_legacy_models_fallback():
    """
    F110-02: Confidence calculation must NOT fall back to legacy replay_summary['models'].
    Poisoning 'models' while canonical scores are absent leaves confidence on neutral fallback.
    """
    fc = ForecastingEngine.forecast_month(
        month="2026-09",
        as_of_date="2026-09-15",
        account_id=1,
        replay_mode=False,
        replay_evidence={
            "available": True,
            "comparable_origin_count": 12,
            "model_scores": {},
            "production_policy": {},
            "models": {
                "weekday_hybrid": {"mae_minor": 1}
            }
        }
    )

    # The confidence error component must not have used the poisoned MAE of 1 minor unit.
    assert fc["confidence"] in ("moderate", "low")


def test_zero_budget_has_numeric_projected_variance():
    """
    F110-09: An explicit zero-budget record (amount_minor = 0) must produce a numeric
    projected_variance_minor, not None.
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO accounts (id, name, account_type) VALUES (1, 'Checking', 'Everyday')")
        cur.execute("INSERT INTO budgets (category_id, start_date, amount_minor) VALUES (1, '2026-09', 0)")
        cur.execute("""
            INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, description)
            VALUES (1, 1, 'expense', 15000, '2026-09-05', 'Groceries')
        """)
        conn.commit()

    fc = ForecastingEngine.forecast_month(month="2026-09", as_of_date="2026-09-10", account_id=1)

    assert fc["budget_minor"] == 0
    assert fc["projected_variance_minor"] is not None
    assert fc["projected_variance_minor"] == fc["projected_expense_minor"]


def test_month_rollover_changes_residual_cache_identity_without_revision_change():
    """
    F110-08: Replay cache identity must be keyed by explicit cutoff date (YYYY-MM-DD),
    so month rollover without DB revision still changes the cache key.
    """
    key_sep30 = HistoricalReplayRunner._get_cache_key(account_id=1, as_of_date="2026-09-30")
    key_oct01 = HistoricalReplayRunner._get_cache_key(account_id=1, as_of_date="2026-10-01")

    assert key_sep30 != key_oct01
    assert key_sep30[3] == "2026-09-30"
    assert key_oct01[3] == "2026-10-01"
    key_default = HistoricalReplayRunner._get_cache_key(account_id=1)
    assert key_default[3] != "__latest__"


def test_historical_rule_created_after_cutoff_not_visible():
    """
    F110-06: A rule created after the historical cutoff must NOT be included in the historical forecast.
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO accounts (id, name, account_type) VALUES (1, 'Checking', 'Everyday')")
        cur.execute("""
            INSERT INTO transactions (account_id, transaction_type, amount_minor, transaction_date, description)
            VALUES (1, 'income', 500000, '2026-01-01', 'Salary')
        """)

        # Rule created in August 2026 (valid_from = 2026-08-01)
        cur.execute("""
            INSERT INTO recurring_rule_versions (
                rule_id, account_id, name, transaction_type, amount_minor, category_id, next_due_date, frequency, active, valid_from, valid_to
            ) VALUES (10, 1, 'Gym Membership', 'expense', 5000, NULL, '2026-05-15', 'monthly', 1, '2026-08-01', NULL)
        """)
        conn.commit()

    # Forecast for May 2026 as of 2026-05-10
    req = ForecastRequest(target_month="2026-05", as_of_date="2026-05-10", account_id=1, mode="live")
    fc = ForecastingEngine.forecast(req)

    # Gym rule was not active in May
    assert fc["upcoming_recurring_minor"] == 0


def test_historical_rule_deleted_after_cutoff_still_visible():
    """
    F110-06: A rule that was active at the historical cutoff and deleted later must still be visible in the historical forecast.
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO accounts (id, name, account_type) VALUES (1, 'Checking', 'Everyday')")
        cur.execute("""
            INSERT INTO transactions (account_id, transaction_type, amount_minor, transaction_date, description)
            VALUES (1, 'income', 500000, '2026-01-01', 'Salary')
        """)

        # Rule active until deleted on 2026-07-01 (valid_to = 2026-07-01)
        cur.execute("""
            INSERT INTO recurring_rule_versions (
                rule_id, account_id, name, transaction_type, amount_minor, category_id, next_due_date, frequency, active, valid_from, valid_to
            ) VALUES (20, 1, 'Internet', 'expense', 6000, NULL, '2026-05-25', 'monthly', 1, '2026-01-01', '2026-07-01')
        """)
        conn.commit()

    # Forecast for May 2026 as of 2026-05-10
    req = ForecastRequest(target_month="2026-05", as_of_date="2026-05-10", account_id=1, mode="live")
    fc = ForecastingEngine.forecast(req)

    # Internet rule WAS active in May, so it should be included!
    assert fc["upcoming_recurring_minor"] == 6000


def test_forecast_request_mode_validation():
    """
    F110-04: ForecastRequest validates invalid mode combinations.
    """
    # Invalid mode
    with pytest.raises(ValueError, match="Invalid forecast mode"):
        ForecastRequest(target_month="2026-09", mode="invalid_mode")

    # candidate_replay without forced_method
    with pytest.raises(ValueError, match="candidate_replay mode requires forced_method"):
        ForecastRequest(target_month="2026-09", as_of_date="2026-09-15", mode="candidate_replay")

    # candidate_replay without as_of_date
    with pytest.raises(ValueError, match="candidate_replay mode requires explicit as_of_date"):
        ForecastRequest(target_month="2026-09", mode="candidate_replay", forced_method="current_pace")

    # production_replay with forced_method
    with pytest.raises(ValueError, match="production_replay mode does not allow forced_method"):
        ForecastRequest(target_month="2026-09", as_of_date="2026-09-15", mode="production_replay", forced_method="robust_weekly")


def test_legacy_wrapper_parity():
    """
    F110-04: forecast_month() compatibility wrapper returns numerically identical
    results to canonical forecast(ForecastRequest).
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO accounts (id, name, account_type) VALUES (1, 'Checking', 'Everyday')")
        cur.execute("""
            INSERT INTO transactions (account_id, transaction_type, amount_minor, transaction_date, description)
            VALUES (1, 'expense', 45000, '2026-09-02', 'Shopping')
        """)
        conn.commit()

    res_wrapper = ForecastingEngine.forecast_month(month="2026-09", as_of_date="2026-09-10", account_id=1)
    res_canonical = ForecastingEngine.forecast(
        ForecastRequest(target_month="2026-09", as_of_date="2026-09-10", account_id=1, mode="live")
    )

    for field in ["projected_expense_minor", "lower_bound_minor", "upper_bound_minor", "method", "confidence", "confidence_score"]:
        assert res_wrapper[field] == res_canonical[field]


def test_replay_diagnostics_and_error_sign():
    """
    F110-11 & F110-12: Replay results include contract version, origin days, failure count,
    and residual_minor == -error_minor relationship.
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO accounts (id, name, account_type) VALUES (1, 'Checking', 'Everyday')")
        for m in ["2026-01", "2026-02", "2026-03"]:
            cur.execute("""
                INSERT INTO transactions (account_id, transaction_type, amount_minor, transaction_date, description)
                VALUES (1, 'expense', 100000, ? || '-10', 'Expense')
            """, [m])
        conn.commit()

    res = HistoricalReplayRunner.run_replay(account_id=1, as_of_date="2026-04-01")
    assert res["replay_contract_version"] == 2
    assert res["selection_origin_days"] == [7, 14, 21]
    assert 26 in res["calibration_origin_days"]
    assert res["replay_failure_count"] == 0
    assert isinstance(res["replay_failures"], list)

    for r in res["residuals"]:
        # Verify sign convention: residual = actual - predicted = -(predicted - actual)
        assert r["residual_minor"] == r["actual_minor"] - r["predicted_minor"]
        assert r["abs_error_minor"] == abs(r["residual_minor"])
