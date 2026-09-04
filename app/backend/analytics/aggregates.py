"""
Canonical Aggregation Layer for FinScope Analytics.
Queries database to compute exact integer minor unit summaries across
periods, categories, merchants, and time dimensions.
"""

from typing import Dict, Any, List, Optional, Tuple
from app.backend.database.connection import get_db_connection
from app.backend.analytics.semantics import calculate_net_spending

class AggregateQueries:
    @staticmethod
    def get_monthly_pnl(month: str, account_id: Optional[int] = None) -> Dict[str, int]:
        """Returns exact integer minor units for income, gross expense, refunds, net spending, and net flow."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND account_id = ?" if account_id else ""
            params = [f"{month}%"] + ([account_id] if account_id else [])

            cur.execute(f"""
                SELECT 
                    transaction_type,
                    COALESCE(SUM(amount_minor), 0) as total_minor,
                    COUNT(id) as count
                FROM active_transactions
                WHERE transaction_date LIKE ? {acc_clause}
                GROUP BY transaction_type
            """, params)

            totals = {row["transaction_type"]: row["total_minor"] for row in cur.fetchall()}
            income = totals.get("income", 0)
            gross_expense = totals.get("expense", 0)
            refund = totals.get("refund", 0)
            net_spending = calculate_net_spending(gross_expense, refund)
            net_flow = income - net_spending

            return {
                "income_minor": income,
                "gross_expense_minor": gross_expense,
                "refund_minor": refund,
                "net_spending_minor": net_spending,
                "net_flow_minor": net_flow
            }

    @staticmethod
    def get_monthly_history(limit_months: int = 24, account_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns chronologically sorted monthly summaries in minor units."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND account_id = ?" if account_id else ""
            params = [account_id] if account_id else []

            cur.execute(f"""
                SELECT 
                    strftime('%Y-%m', transaction_date) as month,
                    transaction_type,
                    COALESCE(SUM(amount_minor), 0) as total_minor,
                    COUNT(id) as count
                FROM active_transactions
                WHERE transaction_type IN ('income', 'expense', 'refund') {acc_clause}
                GROUP BY month, transaction_type
                ORDER BY month ASC
            """, params)

            months_map: Dict[str, Dict[str, int]] = {}
            for row in cur.fetchall():
                m = row["month"]
                if not m:
                    continue
                if m not in months_map:
                    months_map[m] = {"income": 0, "expense": 0, "refund": 0, "count": 0}
                t_type = row["transaction_type"]
                months_map[m][t_type] = row["total_minor"]
                months_map[m]["count"] += row["count"]

            sorted_months = sorted(months_map.keys())
            if limit_months and len(sorted_months) > limit_months:
                sorted_months = sorted_months[-limit_months:]

            res = []
            for m in sorted_months:
                data = months_map[m]
                net_exp = calculate_net_spending(data["expense"], data["refund"])
                res.append({
                    "month": m,
                    "income_minor": data["income"],
                    "gross_expense_minor": data["expense"],
                    "refund_minor": data["refund"],
                    "net_spending_minor": net_exp,
                    "net_flow_minor": data["income"] - net_exp,
                    "transaction_count": data["count"]
                })
            return res

    @staticmethod
    def get_category_monthly_series(category_id: int, account_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns monthly net expense for a specific category."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND account_id = ?" if account_id else ""
            params = [category_id] + ([account_id] if account_id else [])

            cur.execute(f"""
                SELECT 
                    strftime('%Y-%m', transaction_date) as month,
                    transaction_type,
                    COALESCE(SUM(amount_minor), 0) as total_minor,
                    COUNT(id) as count
                FROM active_transactions
                WHERE category_id = ?
                  AND transaction_type IN ('expense', 'refund') {acc_clause}
                GROUP BY month, transaction_type
                ORDER BY month ASC
            """, params)

            month_data: Dict[str, Dict[str, int]] = {}
            for row in cur.fetchall():
                m = row["month"]
                if not m:
                    continue
                if m not in month_data:
                    month_data[m] = {"expense": 0, "refund": 0, "count": 0}
                t_type = row["transaction_type"]
                month_data[m][t_type] = row["total_minor"]
                month_data[m]["count"] += row["count"]

            res = []
            for m in sorted(month_data.keys()):
                d = month_data[m]
                net = calculate_net_spending(d["expense"], d["refund"])
                res.append({
                    "month": m,
                    "net_spending_minor": net,
                    "count": d["count"]
                })
            return res

    @staticmethod
    def get_categories_breakdown(month: str, account_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns all expense categories with net spending, transaction count, and average ticket."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND t.account_id = ?" if account_id else ""
            params = [f"{month}%"] + ([account_id] if account_id else [])

            cur.execute(f"""
                SELECT 
                    c.id,
                    c.name,
                    c.color,
                    c.icon,
                    c.essentiality,
                    SUM(
                        CASE 
                            WHEN t.transaction_type = 'expense' THEN t.amount_minor
                            WHEN t.transaction_type = 'refund' THEN -t.amount_minor
                            ELSE 0
                        END
                    ) as net_minor,
                    SUM(CASE WHEN t.transaction_type = 'expense' THEN 1 ELSE 0 END) as tx_count
                FROM categories c
                JOIN active_transactions t ON t.category_id = c.id
                WHERE t.transaction_type IN ('expense', 'refund')
                  AND t.transaction_date LIKE ? {acc_clause}
                GROUP BY c.id
                ORDER BY net_minor DESC
            """, params)

            items = []
            for row in cur.fetchall():
                net = max(0, row["net_minor"])
                cnt = row["tx_count"]
                avg_ticket = (net // cnt) if cnt > 0 else 0
                items.append({
                    "id": row["id"],
                    "name": row["name"],
                    "color": row["color"],
                    "icon": row["icon"],
                    "essentiality": row["essentiality"] or "discretionary",
                    "net_minor": net,
                    "count": cnt,
                    "avg_ticket_minor": avg_ticket
                })
            return items

    @staticmethod
    def get_merchants_breakdown(month: str, category_id: Optional[int] = None, account_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns merchants breakdown for a given month, optionally filtered by category."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            clauses = ["t.transaction_type IN ('expense', 'refund')", "t.transaction_date LIKE ?"]
            params: List[Any] = [f"{month}%"]

            if category_id:
                clauses.append("t.category_id = ?")
                params.append(category_id)
            if account_id:
                clauses.append("t.account_id = ?")
                params.append(account_id)

            where_sql = " AND ".join(clauses)

            cur.execute(f"""
                SELECT 
                    COALESCE(NULLIF(t.merchant_name, ''), 'Unspecified') as merchant,
                    SUM(
                        CASE 
                            WHEN t.transaction_type = 'expense' THEN t.amount_minor
                            WHEN t.transaction_type = 'refund' THEN -t.amount_minor
                            ELSE 0
                        END
                    ) as net_minor,
                    SUM(CASE WHEN t.transaction_type = 'expense' THEN 1 ELSE 0 END) as tx_count
                FROM active_transactions t
                WHERE {where_sql}
                GROUP BY merchant
                ORDER BY net_minor DESC
            """, params)

            items = []
            for row in cur.fetchall():
                net = max(0, row["net_minor"])
                cnt = row["tx_count"]
                items.append({
                    "merchant": row["merchant"],
                    "net_minor": net,
                    "count": cnt,
                    "avg_ticket_minor": (net // cnt) if cnt > 0 else 0
                })
            return items
