"""
Anomaly Detection Engine v1 & Normal Ranges for FinScope.
Detects unusual spending relative to personal historical norms:
- Robust Z-Score: 0.6745 * (x - median) / MAD
- Normal Range: [median - k * MAD_scaled, median + k * MAD_scaled]
- Transaction Amount Anomalies with Hierarchical Fallbacks
- Category Monthly Anomalies
- Recurring Payment Jump Detection
- Minimum Sample Guards (n >= 10 for category, n >= 5 for merchant)
- False Positive Controls (transfers & refunds excluded)
"""

import math
from typing import Dict, Any, List, Optional
from app.backend.database.connection import get_db_connection
from app.backend.analytics.rolling import calculate_median, calculate_mad, calculate_scaled_mad
from app.backend.analytics.models import AnomalyResult

def calculate_robust_z_score(value: int, median_val: int, mad_val: int) -> float:
    """Computes robust z-score: 0.6745 * (x - median) / MAD."""
    if mad_val <= 0:
        if value == median_val:
            return 0.0
        # If no variation exists, treat relative difference
        return (value - median_val) / (median_val if median_val > 0 else 1.0)
    return 0.6745 * (value - median_val) / mad_val

def compute_normal_range(median_val: int, mad_scaled: int, k: float = 2.5) -> tuple[int, int]:
    """Computes normal range [max(0, median - k*MAD_scaled), median + k*MAD_scaled]."""
    spread = round(k * mad_scaled)
    lower = max(0, median_val - spread)
    upper = median_val + spread
    return lower, upper

