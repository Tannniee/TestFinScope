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


def generate_occurrences(
    next_due_date: Optional[str],
    frequency: str,
    start_date: date,
    end_date: date
) -> List[date]:
    """
    Expands a recurring rule into occurrences strictly falling within:
    start_date < occurrence_date <= end_date.
    Frequencies supported: weekly, fortnightly, monthly, quarterly, yearly.
    """
    if not next_due_date:
        return []
    try:
        cur_due = datetime.strptime(str(next_due_date)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return []

    freq = (frequency or "monthly").strip().casefold()

    # If the due date is already beyond end_date, no occurrences can fall in the window
    if cur_due > end_date:
        return []

    def advance_date(d: date, step_idx: int) -> date:
        if freq in ("weekly", "week"):
            return d + timedelta(days=7 * step_idx)
        elif freq in ("fortnightly", "biweekly", "bi-weekly"):
            return d + timedelta(days=14 * step_idx)
        elif freq in ("monthly", "month"):
            y = d.year + (d.month - 1 + step_idx) // 12
            m = (d.month - 1 + step_idx) % 12 + 1
            max_d = calendar.monthrange(y, m)[1]
            return date(y, m, min(d.day, max_d))
        elif freq in ("quarterly", "quarter"):
            step = step_idx * 3
            y = d.year + (d.month - 1 + step) // 12
            m = (d.month - 1 + step) % 12 + 1
            max_d = calendar.monthrange(y, m)[1]
            return date(y, m, min(d.day, max_d))
        elif freq in ("yearly", "annual", "annually"):
            y = d.year + step_idx
            max_d = calendar.monthrange(y, d.month)[1]
            return date(y, d.month, min(d.day, max_d))
        else:
            # Default monthly
            y = d.year + (d.month - 1 + step_idx) // 12
            m = (d.month - 1 + step_idx) % 12 + 1
            max_d = calendar.monthrange(y, m)[1]
            return date(y, m, min(d.day, max_d))

    occurrences: List[date] = []
    step = 0
    while True:
        occ = advance_date(cur_due, step)
        if occ > end_date:
            break
        if occ > start_date:
            occurrences.append(occ)
        step += 1
        if step > 500:
            break

    return occurrences


class ForecastingEngine:
    @staticmethod
    def forecast_month(
        month: str,
        account_id: Optional[int] = None,
        as_of_date: Optional[str] = None,
        context: Optional[AnalyticsContext] = None,
        replay_mode: bool = False
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
            actual_income_to_date_minor = 0
            actual_refund_minor = 0
            actual_recurring_minor = 0
            actual_cat_spends: Dict[int, int] = {}
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
                    actual_cat_spends[cid] = actual_cat_spends.get(cid, 0) + amt
                    if r["is_recurring"]:
                        actual_recurring_minor += amt
                elif tt == "income":
                    actual_income_to_date_minor += amt
                elif tt == "refund":
                    actual_refund_minor += amt
                    actual_cat_spends[cid] = actual_cat_spends.get(cid, 0) - amt

            actual_net_spend_to_date = calculate_net_spending(actual_expense_minor, actual_refund_minor)

            # 2. Known Upcoming Recurring Expenses & Income (F105-02 & F105-03)
            # Schedule expansion window: strictly after current elapsed cutoff, up to end of target month
            window_start = cur_dt if (cur_dt.year == year and cur_dt.month == m_int) else (
                date(year, m_int, 1) - timedelta(days=1) if cur_dt < date(year, m_int, 1) else date(year, m_int, elapsed_day)
            )
            window_end = date(year, m_int, num_days)

            upcoming_recurring_minor = 0
            upcoming_recurring_income_minor = 0
            upcoming_by_cat: Dict[int, int] = {}
            seen_rules = set()
            seen_bills = set()

            # 2a. Explicit rules from recurring_rules table (with frequency expansion)
            rec_acc_clause = " AND account_id = ?" if context.account_id else ""
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

            # 2b. Historical recurring transactions (AUD-006B: deterministic latest selection)
            # Query recurring transactions from past 3 months strictly before target month and <= as_of_cutoff
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
                if rule_id is not None and rule_id in seen_rules:
                    continue

                raw_b_name = r["bill_name"]
                acc_id = r["account_id"]
                key = recurring_key(acc_id, raw_b_name)
                if key in seen_bills:
                    continue

                seen_bills.add(key)
                if rule_id is not None:
                    seen_rules.add(rule_id)

                day_num = r["usual_day"]
                if day_num > elapsed_day and day_num <= num_days:
                    amt = r["amount_minor"]
                    upcoming_recurring_minor += amt
                    cid = r["category_id"] or 0
                    upcoming_by_cat[cid] = upcoming_by_cat.get(cid, 0) + amt

            # 3. Dynamic Historical Weekday Rates (past 3 completed months strictly before target month)
            hist_start_str = f"{year - 1 if m_int <= 3 else year}-{(m_int - 4) % 12 + 1:02d}-01"
            h_sy, h_sm = map(int, hist_start_str.split("-")[:2])
            h_start_date = date(h_sy, h_sm, 1)
            h_end_date = date(year, m_int, 1) - timedelta(days=1)
            if cur_dt < h_end_date:
                h_end_date = cur_dt

            actual_wday_counts = count_weekdays_in_historical_window(h_start_date, h_end_date)

            # Robust Expense rates (F105-08: grouped by transaction_date to cap extreme single-day outliers)
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
                wday_daily_spends[w].append(r["day_total_minor"])

            weekday_avg_minor: Dict[int, int] = {}
            for w in range(7):
                spends = wday_daily_spends[w]
                occ = max(1, actual_wday_counts.get(w, 1))
                if not spends:
                    weekday_avg_minor[w] = 0
                elif occ >= 4 and len(spends) >= 2:
                    # Robust estimator: median daily spend blended with MAD-capped mean
                    med = calculate_median(spends)
                    devs = [abs(x - med) for x in spends]
                    mad = calculate_median(devs)
                    cap = med + max(1000, round(3.0 * mad))
                    capped_spends = [min(x, cap) for x in spends]
                    capped_mean = round(sum(capped_spends) / float(occ))
                    # Blend 60% median rate with 40% capped mean
                    weekday_avg_minor[w] = round(0.60 * (med * len(spends) / float(occ)) + 0.40 * capped_mean)
                else:
                    tot = sum(spends)
                    weekday_avg_minor[w] = round(tot / float(occ)) if tot > 0 else 0

            # Income rates (F105-03: explicitly filter is_recurring = 0 to prevent salary double counting)
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

            # 4. Model Eligibility by Data Sufficiency (F105-07)
            cur.execute(f"""
                SELECT COUNT(DISTINCT strftime('%Y-%m', t.transaction_date)) as m_count,
                       COUNT(t.id) as tx_count
                FROM active_transactions t 
                WHERE t.transaction_type = 'expense'
                  AND transaction_date < ? || '-01'
                  AND transaction_date <= ? {acc_clause}
            """, [context.as_of_month, as_of_cutoff] + acc_params)
            m_row = cur.fetchone()
            completed_months = m_row["m_count"] if m_row else 0
            tx_count = m_row["tx_count"] if m_row else 0

            # Historical monthly spends for stability and model baseline
            cur.execute(f"""
                SELECT 
                    strftime('%Y-%m', t.transaction_date) as m,
                    COALESCE(SUM(CASE WHEN t.transaction_type = 'expense' THEN t.amount_minor ELSE 0 END), 0) -
                    COALESCE(SUM(CASE WHEN t.transaction_type = 'refund' THEN t.amount_minor ELSE 0 END), 0) as net_spend
                FROM active_transactions t
                WHERE t.transaction_date < ? || '-01'
                  AND t.transaction_date <= ? {acc_clause}
                GROUP BY m
                ORDER BY m ASC
            """, [context.as_of_month, as_of_cutoff] + acc_params)
            hist_monthly_spends = [max(0, r["net_spend"]) for r in cur.fetchall() if r["net_spend"] is not None]

            # Model method determination
            if completed_months < 2 and not replay_mode:
                model_method = "current_pace"
                method_name = "Current Pace + Known Recurring"
                model_reason = "Minimal history (< 2 complete months); using current pace"
                daily_pace = (actual_net_spend_to_date // elapsed_day) if elapsed_day > 0 else 0
                remaining_variable_minor = daily_pace * remaining_days
            elif completed_months < 6 and not replay_mode:
                model_method = "three_month_median"
                method_name = "Recent Median + Known Recurring"
                model_reason = f"Early history ({completed_months} complete months); using recent median"
                if hist_monthly_spends and remaining_days > 0:
                    med_monthly = calculate_median(hist_monthly_spends[-3:])
                    est_variable_total = max(0, med_monthly - upcoming_recurring_minor)
                    remaining_variable_minor = round(est_variable_total * (remaining_days / float(num_days)))
                else:
                    remaining_variable_minor = 0
            elif completed_months < 12:
                model_method = "weekday_hybrid"
                method_name = "FinScope Hybrid (Actual + Scheduled Recurring + Robust Weekday Variable)"
                model_reason = f"Established history ({completed_months} complete months); using weekday hybrid"
                # Fallback if no weekday rates
                if sum(weekday_avg_minor.values()) == 0 and elapsed_day > 0:
                    daily_pace = actual_net_spend_to_date // elapsed_day
                    for w in range(7):
                        weekday_avg_minor[w] = daily_pace
                remaining_variable_minor = 0
                for d in range(elapsed_day + 1, num_days + 1):
                    day_obj = date(year, m_int, d)
                    sqlite_w = (day_obj.weekday() + 1) % 7
                    remaining_variable_minor += weekday_avg_minor.get(sqlite_w, 0)
            else:
                model_method = "weekday_hybrid"
                method_name = "FinScope Hybrid (Actual + Scheduled Recurring + Robust Weekday Variable)"
                model_reason = f"Seasonal history available ({completed_months} complete months)"
                if sum(weekday_avg_minor.values()) == 0 and elapsed_day > 0:
                    daily_pace = actual_net_spend_to_date // elapsed_day
                    for w in range(7):
                        weekday_avg_minor[w] = daily_pace
                remaining_variable_minor = 0
                for d in range(elapsed_day + 1, num_days + 1):
                    day_obj = date(year, m_int, d)
                    sqlite_w = (day_obj.weekday() + 1) % 7
                    remaining_variable_minor += weekday_avg_minor.get(sqlite_w, 0)

            # Expected variable income
            expected_variable_income_minor = 0
            for d in range(elapsed_day + 1, num_days + 1):
                day_obj = date(year, m_int, d)
                sqlite_w = (day_obj.weekday() + 1) % 7
                expected_variable_income_minor += weekday_income_avg.get(sqlite_w, 0)

            # If replay mode forced hybrid computation
            if replay_mode:
                model_method = "weekday_hybrid"
                method_name = "FinScope Hybrid"
                model_reason = "Production Replay Evaluation"
                if sum(weekday_avg_minor.values()) == 0 and elapsed_day > 0:
                    daily_pace = actual_net_spend_to_date // elapsed_day
                    for w in range(7):
                        weekday_avg_minor[w] = daily_pace
                remaining_variable_minor = 0
                for d in range(elapsed_day + 1, num_days + 1):
                    day_obj = date(year, m_int, d)
                    sqlite_w = (day_obj.weekday() + 1) % 7
                    remaining_variable_minor += weekday_avg_minor.get(sqlite_w, 0)

            # Projected total expense
            projected_total_minor = (
                actual_net_spend_to_date +
                upcoming_recurring_minor +
                remaining_variable_minor
            )

            # Projected Income & Net Flow (F105-03 reconciled)
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

            # 5. Category Forecasts & Exact Reconciliation (F105-04)
            cur.execute("""
                SELECT id, name, color, type FROM categories WHERE type = 'expense' AND is_archived = 0
            """)
            all_expense_cats = cur.fetchall()

            cur.execute("""
                SELECT category_id, amount_minor FROM budgets WHERE start_date = ?
            """, [context.as_of_month])
            budget_map = {row["category_id"]: row["amount_minor"] for row in cur.fetchall()}
            total_budget_minor = sum(budget_map.values()) if budget_map else None

            # Category historical rates
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
            total_hist_spend = sum(cat_hist_totals.values())

            # Normalized category weights
            raw_weights: Dict[int, float] = {}
            for c in all_expense_cats:
                cid = c["id"]
                c_actual = max(0, actual_cat_spends.get(cid, 0))
                curr_share = (c_actual / float(actual_net_spend_to_date)) if actual_net_spend_to_date > 0 else 0.0
                hist_share = (cat_hist_totals[cid] / float(total_hist_spend)) if (total_hist_spend > 0 and cid in cat_hist_totals) else 0.0

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
                n_cats = len(all_expense_cats)
                for c in all_expense_cats:
                    norm_weights[c["id"]] = (1.0 / n_cats) if n_cats > 0 else 0.0

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
                c_actual = max(0, actual_cat_spends.get(cid, 0))
                c_upcoming = upcoming_by_cat.get(cid, 0)
                c_var_amt = cat_vars.get(cid, 0)
                c_proj = c_actual + c_upcoming + c_var_amt
                c_budget = budget_map.get(cid)
                c_var = (c_proj - c_budget) if c_budget is not None else None

                if c_proj > 0 or c_budget is not None:
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

            # 6. Multi-Factor Reliability Score (F105-05)
            # Component A: Data Sufficiency (30%)
            data_suff_score = min(100.0, (completed_months / 12.0) * 80.0 + min(20.0, (tx_count / 50.0) * 20.0))

            # Component B: Historical Forecast Error (35%)
            mean_replay_mae = None
            if not replay_mode:
                try:
                    from app.backend.analytics.forecast_replay import HistoricalReplayRunner
                    replay_summary = HistoricalReplayRunner.run_replay(account_id=context.account_id, as_of_date=as_of_cutoff)
                    if replay_summary.get("available") and "finscope_hybrid" in replay_summary.get("models", {}):
                        mean_replay_mae = replay_summary["models"]["finscope_hybrid"]["mae_minor"]
                except Exception:
                    mean_replay_mae = None

            if mean_replay_mae is not None and projected_total_minor > 0:
                rel_error = min(1.0, mean_replay_mae / float(max(projected_total_minor, 1000)))
                error_score = max(0.0, (1.0 - rel_error) * 100.0)
            else:
                error_score = 50.0

            # Component C: Behavioural Stability (20%)
            if len(hist_monthly_spends) >= 3:
                med_spend = calculate_median(hist_monthly_spends)
                mad_spend = calculate_median([abs(x - med_spend) for x in hist_monthly_spends])
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

            # 7. Calibrated Range vs Early Estimate (F105-06)
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
                    if r_type == "calibrated_range" and len(r_residuals) >= 6:
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
                lower_bound_minor = max(actual_net_spend_to_date, projected_total_minor + p10)
                upper_bound_minor = max(projected_total_minor, projected_total_minor + p90)
            else:
                range_type = "early_estimate"
                shrinkage_factor = max(0.20, 1.0 - progress * 0.70)
                spread_minor = round(remaining_variable_minor * 0.18 * shrinkage_factor)
                lower_bound_minor = max(actual_net_spend_to_date, projected_total_minor - spread_minor)
                upper_bound_minor = projected_total_minor + spread_minor

            proj_budget_variance = (projected_total_minor - total_budget_minor) if total_budget_minor else None

            # Diagnostics Payload (F105-10)
            diagnostics = {
                "history_months": completed_months,
                "transaction_count": tx_count,
                "recurring_coverage_ratio": round(rec_coverage_ratio, 3),
                "replay_sample_count": len(calibrated_residuals),
                "recent_mae_minor": mean_replay_mae,
                "selected_method": model_method,
                "selection_reason": model_reason,
                "confidence_score": confidence_score,
                "confidence_breakdown": {
                    "data_sufficiency": round(data_suff_score, 1),
                    "forecast_error": round(error_score, 1),
                    "stability": round(stability_score, 1),
                    "recurring_coverage": round(recurring_score, 1)
                },
                "range_type": range_type
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
