"""
Anomaly Detection Engine v2 & Normal Ranges for FinScope.
Detects unusual spending relative to personal historical norms:
- Robust Z-Score: 0.6745 * (x - median) / MAD
- Normal Range: [median - k * MAD_scaled, median + k * MAD_scaled]
- Transaction Amount Anomalies with Hierarchical Fallback:
    merchant + category -> merchant -> category -> overall comparable transactions
- Minimum Sample Guards: merchant >= 5, category >= 10, overall >= 20
- Separate Recurring Payment Jump Detection
- Dismissal/Expected feedback tracking via InsightHistoryTracker
- False Positive Controls (transfers & refunds separated)
- Multi-Currency & Canonical Money Normalization (base currency for portfolio, account native for account)
"""

import math
from datetime import date, datetime
from typing import Dict, Any, List, Optional, Tuple
from app.backend.database.connection import get_db_connection
from app.backend.analytics.rolling import calculate_median, calculate_mad, calculate_scaled_mad
from app.backend.analytics.models import AnomalyResult
from app.backend.analytics.context import AnalyticsContext, resolve_analytics_context
from app.backend.analytics.money_context import resolve_analytics_money_context
from app.backend.analytics.insight_history import InsightHistoryTracker


def calculate_robust_z_score(value: int, median_val: int, mad_val: int) -> float:
    """Computes robust z-score: 0.6745 * (x - median) / MAD."""
    if mad_val <= 0:
        if value == median_val:
            return 0.0
        return (value - median_val) / (median_val if median_val > 0 else 1.0)
    return 0.6745 * (value - median_val) / float(mad_val)


