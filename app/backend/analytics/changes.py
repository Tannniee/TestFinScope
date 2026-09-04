"""
What Changed? v2.1 Analytics Engine for FinScope.
Implements multi-level variance decomposition with explicit refund effects:
- Level 1: Total Spend Variance (net of refunds)
- Level 2: Category Contribution Share
- Level 3: Merchant Drill-down within Category
- Level 4: 3-Way Frequency, Ticket, and Refund Decomposition:
    Freq Effect = (N1 - N0) * (A0 + A1) / 2
    Refund Effect = -(R1 - R0)
    Ticket Effect = Net Delta - (Freq Effect + Refund Effect)
    Identity: Freq Effect + Ticket Effect + Refund Effect == Net Delta (exact integer cents)
- Level 5: Time Contribution (Monday–Sunday and Weekday vs Weekend)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from app.backend.database.connection import get_db_connection
from app.backend.analytics.models import DriverDecomposition
from app.backend.analytics.context import AnalyticsContext, resolve_analytics_context

def decompose_frequency_ticket_refund(
    n0: int,
    n1: int,
    gross0_minor: int,
    gross1_minor: int,
    refund0_minor: int,
    refund1_minor: int
) -> tuple[int, int, int]:
    """
    Computes exact integer minor unit decomposition:
    - Frequency Effect: purchase count change on gross transactions
    - Refund Effect: -(R1 - R0)
    - Ticket Effect: remainder assigned to guarantee exact penny reconciliation
    Identity: freq + ticket + refund === net_delta
    """
    net0_minor = max(0, gross0_minor - refund0_minor)
    net1_minor = max(0, gross1_minor - refund1_minor)
    net_delta = net1_minor - net0_minor
    refund_effect = -(refund1_minor - refund0_minor)

    if n0 == 0 and n1 == 0:
        return 0, 0, refund_effect

    if n0 == 0:
        # Brand new gross spending
        freq_effect = gross1_minor
        ticket_effect = net_delta - (freq_effect + refund_effect)
        return freq_effect, ticket_effect, refund_effect

    if n1 == 0:
        # Gross spending ceased
        freq_effect = -gross0_minor
        ticket_effect = net_delta - (freq_effect + refund_effect)
        return freq_effect, ticket_effect, refund_effect

    a0 = gross0_minor / float(n0)
    a1 = gross1_minor / float(n1)

    freq_raw = (n1 - n0) * (a0 + a1) / 2.0
    freq_effect = round(freq_raw)
    ticket_effect = net_delta - (freq_effect + refund_effect)

    return freq_effect, ticket_effect, refund_effect

def decompose_frequency_and_ticket(
    n0: int,
    n1: int,
    spend0_minor: int,
    spend1_minor: int
) -> tuple[int, int]:
    """Backward-compatible helper returning (freq_effect, ticket_effect) with 0 refunds."""
    freq, ticket, _ = decompose_frequency_ticket_refund(n0, n1, spend0_minor, spend1_minor, 0, 0)
    return freq, ticket

class WhatChangedEngine:
    @staticmethod
    def analyze_changes(
        current_month: str,
        comparison_month: Optional[str] = None,
        account_id: Optional[int] = None,
        max_day: Optional[int] = None,
        context: Optional[AnalyticsContext] = None
    ) -> Dict[str, Any]:
        """
        Performs full What Changed? v2.1 analysis with refund decomposition
        and category drivers. Accepts either months or canonical AnalyticsContext.
        """
        if context is None:
            context = resolve_analytics_context(
                month=current_month,
                account_id=account_id
            )

        curr_start, curr_end = context.sql_date_range()
        comp_range = context.comparison_sql_date_range()
        if not comp_range:
            comp_start, comp_end = curr_start, curr_end
        else:
            comp_start, comp_end = comp_range

        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND t.account_id = ?" if context.account_id else ""
            acc_params = [context.account_id] if context.account_id else []

            # 1. Fetch categories for current period
            cur.execute(f"""
                SELECT 
                    c.id,
                    c.name,
                    c.color,
                    c.icon,
                    COALESCE(SUM(CASE WHEN t.transaction_type = 'expense' THEN t.amount_minor ELSE 0 END), 0) as gross_minor,
                    COALESCE(SUM(CASE WHEN t.transaction_type = 'refund' THEN t.amount_minor ELSE 0 END), 0) as refund_minor,
                    SUM(CASE WHEN t.transaction_type = 'expense' THEN 1 ELSE 0 END) as tx_count
                FROM categories c
                LEFT JOIN active_transactions t ON t.category_id = c.id
                    AND t.transaction_type IN ('expense', 'refund')
                    AND t.transaction_date >= ? AND t.transaction_date <= ? {acc_clause}
                WHERE c.type = 'expense' AND c.is_archived = 0
                GROUP BY c.id
            """, [curr_start, curr_end] + acc_params)
            
            curr_cats = {}
            for row in cur.fetchall():
                gross = row["gross_minor"]
                ref = row["refund_minor"]
                net = max(0, gross - ref)
                curr_cats[row["id"]] = {
                    "name": row["name"],
                    "color": row["color"],
                    "icon": row["icon"],
                    "gross_minor": gross,
                    "refund_minor": ref,
                    "net_minor": net,
                    "tx_count": row["tx_count"]
                }

            # 2. Fetch categories for comparison period
            cur.execute(f"""
                SELECT 
                    c.id,
                    COALESCE(SUM(CASE WHEN t.transaction_type = 'expense' THEN t.amount_minor ELSE 0 END), 0) as gross_minor,
                    COALESCE(SUM(CASE WHEN t.transaction_type = 'refund' THEN t.amount_minor ELSE 0 END), 0) as refund_minor,
                    SUM(CASE WHEN t.transaction_type = 'expense' THEN 1 ELSE 0 END) as tx_count
                FROM categories c
                LEFT JOIN active_transactions t ON t.category_id = c.id
                    AND t.transaction_type IN ('expense', 'refund')
                    AND t.transaction_date >= ? AND t.transaction_date <= ? {acc_clause}
                WHERE c.type = 'expense' AND c.is_archived = 0
                GROUP BY c.id
            """, [comp_start, comp_end] + acc_params)

            prev_cats = {}
            for row in cur.fetchall():
                gross = row["gross_minor"]
                ref = row["refund_minor"]
                net = max(0, gross - ref)
                prev_cats[row["id"]] = {
                    "gross_minor": gross,
                    "refund_minor": ref,
                    "net_minor": net,
                    "tx_count": row["tx_count"]
                }

            total_curr_minor = sum(c["net_minor"] for c in curr_cats.values())
            total_prev_minor = sum(prev_cats.get(cid, {}).get("net_minor", 0) for cid in curr_cats)
            total_delta_minor = total_curr_minor - total_prev_minor

            # Positive deltas sum (for share calculation)
            sum_pos_deltas = sum(
                max(0, curr_cats[cid]["net_minor"] - prev_cats.get(cid, {}).get("net_minor", 0))
                for cid in curr_cats
            )

            drivers: List[DriverDecomposition] = []
            for cid, cdata in curr_cats.items():
                pdata = prev_cats.get(cid, {"gross_minor": 0, "refund_minor": 0, "net_minor": 0, "tx_count": 0})
                c_net = cdata["net_minor"]
                p_net = pdata["net_minor"]
                delta_minor = c_net - p_net

                if c_net == 0 and p_net == 0:
                    continue

                n0 = pdata["tx_count"]
                n1 = cdata["tx_count"]
                g0 = pdata["gross_minor"]
                g1 = cdata["gross_minor"]
                r0 = pdata["refund_minor"]
                r1 = cdata["refund_minor"]

                freq_eff, ticket_eff, ref_eff = decompose_frequency_ticket_refund(n0, n1, g0, g1, r0, r1)

                share = (delta_minor / sum_pos_deltas) if (delta_minor > 0 and sum_pos_deltas > 0) else 0.0

                # Classification tag
                if p_net == 0 and c_net > 0:
                    tag = "NEW"
                elif c_net == 0 and p_net > 0:
                    tag = "REDUCED"
                elif r1 > r0 and ref_eff < 0 and abs(ref_eff) > abs(freq_eff):
                    tag = "REFUND_IMPACT"
                elif delta_minor > 0:
                    if abs(freq_eff) > abs(ticket_eff) and freq_eff > 0:
                        tag = "INCREASED_FREQUENCY"
                    elif ticket_eff > 0:
                        tag = "HIGHER_TICKET"
                    else:
                        tag = "EXPENSE_INCREASE"
                else:
                    tag = "REDUCED"

                drivers.append(DriverDecomposition(
                    dimension="category",
                    name=cdata["name"],
                    entity_id=cid,
                    color=cdata["color"],
                    current_minor=c_net,
                    previous_minor=p_net,
                    delta_minor=delta_minor,
                    share_of_increase=share,
                    frequency_effect_minor=freq_eff,
                    ticket_effect_minor=ticket_eff,
                    refund_effect_minor=ref_eff,
                    tag=tag,
                    details={
                        "n0": n0, "n1": n1,
                        "g0": g0, "g1": g1,
                        "r0": r0, "r1": r1,
                        "icon": cdata["icon"]
                    }
                ))

            # Sort drivers: highest positive impact first, then decreases
            drivers.sort(key=lambda d: d.delta_minor, reverse=True)

            # Overall decomposition
            total_g0 = sum(p.get("gross_minor", 0) for p in prev_cats.values())
            total_g1 = sum(c["gross_minor"] for c in curr_cats.values())
            total_r0 = sum(p.get("refund_minor", 0) for p in prev_cats.values())
            total_r1 = sum(c["refund_minor"] for c in curr_cats.values())
            total_n0 = sum(p.get("tx_count", 0) for p in prev_cats.values())
            total_n1 = sum(c["tx_count"] for c in curr_cats.values())

            overall_freq_minor, overall_ticket_minor, overall_refund_minor = decompose_frequency_ticket_refund(
                total_n0, total_n1, total_g0, total_g1, total_r0, total_r1
            )

            # 3. Weekday vs Weekend Contribution & Daily Contribution
            weekday_labels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            cur.execute(f"""
                SELECT 
                    strftime('%w', transaction_date) as wday,
                    SUM(
                        CASE 
                            WHEN transaction_type = 'expense' THEN amount_minor
                            WHEN transaction_type = 'refund' THEN -amount_minor
                            ELSE 0
                        END
                    ) as net_minor
                FROM active_transactions t
                WHERE t.transaction_type IN ('expense', 'refund')
                  AND t.transaction_date >= ? AND t.transaction_date <= ? {acc_clause}
                GROUP BY wday
            """, [curr_start, curr_end] + acc_params)
            curr_wd = {int(row["wday"]): row["net_minor"] for row in cur.fetchall()}

            cur.execute(f"""
                SELECT 
                    strftime('%w', transaction_date) as wday,
                    SUM(
                        CASE 
                            WHEN transaction_type = 'expense' THEN amount_minor
                            WHEN transaction_type = 'refund' THEN -amount_minor
                            ELSE 0
                        END
                    ) as net_minor
                FROM active_transactions t
                WHERE t.transaction_type IN ('expense', 'refund')
                  AND t.transaction_date >= ? AND t.transaction_date <= ? {acc_clause}
                GROUP BY wday
            """, [comp_start, comp_end] + acc_params)
            prev_wd = {int(row["wday"]): row["net_minor"] for row in cur.fetchall()}

            day_contributions = []
            for d_idx in range(7):
                c_val = curr_wd.get(d_idx, 0)
                p_val = prev_wd.get(d_idx, 0)
                d_delta = c_val - p_val
                day_contributions.append({
                    "day": weekday_labels[d_idx],
                    "day_index": d_idx,
                    "current": round(c_val / 100.0, 2),
                    "previous": round(p_val / 100.0, 2),
                    "delta": round(d_delta / 100.0, 2),
                    "delta_minor": d_delta
                })

            curr_weekend_minor = curr_wd.get(0, 0) + curr_wd.get(6, 0)
            curr_weekday_minor = sum(curr_wd.get(d, 0) for d in range(1, 6))

            prev_weekend_minor = prev_wd.get(0, 0) + prev_wd.get(6, 0)
            prev_weekday_minor = sum(prev_wd.get(d, 0) for d in range(1, 6))

            weekend_delta_minor = curr_weekend_minor - prev_weekend_minor
            weekday_delta_minor = curr_weekday_minor - prev_weekday_minor

            # Waterfall steps construction for UI
            waterfall_steps = []
            waterfall_steps.append({
                "label": context.comparison_label,
                "amount": round(total_prev_minor / 100.0, 2),
                "is_total": True
            })
            for d in drivers[:6]:
                if abs(d.delta_minor) > 0:
                    waterfall_steps.append({
                        "label": d.name,
                        "amount": round(d.delta_minor / 100.0, 2),
                        "color": d.color,
                        "is_total": False
                    })
            other_drivers = drivers[6:]
            other_delta = sum(d.delta_minor for d in other_drivers)
            if abs(other_delta) > 0:
                waterfall_steps.append({
                    "label": "Other Categories",
                    "amount": round(other_delta / 100.0, 2),
                    "color": "#8E8E93",
                    "is_total": False
                })
            waterfall_steps.append({
                "label": context.period_label,
                "amount": round(total_curr_minor / 100.0, 2),
                "is_total": True
            })

            return {
                "current_month": context.as_of_month,
                "comparison_month": comparison_month or (context.comparison_start.strftime("%Y-%m") if context.comparison_start else ""),
                "context": context.to_dict(),
                "total_current_minor": total_curr_minor,
                "total_current": round(total_curr_minor / 100.0, 2),
                "total_previous_minor": total_prev_minor,
                "total_previous": round(total_prev_minor / 100.0, 2),
                "total_delta_minor": total_delta_minor,
                "total_delta": round(total_delta_minor / 100.0, 2),
                "overall_frequency_effect_minor": overall_freq_minor,
                "overall_frequency_effect": round(overall_freq_minor / 100.0, 2),
                "overall_ticket_effect_minor": overall_ticket_minor,
                "overall_ticket_effect": round(overall_ticket_minor / 100.0, 2),
                "overall_refund_effect_minor": overall_refund_minor,
                "overall_refund_effect": round(overall_refund_minor / 100.0, 2),
                "weekend_delta_minor": weekend_delta_minor,
                "weekend_delta": round(weekend_delta_minor / 100.0, 2),
                "weekday_delta_minor": weekday_delta_minor,
                "weekday_delta": round(weekday_delta_minor / 100.0, 2),
                "day_contributions": day_contributions,
                "drivers": [d.to_dict() for d in drivers],
                "waterfall": waterfall_steps
            }

    @staticmethod
    def get_merchant_drilldown(
        category_id: int,
        current_month: Optional[str] = None,
        account_id: Optional[int] = None,
        context: Optional[AnalyticsContext] = None
    ) -> List[Dict[str, Any]]:
        """
        Drills down into merchants within a specific category to show which merchants
        drove the category's spending increase or decrease.
        """
        if context is None:
            context = resolve_analytics_context(
                month=current_month,
                account_id=account_id,
                category_id=category_id
            )

        curr_start, curr_end = context.sql_date_range()
        comp_range = context.comparison_sql_date_range()
        comp_start, comp_end = comp_range if comp_range else (curr_start, curr_end)

        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND t.account_id = ?" if context.account_id else ""
            acc_params = [context.account_id] if context.account_id else []

            # Current merchants
            cur.execute(f"""
                SELECT 
                    COALESCE(NULLIF(t.merchant_name, ''), 'Unknown') as m_name,
                    COALESCE(SUM(CASE WHEN t.transaction_type = 'expense' THEN t.amount_minor ELSE 0 END), 0) as gross_minor,
                    COALESCE(SUM(CASE WHEN t.transaction_type = 'refund' THEN t.amount_minor ELSE 0 END), 0) as refund_minor,
                    SUM(CASE WHEN t.transaction_type = 'expense' THEN 1 ELSE 0 END) as tx_count
                FROM active_transactions t
                WHERE t.category_id = ?
                  AND t.transaction_type IN ('expense', 'refund')
                  AND t.transaction_date >= ? AND t.transaction_date <= ? {acc_clause}
                GROUP BY m_name
            """, [category_id, curr_start, curr_end] + acc_params)
            curr_merchants = {
                row["m_name"]: {
                    "gross_minor": row["gross_minor"],
                    "refund_minor": row["refund_minor"],
                    "net_minor": max(0, row["gross_minor"] - row["refund_minor"]),
                    "tx_count": row["tx_count"]
                }
                for row in cur.fetchall()
            }

            # Previous merchants
            cur.execute(f"""
                SELECT 
                    COALESCE(NULLIF(t.merchant_name, ''), 'Unknown') as m_name,
                    COALESCE(SUM(CASE WHEN t.transaction_type = 'expense' THEN t.amount_minor ELSE 0 END), 0) as gross_minor,
                    COALESCE(SUM(CASE WHEN t.transaction_type = 'refund' THEN t.amount_minor ELSE 0 END), 0) as refund_minor,
                    SUM(CASE WHEN t.transaction_type = 'expense' THEN 1 ELSE 0 END) as tx_count
                FROM active_transactions t
                WHERE t.category_id = ?
                  AND t.transaction_type IN ('expense', 'refund')
                  AND t.transaction_date >= ? AND t.transaction_date <= ? {acc_clause}
                GROUP BY m_name
            """, [category_id, comp_start, comp_end] + acc_params)
            prev_merchants = {
                row["m_name"]: {
                    "gross_minor": row["gross_minor"],
                    "refund_minor": row["refund_minor"],
                    "net_minor": max(0, row["gross_minor"] - row["refund_minor"]),
                    "tx_count": row["tx_count"]
                }
                for row in cur.fetchall()
            }

            all_names = set(curr_merchants.keys()).union(set(prev_merchants.keys()))
            items = []

            for name in all_names:
                c = curr_merchants.get(name, {"gross_minor": 0, "refund_minor": 0, "net_minor": 0, "tx_count": 0})
                p = prev_merchants.get(name, {"gross_minor": 0, "refund_minor": 0, "net_minor": 0, "tx_count": 0})
                c_net = c["net_minor"]
                p_net = p["net_minor"]
                delta = c_net - p_net

                freq_eff, ticket_eff, ref_eff = decompose_frequency_ticket_refund(
                    p["tx_count"], c["tx_count"],
                    p["gross_minor"], c["gross_minor"],
                    p["refund_minor"], c["refund_minor"]
                )

                if p_net == 0 and c_net > 0:
                    tag = "NEW_MERCHANT"
                elif c_net == 0 and p_net > 0:
                    tag = "REDUCED"
                elif ref_eff != 0 and abs(ref_eff) >= abs(freq_eff):
                    tag = "REFUND_CHANGE"
                elif delta > 0:
                    if abs(freq_eff) > abs(ticket_eff):
                        tag = "MORE_FREQUENT"
                    else:
                        tag = "HIGHER_TICKET"
                else:
                    if abs(freq_eff) > abs(ticket_eff):
                        tag = "LESS_FREQUENT"
                    else:
                        tag = "LOWER_TICKET"

                items.append({
                    "merchant": name,
                    "current_minor": c_net,
                    "current": round(c_net / 100.0, 2),
                    "previous_minor": p_net,
                    "previous": round(p_net / 100.0, 2),
                    "delta_minor": delta,
                    "delta": round(delta / 100.0, 2),
                    "frequency_effect_minor": freq_eff,
                    "frequency_effect": round(freq_eff / 100.0, 2),
                    "ticket_effect_minor": ticket_eff,
                    "ticket_effect": round(ticket_eff / 100.0, 2),
                    "refund_effect_minor": ref_eff,
                    "refund_effect": round(ref_eff / 100.0, 2),
                    "tag": tag,
                    "tx_count_current": c["tx_count"],
                    "tx_count_previous": p["tx_count"]
                })

            items.sort(key=lambda x: abs(x["delta_minor"]), reverse=True)
            return items
