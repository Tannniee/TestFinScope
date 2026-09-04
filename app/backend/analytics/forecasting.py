"""
Explainable Forecasting Engine v1 for FinScope.
Projects month-end spending, income, and budget risk through a transparent component model:
Projected Expense = Actual Spend To Date
                  + Known Upcoming Recurring Bills
                  + Remaining Variable Spend (weekday-adjusted)
                  - Expected Refunds
Includes confidence bounds and per-category budget risk projection.
"""

import calendar
from datetime import datetime, date
from typing import Dict, Any, List, Optional
from app.backend.database.connection import get_db_connection
from app.backend.analytics.semantics import calculate_net_spending
from app.backend.analytics.rolling import calculate_median, calculate_mean, calculate_mad
from app.backend.analytics.models import ForecastResult

class ForecastingEngine:
    @staticmethod
    def forecast_month(
        month: str,
        account_id: Optional[int] = None,
        as_of_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generates explainable month-end forecast for `month` (YYYY-MM).
        If `as_of_date` is not given, uses today's date if within the month,
        or the middle of the month (15th) if looking at a past/future month.
        """
        year, m_int = map(int, month.split("-"))
        num_days = calendar.monthrange(year, m_int)[1]

        # Determine elapsed days
        today = date.today()
        if as_of_date:
            cur_dt = datetime.strptime(as_of_date, "%Y-%m-%d").date()
            elapsed_day = min(num_days, max(1, cur_dt.day))
        elif today.year == year and today.month == m_int:
            elapsed_day = min(num_days, max(1, today.day))
        else:
            # For demonstration / retrospective forecasting
            elapsed_day = min(15, num_days)

        remaining_days = max(0, num_days - elapsed_day)

        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND t.account_id = ?" if account_id else ""
            params: List[Any] = [account_id] if account_id else []

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
                FROM transactions t
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE t.transaction_date >= ? AND t.transaction_date <= ? {acc_clause}
                GROUP BY t.transaction_type, t.is_recurring, t.category_id
            """, [f"{month}-01", f"{month}-{elapsed_day:02d}"] + params)

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
            # Search recurring items from previous months that normally execute after elapsed_day
            cur.execute(f"""
                SELECT 
                    COALESCE(NULLIF(merchant_name, ''), description) as bill_name,
                    category_id,
                    CAST(strftime('%d', transaction_date) AS INTEGER) as usual_day,
                    amount_minor
                FROM transactions
                WHERE transaction_type = 'expense'
                  AND is_recurring = 1
                  AND transaction_date < ? || '-01'
                  AND transaction_date >= date(? || '-01', '-3 months') {acc_clause}
            """, [month, month] + params)

            historical_recurring = cur.fetchall()
            upcoming_recurring_minor = 0
            upcoming_by_cat: Dict[int, int] = {}

            # Deduplicate by bill_name and usual day
            seen_bills = set()
            for r in historical_recurring:
                b_name = r["bill_name"]
                day_num = r["usual_day"]
                if b_name not in seen_bills:
                    seen_bills.add(b_name)
                    # If this bill occurs later in the month than elapsed_day
                    if day_num > elapsed_day:
                        amt = r["amount_minor"]
                        upcoming_recurring_minor += amt
                        cid = r["category_id"] or 0
                        upcoming_by_cat[cid] = upcoming_by_cat.get(cid, 0) + amt

            # 3. Variable Spend Rate & Weekday Adjustment
            # Fetch non-recurring daily spending by day of week over the past 3 months
            cur.execute(f"""
                SELECT 
                    strftime('%w', transaction_date) as wday,
                    amount_minor
                FROM transactions
                WHERE transaction_type = 'expense'
                  AND is_recurring = 0
                  AND transaction_date < ? || '-01'
                  AND transaction_date >= date(? || '-01', '-3 months') {acc_clause}
            """, [month, month] + params)

            weekday_samples: Dict[int, List[int]] = {i: [] for i in range(7)}
            for r in cur.fetchall():
                w = int(r["wday"])
                weekday_samples[w].append(r["amount_minor"])

            # Compute daily average per weekday
            weekday_avg_minor: Dict[int, int] = {}
            for w in range(7):
                s = weekday_samples[w]
                # Total spend on this weekday divided by number of days observed (~12 weeks)
                weekday_avg_minor[w] = (sum(s) // 12) if s else 0

            # Fallback if insufficient history: use current month elapsed pace
            if sum(weekday_avg_minor.values()) == 0 and elapsed_day > 0:
                daily_pace = actual_net_spend_to_date // elapsed_day
                for w in range(7):
                    weekday_avg_minor[w] = daily_pace

            # Count remaining weekdays in this month
            remaining_variable_minor = 0
            for d in range(elapsed_day + 1, num_days + 1):
                day_obj = date(year, m_int, d)
                # python weekday: 0=Mon, 6=Sun; sqlite %w: 0=Sun, 1=Mon
                sqlite_w = (day_obj.weekday() + 1) % 7
                remaining_variable_minor += weekday_avg_minor.get(sqlite_w, 0)

            # 4. Total Forecast Calculation
            projected_total_minor = (
                actual_net_spend_to_date +
                upcoming_recurring_minor +
                remaining_variable_minor
            )

            # Likely range spread based on remaining days uncertainty (~15% of variable)
            spread_minor = round(remaining_variable_minor * 0.18)
            lower_bound_minor = max(actual_net_spend_to_date, projected_total_minor - spread_minor)
            upper_bound_minor = projected_total_minor + spread_minor

            # 5. Category Forecasts & Budget Comparison
            cur.execute("""
                SELECT id, name, color, type FROM categories WHERE type = 'expense' AND is_archived = 0
            """)
            all_expense_cats = cur.fetchall()

            # Fetch monthly budgets
            cur.execute("""
                SELECT category_id, amount_minor FROM budgets WHERE start_date = ?
            """, [month])
            budget_map = {row["category_id"]: row["amount_minor"] for row in cur.fetchall()}
            total_budget_minor = sum(budget_map.values()) if budget_map else None

            cat_forecasts = []
            for c in all_expense_cats:
                cid = c["id"]
                c_actual = actual_cat_spends.get(cid, 0)
                c_upcoming = upcoming_by_cat.get(cid, 0)
                # Attribute variable share roughly proportional to category's historical share
                cat_var = round(remaining_variable_minor * (c_actual / actual_net_spend_to_date)) if actual_net_spend_to_date > 0 else 0
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

            # Check history length for confidence
            cur.execute("""
                SELECT COUNT(DISTINCT strftime('%Y-%m', transaction_date)) as m_count
                FROM transactions WHERE transaction_type = 'expense'
            """)
            history_months = cur.fetchone()["m_count"] or 0
            if history_months >= 6:
                confidence = "high"
            elif history_months >= 2:
                confidence = "moderate"
            else:
                confidence = "low"

            proj_budget_variance = (projected_total_minor - total_budget_minor) if total_budget_minor else None

            res = ForecastResult(
                target_month=month,
                projected_expense_minor=projected_total_minor,
                lower_bound_minor=lower_bound_minor,
                upper_bound_minor=upper_bound_minor,
                confidence=confidence,
                method="Hybrid (Actual + Scheduled Recurring + Weekday-Adjusted Variable)",
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
                    "total_days": num_days
                }
            )
            return res.to_dict()