def compute_normal_range(median_val: int, mad_scaled: int, k: float = 2.5) -> Tuple[int, int]:
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
        k_range: float = 2.5,
        context: Optional[AnalyticsContext] = None
    ) -> List[Dict[str, Any]]:
        """
        Runs comprehensive anomaly detection for a specific period/month:
        1. Hierarchical individual transaction anomalies (merchant -> category -> overall)
        2. Unusually high category monthly totals
        3. Recurring subscription/bill jumps
        """
        if context is None:
            context = resolve_analytics_context(month=month, account_id=account_id)

        eff_account_id = context.account_id if context else account_id
        money_ctx = resolve_analytics_money_context(eff_account_id)
        mat_threshold = money_ctx.materiality_minor()

        curr_start, curr_end = context.sql_date_range()
        anomalies: List[AnomalyResult] = []

        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND t.account_id = ?" if context.account_id else ""
            acc_params: List[Any] = [context.account_id] if context.account_id else []
            tx_amt = money_ctx.tx_amount_expr

            # Historical 6-month window prior to current period
            hist_end = curr_start
            hist_start = f"{int(curr_start[:4]) - 1 if curr_start[5:7] <= '06' else curr_start[:4]}-{((int(curr_start[5:7]) - 7) % 12 + 1):02d}-01"

            # 1. Fetch Merchant History (for merchant-level baseline)
            cur.execute(f"""
                SELECT 
                    COALESCE(NULLIF(t.merchant_name, ''), 'Unknown') as m_name,
                    t.category_id,
                    {tx_amt} as amount_minor
                FROM active_transactions t
                WHERE t.transaction_type = 'expense'
                  AND t.transaction_date < ?
                  AND t.transaction_date >= ? {acc_clause}
            """, [hist_end, hist_start] + acc_params)

            merchant_history: Dict[str, List[int]] = {}
            category_history: Dict[int, List[int]] = {}
            overall_history: List[int] = []

            for row in cur.fetchall():
                amt = row["amount_minor"]
                m_name = row["m_name"]
                cid = row["category_id"]

                overall_history.append(amt)
                if m_name != "Unknown":
                    if m_name not in merchant_history:
                        merchant_history[m_name] = []
                    merchant_history[m_name].append(amt)

                if cid:
                    if cid not in category_history:
                        category_history[cid] = []
                    category_history[cid].append(amt)

            # Precalculate category baselines
            category_baselines: Dict[int, Dict[str, Any]] = {}
            for cid, amounts in category_history.items():
                if len(amounts) >= 10:
                    med = calculate_median(amounts)
                    mad = calculate_mad(amounts)
                    mad_scaled = calculate_scaled_mad(amounts)
                    low, up = compute_normal_range(med, mad_scaled, k_range)
                    category_baselines[cid] = {
                        "median": med,
                        "mad": mad,
                        "lower": low,
                        "upper": up,
                        "n": len(amounts)
                    }

            # Precalculate merchant baselines
            merchant_baselines: Dict[str, Dict[str, Any]] = {}
            for m_name, amounts in merchant_history.items():
                if len(amounts) >= 5:
                    med = calculate_median(amounts)
                    mad = calculate_mad(amounts)
                    mad_scaled = calculate_scaled_mad(amounts)
                    low, up = compute_normal_range(med, mad_scaled, k_range)
                    merchant_baselines[m_name] = {
                        "median": med,
                        "mad": mad,
                        "lower": low,
                        "upper": up,
                        "n": len(amounts)
                    }

            # Precalculate overall baseline
            overall_baseline = None
            if len(overall_history) >= 20:
                med = calculate_median(overall_history)
                mad = calculate_mad(overall_history)
                mad_scaled = calculate_scaled_mad(overall_history)
                low, up = compute_normal_range(med, mad_scaled, k_range)
                overall_baseline = {
                    "median": med,
                    "mad": mad,
                    "lower": low,
                    "upper": up,
                    "n": len(overall_history)
                }

            # 2. Evaluate Individual Expense Transactions in Current Month
            cur.execute(f"""
                SELECT 
                    t.id,
                    t.merchant_name,
                    t.description,
                    {tx_amt} as amount_minor,
                    t.category_id,
                    c.name as category_name,
                    t.transaction_date,
                    t.is_recurring
                FROM active_transactions t
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE t.transaction_type = 'expense'
                  AND t.transaction_date >= ? AND t.transaction_date <= ? {acc_clause}
                ORDER BY {tx_amt} DESC
            """, [curr_start, curr_end] + acc_params)

            curr_txs = cur.fetchall()

            for tx in curr_txs:
                tx_id = tx["id"]
                amt = tx["amount_minor"]
                cid = tx["category_id"]
                cname = tx["category_name"] or "General"
                m_name = tx["merchant_name"] or tx["description"]

                # Check dismissal
                anomaly_key = f"tx_amount_{tx_id}"
                if InsightHistoryTracker.is_dismissed(anomaly_key):
                    continue

                # Hierarchical Baseline: Merchant -> Category -> Overall (FSC-M07)
                baseline = None
                baseline_level = None

                if m_name in merchant_baselines:
                    baseline = merchant_baselines[m_name]
                    baseline_level = "merchant"
                elif cid in category_baselines:
                    baseline = category_baselines[cid]
                    baseline_level = "category"
                elif overall_baseline:
                    baseline = overall_baseline
                    baseline_level = "overall"

                if baseline:
                    score = calculate_robust_z_score(amt, baseline["median"], baseline["mad"])
                    diff_from_med = amt - baseline["median"]
                    if amt > baseline["upper"] and score >= 3.0 and diff_from_med >= mat_threshold:
                        severity = "strong" if score >= 4.5 else "moderate"
                        if baseline_level == "merchant":
                            explanation = (
                                f"Purchase of {money_ctx.format(amt)} at '{m_name}' is unusually large "
                                f"compared to your usual merchant range ({money_ctx.format(baseline['lower'])}–{money_ctx.format(baseline['upper'])})."
                            )
                            title = f"Unusually large payment to {m_name}"
                        elif baseline_level == "category":
                            explanation = (
                                f"Purchase of {money_ctx.format(amt)} at '{m_name}' is unusually large "
                                f"for {cname} (typical range {money_ctx.format(baseline['lower'])}–{money_ctx.format(baseline['upper'])})."
                            )
                            title = f"Unusually large {cname} purchase"
                        else:
                            explanation = (
                                f"Purchase of {money_ctx.format(amt)} at '{m_name}' is unusually large "
                                f"compared to your overall typical spending (typical range {money_ctx.format(baseline['lower'])}–{money_ctx.format(baseline['upper'])})."
                            )
                            title = f"Unusually large purchase"

                        anomalies.append(AnomalyResult(
                            anomaly_id=anomaly_key,
                            anomaly_type="transaction_amount",
                            title=title,
                            entity_type="transaction",
                            entity_id=tx_id,
                            entity_name=m_name,
                            actual_minor=amt,
                            expected_median_minor=baseline["median"],
                            normal_range_lower_minor=baseline["lower"],
                            normal_range_upper_minor=baseline["upper"],
                            robust_score=score,
                            severity=severity,
                            confidence="high" if baseline["n"] >= 15 else "moderate",
                            explanation=explanation,
                            drilldown_filter={"transaction_id": tx_id, "category_id": cid},
                            currency=money_ctx.currency
                        ))

            # 3. Recurring Payment Jumps
            cur.execute(f"""
                SELECT 
                    t.id,
                    t.merchant_name,
                    t.description,
                    {tx_amt} as amount_minor,
                    t.category_id,
                    c.name as category_name
                FROM active_transactions t
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE t.transaction_type = 'expense'
                  AND t.is_recurring = 1
                  AND t.transaction_date >= ? AND t.transaction_date <= ? {acc_clause}
            """, [curr_start, curr_end] + acc_params)

            for rec in cur.fetchall():
                rec_id = rec["id"]
                anomaly_key = f"rec_jump_{rec_id}"
                if InsightHistoryTracker.is_dismissed(anomaly_key):
                    continue

                merchant_key = rec["merchant_name"] or rec["description"]
                amt = rec["amount_minor"]

                cur.execute(f"""
                    SELECT {tx_amt} as amount_minor
                    FROM active_transactions t
                    WHERE t.transaction_type = 'expense'
                      AND t.is_recurring = 1
                      AND (t.merchant_name = ? OR t.description = ?)
                      AND t.transaction_date < ? {acc_clause}
                    ORDER BY t.transaction_date DESC
                    LIMIT 5
                """, [merchant_key, merchant_key, curr_start] + acc_params)

                prev_rec_amts = [row["amount_minor"] for row in cur.fetchall()]
                if len(prev_rec_amts) >= 2:
                    med_prev = calculate_median(prev_rec_amts)
                    diff = amt - med_prev
                    if diff >= (mat_threshold // 10) and (diff / float(med_prev if med_prev > 0 else 1)) >= 0.10:
                        explanation = (
                            f"Recurring bill '{merchant_key}' increased from usual {money_ctx.format(med_prev)} "
                            f"to {money_ctx.format(amt)} (+{money_ctx.format(diff)})."
                        )
                        anomalies.append(AnomalyResult(
                            anomaly_id=anomaly_key,
                            anomaly_type="recurring_jump",
                            title=f"Recurring bill increase: {merchant_key}",
                            entity_type="transaction",
                            entity_id=rec_id,
                            entity_name=merchant_key,
                            actual_minor=amt,
                            expected_median_minor=med_prev,
                            normal_range_lower_minor=med_prev,
                            normal_range_upper_minor=med_prev,
                            robust_score=round(diff / (med_prev if med_prev > 0 else 1) * 5.0, 2),
                            severity="moderate" if diff > (mat_threshold // 5) else "mild",
                            confidence="high",
                            explanation=explanation,
                            drilldown_filter={"transaction_id": rec_id, "category_id": rec["category_id"]},
                            currency=money_ctx.currency
                        ))

            # 4. Category Monthly Total Anomalies (Dense zero months & matched comparison, FSC-M07)
            y, m_val = map(int, context.as_of_month.split("-"))
            hist_months = []
            cy, cm = y, m_val
            for _ in range(6):
                if cm == 1:
                    cy -= 1
                    cm = 12
                else:
                    cm -= 1
                hist_months.append(f"{cy:04d}-{cm:02d}")
            hist_months.reverse()

            matched_day_clause = ""
            matched_params = []
            if context.is_current_month and context.max_day > 0:
                matched_day_clause = " AND CAST(strftime('%d', t.transaction_date) AS INTEGER) <= ?"
                matched_params = [context.max_day]

            cur.execute(f"""
                SELECT 
                    c.id,
                    c.name,
                    strftime('%Y-%m', t.transaction_date) as m,
                    SUM(
                        CASE 
                            WHEN t.transaction_type = 'expense' THEN {tx_amt}
                            WHEN t.transaction_type = 'refund' THEN -{tx_amt}
                            ELSE 0
                        END
                    ) as monthly_net
                FROM categories c
                JOIN active_transactions t ON t.category_id = c.id
                WHERE t.transaction_type IN ('expense', 'refund')
                  AND t.transaction_date < ?
                  AND t.transaction_date >= ? || '-01' {matched_day_clause} {acc_clause}
                GROUP BY c.id, m
            """, [curr_start, hist_months[0]] + matched_params + acc_params)

            sparse_cat_history: Dict[int, Dict[str, int]] = {}
            for row in cur.fetchall():
                cid = row["id"]
                if cid not in sparse_cat_history:
                    sparse_cat_history[cid] = {}
                sparse_cat_history[cid][row["m"]] = max(0, row["monthly_net"])

            # Dense 6-month history for each category
            monthly_cat_history: Dict[int, List[int]] = {}
            for cid, m_map in sparse_cat_history.items():
                monthly_cat_history[cid] = [m_map.get(hm, 0) for hm in hist_months]

            # Current period category totals
            cur.execute(f"""
                SELECT 
                    c.id,
                    c.name,
                    SUM(
                        CASE 
                            WHEN t.transaction_type = 'expense' THEN {tx_amt}
                            WHEN t.transaction_type = 'refund' THEN -{tx_amt}
                            ELSE 0
                        END
                    ) as current_net
                FROM categories c
                JOIN active_transactions t ON t.category_id = c.id
                WHERE t.transaction_type IN ('expense', 'refund')
                  AND t.transaction_date >= ? AND t.transaction_date <= ? {acc_clause}
                GROUP BY c.id
            """, [curr_start, curr_end] + acc_params)

            for row in cur.fetchall():
                cid = row["id"]
                curr_net = max(0, row["current_net"])
                cname = row["name"]
                hist = monthly_cat_history.get(cid, [])

                anomaly_key = f"cat_monthly_{cid}_{context.as_of_month}"
                if InsightHistoryTracker.is_dismissed(anomaly_key):
                    continue

                if len(hist) >= 3:
                    med = calculate_median(hist)
                    mad = calculate_mad(hist)
                    mad_scaled = calculate_scaled_mad(hist)
                    low, up = compute_normal_range(med, mad_scaled, k_range)
                    score = calculate_robust_z_score(curr_net, med, mad)

                    if curr_net > up and (curr_net - med) >= mat_threshold and score >= 2.5:
                        explanation = (
                            f"{cname} spending of {money_ctx.format(curr_net)} is above "
                            f"its typical range ({money_ctx.format(low)}–{money_ctx.format(up)})."
                        )
                        anomalies.append(AnomalyResult(
                            anomaly_id=anomaly_key,
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
                            drilldown_filter={"category_id": cid, "month": context.as_of_month},
                            currency=money_ctx.currency
                        ))

        sev_weight = {"strong": 3, "moderate": 2, "mild": 1}
        anomalies.sort(key=lambda a: (sev_weight.get(a.severity, 0), a.robust_score), reverse=True)
        return [a.to_dict() for a in anomalies]

    @staticmethod
    def get_category_normal_ranges(
        account_id: Optional[int] = None,
        as_of_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Computes baseline normal ranges for all expense categories for visualization."""
        ref_date = as_of_date or date.today().isoformat()
        money_ctx = resolve_analytics_money_context(account_id)
        tx_amt = money_ctx.tx_amount_expr

        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND t.account_id = ?" if account_id else ""
            acc_params: List[Any] = [account_id] if account_id else []

            cur.execute(f"""
                SELECT 
                    c.id,
                    c.name,
                    c.color,
                    strftime('%Y-%m', t.transaction_date) as m,
                    SUM(
                        CASE 
                            WHEN t.transaction_type = 'expense' THEN {tx_amt}
                            WHEN t.transaction_type = 'refund' THEN -{tx_amt}
                            ELSE 0
                        END
                    ) as net_minor
                FROM categories c
                JOIN active_transactions t ON t.category_id = c.id
                WHERE t.transaction_type IN ('expense', 'refund')
                  AND t.transaction_date < ?
                  AND t.transaction_date >= date(?, '-6 months') {acc_clause}
                GROUP BY c.id, m
            """, [ref_date, ref_date] + acc_params)

            cat_hist: Dict[int, Dict[str, Any]] = {}
            for row in cur.fetchall():
                cid = row["id"]
                if cid not in cat_hist:
                    cat_hist[cid] = {"name": row["name"], "color": row["color"], "values": []}
                cat_hist[cid]["values"].append(max(0, row["net_minor"]))

            ranges = []
            for cid, data in cat_hist.items():
                vals = data["values"]
                if len(vals) >= 2:
                    med = calculate_median(vals)
                    mad_scaled = calculate_scaled_mad(vals)
                    low, up = compute_normal_range(med, mad_scaled, k=2.0)
                    ranges.append({
                        "category_id": cid,
                        "category_name": data["name"],
                        "color": data["color"],
                        "currency": money_ctx.currency,
                        "median_minor": med,
                        "median": money_ctx.to_major(med),
                        "lower_minor": low,
                        "lower": money_ctx.to_major(low),
                        "upper_minor": up,
                        "upper": money_ctx.to_major(up),
                        "sample_months": len(vals)
                    })

            ranges.sort(key=lambda x: x["median_minor"], reverse=True)
            return ranges
