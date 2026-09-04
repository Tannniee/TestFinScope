import calendar
from datetime import datetime, date
from typing import Dict, Any, List, Optional
from app.backend.database.connection import get_db_connection
from app.backend.analytics.aggregates import AggregateQueries
from app.backend.analytics.rolling import RollingAnalyticsEngine
from app.backend.analytics.changes import WhatChangedEngine
from app.backend.analytics.fingerprint import SpendingFingerprintEngine
from app.backend.analytics.anomalies import AnomalyDetectionEngine
from app.backend.analytics.forecasting import ForecastingEngine
from app.backend.analytics.backtesting import BacktestingEngine
from app.backend.analytics.insight_rules import InsightRulesGenerator
from app.backend.analytics.insight_ranker import InsightRanker

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
        """
        Calculates core KPIs with central financial semantics:
        - Transfers excluded from Income & Expense.
        - Refunds offset Category Expense (never counted as income).
        - Calculations performed in exact integer minor units (cents).
        """
        prev_month = AnalyticsService._get_previous_month(month)

        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND account_id = ?" if account_id else ""
            params_curr = [f"{month}%"] + ([account_id] if account_id else [])
            params_prev = [f"{prev_month}%"] + ([account_id] if account_id else [])

            # 1. Current month totals by type (minor units)
            cur.execute(f"""
                SELECT 
                    transaction_type,
                    COALESCE(SUM(amount_minor), 0) as total_minor,
                    COUNT(id) as count
                FROM active_transactions
                WHERE transaction_date LIKE ? {acc_clause}
                GROUP BY transaction_type
            """, params_curr)
            curr_map = {row["transaction_type"]: row["total_minor"] for row in cur.fetchall()}

            # 2. Previous month totals by type
            cur.execute(f"""
                SELECT 
                    transaction_type,
                    COALESCE(SUM(amount_minor), 0) as total_minor
                FROM active_transactions
                WHERE transaction_date LIKE ? {acc_clause}
                GROUP BY transaction_type
            """, params_prev)
            prev_map = {row["transaction_type"]: row["total_minor"] for row in cur.fetchall()}

            # Central Financial Semantics:
            # Income = 'income'
            # Gross Expense = 'expense'
            # Net Expense = Gross Expense - 'refund'
            # Transfers are excluded!
            income_minor = curr_map.get("income", 0)
            gross_expense_minor = curr_map.get("expense", 0)
            refund_minor = curr_map.get("refund", 0)
            net_expense_minor = max(0, gross_expense_minor - refund_minor)
            net_flow_minor = income_minor - net_expense_minor

            prev_income_minor = prev_map.get("income", 0)
            prev_gross_expense_minor = prev_map.get("expense", 0)
            prev_refund_minor = prev_map.get("refund", 0)
            prev_net_expense_minor = max(0, prev_gross_expense_minor - prev_refund_minor)
            prev_net_flow_minor = prev_income_minor - prev_net_expense_minor

            savings_rate = (net_flow_minor / income_minor * 100.0) if income_minor > 0 else 0.0
            prev_savings_rate = (prev_net_flow_minor / prev_income_minor * 100.0) if prev_income_minor > 0 else 0.0

            income_delta_pct = ((income_minor - prev_income_minor) / prev_income_minor * 100.0) if prev_income_minor > 0 else 0.0
            expense_delta_pct = ((net_expense_minor - prev_net_expense_minor) / prev_net_expense_minor * 100.0) if prev_net_expense_minor > 0 else 0.0

            # Convert to standard decimal units for frontend
            income = round(income_minor / 100.0, 2)
            expense = round(net_expense_minor / 100.0, 2)
            net_flow = round(net_flow_minor / 100.0, 2)

            # Daily Cash Flow & Spending (excluding transfers)
            year, m_int = map(int, month.split("-"))
            num_days = calendar.monthrange(year, m_int)[1]
            all_days = [f"{month}-{d:02d}" for d in range(1, num_days + 1)]

            cur.execute(f"""
                SELECT 
                    transaction_date,
                    transaction_type,
                    SUM(amount_minor) as total_minor
                FROM active_transactions
                WHERE transaction_date LIKE ? {acc_clause}
                  AND transaction_type IN ('income', 'expense', 'refund')
                GROUP BY transaction_date, transaction_type
                ORDER BY transaction_date ASC
            """, params_curr)

            daily_income_map = {}
            daily_expense_map = {}
            for row in cur.fetchall():
                d = row["transaction_date"]
                t_type = row["transaction_type"]
                amt = row["total_minor"]
                if t_type == "income":
                    daily_income_map[d] = daily_income_map.get(d, 0) + amt
                elif t_type == "expense":
                    daily_expense_map[d] = daily_expense_map.get(d, 0) + amt
                elif t_type == "refund":
                    daily_expense_map[d] = daily_expense_map.get(d, 0) - amt

            trend_days = []
            trend_income = []
            trend_expense = []
            for d in all_days:
                day_label = d.split("-")[2]
                trend_days.append(day_label)
                trend_income.append(round(daily_income_map.get(d, 0) / 100.0, 2))
                trend_expense.append(round(max(0, daily_expense_map.get(d, 0)) / 100.0, 2))

            # Category Breakdown (net of refunds)
            cur.execute(f"""
                SELECT 
                    c.id,
                    c.name,
                    c.color,
                    c.icon,
                    SUM(
                        CASE 
                            WHEN t.transaction_type = 'expense' THEN t.amount_minor
                            WHEN t.transaction_type = 'refund' THEN -t.amount_minor
                            ELSE 0
                        END
                    ) as net_cat_minor,
                    COUNT(t.id) as count
                FROM active_transactions t
                JOIN categories c ON t.category_id = c.id
                WHERE t.transaction_type IN ('expense', 'refund')
                  AND t.transaction_date LIKE ? {acc_clause}
                GROUP BY c.id
                HAVING net_cat_minor > 0
                ORDER BY net_cat_minor DESC
            """, params_curr)

            categories_breakdown = []
            for row in cur.fetchall():
                cat_minor = row["net_cat_minor"]
                cat_total = round(cat_minor / 100.0, 2)
                pct = (cat_minor / net_expense_minor * 100.0) if net_expense_minor > 0 else 0.0
                categories_breakdown.append({
                    "id": row["id"],
                    "name": row["name"],
                    "color": row["color"],
                    "icon": row["icon"],
                    "amount": cat_total,
                    "percentage": round(pct, 1),
                    "count": row["count"]
                })

            # Essential vs Discretionary
            cur.execute(f"""
                SELECT 
                    essentiality,
                    SUM(
                        CASE 
                            WHEN transaction_type = 'expense' THEN amount_minor
                            WHEN transaction_type = 'refund' THEN -amount_minor
                            ELSE 0
                        END
                    ) as total_minor
                FROM active_transactions
                WHERE transaction_type IN ('expense', 'refund')
                  AND transaction_date LIKE ? {acc_clause}
                GROUP BY essentiality
            """, params_curr)
            ess_map = {row["essentiality"]: row["total_minor"] for row in cur.fetchall()}
            essential_minor = max(0, ess_map.get("essential", 0))
            discretionary_minor = max(0, ess_map.get("discretionary", 0))

            essential_total = round(essential_minor / 100.0, 2)
            discretionary_total = round(discretionary_minor / 100.0, 2)

            return {
                "month": month,
                "previous_month": prev_month,
                "kpis": {
                    "income": income,
                    "income_delta_pct": round(income_delta_pct, 1),
                    "expense": expense,
                    "expense_delta_pct": round(expense_delta_pct, 1),
                    "net_flow": net_flow,
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
                    "essential": essential_total,
                    "discretionary": discretionary_total,
                    "essential_pct": round(essential_minor / net_expense_minor * 100.0, 1) if net_expense_minor > 0 else 0.0,
                    "discretionary_pct": round(discretionary_minor / net_expense_minor * 100.0, 1) if net_expense_minor > 0 else 0.0
                }
            }

    @staticmethod
    def get_calendar_data(month: str, account_id: Optional[int] = None) -> Dict[str, Any]:
        """Returns daily sums of income, expense (net of refunds), and net flow."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND account_id = ?" if account_id else ""
            params = [f"{month}%"] + ([account_id] if account_id else [])

            cur.execute(f"""
                SELECT 
                    transaction_date,
                    transaction_type,
                    SUM(amount_minor) as total_minor,
                    COUNT(id) as count
                FROM active_transactions
                WHERE transaction_date LIKE ? {acc_clause}
                  AND transaction_type IN ('income', 'expense', 'refund')
                GROUP BY transaction_date, transaction_type
            """, params)

            days_data = {}
            for row in cur.fetchall():
                d = row["transaction_date"]
                if d not in days_data:
                    days_data[d] = {"income_minor": 0, "expense_minor": 0, "count": 0}
                t_type = row["transaction_type"]
                amt = row["total_minor"]
                if t_type == "income":
                    days_data[d]["income_minor"] += amt
                elif t_type == "expense":
                    days_data[d]["expense_minor"] += amt
                elif t_type == "refund":
                    days_data[d]["expense_minor"] -= amt
                days_data[d]["count"] += row["count"]

            out = {}
            for d, val in days_data.items():
                inc = round(val["income_minor"] / 100.0, 2)
                exp = round(max(0, val["expense_minor"]) / 100.0, 2)
                net = round((val["income_minor"] - val["expense_minor"]) / 100.0, 2)
                out[d] = {
                    "income": inc,
                    "expense": exp,
                    "net": net,
                    "count": val["count"]
                }

            return {
                "month": month,
                "days": out
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

            # 1. "What Changed?" Category Variance (net of refunds)
            cur.execute(f"""
                SELECT 
                    c.id,
                    c.name,
                    c.color,
                    COALESCE(
                        SUM(
                            CASE 
                                WHEN t.transaction_type = 'expense' THEN t.amount_minor
                                WHEN t.transaction_type = 'refund' THEN -t.amount_minor
                                ELSE 0
                            END
                        ), 0
                    ) as current_minor
                FROM categories c
                LEFT JOIN transactions t ON t.category_id = c.id 
                    AND t.transaction_type IN ('expense', 'refund')
                    AND t.transaction_date LIKE ? {acc_clause}
                WHERE c.type = 'expense' AND c.is_archived = 0
                GROUP BY c.id
            """, params_curr)
            curr_cats = {
                row["id"]: {"name": row["name"], "color": row["color"], "current_minor": row["current_minor"]}
                for row in cur.fetchall()
            }

            cur.execute(f"""
                SELECT 
                    c.id,
                    COALESCE(
                        SUM(
                            CASE 
                                WHEN t.transaction_type = 'expense' THEN t.amount_minor
                                WHEN t.transaction_type = 'refund' THEN -t.amount_minor
                                ELSE 0
                            END
                        ), 0
                    ) as prev_minor
                FROM categories c
                LEFT JOIN transactions t ON t.category_id = c.id 
                    AND t.transaction_type IN ('expense', 'refund')
                    AND t.transaction_date LIKE ? {acc_clause}
                WHERE c.type = 'expense' AND c.is_archived = 0
                GROUP BY c.id
            """, params_prev)
            for row in cur.fetchall():
                if row["id"] in curr_cats:
                    curr_cats[row["id"]]["prev_minor"] = row["prev_minor"]

            variance_items = []
            for cat_id, data in curr_cats.items():
                curr_val = round(max(0, data.get("current_minor", 0)) / 100.0, 2)
                prev_val = round(max(0, data.get("prev_minor", 0)) / 100.0, 2)
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

            variance_items.sort(key=lambda x: abs(x["delta"]), reverse=True)

            # 2. Weekday Distribution
            cur.execute(f"""
                SELECT 
                    transaction_date,
                    amount_minor
                FROM active_transactions
                WHERE transaction_type = 'expense'
                  AND transaction_date LIKE ? {acc_clause}
            """, params_curr)

            weekday_totals = [0] * 7
            weekday_counts = [0] * 7
            weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

            for row in cur.fetchall():
                dt = datetime.strptime(row["transaction_date"], "%Y-%m-%d")
                w = dt.weekday()
                weekday_totals[w] += row["amount_minor"]
                weekday_counts[w] += 1

            weekday_data = [
                {
                    "day": weekday_labels[i],
                    "total": round(weekday_totals[i] / 100.0, 2),
                    "average": round((weekday_totals[i] / weekday_counts[i]) / 100.0, 2) if weekday_counts[i] > 0 else 0.0,
                    "count": weekday_counts[i]
                }
                for i in range(7)
            ]

            # 3. Cumulative Spending Comparison
            year, m_int = map(int, month.split("-"))
            num_days = calendar.monthrange(year, m_int)[1]

            cur.execute(f"""
                SELECT 
                    transaction_date,
                    SUM(
                        CASE 
                            WHEN transaction_type = 'expense' THEN amount_minor
                            WHEN transaction_type = 'refund' THEN -amount_minor
                            ELSE 0
                        END
                    ) as day_minor
                FROM active_transactions
                WHERE transaction_type IN ('expense', 'refund') AND transaction_date LIKE ? {acc_clause}
                GROUP BY transaction_date
            """, params_curr)
            curr_day_spend = {int(row["transaction_date"].split("-")[2]): row["day_minor"] for row in cur.fetchall()}

            cur.execute(f"""
                SELECT 
                    transaction_date,
                    SUM(
                        CASE 
                            WHEN transaction_type = 'expense' THEN amount_minor
                            WHEN transaction_type = 'refund' THEN -amount_minor
                            ELSE 0
                        END
                    ) as day_minor
                FROM active_transactions
                WHERE transaction_type IN ('expense', 'refund') AND transaction_date LIKE ? {acc_clause}
                GROUP BY transaction_date
            """, params_prev)
            prev_day_spend = {int(row["transaction_date"].split("-")[2]): row["day_minor"] for row in cur.fetchall()}

            cum_days = []
            cum_curr = []
            cum_prev = []
            curr_running = 0
            prev_running = 0

            for d in range(1, num_days + 1):
                cum_days.append(str(d))
                curr_running += curr_day_spend.get(d, 0)
                prev_running += prev_day_spend.get(d, 0)
                cum_curr.append(round(max(0, curr_running) / 100.0, 2))
                cum_prev.append(round(max(0, prev_running) / 100.0, 2))

            # 4. Top Merchants (expense only)
            cur.execute(f"""
                SELECT 
                    merchant_name,
                    COUNT(id) as count,
                    SUM(amount_minor) as total_minor
                FROM active_transactions
                WHERE transaction_type = 'expense' 
                  AND merchant_name != '' 
                  AND transaction_date LIKE ? {acc_clause}
                GROUP BY merchant_name
                ORDER BY total_minor DESC
                LIMIT 8
            """, params_curr)

            top_merchants = [
                {
                    "merchant": row["merchant_name"],
                    "count": row["count"],
                    "total": round(row["total_minor"] / 100.0, 2)
                }
                for row in cur.fetchall()
            ]

            # 5. Transaction Distribution
            cur.execute(f"""
                SELECT amount_minor
                FROM active_transactions
                WHERE transaction_type = 'expense' AND transaction_date LIKE ? {acc_clause}
            """, params_curr)

            buckets = {"<$15": 0, "$15–$50": 0, "$50–$100": 0, "$100–$250": 0, ">$250": 0}
            for row in cur.fetchall():
                a = row["amount_minor"] / 100.0
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

    @staticmethod
    def get_analytics_context(
        month: Optional[str] = None,
        account_id: Optional[int] = None,
        category_id: Optional[int] = None,
        merchant_id: Optional[int] = None,
        comparison_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """Resolves canonical temporal context and comparison period."""
        from app.backend.analytics.context import resolve_analytics_context
        ctx = resolve_analytics_context(
            month=month,
            account_id=account_id,
            category_id=category_id,
            merchant_id=merchant_id,
            comparison_mode=comparison_mode
        )
        return ctx.to_dict()

    @staticmethod
    def get_rolling_metrics(
        metric: str = "expense",
        category_id: Optional[int] = None,
        account_id: Optional[int] = None,
        as_of_month: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calculates 3M, 6M, 12M Mean, Median, MAD, and EWMA historical baselines
        using zero-filled calendar month series (missing months treated as $0).
        """
        from app.backend.analytics.period_series import calendar_month_series, check_data_sufficiency

        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND account_id = ?" if account_id else ""
            acc_params = [account_id] if account_id else []

            # 1. Fetch earliest and latest month
            cur.execute(f"""
                SELECT MIN(transaction_date) as min_d, MAX(transaction_date) as max_d
                FROM active_transactions
                WHERE transaction_type IN ('income', 'expense', 'refund') {acc_clause}
            """, acc_params)
            row = cur.fetchone()
            if not row or not row["min_d"]:
                suff = check_data_sufficiency("rolling_3m", 0, 0)
                return {
                    "available": False,
                    "data_sufficiency": suff.to_dict(),
                    "current": 0.0,
                    "mean_3": 0.0, "median_3": 0.0,
                    "mean_6": 0.0, "median_6": 0.0,
                    "mean_12": 0.0, "ewma_3": 0.0, "mad_6": 0.0,
                    "sample_size_months": 0
                }

            earliest_m = row["min_d"][:7]
            end_m = as_of_month or row["max_d"][:7]

            if category_id:
                cur.execute(f"""
                    SELECT 
                        strftime('%Y-%m', transaction_date) as m,
                        SUM(
                            CASE 
                                WHEN transaction_type = 'expense' THEN amount_minor
                                WHEN transaction_type = 'refund' THEN -amount_minor
                                ELSE 0
                            END
                        ) as net_minor
                    FROM active_transactions
                    WHERE category_id = ?
                      AND transaction_type IN ('expense', 'refund')
                      AND strftime('%Y-%m', transaction_date) <= ? {acc_clause}
                    GROUP BY m
                    ORDER BY m ASC
                """, [category_id, end_m] + acc_params)
                raw_dict = {r["m"]: max(0, r["net_minor"]) for r in cur.fetchall()}
            else:
                t_filter = "transaction_type = 'income'" if metric == "income" else "transaction_type IN ('expense', 'refund')"
                cur.execute(f"""
                    SELECT 
                        strftime('%Y-%m', transaction_date) as m,
                        SUM(
                            CASE 
                                WHEN transaction_type = 'income' THEN amount_minor
                                WHEN transaction_type = 'expense' THEN amount_minor
                                WHEN transaction_type = 'refund' THEN -amount_minor
                                ELSE 0
                            END
                        ) as net_minor
                    FROM active_transactions
                    WHERE {t_filter}
                      AND strftime('%Y-%m', transaction_date) <= ? {acc_clause}
                    GROUP BY m
                    ORDER BY m ASC
                """, [end_m] + acc_params)
                raw_dict = {r["m"]: max(0, r["net_minor"]) for r in cur.fetchall()}

            # Zero-fill series from earliest recorded month to end_m
            series_objs = calendar_month_series(
                start_month=earliest_m,
                end_month=end_m,
                raw_dict=raw_dict,
                earliest_recorded_month=earliest_m
            )
            values = [s.value_minor for s in series_objs]

            if not values:
                suff = check_data_sufficiency("rolling_3m", 0, 0)
                return {
                    "available": False,
                    "data_sufficiency": suff.to_dict(),
                    "current": 0.0,
                    "mean_3": 0.0, "median_3": 0.0,
                    "mean_6": 0.0, "median_6": 0.0,
                    "mean_12": 0.0, "ewma_3": 0.0, "mad_6": 0.0,
                    "sample_size_months": 0
                }

            curr_val = values[-1]
            hist = values[:-1]
            base_metrics = RollingAnalyticsEngine.compute_rolling_baselines(hist, curr_val)
            suff = check_data_sufficiency("rolling_3m", len(hist), len(hist))

            base_metrics["data_sufficiency"] = suff.to_dict()
            base_metrics["available"] = (len(hist) >= 1)
            base_metrics["zero_filled_series"] = [s.to_dict() for s in series_objs[-12:]]
            return base_metrics

    @staticmethod
    def get_what_changed(
        current_month: str,
        comparison_month: Optional[str] = None,
        account_id: Optional[int] = None,
        max_day: Optional[int] = None,
        comparison_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """Provides What Changed? v2.1 frequency, ticket, and refund decomposition."""
        from app.backend.analytics.context import resolve_analytics_context
        ctx = resolve_analytics_context(
            month=current_month,
            account_id=account_id,
            comparison_mode=comparison_mode
        )
        return WhatChangedEngine.analyze_changes(current_month, comparison_month, account_id, max_day, context=ctx)

    @staticmethod
    def get_merchant_drilldown(
        category_id: int,
        current_month: Optional[str] = None,
        account_id: Optional[int] = None,
        comparison_mode: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Drills down into merchants within a specific category to show drivers of change."""
        from app.backend.analytics.context import resolve_analytics_context
        ctx = resolve_analytics_context(
            month=current_month,
            account_id=account_id,
            category_id=category_id,
            comparison_mode=comparison_mode
        )
        return WhatChangedEngine.get_merchant_drilldown(category_id, current_month, account_id, context=ctx)

    @staticmethod
    def get_spending_fingerprint(
        months_window: int = 6,
        account_id: Optional[int] = None,
        as_of_month: Optional[str] = None
    ) -> Dict[str, Any]:
        """Computes spending fingerprint, percentiles, rhythm, diversity, and weekday spend."""
        return SpendingFingerprintEngine.generate_fingerprint(months_window, account_id, as_of_month=as_of_month)

    @staticmethod
    def get_anomalies(
        month: str,
        account_id: Optional[int] = None,
        k_range: float = 2.5
    ) -> List[Dict[str, Any]]:
        """Detects unusual transactions, category overruns, and recurring payment jumps."""
        from app.backend.analytics.context import resolve_analytics_context
        ctx = resolve_analytics_context(month=month, account_id=account_id)
        return AnomalyDetectionEngine.detect_anomalies(month, account_id, k_range, context=ctx)

    @staticmethod
    def get_normal_ranges(
        account_id: Optional[int] = None,
        as_of_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Computes typical normal ranges for all categories."""
        return AnomalyDetectionEngine.get_category_normal_ranges(account_id, as_of_date)

    @staticmethod
    def get_forecast(
        month: str,
        account_id: Optional[int] = None,
        as_of_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generates transparent, explainable month-end forecast with budget comparison."""
        from app.backend.analytics.context import resolve_analytics_context
        ctx = resolve_analytics_context(month=month, account_id=account_id)
        return ForecastingEngine.forecast_month(month, account_id, as_of_date, context=ctx)

    @staticmethod
    def get_ranked_insights(
        month: str,
        account_id: Optional[int] = None,
        limit: int = 5
    ) -> Dict[str, Any]:
        """Synthesizes insights across all analytics modules and ranks them by absolute impact & unusualness."""
        from app.backend.analytics.context import resolve_analytics_context
        ctx = resolve_analytics_context(month=month, account_id=account_id)

        changes = WhatChangedEngine.analyze_changes(month, context=ctx)
        anomalies = AnomalyDetectionEngine.detect_anomalies(month, account_id, context=ctx)
        forecast = ForecastingEngine.forecast_month(month, account_id, context=ctx)

        candidates = InsightRulesGenerator.generate_candidates(changes, anomalies, forecast, month)
        ranked = InsightRanker.rank_and_deduplicate(candidates, limit=limit, month=month, persist=True)
        return {
            "month": month,
            "context": ctx.to_dict(),
            "insights": ranked,
            "total_candidates": len(candidates)
        }

    @staticmethod
    def dismiss_insight(insight_key: str) -> bool:
        """Dismisses an insight so it will not reappear."""
        from app.backend.analytics.insight_history import InsightHistoryTracker
        return InsightHistoryTracker.dismiss_insight(insight_key)

    @staticmethod
    def get_backtest_evaluation(account_id: Optional[int] = None) -> Dict[str, Any]:
        """Evaluates historical forecasting baselines using rolling-origin backtesting."""
        history = AggregateQueries.get_monthly_history(limit_months=24, account_id=account_id)
        series = [d["net_spending_minor"] for d in history]
        return BacktestingEngine.evaluate_models(series)
