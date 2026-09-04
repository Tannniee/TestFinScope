"""
Explainable Forecasting Engine V2 for FinScope.
Projects month-end spending, income, and budget risk through a transparent component model:
Projected Expense = Actual Spend To Date
                  + Known Upcoming Recurring Bills
                  + Remaining Variable Spend (exact weekday-frequency adjusted)
                  - Expected Refunds
Includes confidence bounds, category-level projections, and reconciliation validation.
"""

import calendar
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
from app.backend.database.connection import get_db_connection
from app.backend.analytics.semantics import calculate_net_spending
from app.backend.analytics.models import ForecastResult
from app.backend.analytics.context import AnalyticsContext, resolve_analytics_context
from app.backend.analytics.reconciliation import reconcile_forecast_components

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
        context: Optional[AnalyticsContext] = None
    ) -> Dict[str, Any]:
        """
        Generates explainable month-end forecast for `month` (YYYY-MM).
        Uses dynamic historical weekday counts and category-specific projections.
        """
        if context is None:
            context = resolve_analytics_context(month=month, account_id=account_id)

        year, m_int = map(int, context.as_of_month.split("-"))
        num_days = calendar.monthrange(year, m_int)[1]

        # Determine elapsed days
        if as_of_date:
            cur_dt = datetime.strptime(as_of_date, "%Y-%m-%d").date()
            elapsed_day = min(num_days, max(1, cur_dt.day))
        elif context.is_current_month:
            elapsed_day = min(num_days, max(1, context.end_date.day))
        else:
            # Retrospective/hypothetical mid-month forecast
            elapsed_day = min(15, num_days)

        remaining_days = max(0, num_days - elapsed_day)

        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND t.account_id = ?" if context.account_id else ""
            acc_params: List[Any] = [context.account_id] if context.account_id else []

            # 1. Actual Spend To Date (days 1 to elapsed_day)
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
                elif tt == "refund":
                    actual_refund_minor += amt
                    actual_cat_spends[cid] = actual_cat_spends.get(cid, 0) - amt

            actual_net_spend_to_date = calculate_net_spending(actual_expense_minor, actual_refund_minor)

            # 2. Known Upcoming Recurring Expenses
            cur.execute(f"""
                SELECT 
                    COALESCE(NULLIF(merchant_name, ''), description) as bill_name,
                    category_id,
                    CAST(strftime('%d', transaction_date) AS INTEGER) as usual_day,
                    amount_minor
                FROM active_transactions t
                WHERE t.transaction_type = 'expense'
                  AND is_recurring = 1
                  AND transaction_date < ? || '-01'
                  AND transaction_date >= date(? || '-01', '-3 months') {acc_clause}
            """, [context.as_of_month, context.as_of_month] + acc_params)

            historical_recurring = cur.fetchall()
            upcoming_recurring_minor = 0
            upcoming_by_cat: Dict[int, int] = {}
            seen_bills = set()

            for r in historical_recurring:
                b_name = r["bill_name"]
                day_num = r["usual_day"]
                if b_name not in seen_bills:
                    seen_bills.add(b_name)
                    if day_num > elapsed_day:
                        amt = r["amount_minor"]
                        upcoming_recurring_minor += amt
                        cid = r["category_id"] or 0
                        upcoming_by_cat[cid] = upcoming_by_cat.get(cid, 0) + amt

            # 3. Dynamic Historical Weekday Rate (past 3 completed months)
            # Define window start & end dates
            hist_start_str = f"{year - 1 if m_int <= 3 else year}-{(m_int - 4) % 12 + 1:02d}-01"
            hist_end_str = f"{context.as_of_month}-01"

            h_sy, h_sm = map(int, hist_start_str.split("-")[:2])
            h_start_date = date(h_sy, h_sm, 1)
            # Yesterday relative to start of current month
            h_end_date = date(year, m_int, 1) - timedelta(days=1)

            actual_wday_counts = count_weekdays_in_historical_window(h_start_date, h_end_date)

            cur.execute(f"""
                SELECT 
                    strftime('%w', transaction_date) as wday,
                    SUM(amount_minor) as total_minor
                FROM active_transactions t
                WHERE t.transaction_type = 'expense'
                  AND is_recurring = 0
                  AND transaction_date >= ? AND transaction_date <= ? {acc_clause}
                GROUP BY wday
            """, [h_start_date.isoformat(), h_end_date.isoformat()] + acc_params)

            weekday_spend_totals = {int(r["wday"]): r["total_minor"] for r in cur.fetchall()}

            # Dynamic weekday average rate
            weekday_avg_minor: Dict[int, int] = {}
            for w in range(7):
                tot = weekday_spend_totals.get(w, 0)
                occ = max(1, actual_wday_counts.get(w, 1))
                weekday_avg_minor[w] = round(tot / float(occ)) if tot > 0 else 0

            # Fallback if no history: use current pace
            if sum(weekday_avg_minor.values()) == 0 and elapsed_day > 0:
                daily_pace = actual_net_spend_to_date // elapsed_day
                for w in range(7):
                    weekday_avg_minor[w] = daily_pace

            # Count remaining weekdays in this month
            remaining_variable_minor = 0
            for d in range(elapsed_day + 1, num_days + 1):
                day_obj = date(year, m_int, d)
                sqlite_w = (day_obj.weekday() + 1) % 7
                remaining_variable_minor += weekday_avg_minor.get(sqlite_w, 0)

            # 4. Total Forecast Calculation & Exact Reconciliation
            projected_total_minor = (
                actual_net_spend_to_date +
                upcoming_recurring_minor +
                remaining_variable_minor
            )

            recon = reconcile_forecast_components(
                actual_to_date_minor=actual_net_spend_to_date,
                recurring_minor=upcoming_recurring_minor,
                variable_minor=remaining_variable_minor,
                irregular_minor=0,
                expected_refund_minor=0,
                total_minor=projected_total_minor
            )

            spread_minor = round(remaining_variable_minor * 0.18)
            lower_bound_minor = max(actual_net_spend_to_date, projected_total_minor - spread_minor)
            upper_bound_minor = projected_total_minor + spread_minor

            # 5. Category Forecasts & Budget Comparison
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

            cat_forecasts = []
            for c in all_expense_cats:
                cid = c["id"]
                c_actual = max(0, actual_cat_spends.get(cid, 0))
                c_upcoming = upcoming_by_cat.get(cid, 0)

                # Variable allocation: weighted by current actual share or historical share if current is 0
                if actual_net_spend_to_date > 0 and c_actual > 0:
                    cat_weight = c_actual / float(actual_net_spend_to_date)
                elif total_hist_spend > 0 and cid in cat_hist_totals:
                    cat_weight = cat_hist_totals[cid] / float(total_hist_spend)
                else:
                    cat_weight = 0.0

                cat_var = round(remaining_variable_minor * cat_weight)
                c_proj = c_actual + c_upcoming + cat_var
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

            # History months for confidence
            cur.execute(f"""
                SELECT COUNT(DISTINCT strftime('%Y-%m', t.transaction_date)) as m_count
                FROM active_transactions t WHERE t.transaction_type = 'expense' {acc_clause}
            """, acc_params)
            history_months = cur.fetchone()["m_count"] or 0
            if history_months >= 6:
                confidence = "high"
            elif history_months >= 2:
                confidence = "moderate"
            else:
                confidence = "low"

            proj_budget_variance = (projected_total_minor - total_budget_minor) if total_budget_minor else None

            res = ForecastResult(
                target_month=context.as_of_month,
                projected_expense_minor=projected_total_minor,
                lower_bound_minor=lower_bound_minor,
                upper_bound_minor=upper_bound_minor,
                confidence=confidence,
                method="FinScope Hybrid (Actual + Scheduled Recurring + Exact Weekday-Adjusted Variable)",
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
                    "reconciliation": recon.to_dict()
                }
            )
            return res.to_dict()
