"""
Spending Fingerprint Analytics Engine for FinScope.
Produces objective behavioural metrics describing the user's spending structure:
- Typical Transaction Percentiles (Median, P75, P90, Max)
- Robust Spending Variability (MAD / Median)
- Weekend Concentration (Weekend / Discretionary Spend)
- Recurring & Essential Ratios
- Category Diversity Score (Normalized Shannon Entropy)
- Merchant Concentration
- Burstiness / Rhythm (Inter-event time CV ratio: B = (r-1)/(r+1))
- Category Persistence (Monthly cosine vector similarity)
"""

import math
from datetime import datetime
from typing import Dict, Any, List, Optional
from app.backend.database.connection import get_db_connection
from app.backend.analytics.rolling import calculate_median, calculate_mean, calculate_mad
from app.backend.analytics.models import FingerprintResult

def calculate_percentile(sorted_values: List[int], p: float) -> int:
    """Calculates the p-th percentile (0.0 to 1.0) from a sorted list of ints."""
    if not sorted_values:
        return 0
    k = (len(sorted_values) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    d0 = sorted_values[int(f)] * (c - k)
    d1 = sorted_values[int(c)] * (k - f)
    return round(d0 + d1)

def calculate_shannon_diversity(proportions: List[float]) -> int:
    """Normalized entropy H / log(K) mapped to 0-100 scale."""
    valid_p = [p for p in proportions if p > 0.0]
    k = len(valid_p)
    if k <= 1:
        return 0
    h = -sum(p * math.log(p) for p in valid_p)
    max_h = math.log(k)
    normalized = h / max_h if max_h > 0 else 0.0
    return round(normalized * 100)

def calculate_cosine_similarity(vec_a: Dict[int, int], vec_b: Dict[int, int]) -> float:
    """Cosine similarity between two category spending vectors."""
    all_keys = set(vec_a.keys()).union(set(vec_b.keys()))
    if not all_keys:
        return 1.0
    dot_product = sum(vec_a.get(k, 0) * vec_b.get(k, 0) for k in all_keys)
    norm_a = math.sqrt(sum(val ** 2 for val in vec_a.values()))
    norm_b = math.sqrt(sum(val ** 2 for val in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return round(dot_product / (norm_a * norm_b), 3)

class SpendingFingerprintEngine:
    @staticmethod
    def generate_fingerprint(months_window: int = 6, account_id: Optional[int] = None) -> Dict[str, Any]:
        """Calculates spending fingerprint for the last N months."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND account_id = ?" if account_id else ""
            params: List[Any] = [account_id] if account_id else []

            # 1. Fetch distinct recent months
            cur.execute(f"""
                SELECT DISTINCT strftime('%Y-%m', transaction_date) as m
                FROM transactions
                WHERE transaction_type IN ('expense', 'refund') {acc_clause}
                ORDER BY m DESC
                LIMIT ?
            """, params + [months_window])
            recent_months = [row["m"] for row in cur.fetchall()]
            if not recent_months:
                return {"error": "Insufficient transaction history for fingerprint", "sample_months": 0}

            recent_months.sort()
            start_month = recent_months[0]
            end_month = recent_months[-1]

            # 2. Fetch all individual expense transactions in window
            cur.execute(f"""
                SELECT 
                    id,
                    transaction_date,
                    transaction_time,
                    amount_minor,
                    category_id,
                    merchant_name,
                    essentiality,
                    is_recurring
                FROM transactions
                WHERE transaction_type = 'expense'
                  AND transaction_date >= ? AND transaction_date <= ? || '-31' {acc_clause}
                ORDER BY transaction_date ASC, transaction_time ASC
            """, [start_month, end_month] + params)

            tx_rows = cur.fetchall()
            tx_count = len(tx_rows)
            if tx_count == 0:
                return {"error": "No expense transactions in selected window", "sample_months": len(recent_months)}

            amounts = sorted([row["amount_minor"] for row in tx_rows])
            median_amt = calculate_median(amounts)
            mean_amt = calculate_mean(amounts)
            p75_amt = calculate_percentile(amounts, 0.75)
            p90_amt = calculate_percentile(amounts, 0.90)
            max_amt = amounts[-1] if amounts else 0

            # Variability (MAD / median)
            mad_amt = calculate_mad(amounts)
            variability = (mad_amt / median_amt) if median_amt > 0 else 0.0

            # Weekend Concentration & Essentiality & Recurring
            total_spend_minor = sum(amounts)
            weekend_spend_minor = 0
            discretionary_spend_minor = 0
            weekend_discretionary_spend_minor = 0
            essential_spend_minor = 0
            recurring_spend_minor = 0
            weekday_spending = [0] * 7
            weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

            for row in tx_rows:
                dt = datetime.strptime(row["transaction_date"], "%Y-%m-%d")
                w = dt.weekday()
                weekday_spending[w] += row["amount_minor"]
                amt = row["amount_minor"]
                is_weekend = (w >= 5)  # Sat=5, Sun=6

                if is_weekend:
                    weekend_spend_minor += amt
                if row["essentiality"] == "essential":
                    essential_spend_minor += amt
                else:
                    discretionary_spend_minor += amt
                    if is_weekend:
                        weekend_discretionary_spend_minor += amt
                if row["is_recurring"]:
                    recurring_spend_minor += amt

            weekend_ratio = (weekend_discretionary_spend_minor / discretionary_spend_minor) if discretionary_spend_minor > 0 else (weekend_spend_minor / total_spend_minor if total_spend_minor > 0 else 0.0)
            essential_ratio = (essential_spend_minor / total_spend_minor) if total_spend_minor > 0 else 0.0
            recurring_ratio = (recurring_spend_minor / total_spend_minor) if total_spend_minor > 0 else 0.0

            most_active_wday_idx = weekday_spending.index(max(weekday_spending))
            most_active_wday = weekday_names[most_active_wday_idx]

            # Category Diversity (Shannon Entropy)
            cat_totals: Dict[int, int] = {}
            for row in tx_rows:
                cid = row["category_id"] or 0
                cat_totals[cid] = cat_totals.get(cid, 0) + row["amount_minor"]

            proportions = [(amt / total_spend_minor) for amt in cat_totals.values()] if total_spend_minor > 0 else []
            diversity_score = calculate_shannon_diversity(proportions)

            # Top Merchants Share
            merchant_totals: Dict[str, int] = {}
            for row in tx_rows:
                m_name = row["merchant_name"] or "Unknown"
                merchant_totals[m_name] = merchant_totals.get(m_name, 0) + row["amount_minor"]

            sorted_merchants = sorted(merchant_totals.values(), reverse=True)
            top_merchants_share = (sum(sorted_merchants[:3]) / total_spend_minor) if total_spend_minor > 0 else 0.0

            # Burstiness B = (r - 1) / (r + 1) where r = std(dt) / mean(dt)
            # dt is difference in hours between transactions
            dt_hours = []
            for i in range(1, len(tx_rows)):
                t_prev = datetime.strptime(f"{tx_rows[i-1]['transaction_date']} {tx_rows[i-1]['transaction_time'] or '12:00'}", "%Y-%m-%d %H:%M")
                t_curr = datetime.strptime(f"{tx_rows[i]['transaction_date']} {tx_rows[i]['transaction_time'] or '12:00'}", "%Y-%m-%d %H:%M")
                delta_h = max(0.1, (t_curr - t_prev).total_seconds() / 3600.0)
                dt_hours.append(delta_h)

            if len(dt_hours) >= 5:
                mean_dt = sum(dt_hours) / len(dt_hours)
                var_dt = sum((x - mean_dt) ** 2 for x in dt_hours) / (len(dt_hours) - 1)
                std_dt = math.sqrt(var_dt)
                r = (std_dt / mean_dt) if mean_dt > 0 else 1.0
                burstiness = (r - 1.0) / (r + 1.0)
            else:
                burstiness = 0.0

            # Category Persistence: Average cosine similarity across consecutive months
            cur.execute(f"""
                SELECT 
                    strftime('%Y-%m', transaction_date) as m,
                    category_id,
                    SUM(amount_minor) as total_minor
                FROM transactions
                WHERE transaction_type = 'expense'
                  AND transaction_date >= ? AND transaction_date <= ? || '-31' {acc_clause}
                GROUP BY m, category_id
            """, [start_month, end_month] + params)

            monthly_cat_vectors: Dict[str, Dict[int, int]] = {}
            for row in cur.fetchall():
                m = row["m"]
                cid = row["category_id"] or 0
                if m not in monthly_cat_vectors:
                    monthly_cat_vectors[m] = {}
                monthly_cat_vectors[m][cid] = row["total_minor"]

            ordered_m = sorted(monthly_cat_vectors.keys())
            sims = []
            for i in range(1, len(ordered_m)):
                sim = calculate_cosine_similarity(monthly_cat_vectors[ordered_m[i-1]], monthly_cat_vectors[ordered_m[i]])
                sims.append(sim)
            persistence_score = (sum(sims) / len(sims)) if sims else 1.0
            consistency_score = round(persistence_score * 100)

            # Category variability identification
            cur.execute("""
                SELECT id, name FROM categories WHERE type = 'expense'
            """)
            cat_names = {row["id"]: row["name"] for row in cur.fetchall()}

            most_var_cat = "Variable Spending"
            most_stable_cat = "Housing & Rent"
            if len(ordered_m) >= 3:
                cat_spreads = {}
                for cid, cname in cat_names.items():
                    vals = [monthly_cat_vectors.get(m, {}).get(cid, 0) for m in ordered_m]
                    if any(v > 0 for v in vals):
                        med = calculate_median(vals)
                        mad = calculate_mad(vals)
                        cat_spreads[cname] = (mad / med) if med > 0 else 0.0
                if cat_spreads:
                    sorted_spreads = sorted(cat_spreads.items(), key=lambda x: x[1], reverse=True)
                    most_var_cat = sorted_spreads[0][0]
                    most_stable_cat = sorted_spreads[-1][0]

            fp = FingerprintResult(
                period_label=f"{start_month} to {end_month}",
                sample_months=len(recent_months),
                transaction_count=tx_count,
                median_transaction_minor=median_amt,
                mean_transaction_minor=mean_amt,
                p75_transaction_minor=p75_amt,
                p90_transaction_minor=p90_amt,
                largest_transaction_minor=max_amt,
                spending_variability=variability,
                weekend_concentration=weekend_ratio,
                recurring_expense_ratio=recurring_ratio,
                essential_ratio=essential_ratio,
                category_diversity_score=diversity_score,
                spending_consistency_score=consistency_score,
                burstiness_score=burstiness,
                category_persistence_score=persistence_score,
                most_active_weekday=most_active_wday,
                most_variable_category=most_var_cat,
                most_stable_category=most_stable_cat,
                top_merchants_share=top_merchants_share,
                metadata={
                    "start_month": start_month,
                    "end_month": end_month,
                    "months": recent_months
                }
            )
            return fp.to_dict()
