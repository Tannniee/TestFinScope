import calendar
from datetime import datetime, date
from typing import Dict, Any, List, Optional
from app.backend.database.connection import get_db_connection

class AnalyticsService:
    @staticmethod
    def _get_previous_month(month_str: str) -> str:
        """Takes 'YYYY-MM' and returns the previous month 'YYYY-MM'."""
        year, month = map(int, month_str.split("-"))
        if month == 1:
            return f"{year - 1}-12"
        return f"{year}-{month - 1:02d}"

    @staticmethod
    def get_month_summary(month: str, account_id: Optional[int] = None) -> Dict[str, Any]:
        """Calculates core KPI cards, cash flow trend, donut breakdown, and daily spending."""
        prev_month = AnalyticsService._get_previous_month(month)

        with get_db_connection() as conn:
            cur = conn.cursor()

            # Filter clause
            acc_clause = " AND account_id = ?" if account_id else ""
            params_curr = [f"{month}%"] + ([account_id] if account_id else [])
            params_prev = [f"{prev_month}%"] + ([account_id] if account_id else [])

            # Current month totals
            cur.execute(f"""
                SELECT 
                    transaction_type,
                    COALESCE(SUM(amount), 0.0) as total,
                    COUNT(id) as count
                FROM transactions
                WHERE transaction_date LIKE ? {acc_clause}
                GROUP BY transaction_type
            """, params_curr)
            curr_totals = {row["transaction_type"]: row["total"] for row in cur.fetchall()}

            # Previous month totals
            cur.execute(f"""
                SELECT 
                    transaction_type,
                    COALESCE(SUM(amount), 0.0) as total
                FROM transactions
                WHERE transaction_date LIKE ? {acc_clause}
                GROUP BY transaction_type
            """, params_prev)
            prev_totals = {row["transaction_type"]: row["total"] for row in cur.fetchall()}

            income = curr_totals.get("income", 0.0)
            expense = curr_totals.get("expense", 0.0)
            net_flow = income - expense
            savings_rate = (net_flow / income * 100.0) if income > 0 else 0.0

            prev_income = prev_totals.get("income", 0.0)
            prev_expense = prev_totals.get("expense", 0.0)
            prev_net = prev_income - prev_expense
            prev_savings_rate = (prev_net / prev_income * 100.0) if prev_income > 0 else 0.0

            income_delta_pct = ((income - prev_income) / prev_income * 100.0) if prev_income > 0 else 0.0
            expense_delta_pct = ((expense - prev_expense) / prev_expense * 100.0) if prev_expense > 0 else 0.0

            # Daily Cash Flow & Spending
            year, m_int = map(int, month.split("-"))
            num_days = calendar.monthrange(year, m_int)[1]
            all_days = [f"{month}-{d:02d}" for d in range(1, num_days + 1)]

            cur.execute(f"""
                SELECT 
                    transaction_date,
                    transaction_type,
                    SUM(amount) as total
                FROM transactions
                WHERE transaction_date LIKE ? {acc_clause}
                GROUP BY transaction_date, transaction_type
                ORDER BY transaction_date ASC
            """, params_curr)

            daily_income_map = {}
            daily_expense_map = {}
            for row in cur.fetchall():
                d = row["transaction_date"]
                if row["transaction_type"] == "income":
                    daily_income_map[d] = row["total"]
                elif row["transaction_type"] == "expense":
                    daily_expense_map[d] = row["total"]

            trend_days = []
            trend_income = []
            trend_expense = []
            for d in all_days:
                day_label = d.split("-")[2]
                trend_days.append(day_label)
                trend_income.append(round(daily_income_map.get(d, 0.0), 2))
                trend_expense.append(round(daily_expense_map.get(d, 0.0), 2))

            # Category Breakdown for Expenses
            cur.execute(f"""
                SELECT 
                    c.id,
                    c.name,
                    c.color,
                    c.icon,
                    COALESCE(SUM(t.amount), 0.0) as total,
                    COUNT(t.id) as count
                FROM transactions t
                JOIN categories c ON t.category_id = c.id
                WHERE t.transaction_type = 'expense'
                  AND t.transaction_date LIKE ? {acc_clause}
                GROUP BY c.id
                ORDER BY total DESC
            """, params_curr)

            categories_breakdown = []
            for row in cur.fetchall():
                cat_total = row["total"]
                pct = (cat_total / expense * 100.0) if expense > 0 else 0.0
                categories_breakdown.append({
                    "id": row["id"],
                    "name": row["name"],
                    "color": row["color"],
                    "icon": row["icon"],
                    "amount": round(cat_total, 2),
                    "percentage": round(pct, 1),
                    "count": row["count"]
                })

            # Essential vs Discretionary
            cur.execute(f"""
                SELECT 
                    essentiality,
                    COALESCE(SUM(amount), 0.0) as total
                FROM transactions
                WHERE transaction_type = 'expense'
                  AND transaction_date LIKE ? {acc_clause}
                GROUP BY essentiality
            """, params_curr)
            essentiality_map = {row["essentiality"]: row["total"] for row in cur.fetchall()}
            essential_total = essentiality_map.get("essential", 0.0)
            discretionary_total = essentiality_map.get("discretionary", 0.0)

            return {
                "month": month,
                "previous_month": prev_month,
                "kpis": {
                    "income": round(income, 2),
                    "income_delta_pct": round(income_delta_pct, 1),
                    "expense": round(expense, 2),
                    "expense_delta_pct": round(expense_delta_pct, 1),
                    "net_flow": round(net_flow, 2),
                    "savings_rate": round(savings_rate, 1),
                    "prev_savings_rate": round(prev_savings_rate, 1)
                },
                "trend": {
                    "days": trend_days,
                    "income": trend_income,
                    "expense": trend_expense
                },
                "categories": categories_breakdown,
                "essentiality": {
                    "essential": round(essential_total, 2),
                    "discretionary": round(discretionary_total, 2),
                    "essential_pct": round(essential_total / expense * 100.0, 1) if expense > 0 else 0.0,
                    "discretionary_pct": round(discretionary_total / expense * 100.0, 1) if expense > 0 else 0.0
                }
            }

    @staticmethod
    def get_calendar_data(month: str, account_id: Optional[int] = None) -> Dict[str, Any]:
        """Returns daily sums of income, expense, net flow, and transaction count for a month."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND account_id = ?" if account_id else ""
            params = [f"{month}%"] + ([account_id] if account_id else [])

            cur.execute(f"""
                SELECT 
                    transaction_date,
                    transaction_type,
                    SUM(amount) as total,
                    COUNT(id) as count
                FROM transactions
                WHERE transaction_date LIKE ? {acc_clause}
                GROUP BY transaction_date, transaction_type
            """, params)

            days_data = {}
            for row in cur.fetchall():
                d = row["transaction_date"]
                if d not in days_data:
                    days_data[d] = {"income": 0.0, "expense": 0.0, "count": 0}
                t_type = row["transaction_type"]
                if t_type == "income":
                    days_data[d]["income"] += row["total"]
                elif t_type == "expense":
                    days_data[d]["expense"] += row["total"]
                days_data[d]["count"] += row["count"]

            for d, val in days_data.items():
                val["net"] = round(val["income"] - val["expense"], 2)
                val["income"] = round(val["income"], 2)
                val["expense"] = round(val["expense"], 2)

            return {
                "month": month,
                "days": days_data
            }

    @staticmethod
    def get_analytics_deep_dive(month: str, account_id: Optional[int] = None) -> Dict[str, Any]:
        """Provides 'What Changed?' variance, weekday distributions, cumulative pacing, and top merchants."""
        prev_month = AnalyticsService._get_previous_month(month)

        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND account_id = ?" if account_id else ""
            params_curr = [f"{month}%"] + ([account_id] if account_id else [])
            params_prev = [f"{prev_month}%"] + ([account_id] if account_id else [])

            # 1. "What Changed?" Category Variance
            cur.execute(f"""
                SELECT 
                    c.id,
                    c.name,
                    c.color,
                    COALESCE(SUM(t.amount), 0.0) as current_amount
                FROM categories c
                LEFT JOIN transactions t ON t.category_id = c.id 
                    AND t.transaction_type = 'expense'
                    AND t.transaction_date LIKE ? {acc_clause}
                WHERE c.type = 'expense' AND c.is_archived = 0
                GROUP BY c.id
            """, params_curr)
            curr_cats = {row["id"]: {"name": row["name"], "color": row["color"], "current": row["current_amount"]} for row in cur.fetchall()}

            cur.execute(f"""
                SELECT 
                    c.id,
                    COALESCE(SUM(t.amount), 0.0) as prev_amount
                FROM categories c
                LEFT JOIN transactions t ON t.category_id = c.id 
                    AND t.transaction_type = 'expense'
                    AND t.transaction_date LIKE ? {acc_clause}
                WHERE c.type = 'expense' AND c.is_archived = 0
                GROUP BY c.id
            """, params_prev)
            for row in cur.fetchall():
                if row["id"] in curr_cats:
                    curr_cats[row["id"]]["previous"] = row["prev_amount"]

            variance_items = []
            for cat_id, data in curr_cats.items():
                curr_val = round(data.get("current", 0.0), 2)
                prev_val = round(data.get("previous", 0.0), 2)
                delta = round(curr_val - prev_val, 2)
                pct_change = round((delta / prev_val * 100.0), 1) if prev_val > 0 else (100.0 if curr_val > 0 else 0.0)

                if curr_val > 0 or prev_val > 0:
                    variance_items.append({
                        "id": cat_id,
                        "name": data["name"],
                        "color": data["color"],
                        "current": curr_val,
                        "previous": prev_val,
                        "delta": delta,
                        "pct_change": pct_change,
                        "direction": "increased" if delta > 0 else ("decreased" if delta < 0 else "neutral")
                    })

            # Sort by absolute impact
            variance_items.sort(key=lambda x: abs(x["delta"]), reverse=True)

            # 2. Weekday Distribution (0=Monday, 6=Sunday)
            cur.execute(f"""
                SELECT 
                    transaction_date,
                    amount
                FROM transactions
                WHERE transaction_type = 'expense'
                  AND transaction_date LIKE ? {acc_clause}
            """, params_curr)

            weekday_totals = [0.0] * 7
            weekday_counts = [0] * 7
            weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

            for row in cur.fetchall():
                dt = datetime.strptime(row["transaction_date"], "%Y-%m-%d")
                w = dt.weekday()
                weekday_totals[w] += row["amount"]
                weekday_counts[w] += 1

            weekday_data = [
                {
                    "day": weekday_labels[i],
                    "total": round(weekday_totals[i], 2),
                    "average": round(weekday_totals[i] / weekday_counts[i], 2) if weekday_counts[i] > 0 else 0.0,
                    "count": weekday_counts[i]
                }
                for i in range(7)
            ]

            # 3. Cumulative Spending Comparison
            year, m_int = map(int, month.split("-"))
            num_days = calendar.monthrange(year, m_int)[1]

            # Current month cumulative
            cur.execute(f"""
                SELECT transaction_date, SUM(amount) as total
                FROM transactions
                WHERE transaction_type = 'expense' AND transaction_date LIKE ? {acc_clause}
                GROUP BY transaction_date
                ORDER BY transaction_date ASC
            """, params_curr)
            curr_day_spend = {int(row["transaction_date"].split("-")[2]): row["total"] for row in cur.fetchall()}

            # Prev month cumulative
            cur.execute(f"""
                SELECT transaction_date, SUM(amount) as total
                FROM transactions
                WHERE transaction_type = 'expense' AND transaction_date LIKE ? {acc_clause}
                GROUP BY transaction_date
                ORDER BY transaction_date ASC
            """, params_prev)
            prev_day_spend = {int(row["transaction_date"].split("-")[2]): row["total"] for row in cur.fetchall()}

            cum_days = []
            cum_curr = []
            cum_prev = []
            curr_running = 0.0
            prev_running = 0.0

            for d in range(1, num_days + 1):
                cum_days.append(str(d))
                curr_running += curr_day_spend.get(d, 0.0)
                prev_running += prev_day_spend.get(d, 0.0)
                cum_curr.append(round(curr_running, 2))
                cum_prev.append(round(prev_running, 2))

            # 4. Top Merchants
            cur.execute(f"""
                SELECT 
                    merchant_name,
                    COUNT(id) as count,
                    SUM(amount) as total
                FROM transactions
                WHERE transaction_type = 'expense' 
                  AND merchant_name != '' 
                  AND transaction_date LIKE ? {acc_clause}
                GROUP BY merchant_name
                ORDER BY total DESC
                LIMIT 8
            """, params_curr)

            top_merchants = [
                {
                    "merchant": row["merchant_name"],
                    "count": row["count"],
                    "total": round(row["total"], 2)
                }
                for row in cur.fetchall()
            ]

            # 5. Transaction Size Buckets
            cur.execute(f"""
                SELECT amount
                FROM transactions
                WHERE transaction_type = 'expense' AND transaction_date LIKE ? {acc_clause}
            """, params_curr)

            buckets = {"<$15": 0, "$15–$50": 0, "$50–$100": 0, "$100–$250": 0, ">$250": 0}
            for row in cur.fetchall():
                a = row["amount"]
                if a < 15:
                    buckets["<$15"] += 1
                elif a < 50:
                    buckets["$15–$50"] += 1
                elif a < 100:
                    buckets["$50–$100"] += 1
                elif a < 250:
                    buckets["$100–$250"] += 1
                else:
                    buckets[">$250"] += 1

            return {
                "month": month,
                "previous_month": prev_month,
                "variance": variance_items,
                "weekday": weekday_data,
                "cumulative": {
                    "days": cum_days,
                    "current": cum_curr,
                    "previous": cum_prev
                },
                "merchants": top_merchants,
                "distribution": buckets
            }
