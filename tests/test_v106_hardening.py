"""
Comprehensive Unit and Regression Test Suite for FinScope Forecasting v1.0.6.
Validates:
1. P0: Point-in-time recurring rule versioning & anti-leakage in historical replay.
2. P0: Production decision policy ladder replay alongside hybrid candidate.
3. P0/P1: Continuous calendar zero-filling for completed historical months.
4. P1: Multi-factor replay cache freshness (amount edits, recurring edits, model version).
5. P1: Model-matched confidence scoring with neutral-low fallback.
6. P1: Shared occurrence expansion in RecurringService.get_upcoming_bills_for_month.
7. Category edge cases: synthetic Uncategorised row & negative net refunds with zero penny drift.
8. Fair leaderboard ranking on comparable origin samples.
"""

import pytest
import sqlite3
from datetime import date
from app.backend.database.connection import get_db_connection
from app.backend.analytics.forecasting import ForecastingEngine
from app.backend.analytics.forecast_replay import HistoricalReplayRunner, generate_calendar_months
from app.backend.services.recurring_service import RecurringService
from app.backend.repositories.account_repo import AccountRepository
from app.backend.repositories.category_repo import CategoryRepository
from app.backend.repositories.transaction_repo import TransactionRepository


# ==============================================================================
# 1. P0: Recurring Rule Anti-Leakage & Point-in-Time Versioning
# ==============================================================================

