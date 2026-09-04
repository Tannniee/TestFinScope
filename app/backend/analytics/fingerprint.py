"""
Spending Fingerprint Analytics Engine V2 for FinScope.
Produces objective behavioural metrics describing the user's spending structure:
- Typical Transaction Percentiles (Median, P75, P90, Max)
- Robust Spending Variability (MAD / Median)
- Disambiguated Weekday Metrics:
    * Average Transaction Size by Weekday: total spend on weekday / tx count
    * Average Daily Spend by Weekday: total spend on weekday / calendar occurrences of weekday
- Weekend Concentration (Weekend / Discretionary Spend)
- Recurring & Essential Ratios
- Category Diversity Score (Normalized Shannon Entropy)
- Merchant Concentration
- Burstiness / Rhythm (Inter-event time CV ratio: B = (r-1)/(r+1))
- Category Persistence (Monthly cosine vector similarity with sample guard)
- Data Sufficiency Evaluation avoiding fake certainty on sparse data
"""

import math
import calendar
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
from app.backend.database.connection import get_db_connection
from app.backend.analytics.rolling import calculate_median, calculate_mean, calculate_mad
from app.backend.analytics.models import FingerprintResult
from app.backend.analytics.period_series import check_data_sufficiency

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

def count_weekday_occurrences_in_range(start_date: date, end_date: date) -> List[int]:
    """Counts actual occurrences of Monday(0)..Sunday(6) between two dates."""
    counts = [0] * 7
    cur = start_date
    while cur <= end_date:
        counts[cur.weekday()] += 1
        cur += timedelta(days=1)
    return counts

class SpendingFingerprintEngine:
    @staticmethod
    def generate_fingerprint(
        months_window: int = 6,
        account_id: Optional[int] = None,
        as_of_month: Optional[str] = None
    ) -> Dict[str, Any]:
        """Calculates spending fingerprint for the last N months up to as_of_month."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND account_id = ?" if account_id else ""
            acc_params: List[Any] = [account_id] if account_id else []

            # 1. Fetch distinct recent months up to as_of_month
            month_clause = " AND strftime('%Y-%m', transaction_date) <= ?" if as_of_month else ""
            m_params = ([as_of_month] if as_of_month else []) + acc_params

            cur.execute(f"""
                SELECT DISTINCT strftime('%Y-%m', transaction_date) as m
                FROM active_transactions
                WHERE transaction_type IN ('expense', 'refund') {month_clause} {acc_clause}
                ORDER BY m DESC
                LIMIT ?
            """, m_params + [months_window])
            recent_months = [row["m"] for row in cur.fetchall()]

            if not recent_months:
                sufficiency = check_data_sufficiency("fingerprint", 0, 0)
                return {
                    "available": False,
                    "data_sufficiency": sufficiency.to_dict(),
                    "period_label": "No data",
                    "sample_months": 0,
                    "transaction_count": 0
                }

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
                FROM active_transactions
                WHERE transaction_type = 'expense'
                  AND transaction_date >= ? AND transaction_date <= ? || '-31' {acc_clause}
                ORDER BY transaction_date ASC, transaction_time ASC
            """, [start_month, end_month] + acc_params)

            tx_rows = cur.fetchall()
            tx_count = len(tx_rows)
            sufficiency = check_data_sufficiency("fingerprint", tx_count, len(recent_months))

            if tx_count == 0:
                return {
                    "available": False,
                    "data_sufficiency": sufficiency.to_dict(),
                    "period_label": f"{start_month} to {end_month}",
                    "sample_months": len(recent_months),
                    "transaction_count": 0
                }

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

            weekday_spend_totals = [0] * 7
            weekday_tx_counts = [0] * 7
            daily_spend_map: Dict[str, int] = {}
            weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

            for row in tx_rows:
                t_date_str = row["transaction_date"]
                dt = datetime.strptime(t_date_str, "%Y-%m-%d")
                w = dt.weekday()
                amt = row["amount_minor"]

                weekday_spend_totals[w] += amt
                weekday_tx_counts[w] += 1
                daily_spend_map[t_date_str] = daily_spend_map.get(t_date_str, 0) + amt

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

            # 3. Disambiguate:
            # (A) Average Transaction Size by Weekday: total spend / tx count
            # (B) Average Daily Spend by Weekday: total spend / calendar weekday occurrences
            sy, sm = map(int, start_month.split("-"))
            ey, em = map(int, end_month.split("-"))
            end_days = calendar.monthrange(ey, em)[1]
            cal_start = date(sy, sm, 1)
            cal_end = date(ey, em, end_days)
            wday_cal_occurrences = count_weekday_occurrences_in_range(cal_start, cal_end)

            weekday_breakdown = []
            for w in range(7):
                tot = weekday_spend_totals[w]
                cnt = weekday_tx_counts[w]
                occ = max(1, wday_cal_occurrences[w])
                avg_tx_size = (tot / cnt) if cnt > 0 else 0
                avg_daily_spend = (tot / occ)

                weekday_breakdown.append({
                    "day_index": w,
                    "day_name": weekday_names[w],
                    "total_spend": round(tot / 100.0, 2),
                    "transaction_count": cnt,
                    "calendar_occurrences": occ,
                    "avg_transaction_size": round(avg_tx_size / 100.0, 2),
                    "avg_daily_spend": round(avg_daily_spend / 100.0, 2)
                })

            weekend_ratio = (weekend_discretionary_spend_minor / discretionary_spend_minor) if discretionary_spend_minor > 0 else (weekend_spend_minor / total_spend_minor if total_spend_minor > 0 else 0.0)
            essential_ratio = (essential_spend_minor / total_spend_minor) if total_spend_minor > 0 else 0.0
            recurring_ratio = (recurring_spend_minor / total_spend_minor) if total_spend_minor > 0 else 0.0

            # Find day with highest daily spend
            highest_daily_wday_idx = max(range(7), key=lambda w: weekday_spend_totals[w] / max(1, wday_cal_occurrences[w]))
            most_active_wday = weekday_names[highest_daily_wday_idx]

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
                FROM active_transactions
                WHERE transaction_type = 'expense'
                  AND transaction_date >= ? AND transaction_date <= ? || '-31' {acc_clause}
                GROUP BY m, category_id
            """, [start_month, end_month] + acc_params)

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
                    "months": recent_months,
                    "data_sufficiency": sufficiency.to_dict(),
                    "weekday_breakdown": weekday_breakdown
                }
            )
            out = fp.to_dict()
            out["available"] = True
            out["data_sufficiency"] = sufficiency.to_dict()
            out["weekday_breakdown"] = weekday_breakdown
            return out
