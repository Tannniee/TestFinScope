"""
Explainable Forecasting Engine V2 for FinScope (v1.0.5).
Projects month-end spending, income, and budget risk through a transparent component model:
Projected Expense = Actual Spend To Date
                  + Known Upcoming Recurring Bills (frequency-expanded)
                  + Remaining Variable Spend (robust weekday-adjusted)
                  - Expected Refunds
Includes calibrated confidence bounds based on historical replay residuals,
exact category reconciliation with zero drift, and data-sufficiency method selection.
"""

import calendar
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
from app.backend.database.connection import get_db_connection
from app.backend.analytics.semantics import calculate_net_spending
from app.backend.analytics.models import ForecastResult
from app.backend.analytics.context import AnalyticsContext, resolve_analytics_context
from app.backend.analytics.reconciliation import reconcile_forecast_components
from app.backend.analytics.rolling import calculate_median, calculate_mean
from app.backend.services.merchant_service import normalize_merchant_name
from app.backend.analytics.recurring_schedule import generate_occurrences
from app.backend.analytics.forecast_strategies import (
    ForecastContext,
    ModelSelector,
    default_registry,
    ForecastEstimate,
)


def recurring_key(account_id_or_name: Any, name: Optional[str] = None) -> tuple:
    """Canonicalize recurring bill identities scoped by account (V103-04)."""
    if name is None and isinstance(account_id_or_name, str):
        acc_id = None
        raw_name = account_id_or_name
    else:
        acc_id = account_id_or_name
        raw_name = name
    return (
        acc_id,
        normalize_merchant_name(raw_name or "").strip().casefold()
    )


def count_weekdays_in_historical_window(start_d: date, end_d: date) -> Dict[int, int]:
    """Counts actual occurrences of Monday(1)..Sunday(0 in sqlite %w) between dates."""
    counts = {i: 0 for i in range(7)}
    cur = start_d
    while cur <= end_d:
        # SQLite %w: 0=Sun, 1=Mon, ..., 6=Sat
        w = (cur.weekday() + 1) % 7
        counts[w] += 1
        cur += timedelta(days=1)
    return counts