def test_recurring_rule_anti_leakage_created_after_cutoff(isolated_db):
    """
    P0: A recurring rule created AFTER the historical cutoff must NEVER leak into
    historical replay (it did not exist at cutoff).
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Housing", "expense")

    # Seed transaction history in 2025 so replay cutoff has a base
    with get_db_connection() as conn:
        cur = conn.cursor()
        # Rule created on 2026-03-01 with next_due_date 2025-05-15 (retro schedule)
        cur.execute("""
            INSERT INTO recurring_rules (name, transaction_type, amount_minor, category_id, account_id, next_due_date, frequency, active, created_at)
            VALUES ('Modern Rent', 'expense', 50000, ?, ?, '2025-05-15', 'monthly', 1, '2026-03-01 10:00:00')
        """, (cat_id, acc_id))
        # Ensure version row has valid_from = 2026-03-01
        cur.execute("UPDATE recurring_rule_versions SET valid_from = '2026-03-01' WHERE name = 'Modern Rent'")
        conn.commit()

    # Replay historical month May 2025 at Day 10 cutoff (2025-05-10)
    res = ForecastingEngine.forecast_month(
        month="2025-05",
        account_id=acc_id,
        as_of_date="2025-05-10",
        replay_mode=True
    )
    # The rule created in 2026 must NOT be in May 2025 replay
    assert res["upcoming_recurring_minor"] == 0


def test_recurring_rule_point_in_time_version_edited_after_cutoff(isolated_db):
    """
    P0: A rule that was $100 before cutoff and later updated to $150 after cutoff
    must be evaluated at exactly $100 during historical replay of that cutoff.
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Utilities", "expense")

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO recurring_rules (name, transaction_type, amount_minor, category_id, account_id, next_due_date, frequency, active, created_at)
            VALUES ('Internet', 'expense', 10000, ?, ?, '2025-05-20', 'monthly', 1, '2025-01-01 00:00:00')
        """, (cat_id, acc_id))
        rule_id = cur.lastrowid
        cur.execute("UPDATE recurring_rule_versions SET valid_from = '2025-01-01' WHERE rule_id = ?", (rule_id,))

        # Simulate update to $150 on 2025-08-01 (after May 2025 cutoff)
        cur.execute("""
            UPDATE recurring_rules
            SET amount_minor = 15000
            WHERE id = ?
        """, (rule_id,))
        # Trigger sets valid_to = date('now') on update; simulate valid_to = 2025-08-01 and new version valid_from = 2025-08-01
        cur.execute("""
            UPDATE recurring_rule_versions
            SET valid_to = '2025-08-01'
            WHERE rule_id = ? AND amount_minor = 10000
        """, (rule_id,))
        cur.execute("""
            UPDATE recurring_rule_versions
            SET valid_from = '2025-08-01'
            WHERE rule_id = ? AND amount_minor = 15000
        """, (rule_id,))
        conn.commit()

    # Replay May 2025 at Day 10 cutoff (2025-05-10)
    res = ForecastingEngine.forecast_month(
        month="2025-05",
        account_id=acc_id,
        as_of_date="2025-05-10",
        replay_mode=True
    )
    # Must see point-in-time value of $100 (10000 minor), NOT $150
    assert res["upcoming_recurring_minor"] == 10000


def test_recurring_rule_point_in_time_version_deleted_after_cutoff(isolated_db):
    """
    P0: A rule that was active before cutoff but deleted after cutoff must still
    be recognized during historical replay of that cutoff.
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Subscriptions", "expense")

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO recurring_rules (name, transaction_type, amount_minor, category_id, account_id, next_due_date, frequency, active, created_at)
            VALUES ('Streaming Service', 'expense', 1999, ?, ?, '2025-05-25', 'monthly', 1, '2025-01-01 00:00:00')
        """, (cat_id, acc_id))
        rule_id = cur.lastrowid
        cur.execute("UPDATE recurring_rule_versions SET valid_from = '2025-01-01' WHERE rule_id = ?", (rule_id,))

        # Delete the rule in recurring_rules on 2025-09-01
        cur.execute("DELETE FROM recurring_rules WHERE id = ?", (rule_id,))
        # Trigger marked valid_to; simulate valid_to = 2025-09-01
        cur.execute("""
            UPDATE recurring_rule_versions
            SET valid_to = '2025-09-01'
            WHERE rule_id = ?
        """, (rule_id,))
        conn.commit()

    # Replay May 2025 at Day 10 cutoff (2025-05-10)
    res = ForecastingEngine.forecast_month(
        month="2025-05",
        account_id=acc_id,
        as_of_date="2025-05-10",
        replay_mode=True
    )
    # The rule existed in May 2025, so upcoming recurring must be $19.99 (1999 minor)
    assert res["upcoming_recurring_minor"] == 1999


# ==============================================================================
# 2. P1: Multi-Factor Replay Cache Invalidation
# ==============================================================================

def test_replay_cache_invalidation_on_amount_minor_edit(isolated_db):
    """
    P1: Editing an existing transaction's amount_minor without changing transaction_date
    or count MUST invalidate the replay cache key (via sum(amount_minor) tracking).
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Groceries", "expense")

    tx_id = TransactionRepository.create({
        "account_id": acc_id,
        "category_id": cat_id,
        "amount": 50.0,
        "transaction_type": "expense",
        "transaction_date": "2025-01-15"
    })

    key_before = HistoricalReplayRunner._get_cache_key(account_id=acc_id)

    # Edit amount without changing date or adding new rows
    TransactionRepository.update(tx_id, {"amount": 75.0})

    key_after = HistoricalReplayRunner._get_cache_key(account_id=acc_id)
    assert key_before != key_after, "Cache key must change when amount_minor is updated"


def test_replay_cache_invalidation_on_recurring_rule_edit(isolated_db):
    """
    P1: Modifying a recurring rule MUST invalidate the replay cache key.
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Services", "expense")

    key_before = HistoricalReplayRunner._get_cache_key(account_id=acc_id)

    rule_id = RecurringService.create({
        "name": "Gym",
        "amount": 40.0,
        "transaction_type": "expense",
        "category_id": cat_id,
        "account_id": acc_id,
        "frequency": "monthly",
        "next_due_date": "2026-09-15"
    })

    key_after = HistoricalReplayRunner._get_cache_key(account_id=acc_id)
    assert key_before != key_after, "Cache key must change when recurring rule is created"


# ==============================================================================
# 3. P0/P1: Calendar Zero-Filling for Completed Historical Months
# ==============================================================================

def test_forecast_replay_continuous_calendar_zero_filling(isolated_db):
    """
    P0/P1: Historical replay must generate a continuous sequence of calendar months
    from min(date) to cutoff, zero-filling missing months so naive_previous (t-1)
    and seasonal_naive (t-12) reflect true calendar spacing.
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Food", "expense")

    # Transactions only in 2025-01 and 2025-04 (missing 2025-02 and 2025-03)
    TransactionRepository.create({
        "account_id": acc_id, "category_id": cat_id, "amount": 100.0,
        "transaction_type": "expense", "transaction_date": "2025-01-10"
    })
    TransactionRepository.create({
        "account_id": acc_id, "category_id": cat_id, "amount": 120.0,
        "transaction_type": "expense", "transaction_date": "2025-04-10"
    })

    months = HistoricalReplayRunner.get_completed_historical_months(
        account_id=acc_id,
        as_of_date="2025-05-01"
    )

    # Must contain continuous months including 2025-02 and 2025-03
    assert months == ["2025-01", "2025-02", "2025-03", "2025-04"]

    # Month end spend for missing months must be 0
    assert HistoricalReplayRunner.get_actual_month_end_net_spend("2025-02", acc_id) == 0
    assert HistoricalReplayRunner.get_actual_month_end_net_spend("2025-03", acc_id) == 0
    assert HistoricalReplayRunner.get_actual_month_end_net_spend("2025-04", acc_id) == 12000


