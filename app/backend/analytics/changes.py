"""
What Changed? v2 Analytics Engine for FinScope.
Implements multi-level variance decomposition:
- Level 1: Total Spend Variance (net of refunds)
- Level 2: Category Contribution Share
- Level 3: Merchant Drill-down
- Level 4: Symmetric Frequency vs. Average Ticket Decomposition:
    Freq Effect = (N1 - N0) * (A0 + A1) / 2
    Ticket Effect = (A1 - A0) * (N0 + N1) / 2
    Identity: Freq Effect + Ticket Effect == Total Delta (exact integer cents)
- Level 5: Time Contribution (Weekday vs Weekend shifts)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from app.backend.database.connection import get_db_connection
from app.backend.analytics.semantics import calculate_net_spending
from app.backend.analytics.aggregates import AggregateQueries
from app.backend.analytics.models import DriverDecomposition

def decompose_frequency_and_ticket(
    n0: int,
    n1: int,
    spend0_minor: int,
    spend1_minor: int
) -> tuple[int, int]:
    """
    Computes symmetric frequency and ticket effects in exact integer minor units:
    Freq Effect = (N1 - N0) * (A0 + A1) / 2
    Ticket Effect = Total Delta - Freq Effect (guarantees exact reconciliation)
    """
    total_delta = spend1_minor - spend0_minor
    if n0 == 0 and n1 == 0:
        return 0, 0
    if n0 == 0:
        # Purely new spending
        return total_delta, 0
    if n1 == 0:
        # Spending ceased
        return total_delta, 0

    a0 = spend0_minor / n0
    a1 = spend1_minor / n1

    freq_effect_raw = (n1 - n0) * (a0 + a1) / 2.0
    freq_effect_minor = round(freq_effect_raw)
    ticket_effect_minor = total_delta - freq_effect_minor

    return freq_effect_minor, ticket_effect_minor

class WhatChangedEngine:
    @staticmethod
    def analyze_changes(
        current_month: str,
        comparison_month: str,
        account_id: Optional[int] = None,
        max_day: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Performs full What Changed? v2 analysis comparing current_month vs comparison_month.
        If max_day is provided, restricts both months to days <= max_day for fair partial-month comparison.
        """
        with get_db_connection() as conn:
            cur = conn.cursor()
            acc_clause = " AND t.account_id = ?" if account_id else ""
            day_clause = f" AND CAST(strftime('%d', t.transaction_date) AS INTEGER) <= {max_day}" if max_day else ""

            params_curr = [f"{current_month}%"] + ([account_id] if account_id else [])
            params_prev = [f"{comparison_month}%"] + ([account_id] if account_id else [])

            # 1. Fetch categories for both periods
            cur.execute(f"""
                SELECT 
                    c.id,
                    c.name,
                    c.color,
                    c.icon,
                    COALESCE(
                        SUM(
                            CASE 
                                WHEN t.transaction_type = 'expense' THEN t.amount_minor
                                WHEN t.transaction_type = 'refund' THEN -t.amount_minor
                                ELSE 0
                            END
                        ), 0
                    ) as net_minor,
                    SUM(CASE WHEN t.transaction_type = 'expense' THEN 1 ELSE 0 END) as tx_count
                FROM categories c
                LEFT JOIN transactions t ON t.category_id = c.id
                    AND t.transaction_type IN ('expense', 'refund')
                    AND t.transaction_date LIKE ? {acc_clause} {day_clause}
                WHERE c.type = 'expense' AND c.is_archived = 0
                GROUP BY c.id
            """, params_curr)
            curr_cats = {
                row["id"]: {
                    "name": row["name"],
                    "color": row["color"],
                    "icon": row["icon"],
                    "net_minor": max(0, row["net_minor"]),
                    "tx_count": row["tx_count"]
                }
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
                    ) as net_minor,
                    SUM(CASE WHEN t.transaction_type = 'expense' THEN 1 ELSE 0 END) as tx_count
                FROM categories c
                LEFT JOIN transactions t ON t.category_id = c.id
                    AND t.transaction_type IN ('expense', 'refund')
                    AND t.transaction_date LIKE ? {acc_clause} {day_clause}
                WHERE c.type = 'expense' AND c.is_archived = 0
                GROUP BY c.id
            """, params_prev)
            prev_cats = {
                row["id"]: {
                    "net_minor": max(0, row["net_minor"]),
                    "tx_count": row["tx_count"]
                }
                for row in cur.fetchall()
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
                pdata = prev_cats.get(cid, {"net_minor": 0, "tx_count": 0})
                c_minor = cdata["net_minor"]
                p_minor = pdata["net_minor"]
                delta_minor = c_minor - p_minor

                if c_minor == 0 and p_minor == 0:
                    continue

                n0 = pdata["tx_count"]
                n1 = cdata["tx_count"]
                freq_eff, ticket_eff = decompose_frequency_and_ticket(n0, n1, p_minor, c_minor)

                # Share of increase
                share = (delta_minor / sum_pos_deltas) if (delta_minor > 0 and sum_pos_deltas > 0) else 0.0

                # Classification tag
                if p_minor == 0 and c_minor > 0:
                    tag = "NEW"
                elif c_minor == 0 and p_minor > 0:
                    tag = "REDUCED"
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
                    current_minor=c_minor,
                    previous_minor=p_minor,
                    delta_minor=delta_minor,
                    share_of_increase=share,
                    frequency_effect_minor=freq_eff,
                    ticket_effect_minor=ticket_eff,
                    tag=tag,
                    details={"n0": n0, "n1": n1, "icon": cdata["icon"]}
                ))

            # Sort drivers: highest positive impact first, then decreases
            drivers.sort(key=lambda d: d.delta_minor, reverse=True)

            # Overall decomposition
            total_n0 = sum(prev_cats.get(cid, {}).get("tx_count", 0) for cid in curr_cats)
            total_n1 = sum(c["tx_count"] for c in curr_cats.values())
            overall_freq_minor, overall_ticket_minor = decompose_frequency_and_ticket(
                total_n0, total_n1, total_prev_minor, total_curr_minor
            )

            # 2. Weekday vs Weekend Contribution
            cur.execute(f"""
                SELECT 
                    strftime('%w', transaction_date) as wday,
                    SUM(amount_minor) as total_minor
                FROM transactions
                WHERE transaction_type = 'expense'
                  AND transaction_date LIKE ? {acc_clause} {day_clause}
                GROUP BY wday
            """, params_curr)
            curr_wd = {int(row["wday"]): row["total_minor"] for row in cur.fetchall()}

            cur.execute(f"""
                SELECT 
                    strftime('%w', transaction_date) as wday,
                    SUM(amount_minor) as total_minor
                FROM transactions
                WHERE transaction_type = 'expense'
                  AND transaction_date LIKE ? {acc_clause} {day_clause}
                GROUP BY wday
            """, params_prev)
            prev_wd = {int(row["wday"]): row["total_minor"] for row in cur.fetchall()}

            # Sunday=0, Saturday=6
            curr_weekend_minor = curr_wd.get(0, 0) + curr_wd.get(6, 0)
            curr_weekday_minor = sum(curr_wd.get(d, 0) for d in range(1, 6))

            prev_weekend_minor = prev_wd.get(0, 0) + prev_wd.get(6, 0)
            prev_weekday_minor = sum(prev_wd.get(d, 0) for d in range(1, 6))

            weekend_delta_minor = curr_weekend_minor - prev_weekend_minor
            weekday_delta_minor = curr_weekday_minor - prev_weekday_minor

            # Waterfall steps construction for UI
            waterfall_steps = []
            waterfall_steps.append({
                "label": comparison_month,
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
            # Remainder
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
                "label": current_month,
                "amount": round(total_curr_minor / 100.0, 2),
                "is_total": True
            })

            return {
                "current_month": current_month,
                "comparison_month": comparison_month,
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
                "weekend_delta_minor": weekend_delta_minor,
                "weekend_delta": round(weekend_delta_minor / 100.0, 2),
                "weekday_delta_minor": weekday_delta_minor,
                "weekday_delta": round(weekday_delta_minor / 100.0, 2),
                "drivers": [d.to_dict() for d in drivers],
                "waterfall": waterfall_steps
            }
