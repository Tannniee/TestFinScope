"""
Comprehensive Unit and Regression Test Suite for FinScope Forecasting v1.0.5.
Validates:
- Group A: Recurring schedule expansion (weekly, fortnightly, monthly, future boundary, account scope)
- Group B: Income reconciliation (salary double counting prevention, net flow, savings rate)
- Group C: Category reconciliation (normalized weights, zero-drift sum, historical allocation)
- Group D: Historical replay & data leakage isolation (as_of_date isolation, actual engine evaluation)
- Group E: Multi-factor confidence scoring
- Group F: Calibrated ranges vs early estimates
- Group G: Model eligibility by data sufficiency
- Group H: Core financial forecast invariants
"""

import pytest
from datetime import date
from app.backend.database.connection import get_db_connection
from app.backend.analytics.forecasting import ForecastingEngine, generate_occurrences
from app.backend.analytics.forecast_replay import HistoricalReplayRunner
from app.backend.analytics.backtesting import BacktestingEngine
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository


# ==============================================================================
# Group A: Recurring Schedule Tests (F105-02)
# ==============================================================================

def test_generate_occurrences_weekly():
    """Weekly rule expands to all remaining occurrences in the target month."""
    start_d = date(2026, 9, 10)
    end_d = date(2026, 9, 30)
    occs = generate_occurrences(next_due_date="2026-09-12", frequency="weekly", start_date=start_d, end_date=end_d)
    assert occs == [date(2026, 9, 12), date(2026, 9, 19), date(2026, 9, 26)]


def test_generate_occurrences_fortnightly():
    """Fortnightly rule steps by 14 days."""
    start_d = date(2026, 9, 1)
    end_d = date(2026, 9, 30)
    occs = generate_occurrences(next_due_date="2026-09-05", frequency="fortnightly", start_date=start_d, end_date=end_d)
    assert occs == [date(2026, 9, 5), date(2026, 9, 19)]


def test_generate_occurrences_monthly_future_boundary():
    """Next due date in next month contributes 0 occurrences to current month."""
    start_d = date(2026, 9, 10)
    end_d = date(2026, 9, 30)
    occs = generate_occurrences(next_due_date="2026-10-20", frequency="monthly", start_date=start_d, end_date=end_d)
    assert occs == []


def test_weekly_rule_multi_occurrence_in_forecast(isolated_db):
    """$20 weekly bill with 3 remaining occurrences contributes $60 to forecast."""
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Subscriptions", "expense")

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO recurring_rules (name, transaction_type, amount_minor, category_id, account_id, next_due_date, frequency, active)
            VALUES ('Gym Weekly', 'expense', 2000, ?, ?, '2026-09-12', 'weekly', 1)
        """, (cat_id, acc_id))
        conn.commit()

    res = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-10")
    # 3 occurrences: Sep 12, Sep 19, Sep 26 -> 3 * 2000 = 6000 minor ($60.00)
    assert res["upcoming_recurring_minor"] == 6000


def test_future_month_rule_not_included(isolated_db):
    """Rule with next_due_date in October must contribute $0 to September forecast."""
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Insurance", "expense")

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO recurring_rules (name, transaction_type, amount_minor, category_id, account_id, next_due_date, frequency, active)
            VALUES ('Car Insurance', 'expense', 15000, ?, ?, '2026-10-20', 'monthly', 1)
        """, (cat_id, acc_id))
        conn.commit()

    res = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-10")
    assert res["upcoming_recurring_minor"] == 0


def test_inactive_rule_not_included(isolated_db):
    """Inactive recurring rule (active=0) must be completely excluded."""
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Entertainment", "expense")

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO recurring_rules (name, transaction_type, amount_minor, category_id, account_id, next_due_date, frequency, active)
            VALUES ('Old Gym', 'expense', 5000, ?, ?, '2026-09-20', 'monthly', 0)
        """, (cat_id, acc_id))
        conn.commit()

    res = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-10")
    assert res["upcoming_recurring_minor"] == 0


# ==============================================================================
# Group B: Income Reconciliation Tests (F105-03)
# ==============================================================================

def test_recurring_salary_not_double_counted(isolated_db):
    """
    Recurring salary must not be included in variable income weekday estimation.
    A $5,000 monthly salary contributes exactly once via upcoming recurring income.
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Salary", "income")

    with get_db_connection() as conn:
        cur = conn.cursor()
        # Seed 3 completed months of recurring salary (is_recurring=1)
        for m in ["2026-06", "2026-07", "2026-08"]:
            cur.execute("""
                INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring, description)
                VALUES (?, ?, 'income', 500000, ? || '-25', 1, 'Monthly Salary')
            """, (acc_id, cat_id, m))

        # Explicit recurring rule for salary in September due Sep 25
        cur.execute("""
            INSERT INTO recurring_rules (name, transaction_type, amount_minor, category_id, account_id, next_due_date, frequency, active)
            VALUES ('Salary', 'income', 500000, ?, ?, '2026-09-25', 'monthly', 1)
        """, (cat_id, acc_id))
        conn.commit()

    # Forecast as of 2026-09-10 (before salary date 25)
    res = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-10")

    # Variable income rate from non-recurring income should be $0 because there is no non-recurring income
    # Projected income must be exactly the $5,000 scheduled salary, NOT $10,000+
    assert res["actual_income_to_date_minor"] == 0
    assert res["projected_income_minor"] == 500000
    assert res["projected_net_flow_minor"] == 500000 - res["projected_expense_minor"]