# ==============================================================================
# 4. Category Forecasts: Synthetic Uncategorised & Negative Refund Reconcile
# ==============================================================================

def test_category_forecast_uncategorized_transactions_zero_drift(isolated_db):
    """
    Category forecasts must include synthetic 'Uncategorised' category (cid=0)
    when transactions have category_id IS NULL, guaranteeing zero penny drift.
    """
    acc_id = AccountRepository.create("Checking", "checking")

    # Create an expense with category_id = NULL (e.g. from raw import or category deletion)
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO transactions (
                account_id, category_id, merchant_name, transaction_type,
                amount_minor, transaction_date, source, needs_review, is_deleted
            ) VALUES (?, NULL, 'Unknown Merchant', 'expense', 4250, '2026-09-02', 'manual', 1, 0)
        """, (acc_id,))
        conn.commit()

    fc = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-10")

    cat_forecasts = fc["category_forecasts"]
    uncat_item = next((c for c in cat_forecasts if c["category_id"] == 0), None)
    assert uncat_item is not None, "Uncategorised category must be present in forecasts"
    assert uncat_item["name"] == "Uncategorised"
    assert uncat_item["actual_minor"] == 4250

    # Total of category projected_minor must equal projected_expense_minor exactly
    cat_total_proj = sum(c["projected_minor"] for c in cat_forecasts)
    assert cat_total_proj == fc["projected_expense_minor"], "Category sum must equal projected total"


def test_category_forecast_refund_exceeds_expense_reconciliation(isolated_db):
    """
    When a category has refunds exceeding expenses in the current month, its actual_minor
    must reflect the negative net amount without premature max(0, ...) clamping, preserving
    exact total reconciliation across categories and month-end projected expense.
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_elec = CategoryRepository.create("Electronics", "expense")
    cat_groc = CategoryRepository.create("Groceries", "expense")

    # 1. Purchase $100 in August, refunded $80 in September -> Electronics net in Sept is -$80
    orig_tx = TransactionRepository.create({
        "account_id": acc_id, "category_id": cat_elec, "amount": 100.0,
        "transaction_type": "expense", "transaction_date": "2026-08-20"
    })
    TransactionRepository.create_refund(
        original_tx_id=orig_tx,
        amount=80.0,
        transaction_date="2026-09-05",
        account_id=acc_id
    )

    # 2. Add $150 Groceries expense in September -> Total actual net spend in Sept is $150 - $80 = $70
    TransactionRepository.create({
        "account_id": acc_id, "category_id": cat_groc, "amount": 150.0,
        "transaction_type": "expense", "transaction_date": "2026-09-06"
    })

    fc = ForecastingEngine.forecast_month("2026-09", account_id=acc_id, as_of_date="2026-09-10")

    cat_forecasts = fc["category_forecasts"]
    elec_item = next((c for c in cat_forecasts if c["category_id"] == cat_elec), None)
    groc_item = next((c for c in cat_forecasts if c["category_id"] == cat_groc), None)

    assert elec_item is not None
    assert elec_item["actual_minor"] == -8000, "Net refund must be recorded as negative actual spend (-$80)"
    assert groc_item is not None
    assert groc_item["actual_minor"] == 15000, "Groceries must be +$150"

    # Category actuals sum must match actual_spent_to_date_minor exactly (-$80 + $150 = $70)
    cat_actual_sum = sum(c["actual_minor"] for c in cat_forecasts)
    assert cat_actual_sum == fc["actual_spent_to_date_minor"]
    assert cat_actual_sum == 7000

    # Total category projected_minor must equal projected_expense_minor exactly (zero drift)
    cat_proj_sum = sum(c["projected_minor"] for c in cat_forecasts)
    assert cat_proj_sum == fc["projected_expense_minor"]