class ForecastingEngine:
    @staticmethod
    def forecast_month(
        month: str,
        account_id: Optional[int] = None,
        as_of_date: Optional[str] = None,
        context: Optional[AnalyticsContext] = None,
        replay_mode: bool = False,
        forced_method: Optional[str] = None,
        replay_evidence: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generates explainable month-end forecast for `month` (YYYY-MM).
        Uses dynamic historical weekday counts, frequency-expanded recurring rules,
        reconciled category allocations, and calibrated ranges.
        """
        if context is None:
            context = resolve_analytics_context(month=month, account_id=account_id)

        year, m_int = map(int, context.as_of_month.split("-"))
        num_days = calendar.monthrange(year, m_int)[1]

        # Determine elapsed days and reference cutoff date
        if as_of_date:
            cur_dt = datetime.strptime(as_of_date[:10], "%Y-%m-%d").date()
            if cur_dt.year == year and cur_dt.month == m_int:
                elapsed_day = min(num_days, max(1, cur_dt.day))
            elif cur_dt < date(year, m_int, 1):
                elapsed_day = 0
            else:
                elapsed_day = num_days
            as_of_cutoff = as_of_date[:10]
        elif context.is_current_month:
            cur_dt = context.end_date
            elapsed_day = min(num_days, max(1, cur_dt.day))
            as_of_cutoff = f"{context.as_of_month}-{elapsed_day:02d}"
        else:
            elapsed_day = min(15, num_days)
            cur_dt = date(year, m_int, elapsed_day)
            as_of_cutoff = f"{context.as_of_month}-{elapsed_day:02d}"

        remaining_days = max(0, num_days - elapsed_day)
        remaining_calendar_dates = tuple(f"{context.as_of_month}-{d:02d}" for d in range(elapsed_day + 1, num_days + 1))

        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND t.account_id = ?" if context.account_id else ""
            acc_params: List[Any] = [context.account_id] if context.account_id else []

            # 1. Actual Spend & Income To Date
            actual_rows = []
            if elapsed_day > 0:
                cur.execute(f"""
                    SELECT 
                        t.transaction_type,
                        t.is_recurring,
                        t.category_id,
                        c.name as category_name,
                        c.color as category_color,
                        COALESCE(SUM(t.amount_minor), 0) as total_minor,
                        COUNT(t.id) as count
                    FROM active_transactions t
                    LEFT JOIN categories c ON t.category_id = c.id
                    WHERE t.transaction_date >= ? AND t.transaction_date <= ? {acc_clause}
                    GROUP BY t.transaction_type, t.is_recurring, t.category_id
                """, [f"{context.as_of_month}-01", f"{context.as_of_month}-{elapsed_day:02d}"] + acc_params)
                actual_rows = cur.fetchall()

            actual_expense_minor = 0
            actual_non_recurring_expense_minor = 0
            actual_recurring_minor = 0
            actual_income_to_date_minor = 0
            actual_refund_minor = 0
            actual_cat_spends_net: Dict[int, int] = {}
            actual_cat_non_recurring_expense: Dict[int, int] = {}
            cat_metadata: Dict[int, Dict[str, Any]] = {}

            for r in actual_rows:
                tt = r["transaction_type"]
                amt = r["total_minor"]
                cid = r["category_id"] or 0
                if cid and cid not in cat_metadata:
                    cat_metadata[cid] = {
                        "name": r["category_name"] or "Other",
                        "color": r["category_color"] or "#8E8E93"
                    }

                if tt == "expense":
                    actual_expense_minor += amt
                    actual_cat_spends_net[cid] = actual_cat_spends_net.get(cid, 0) + amt
                    if r["is_recurring"]:
                        actual_recurring_minor += amt
                    else:
                        actual_non_recurring_expense_minor += amt
                        actual_cat_non_recurring_expense[cid] = actual_cat_non_recurring_expense.get(cid, 0) + amt
                elif tt == "income":
                    actual_income_to_date_minor += amt
                elif tt == "refund":
                    actual_refund_minor += amt
                    actual_cat_spends_net[cid] = actual_cat_spends_net.get(cid, 0) - amt

            actual_net_spend_to_date = calculate_net_spending(actual_expense_minor, actual_refund_minor)

            # 2. Known Upcoming Recurring Expenses & Income (F105-02 & F105-03)
            window_start = cur_dt if (cur_dt.year == year and cur_dt.month == m_int) else (
                date(year, m_int, 1) - timedelta(days=1) if cur_dt < date(year, m_int, 1) else date(year, m_int, elapsed_day)
            )
            window_end = date(year, m_int, num_days)

            upcoming_recurring_minor = 0
            upcoming_recurring_income_minor = 0
            upcoming_by_cat: Dict[int, int] = {}
            seen_rules = set()
            seen_bills = set()
            suppressed_inactive_rule_fallback_count = 0

            # 2a. Explicit rules from recurring_rules / recurring_rule_versions (point-in-time anti-leakage)
            rec_acc_clause = " AND account_id = ?" if context.account_id else ""
            if replay_mode and as_of_date:
                rec_params = [as_of_cutoff, as_of_cutoff] + ([context.account_id] if context.account_id else [])
                cur.execute(f"""
                    SELECT rule_id as id, account_id, name, transaction_type, amount_minor, category_id, next_due_date, frequency
                    FROM recurring_rule_versions
                    WHERE active = 1
                      AND date(valid_from) <= ?
                      AND (valid_to IS NULL OR date(valid_to) > ?)
                      {rec_acc_clause}
                    ORDER BY rule_id ASC
                """, rec_params)
            else:
                rec_params = [context.account_id] if context.account_id else []
                cur.execute(f"""
                    SELECT id, account_id, name, transaction_type, amount_minor, category_id, next_due_date, frequency
                    FROM recurring_rules
                    WHERE active = 1 {rec_acc_clause}
                    ORDER BY id ASC
                """, rec_params)

            for r in cur.fetchall():
                rule_id = r["id"]
                rule_acc_id = r["account_id"]
                rule_name = r["name"]
                key = recurring_key(rule_acc_id, rule_name)
                seen_rules.add(rule_id)
                seen_bills.add(key)

                # Active rules without next_due_date are unscheduled (F108-20) -> no occurrences generated
                if not r["next_due_date"]:
                    continue

                occs = generate_occurrences(
                    next_due_date=r["next_due_date"],
                    frequency=r["frequency"],
                    start_date=window_start,
                    end_date=window_end
                )
                occ_count = len(occs)
                if occ_count > 0:
                    if r["transaction_type"] == "expense":
                        amt = r["amount_minor"] * occ_count
                        upcoming_recurring_minor += amt
                        cid = r["category_id"] or 0
                        upcoming_by_cat[cid] = upcoming_by_cat.get(cid, 0) + amt
                    elif r["transaction_type"] == "income":
                        upcoming_recurring_income_minor += r["amount_minor"] * occ_count

            # 2b. Historical recurring transactions fallback (AUD-006B & F108-13)
            cur.execute(f"""
                SELECT 
                    t.account_id,
                    t.recurring_rule_id,
                    COALESCE(NULLIF(merchant_name, ''), description) as bill_name,
                    t.category_id,
                    CAST(strftime('%d', transaction_date) AS INTEGER) as usual_day,
                    amount_minor
                FROM active_transactions t
                WHERE t.transaction_type = 'expense'
                  AND is_recurring = 1
                  AND transaction_date < ? || '-01'
                  AND transaction_date >= date(? || '-01', '-3 months')
                  AND transaction_date <= ? {acc_clause}
                ORDER BY t.transaction_date DESC, t.id DESC
            """, [context.as_of_month, context.as_of_month, as_of_cutoff] + acc_params)

            historical_recurring = cur.fetchall()
            for r in historical_recurring:
                rule_id = r["recurring_rule_id"]
                # F108-13: If historical transaction had an explicit rule_id, it is governed by explicit rule state.
                # If that rule is active, it was already handled in 2a (in seen_rules).
                # If that rule is inactive or deleted, do NOT resurrect it!
                if rule_id is not None:
                    if rule_id in seen_rules:
                        continue
                    else:
                        suppressed_inactive_rule_fallback_count += 1
                        continue

                raw_b_name = r["bill_name"]
                acc_id = r["account_id"]
                key = recurring_key(acc_id, raw_b_name)
                if key in seen_bills:
                    continue

                seen_bills.add(key)

                day_num = r["usual_day"]
                if day_num > elapsed_day and day_num <= num_days:
                    amt = r["amount_minor"]
                    upcoming_recurring_minor += amt
                    cid = r["category_id"] or 0
                    upcoming_by_cat[cid] = upcoming_by_cat.get(cid, 0) + amt

            # 3. Dynamic Historical Weekday Rates & Dense Series (past 3 completed months strictly before target month)
            hist_start_str = f"{year - 1 if m_int <= 3 else year}-{(m_int - 4) % 12 + 1:02d}-01"
            h_sy, h_sm = map(int, hist_start_str.split("-")[:2])
            h_start_date = date(h_sy, h_sm, 1)
            h_end_date = date(year, m_int, 1) - timedelta(days=1)
            if cur_dt < h_end_date:
                h_end_date = cur_dt

            actual_wday_counts = count_weekdays_in_historical_window(h_start_date, h_end_date)

            # Query non-recurring expenses in the weekday window
            cur.execute(f"""
                SELECT 
                    transaction_date,
                    strftime('%w', transaction_date) as wday,
                    SUM(amount_minor) as day_total_minor
                FROM active_transactions t
                WHERE t.transaction_type = 'expense'
                  AND is_recurring = 0
                  AND transaction_date >= ? AND transaction_date <= ? {acc_clause}
                GROUP BY transaction_date, wday
            """, [h_start_date.isoformat(), h_end_date.isoformat()] + acc_params)

            wday_daily_spends: Dict[int, List[int]] = {w: [] for w in range(7)}
            for r in cur.fetchall():
                w = int(r["wday"])
                amt = r["day_total_minor"]
                wday_daily_spends[w].append(amt)

            weekday_avg_minor: Dict[int, int] = {}
            for w in range(7):
                spends = wday_daily_spends[w]
                occ = max(1, actual_wday_counts.get(w, 1))
                if not spends:
                    weekday_avg_minor[w] = 0
                elif occ >= 4 and len(spends) >= 2:
                    med = calculate_median(spends)
                    devs = [abs(x - med) for x in spends]
                    mad = calculate_median(devs)
                    cap = med + max(1000, round(3.0 * mad))
                    capped_spends = [min(x, cap) for x in spends]
                    capped_mean = round(sum(capped_spends) / float(occ))
                    weekday_avg_minor[w] = round(0.60 * (med * len(spends) / float(occ)) + 0.40 * capped_mean)
                else:
                    tot = sum(spends)
                    weekday_avg_minor[w] = round(tot / float(occ)) if tot > 0 else 0

            tot_window_spend = sum(sum(s) for s in wday_daily_spends.values())
            tot_window_days = max(1, sum(actual_wday_counts.values()))
            global_non_recurring_daily_rate = round(tot_window_spend / float(tot_window_days)) if tot_window_spend > 0 else 0
            weekday_sample_counts = {w: len(wday_daily_spends[w]) for w in range(7)}

            # Income rates
            cur.execute(f"""
                SELECT 
                    strftime('%w', transaction_date) as wday,
                    SUM(amount_minor) as total_minor
                FROM active_transactions t
                WHERE t.transaction_type = 'income'
                  AND is_recurring = 0
                  AND transaction_date >= ? AND transaction_date <= ? {acc_clause}
                GROUP BY wday
            """, [h_start_date.isoformat(), h_end_date.isoformat()] + acc_params)
            weekday_income_totals = {int(r["wday"]): r["total_minor"] for r in cur.fetchall()}
            weekday_income_avg: Dict[int, int] = {}
            for w in range(7):
                tot = weekday_income_totals.get(w, 0)
                occ = max(1, actual_wday_counts.get(w, 1))
                weekday_income_avg[w] = round(tot / float(occ)) if tot > 0 else 0

            # 4. Dense Historical Daily & Monthly Non-Recurring Series (F108-02, F108-05, F108-06)
            from app.backend.analytics.forecast_strategies.series import (
                build_dense_daily_series,
                build_dense_monthly_series,
                generate_calendar_months,
                same_month_previous_year
            )
            from app.backend.analytics.forecast_strategies.config import FORECAST_CONFIG

            cur.execute(f"""
                SELECT MIN(transaction_date) as min_d, COUNT(t.id) as tx_count
                FROM active_transactions t 
                WHERE t.transaction_type = 'expense'
                  AND is_recurring = 0
                  AND transaction_date < ? || '-01'
                  AND transaction_date <= ? {acc_clause}
            """, [context.as_of_month, as_of_cutoff] + acc_params)
            m_row = cur.fetchone()
            min_d = m_row["min_d"] if m_row else None
            tx_count = m_row["tx_count"] if m_row else 0

            hist_monthly_non_recurring_expense: Dict[str, int] = {}
            dense_daily_non_recurring_expense: Dict[str, int] = {}
            completed_months = 0

            if min_d:
                prev_m_date = date(year, m_int, 1) - timedelta(days=1)
                end_m = f"{prev_m_date.year:04d}-{prev_m_date.month:02d}"
                start_m = min_d[:7]

                if start_m <= end_m:
                    cur.execute(f"""
                        SELECT 
                            strftime('%Y-%m', t.transaction_date) as m,
                            SUM(t.amount_minor) as total_minor
                        FROM active_transactions t
                        WHERE t.transaction_type = 'expense'
                          AND is_recurring = 0
                          AND transaction_date < ? || '-01'
                          AND transaction_date <= ? {acc_clause}
                        GROUP BY m
                    """, [context.as_of_month, as_of_cutoff] + acc_params)
                    sparse_monthly = {r["m"]: r["total_minor"] for r in cur.fetchall()}
                    hist_monthly_non_recurring_expense = build_dense_monthly_series(start_m, end_m, sparse_monthly)
                    completed_months = len(hist_monthly_non_recurring_expense)

                # Daily non-recurring series for robust weekly analysis (up to past 12 months)
                twelve_m_ago = date(year, m_int, 1) - timedelta(days=365)
                start_daily = max(datetime.strptime(min_d, "%Y-%m-%d").date(), twelve_m_ago)
                end_daily = min(prev_m_date, cur_dt)

                if start_daily <= end_daily:
                    cur.execute(f"""
                        SELECT 
                            transaction_date,
                            SUM(amount_minor) as total_minor
                        FROM active_transactions t
                        WHERE t.transaction_type = 'expense'
                          AND is_recurring = 0
                          AND transaction_date >= ? AND transaction_date <= ? {acc_clause}
                        GROUP BY transaction_date
                    """, [start_daily.isoformat(), end_daily.isoformat()] + acc_params)
                    daily_map = {r["transaction_date"]: r["total_minor"] for r in cur.fetchall()}
                    dense_daily_non_recurring_expense = build_dense_daily_series(start_daily, end_daily, daily_map)

            # Category historical non-recurring rates
            cur.execute(f"""
                SELECT 
                    category_id,
                    SUM(amount_minor) as total_minor
                FROM active_transactions t
                WHERE t.transaction_type = 'expense'
                  AND is_recurring = 0
                  AND transaction_date >= ? AND transaction_date <= ? {acc_clause}
                GROUP BY category_id
            """, [h_start_date.isoformat(), h_end_date.isoformat()] + acc_params)
            cat_hist_totals = {row["category_id"]: row["total_minor"] for row in cur.fetchall()}

            # Build consolidated ForecastContext (v1.0.8 canonical)
            f_ctx = ForecastContext(
                target_month=context.as_of_month,
                as_of_date=as_of_cutoff,
                account_id=context.account_id,
                elapsed_day=elapsed_day,
                remaining_days=remaining_days,
                num_days=num_days,
                remaining_calendar_dates=remaining_calendar_dates,
                actual_expense_minor=actual_expense_minor,
                actual_income_minor=actual_income_to_date_minor,
                actual_refund_minor=actual_refund_minor,
                actual_net_spend_to_date_minor=actual_net_spend_to_date,
                actual_non_recurring_expense_minor=actual_non_recurring_expense_minor,
                actual_recurring_expense_minor=actual_recurring_minor,
                upcoming_recurring_expense_minor=upcoming_recurring_minor,
                upcoming_recurring_income_minor=upcoming_recurring_income_minor,
                hist_monthly_non_recurring_expense=hist_monthly_non_recurring_expense,
                dense_daily_non_recurring_expense=dense_daily_non_recurring_expense,
                weekday_rates=weekday_avg_minor,
                weekday_sample_counts=weekday_sample_counts,
                global_non_recurring_daily_rate=global_non_recurring_daily_rate,
                actual_cat_spends_net=actual_cat_spends_net,
                actual_cat_non_recurring_expense=actual_cat_non_recurring_expense,
                historical_cat_non_recurring_expense=cat_hist_totals,
                cat_metadata=cat_metadata,
                upcoming_recurring_by_cat=upcoming_by_cat,
                completed_months=completed_months,
                transaction_count=tx_count
            )

            # Retrieve replay summary if not in replay_mode and not explicitly provided
            replay_summary = replay_evidence
            if replay_summary is None and not replay_mode:
                try:
                    from app.backend.analytics.forecast_replay import HistoricalReplayRunner
                    replay_summary = HistoricalReplayRunner.run_replay(
                        account_id=context.account_id,
                        as_of_date=as_of_cutoff
                    )
                except Exception:
                    replay_summary = None

            # Strategy Pattern model selection & execution
            selector = ModelSelector()
            strategy, model_reason = selector.select(f_ctx, replay_scores=replay_summary, forced_method=forced_method)
            estimate = strategy.predict(f_ctx)

            model_method = estimate.model_id
            method_name = estimate.method_name
            remaining_variable_minor = estimate.remaining_variable_minor

            # Expected variable income
            expected_variable_income_minor = 0
            for d in range(elapsed_day + 1, num_days + 1):
                day_obj = date(year, m_int, d)
                sqlite_w = (day_obj.weekday() + 1) % 7
                expected_variable_income_minor += weekday_income_avg.get(sqlite_w, 0)

            # Projected total expense
            projected_total_minor = (
                actual_net_spend_to_date +
                upcoming_recurring_minor +
                remaining_variable_minor
            )

            # Projected Income & Net Flow (reconciled)
            projected_income_minor = (
                actual_income_to_date_minor +
                upcoming_recurring_income_minor +
                expected_variable_income_minor
            )
            projected_net_flow_minor = projected_income_minor - projected_total_minor
            projected_savings_rate = round((projected_net_flow_minor / float(projected_income_minor)) * 100.0, 1) if projected_income_minor > 0 else 0.0

            recon = reconcile_forecast_components(
                actual_to_date_minor=actual_net_spend_to_date,
                recurring_minor=upcoming_recurring_minor,
                variable_minor=remaining_variable_minor,
                irregular_minor=0,
                expected_refund_minor=0,
                total_minor=projected_total_minor
            )

            # 5. Category Forecasts & Exact Reconciliation (F108-14, F108-28)
            cur.execute("""
                SELECT id, name, color, type FROM categories WHERE type = 'expense' AND is_archived = 0
            """)
            all_expense_cats = [dict(r) for r in cur.fetchall()]

            cur.execute("""
                SELECT category_id, amount_minor FROM budgets WHERE start_date = ?
            """, [context.as_of_month])
            budget_map = {row["category_id"]: row["amount_minor"] for row in cur.fetchall()}
            total_budget_minor = sum(budget_map.values()) if budget_map else None

            total_hist_spend = sum(cat_hist_totals.values())

            # Support synthetic "Uncategorised" category if uncategorized spend/recurring/history exists
            if (
                (0 in actual_cat_spends_net and actual_cat_spends_net[0] != 0) or
                (0 in upcoming_by_cat and upcoming_by_cat[0] != 0) or
                (0 in cat_hist_totals and cat_hist_totals[0] != 0)
            ):
                all_expense_cats.append({
                    "id": 0,
                    "name": "Uncategorised",
                    "color": "#8E8E93",
                    "type": "expense"
                })

            # Normalized category weights based on NON-RECURRING spending (F108-14)
            raw_weights: Dict[int, float] = {}
            for c in all_expense_cats:
                cid = c["id"]
                c_non_rec_actual = actual_cat_non_recurring_expense.get(cid, 0)
                curr_share = (c_non_rec_actual / float(actual_non_recurring_expense_minor)) if actual_non_recurring_expense_minor > 0 else 0.0
                hist_share = (cat_hist_totals.get(cid, 0) / float(total_hist_spend)) if (total_hist_spend > 0 and cid in cat_hist_totals) else 0.0

                if curr_share > 0 and hist_share > 0:
                    raw_weights[cid] = 0.60 * curr_share + 0.40 * hist_share
                elif curr_share > 0:
                    raw_weights[cid] = curr_share
                elif hist_share > 0:
                    raw_weights[cid] = hist_share
                else:
                    raw_weights[cid] = 0.0

            total_raw_weight = sum(raw_weights.values())
            norm_weights: Dict[int, float] = {}
            if total_raw_weight > 0:
                for cid, w in raw_weights.items():
                    norm_weights[cid] = w / total_raw_weight
            else:
                # F108-28: If no category variable evidence exists, allocate to Uncategorised
                if not any(c["id"] == 0 for c in all_expense_cats):
                    all_expense_cats.append({
                        "id": 0,
                        "name": "Uncategorised",
                        "color": "#8E8E93",
                        "type": "expense"
                    })
                norm_weights = {c["id"]: (1.0 if c["id"] == 0 else 0.0) for c in all_expense_cats}

            # Allocate variable spend to categories and guarantee zero drift
            cat_vars: Dict[int, int] = {}
            for c in all_expense_cats:
                cid = c["id"]
                cat_vars[cid] = round(remaining_variable_minor * norm_weights.get(cid, 0.0))

            var_drift = remaining_variable_minor - sum(cat_vars.values())
            if var_drift != 0 and all_expense_cats:
                top_cid = max(all_expense_cats, key=lambda c: (cat_vars.get(c["id"], 0), norm_weights.get(c["id"], 0.0)))["id"]
                cat_vars[top_cid] += var_drift

            cat_forecasts = []
            for c in all_expense_cats:
                cid = c["id"]
                c_actual = actual_cat_spends_net.get(cid, 0)
                c_upcoming = upcoming_by_cat.get(cid, 0)
                c_var_amt = cat_vars.get(cid, 0)
                c_proj = c_actual + c_upcoming + c_var_amt
                c_budget = budget_map.get(cid)
                c_var = (c_proj - c_budget) if c_budget is not None else None

                if c_proj != 0 or c_actual != 0 or c_budget is not None:
                    cat_forecasts.append({
                        "category_id": cid,
                        "name": c["name"],
                        "color": c["color"],
                        "actual_minor": c_actual,
                        "actual": round(c_actual / 100.0, 2),
                        "projected_minor": c_proj,
                        "projected": round(c_proj / 100.0, 2),
                        "budget_minor": c_budget,
                        "budget": round(c_budget / 100.0, 2) if c_budget is not None else None,
                        "projected_variance_minor": c_var,
                        "projected_variance": round(c_var / 100.0, 2) if c_var is not None else None,
                        "is_over_budget": bool(c_var and c_var > 0)
                    })

            cat_forecasts.sort(key=lambda x: x["projected_minor"], reverse=True)

            # 6. Multi-Factor Reliability Score (F108-16, F108-17)
            # Component A: Data Sufficiency (30%)
            data_suff_score = min(100.0, (completed_months / 12.0) * 80.0 + min(20.0, (tx_count / 50.0) * 20.0))

            # Component B: Historical Forecast Error (35%) (F109 Section 28)
            mean_replay_mae = None
            conf_error_source = None
            if not replay_mode and replay_summary:
                try:
                    if replay_summary.get("available"):
                        cand_scores = replay_summary.get("model_scores") or {}
                        prod_policy = replay_summary.get("production_policy")
                        if prod_policy and "mae_minor" in prod_policy:
                            mean_replay_mae = prod_policy["mae_minor"]
                            conf_error_source = "production_policy"
                        elif model_method in cand_scores:
                            mean_replay_mae = cand_scores[model_method]["mae_minor"]
                            conf_error_source = model_method
                        elif "models" in replay_summary and model_method in replay_summary["models"]:
                            mean_replay_mae = replay_summary["models"][model_method]["mae_minor"]
                            conf_error_source = model_method
                except Exception:
                    mean_replay_mae = None
                    conf_error_source = None

            if mean_replay_mae is not None and projected_total_minor > 0:
                rel_error = min(1.0, mean_replay_mae / float(max(projected_total_minor, 1000)))
                error_score = max(0.0, (1.0 - rel_error) * 100.0)
            else:
                error_score = 35.0

            # Component C: Behavioural Stability on non-recurring series (20%) (F108-17)
            hist_monthly_values = list(hist_monthly_non_recurring_expense.values())
            if len(hist_monthly_values) >= 3:
                med_spend = calculate_median(hist_monthly_values)
                mad_spend = calculate_median([abs(x - med_spend) for x in hist_monthly_values])
                variability = mad_spend / float(max(1, med_spend))
                stability_score = max(0.0, min(100.0, (1.0 - variability * 1.5) * 100.0))
            else:
                stability_score = 50.0

            # Component D: Recurring Coverage (15%)
            rec_coverage_ratio = upcoming_recurring_minor / float(max(1, projected_total_minor))
            recurring_score = min(100.0, rec_coverage_ratio * 100.0)

            confidence_score = round(
                0.30 * data_suff_score +
                0.35 * error_score +
                0.20 * stability_score +
                0.15 * recurring_score
            )
            confidence_score = max(0, min(100, confidence_score))

            if confidence_score >= 70:
                confidence = "high"
            elif confidence_score >= 40:
                confidence = "moderate"
            else:
                confidence = "low"

            # 7. Calibrated Range vs Early Estimate (F108-18, F108-19)
            progress = (elapsed_day / float(num_days)) if num_days > 0 else 1.0
            range_type = "early_estimate"
            calibrated_residuals = []

            if not replay_mode:
                try:
                    from app.backend.analytics.forecast_replay import HistoricalReplayRunner, calculate_percentile
                    r_type, r_residuals = HistoricalReplayRunner.get_calibrated_residuals(
                        account_id=context.account_id,
                        progress=progress
                    )
                    if r_type == "calibrated_range" and len(r_residuals) >= FORECAST_CONFIG.calibrated_range_min_residuals:
                        range_type = "calibrated_range"
                        calibrated_residuals = r_residuals
                except Exception:
                    range_type = "early_estimate"

            if remaining_days == 0:
                lower_bound_minor = projected_total_minor
                upper_bound_minor = projected_total_minor
            elif range_type == "calibrated_range" and calibrated_residuals:
                p10 = calculate_percentile(calibrated_residuals, 10)
                p90 = calculate_percentile(calibrated_residuals, 90)
                raw_lower = projected_total_minor + p10
                raw_upper = projected_total_minor + p90
                lower_bound_minor = max(actual_net_spend_to_date, min(projected_total_minor, raw_lower))
                upper_bound_minor = max(projected_total_minor, raw_upper)
            else:
                range_type = "early_estimate"
                shrinkage_factor = max(0.20, 1.0 - progress * 0.70)
                spread_minor = round(remaining_variable_minor * 0.18 * shrinkage_factor)
                lower_bound_minor = max(actual_net_spend_to_date, projected_total_minor - spread_minor)
                upper_bound_minor = projected_total_minor + spread_minor

            # Invariant: lower_bound_minor <= projected_total_minor <= upper_bound_minor (F108-19)
            lower_bound_minor = min(lower_bound_minor, projected_total_minor)
            upper_bound_minor = max(upper_bound_minor, projected_total_minor)

            proj_budget_variance = (projected_total_minor - total_budget_minor) if total_budget_minor else None

            # Diagnostics Payload (v1.0.9 Section 28 & 29)
            comparable_origins = 0
            if replay_summary and replay_summary.get("available"):
                comparable_origins = replay_summary.get("comparable_origin_count", 0)

            if forced_method:
                selection_evidence = "forced"
            elif model_reason.startswith("Adaptive replay selection"):
                selection_evidence = "comparable_replay"
            else:
                selection_evidence = "fallback"

            diagnostics = {
                "history_months": completed_months,
                "transaction_count": tx_count,
                "recurring_coverage_ratio": round(rec_coverage_ratio, 3),
                "replay_sample_count": len(calibrated_residuals),
                "recent_mae_minor": mean_replay_mae,
                "confidence_error_source": conf_error_source,
                "selected_method": model_method,
                "selection_reason": model_reason,
                "selection_evidence": selection_evidence,
                "comparable_origin_count": comparable_origins,
                "ranking_metric": "median_absolute_error",
                "confidence_score": confidence_score,
                "confidence_breakdown": {
                    "data_sufficiency": round(data_suff_score, 1),
                    "forecast_error": round(error_score, 1),
                    "stability": round(stability_score, 1),
                    "recurring_coverage": round(recurring_score, 1)
                },
                "range_type": range_type,
                "suppressed_inactive_rule_fallback_count": suppressed_inactive_rule_fallback_count
            }

            res = ForecastResult(
                target_month=context.as_of_month,
                projected_expense_minor=projected_total_minor,
                lower_bound_minor=lower_bound_minor,
                upper_bound_minor=upper_bound_minor,
                confidence=confidence,
                confidence_score=confidence_score,
                range_type=range_type,
                method=method_name,
                model_method=model_method,
                actual_spent_to_date_minor=actual_net_spend_to_date,
                upcoming_recurring_minor=upcoming_recurring_minor,
                expected_variable_minor=remaining_variable_minor,
                expected_refunds_minor=0,
                budget_minor=total_budget_minor,
                projected_variance_minor=proj_budget_variance,
                category_forecasts=cat_forecasts,
                components={
                    "elapsed_days": elapsed_day,
                    "remaining_days": remaining_days,
                    "total_days": num_days,
                    "range_type": range_type,
                    "reconciliation": recon.to_dict()
                },
                projected_income_minor=projected_income_minor,
                projected_net_flow_minor=projected_net_flow_minor,
                projected_savings_rate=projected_savings_rate,
                actual_income_to_date_minor=actual_income_to_date_minor,
                diagnostics=diagnostics
            )
            return res.to_dict()