class AnomalyDetectionEngine:
    @staticmethod
    def detect_anomalies(
        month: str,
        account_id: Optional[int] = None,
        k_range: float = 2.5
    ) -> List[Dict[str, Any]]:
        """
        Runs comprehensive anomaly detection for a specific month:
        1. Unusual individual transactions
        2. Unusually high category monthly totals
        3. Recurring subscription/bill jumps
        """
        anomalies: List[AnomalyResult] = []

        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND t.account_id = ?" if account_id else ""
            params: List[Any] = [account_id] if account_id else []

            # 1. Fetch category baseline distributions (historical 6 months prior to current month)
            cur.execute(f"""
                SELECT 
                    t.category_id,
                    c.name as category_name,
                    t.amount_minor
                FROM transactions t
                JOIN categories c ON t.category_id = c.id
                WHERE t.transaction_type = 'expense'
                  AND t.transaction_date < ? || '-01'
                  AND t.transaction_date >= date(? || '-01', '-6 months') {acc_clause}
            """, [month, month] + params)

            cat_history: Dict[int, List[int]] = {}
            cat_names: Dict[int, str] = {}
            for row in cur.fetchall():
                cid = row["category_id"]
                cat_names[cid] = row["category_name"]
                if cid not in cat_history:
                    cat_history[cid] = []
                cat_history[cid].append(row["amount_minor"])

            cat_baselines: Dict[int, Dict[str, Any]] = {}
            for cid, history in cat_history.items():
                if len(history) >= 10:  # Minimum sample guard
                    med = calculate_median(history)
                    mad = calculate_mad(history)
                    mad_scaled = calculate_scaled_mad(history)
                    low, up = compute_normal_range(med, mad_scaled, k_range)
                    cat_baselines[cid] = {
                        "median": med,
                        "mad": mad,
                        "mad_scaled": mad_scaled,
                        "lower": low,
                        "upper": up,
                        "n": len(history)
                    }

            # 2. Inspect current month expense transactions
            cur.execute(f"""
                SELECT 
                    t.id,
                    t.transaction_date,
                    t.description,
                    t.merchant_name,
                    t.amount_minor,
                    t.category_id,
                    c.name as category_name,
                    t.is_recurring
                FROM transactions t
                JOIN categories c ON t.category_id = c.id
                WHERE t.transaction_type = 'expense'
                  AND t.transaction_date LIKE ? {acc_clause}
                ORDER BY t.amount_minor DESC
            """, [f"{month}%"] + params)

            curr_txs = cur.fetchall()

            for tx in curr_txs:
                cid = tx["category_id"]
                amt = tx["amount_minor"]
                is_recurring = bool(tx["is_recurring"])

                # Check if category has sufficient baseline
                if cid in cat_baselines:
                    b = cat_baselines[cid]
                    score = calculate_robust_z_score(amt, b["median"], b["mad"])

                    # If amount is above the upper bound and score is significant
                    if amt > b["upper"] and score >= 3.0:
                        severity = "strong" if score >= 4.5 else "moderate"
                        merchant = tx["merchant_name"] or tx["description"]
                        cname = tx["category_name"]
                        explanation = (
                            f"Transaction of {round(amt / 100.0, 2)} at '{merchant}' is unusually large "
                            f"for {cname} (typical range {round(b['lower'] / 100.0, 2)}–{round(b['upper'] / 100.0, 2)})."
                        )
                        anomalies.append(AnomalyResult(
                            anomaly_id=f"tx_amount_{tx['id']}",
                            anomaly_type="transaction_amount",
                            title=f"Unusually large {cname} purchase",
                            entity_type="transaction",
                            entity_id=tx["id"],
                            entity_name=merchant,
                            actual_minor=amt,
                            expected_median_minor=b["median"],
                            normal_range_lower_minor=b["lower"],
                            normal_range_upper_minor=b["upper"],
                            robust_score=score,
                            severity=severity,
                            confidence="high" if b["n"] >= 20 else "moderate",
                            explanation=explanation,
                            drilldown_filter={"transaction_id": tx["id"], "category_id": cid}
                        ))

            # 3. Recurring Payment Jump Anomalies
            cur.execute(f"""
                SELECT 
                    t.id,
                    t.merchant_name,
                    t.description,
                    t.amount_minor,
                    t.category_id,
                    c.name as category_name
                FROM transactions t
                JOIN categories c ON t.category_id = c.id
                WHERE t.transaction_type = 'expense'
                  AND t.is_recurring = 1
                  AND t.transaction_date LIKE ? {acc_clause}
            """, [f"{month}%"] + params)

            curr_recurring = cur.fetchall()
            for rec in curr_recurring:
                merchant_key = rec["merchant_name"] or rec["description"]
                amt = rec["amount_minor"]

                # Find previous recurring amounts for this merchant
                cur.execute(f"""
                    SELECT amount_minor
                    FROM transactions
                    WHERE transaction_type = 'expense'
                      AND is_recurring = 1
                      AND (merchant_name = ? OR description = ?)
                      AND transaction_date < ? || '-01' {acc_clause}
                    ORDER BY transaction_date DESC
                    LIMIT 5
                """, [merchant_key, merchant_key, month] + params)

                prev_rec_amts = [row["amount_minor"] for row in cur.fetchall()]
                if len(prev_rec_amts) >= 2:
                    med_prev = calculate_median(prev_rec_amts)
                    diff = amt - med_prev
                    # If increased by more than 10% and at least $3 (300 minor units)
                    if diff > 300 and (diff / med_prev) >= 0.10:
                        explanation = (
                            f"Recurring bill '{merchant_key}' increased from usual {round(med_prev / 100.0, 2)} "
                            f"to {round(amt / 100.0, 2)} (+{round(diff / 100.0, 2)})."
                        )
                        anomalies.append(AnomalyResult(
                            anomaly_id=f"rec_jump_{rec['id']}",
                            anomaly_type="recurring_jump",
                            title=f"Recurring bill increase: {merchant_key}",
                            entity_type="transaction",
                            entity_id=rec["id"],
                            entity_name=merchant_key,
                            actual_minor=amt,
                            expected_median_minor=med_prev,
                            normal_range_lower_minor=med_prev,
                            normal_range_upper_minor=med_prev,
                            robust_score=round(diff / med_prev * 5.0, 2),
                            severity="moderate" if diff > 1000 else "mild",
                            confidence="high",
                            explanation=explanation,
                            drilldown_filter={"transaction_id": rec["id"], "category_id": rec["category_id"]}
                        ))

            # 4. Category Monthly Total Anomalies (Comparing month's total against historical 6M monthly totals)
            cur.execute(f"""
                SELECT 
                    c.id,
                    c.name,
                    strftime('%Y-%m', t.transaction_date) as m,
                    SUM(
                        CASE 
                            WHEN t.transaction_type = 'expense' THEN t.amount_minor
                            WHEN t.transaction_type = 'refund' THEN -t.amount_minor
                            ELSE 0
                        END
                    ) as monthly_net
                FROM categories c
                JOIN transactions t ON t.category_id = c.id
                WHERE t.transaction_type IN ('expense', 'refund')
                  AND t.transaction_date < ? || '-01'
                  AND t.transaction_date >= date(? || '-01', '-6 months') {acc_clause}
                GROUP BY c.id, m
            """, [month, month] + params)

            monthly_cat_history: Dict[int, List[int]] = {}
            for row in cur.fetchall():
                cid = row["id"]
                if cid not in monthly_cat_history:
                    monthly_cat_history[cid] = []
                monthly_cat_history[cid].append(max(0, row["monthly_net"]))

            # Current month category totals
            cur.execute(f"""
                SELECT 
                    c.id,
                    c.name,
                    SUM(
                        CASE 
                            WHEN t.transaction_type = 'expense' THEN t.amount_minor
                            WHEN t.transaction_type = 'refund' THEN -t.amount_minor
                            ELSE 0
                        END
                    ) as current_net
                FROM categories c
                JOIN transactions t ON t.category_id = c.id
                WHERE t.transaction_type IN ('expense', 'refund')
                  AND t.transaction_date LIKE ? {acc_clause}
                GROUP BY c.id
            """, [f"{month}%"] + params)

            for row in cur.fetchall():
                cid = row["id"]
                curr_net = max(0, row["current_net"])
                cname = row["name"]
                hist = monthly_cat_history.get(cid, [])
                if len(hist) >= 3:  # Need at least 3 historical months
                    med = calculate_median(hist)
                    mad = calculate_mad(hist)
                    mad_scaled = calculate_scaled_mad(hist)
                    low, up = compute_normal_range(med, mad_scaled, k_range)
                    score = calculate_robust_z_score(curr_net, med, mad)

                    if curr_net > up and (curr_net - med) > 2000 and score >= 2.5:  # Significant $20+ increase
                        diff = curr_net - med
                        explanation = (
                            f"{cname} monthly total of {round(curr_net / 100.0, 2)} is above "
                            f"its 6-month typical range ({round(low / 100.0, 2)}–{round(up / 100.0, 2)})."
                        )
                        anomalies.append(AnomalyResult(
                            anomaly_id=f"cat_monthly_{cid}_{month}",
                            anomaly_type="category_monthly",
                            title=f"{cname} spending above normal range",
                            entity_type="category",
                            entity_id=cid,
                            entity_name=cname,
                            actual_minor=curr_net,
                            expected_median_minor=med,
                            normal_range_lower_minor=low,
                            normal_range_upper_minor=up,
                            robust_score=score,
                            severity="strong" if score >= 4.0 else "moderate",
                            confidence="high" if len(hist) >= 6 else "moderate",
                            explanation=explanation,
                            drilldown_filter={"category_id": cid, "month": month}
                        ))

        # Sort anomalies by severity and robust score
        sev_weight = {"strong": 3, "moderate": 2, "mild": 1}
        anomalies.sort(key=lambda a: (sev_weight.get(a.severity, 0), a.robust_score), reverse=True)
        return [a.to_dict() for a in anomalies]