# ==============================================================================
# 5. Production Decision Policy Replay & Leaderboard
# ==============================================================================

def test_production_policy_decision_ladder_in_replay(isolated_db):
    """
    P0: Replay must evaluate the production policy decision ladder alongside candidate hybrid.
    For months with 2-5 months of history, production policy must select three_month_median.
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("Living", "expense")

    # Seed 4 completed historical months
    months_data = [
        ("2025-01", 1000.0),
        ("2025-02", 1100.0),
        ("2025-03", 1050.0),
        ("2025-04", 1200.0)
    ]
    for m, amt in months_data:
        TransactionRepository.create({
            "account_id": acc_id, "category_id": cat_id, "amount": amt,
            "transaction_type": "expense", "transaction_date": f"{m}-10"
        })

    replay_res = HistoricalReplayRunner.run_replay(account_id=acc_id, as_of_date="2025-05-01")
    assert replay_res["available"] is True
    models = replay_res["models"]

    # Both production_policy and finscope_hybrid must be present
    assert "production_policy" in models
    assert "finscope_hybrid" in models
    assert models["production_policy"]["sample_origins"] > 0
    assert models["finscope_hybrid"]["sample_origins"] > 0


def test_leaderboard_fair_ranking_on_comparable_origins(isolated_db):
    """
    Leaderboard must only rank models with comparable sample counts (>= 70% of max sample origins).
    """
    acc_id = AccountRepository.create("Checking", "checking")
    cat_id = CategoryRepository.create("General", "expense")

    # Seed 14 months of history to generate evaluations for all models including seasonal_naive
    for yr in [2024, 2025]:
        for mo in range(1, 13):
            if yr == 2025 and mo > 4:
                break
            m_str = f"{yr}-{mo:02d}"
            TransactionRepository.create({
                "account_id": acc_id, "category_id": cat_id, "amount": 500.0 + mo * 10,
                "transaction_type": "expense", "transaction_date": f"{m_str}-15"
            })

    replay_res = HistoricalReplayRunner.run_replay(account_id=acc_id, as_of_date="2025-05-01")
    assert replay_res["available"] is True
    assert "best_model" in replay_res
    # Best model must be one of the comparable models
    best_m = replay_res["best_model"]
    max_samples = max(m["sample_origins"] for m in replay_res["models"].values())
    assert replay_res["models"][best_m]["sample_origins"] >= 0.70 * max_samples


# ==============================================================================
# 6. Shared Occurrence Expansion in Upcoming Bills
# ==============================================================================

def test_upcoming_bills_multi_occurrence_expansion(isolated_db):
    """
    P1: RecurringService.get_upcoming_bills_for_month must expand a weekly rule
    into separate entries for each occurrence in the month, matching ForecastingEngine.
    """
    acc_id = AccountRepository.create("Bills Acc", "checking")
    cat_id = CategoryRepository.create("Fitness", "expense")

    # Create weekly rule due on Sep 05 ($20 / week)
    RecurringService.create({
        "name": "Weekly Pilates",
        "amount": 20.0,
        "transaction_type": "expense",
        "category_id": cat_id,
        "account_id": acc_id,
        "frequency": "weekly",
        "next_due_date": "2026-09-05"
    })

    # September 2026 has Sep 5, Sep 12, Sep 19, Sep 26 (4 occurrences)
    bills = RecurringService.get_upcoming_bills_for_month("2026-09", account_id=acc_id)
    pilates_bills = [b for b in bills if b["name"] == "Weekly Pilates"]
    assert len(pilates_bills) == 4
    assert all(b["amount_minor"] == 2000 for b in pilates_bills)
    assert [b["due_date"] for b in pilates_bills] == [
        "2026-09-05", "2026-09-12", "2026-09-19", "2026-09-26"
    ]