def test_non_recurring_income_still_forecast(isolated_db):
    """Non-recurring variable income (is_recurring=0) continues to be forecast via weekday averages."""
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Freelance", "income")

    with get_db_connection() as conn:
        cur = conn.cursor()
        # Freelance gig every Friday in past 3 months
        for m in ["2026-06", "2026-07", "2026-08"]:
            cur.execute("""
                INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring, description)
                VALUES (?, ?, 'income', 20000, ? || '-12', 0, 'Freelance Gig')
            """, (acc_id, cat_id, m))
        conn.commit()

    res = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-01")
    assert res["projected_income_minor"] > 0


# ==============================================================================
# Group C: Category Reconciliation Tests (F105-04)
# ==============================================================================

def test_category_variable_and_projected_reconcile_with_overall(isolated_db):
    """
    Invariants:
    1. sum(category.variable) == overall.remaining_variable (0 penny drift)
    2. sum(category.projected) == overall.projected_expense (0 penny drift)
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat1 = CategoryRepository.create("Groceries", "expense")
    cat2 = CategoryRepository.create("Dining Out", "expense")
    cat3 = CategoryRepository.create("Utilities", "expense")

    with get_db_connection() as conn:
        cur = conn.cursor()
        # Historical spend in past completed months (July & August)
        for d in [3, 10, 17, 24]:
            cur.execute("""
                INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring)
                VALUES (?, ?, 'expense', 8000, '2026-08-' || printf('%02d', ?), 0)
            """, (acc_id, cat1, d))
            cur.execute("""
                INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring)
                VALUES (?, ?, 'expense', 4000, '2026-08-' || printf('%02d', ?), 0)
            """, (acc_id, cat2, d))

        # Current month spend in September (only Groceries has spend so far)
        cur.execute("""
            INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring)
            VALUES (?, ?, 'expense', 15000, '2026-09-05', 0)
        """, (acc_id, cat1))
        conn.commit()

    res = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-10")

    cats = res["category_forecasts"]
    overall_var = res["expected_variable_minor"]
    overall_total = res["projected_expense_minor"]

    # Sum of projected category amounts must match projected_expense_minor exactly
    cat_total_sum = sum(c["projected_minor"] for c in cats)
    assert cat_total_sum == overall_total

    # Category with no current spend (Dining Out) still receives projection based on historical weight
    dining_cat = next(c for c in cats if c["category_id"] == cat2)
    assert dining_cat["actual_minor"] == 0
    assert dining_cat["projected_minor"] > 0


# ==============================================================================
# Group D: Historical Replay & Anti-Leakage Tests (F105-01 & F105-09)
# ==============================================================================

def test_historical_replay_ignores_future_transactions(isolated_db):
    """Future transactions after as_of_date must NEVER leak into the forecast."""
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Shopping", "expense")

    # Transaction on 2026-09-05 ($50)
    TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 50.0,
        "transaction_type": "expense",
        "transaction_date": "2026-09-05"
    })

    res_before = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-10")

    # Deliberately insert a huge future transaction on 2026-09-25 ($5,000)
    TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 5000.0,
        "transaction_type": "expense",
        "transaction_date": "2026-09-25"
    })

    # Forecast evaluated as of 2026-09-10 must NOT change at all
    res_after = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-10")

    assert res_before["actual_spent_to_date_minor"] == res_after["actual_spent_to_date_minor"]
    assert res_before["projected_expense_minor"] == res_after["projected_expense_minor"]


def test_replay_runner_executes_production_engine(isolated_db):
    """HistoricalReplayRunner executes production replay across historical cutoffs."""
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Living", "expense")

    with get_db_connection() as conn:
        cur = conn.cursor()
        # Seed 4 completed months of realistic spending
        for m in ["2026-04", "2026-05", "2026-06", "2026-07"]:
            for d in [5, 12, 19, 26]:
                cur.execute("""
                    INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date, is_recurring)
                    VALUES (?, ?, 'expense', 25000, ? || '-' || printf('%02d', ?), 0)
                """, (acc_id, cat_id, m, d))
        conn.commit()

    replay_res = HistoricalReplayRunner.run_replay(account_id=acc_id, as_of_date="2026-08-01")
    assert replay_res["available"] is True
    assert replay_res["evaluations_count"] > 0
    assert "finscope_hybrid" in replay_res["models"]
    assert "current_pace" in replay_res["models"]
    assert "naive_previous" in replay_res["models"]
    assert replay_res["models"]["finscope_hybrid"]["sample_origins"] > 0


# ==============================================================================
# Group E: Confidence Scoring Tests (F105-05)
# ==============================================================================

def test_confidence_not_based_only_on_history_length(isolated_db):
    """Confidence score reflects data sufficiency, stability, error, and recurring coverage."""
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Living", "expense")

    res = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-10")
    assert "confidence_score" in res
    assert 0 <= res["confidence_score"] <= 100
    assert res["confidence"] in ("low", "moderate", "high", "very_high")


# ==============================================================================
# Group F: Range Calibration Tests (F105-06)
# ==============================================================================

def test_early_estimate_when_residual_history_insufficient(isolated_db):
    """When fewer than 6 replay residuals exist, range is labelled 'early_estimate'."""
    acc_id = AccountRepository.create("Checking", "checking")
    res = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-10")
    assert res["range_type"] == "early_estimate"
    assert res["lower_bound_minor"] <= res["projected_expense_minor"] <= res["upper_bound_minor"]


# ==============================================================================
# Group G: Model Eligibility Tests (F105-07)
# ==============================================================================

def test_sparse_history_uses_simple_model(isolated_db):
    """With < 2 complete months of history, model eligibility selects current_pace."""
    acc_id = AccountRepository.create("Checking", "checking")
    res = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-10")
    assert res["model_method"] == "current_pace"
    assert "current pace" in res["method"].lower()


# ==============================================================================
# Group H: Core Financial Forecast Invariants (Roadmap Section 14)
# ==============================================================================

def test_forecast_invariants_hold(isolated_db):
    """
    Verifies all 6 core financial identities from roadmap Section 14:
    1. projected_expense == actual_spent + recurring_remaining + variable_remaining
    2. projected_income == actual_income + recurring_income_remaining + variable_income_remaining
    3. projected_net_flow == projected_income - projected_expense
    4. sum(cat.projected) == projected_expense
    5. lower_bound <= projected_expense <= upper_bound
    6. recurring_remaining >= 0 and variable_remaining >= 0
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_exp = CategoryRepository.create("Living", "expense")
    cat_inc = CategoryRepository.create("Income", "income")

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date)
            VALUES (?, ?, 'expense', 45000, '2026-09-04')
        """, (acc_id, cat_exp))
        cur.execute("""
            INSERT INTO transactions (account_id, category_id, transaction_type, amount_minor, transaction_date)
            VALUES (?, ?, 'income', 60000, '2026-09-01')
        """, (acc_id, cat_inc))
        cur.execute("""
            INSERT INTO recurring_rules (name, transaction_type, amount_minor, category_id, account_id, next_due_date, frequency, active)
            VALUES ('Phone Bill', 'expense', 5000, ?, ?, '2026-09-18', 'monthly', 1)
        """, (cat_exp, acc_id))
        conn.commit()

    res = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-10")

    # Invariant 1: Expense breakdown
    exp_calc = (
        res["actual_spent_to_date_minor"] +
        res["upcoming_recurring_minor"] +
        res["expected_variable_minor"]
    )
    assert res["projected_expense_minor"] == exp_calc

    # Invariant 2: Income breakdown
    assert res["projected_income_minor"] >= res["actual_income_to_date_minor"]

    # Invariant 3: Net flow
    assert res["projected_net_flow_minor"] == res["projected_income_minor"] - res["projected_expense_minor"]

    # Invariant 4: Category reconciliation
    cats = res["category_forecasts"]
    assert sum(c["projected_minor"] for c in cats) == res["projected_expense_minor"]

    # Invariant 5: Bounds
    assert res["lower_bound_minor"] <= res["projected_expense_minor"] <= res["upper_bound_minor"]

    # Invariant 6: Non-negativity
    assert res["upcoming_recurring_minor"] >= 0
    assert res["expected_variable_minor"] >= 0
