"""
Candidate Insight Rules Generator V2 for FinScope.
Generates candidate insights from analytical modules:
- What Changed? drivers (frequency, ticket, refund effects)
- Rolling historical norm deviations
- Transaction & category anomalies
- Budget & forecast risk projections
- Positive financial achievements
Integrates persistent insight keys and dynamic novelty scoring.
"""

from datetime import datetime
from typing import Dict, Any, List, Optional
from decimal import Decimal
from app.backend.analytics.models import Insight
from app.backend.analytics.insight_history import InsightHistoryTracker
from app.backend.domain.currencies import get_currency_meta
from app.backend.domain.money import format_money, minor_to_major


class InsightRulesGenerator:
    @staticmethod
    def generate_candidates(
        changes_data: Dict[str, Any],
        anomalies_data: List[Dict[str, Any]],
        forecast_data: Dict[str, Any],
        month: str
    ) -> List[Insight]:
        candidates: List[Insight] = []
        now_str = datetime.now().isoformat()
        total_curr_minor = changes_data.get("total_current_minor", 1)

        currency = changes_data.get("currency") or forecast_data.get("currency") or (anomalies_data[0].get("currency") if anomalies_data else None) or "USD"

        meta = get_currency_meta(currency)
        if meta.minor_unit == 0:
            if currency == "VND":
                threshold_20 = 500000
                threshold_30 = 750000
                threshold_50 = 1000000
                threshold_15 = 350000
            else:
                threshold_20 = 3000
                threshold_30 = 4500
                threshold_50 = 7500
                threshold_15 = 2000
        elif meta.minor_unit == 3:
            threshold_20 = 6000
            threshold_30 = 9000
            threshold_50 = 15000
            threshold_15 = 4500
        else:
            threshold_20 = 2000
            threshold_30 = 3000
            threshold_50 = 5000
            threshold_15 = 1500

        # 1. Rules from What Changed? drivers
        drivers = changes_data.get("drivers", [])
        total_delta_minor = changes_data.get("total_delta_minor", 0)

        for d in drivers:
            delta = d["delta_minor"]
            share = d.get("share_of_increase", 0.0)
            name = d["name"]
            cid = d["entity_id"]
            insight_key = f"category_change:{cid}"

            if InsightHistoryTracker.is_dismissed(insight_key):
                continue

            # Significant category increase
            if delta > threshold_20 and share >= 0.20:
                freq_eff = d.get("frequency_effect_minor", 0)
                ticket_eff = d.get("ticket_effect_minor", 0)
                ref_eff = d.get("refund_effect_minor", 0)
                pct_share = round(share * 100)

                driver_narrative = ""
                if ref_eff < 0 and abs(ref_eff) > abs(freq_eff):
                    driver_narrative = "partially offset by refunds"
                elif freq_eff > ticket_eff and freq_eff > 0:
                    driver_narrative = "mainly driven by more frequent purchases"
                elif ticket_eff > 0:
                    driver_narrative = "mainly driven by higher average purchase sizes"
                else:
                    driver_narrative = "reflecting higher spending volume"

                novelty = InsightHistoryTracker.compute_novelty_score(insight_key, delta)

                candidates.append(Insight(
                    id=f"change_{cid}_{month}",
                    insight_type="CHANGE",
                    title=f"{name} drove {pct_share}% of spending increase",
                    summary=f"{name} increased by {format_money(delta, currency)}, {driver_narrative}.",
                    metric="net_spending",
                    entity_type="category",
                    entity_id=cid,
                    current_value_minor=d["current_minor"],
                    baseline_value_minor=d["previous_minor"],
                    delta_value_minor=delta,
                    delta_percent=round((delta / float(d["previous_minor"]) * 100.0), 1) if d["previous_minor"] > 0 else 100.0,
                    severity="warning" if delta > threshold_50 else "info",
                    confidence="high",
                    impact_score=min(1.0, (delta / float(max(1, total_curr_minor))) * 3.0),
                    unusualness_score=0.6,
                    actionability_score=0.85,
                    novelty_score=novelty,
                    final_rank_score=0.0,
                    drilldown_filter={"category_id": cid, "month": month},
                    evidence={
                        "category": name,
                        "current": float(minor_to_major(d["current_minor"], currency)),
                        "previous": float(minor_to_major(d["previous_minor"], currency)),
                        "delta": float(minor_to_major(delta, currency)),
                        "share_of_increase": f"{pct_share}%",
                        "frequency_effect": float(minor_to_major(freq_eff, currency)),
                        "ticket_effect": float(minor_to_major(ticket_eff, currency)),
                        "refund_effect": float(minor_to_major(ref_eff, currency))
                    },
                    generated_at=now_str,
                    insight_key=insight_key,
                    currency=currency
                ))

            # Significant reduction (achievement)
            elif delta < -threshold_30:
                achieve_key = f"achievement:{cid}"
                if not InsightHistoryTracker.is_dismissed(achieve_key):
                    pct_drop = round(abs(delta) / float(d["previous_minor"]) * 100.0) if d["previous_minor"] > 0 else 0
                    novelty = InsightHistoryTracker.compute_novelty_score(achieve_key, abs(delta))
                    candidates.append(Insight(
                        id=f"achieve_{cid}_{month}",
                        insight_type="ACHIEVEMENT",
                        title=f"{name} spending dropped {pct_drop}%",
                        summary=f"You reduced {name} spending by {format_money(abs(delta), currency)} compared to last month.",
                        metric="net_spending",
                        entity_type="category",
                        entity_id=cid,
                        current_value_minor=d["current_minor"],
                        baseline_value_minor=d["previous_minor"],
                        delta_value_minor=delta,
                        delta_percent=-float(pct_drop),
                        severity="success",
                        confidence="high",
                        impact_score=min(1.0, (abs(delta) / float(max(1, total_curr_minor))) * 2.5),
                        unusualness_score=0.5,
                        actionability_score=0.6,
                        novelty_score=novelty,
                        final_rank_score=0.0,
                        drilldown_filter={"category_id": cid, "month": month},
                        evidence={
                            "category": name,
                            "saved": float(minor_to_major(abs(delta), currency)),
                            "drop_pct": f"{pct_drop}%"
                        },
                        generated_at=now_str,
                        insight_key=achieve_key,
                        currency=currency
                    ))

        # 2. Rules from Anomalies
        for a in anomalies_data:
            a_id = a.get("anomaly_id", "")
            if InsightHistoryTracker.is_dismissed(a_id):
                continue

            sev = a.get("severity", "moderate")
            sev_map = {"strong": "critical", "moderate": "warning", "mild": "info"}
            actual_m = a.get("actual_minor", 0)
            expected_m = a.get("expected_median_minor", 0)
            diff_m = max(0, actual_m - expected_m)
            novelty = InsightHistoryTracker.compute_novelty_score(a_id, diff_m)

            candidates.append(Insight(
                id=a_id,
                insight_type="ANOMALY",
                title=a.get("title", "Spending anomaly detected"),
                summary=a.get("explanation", ""),
                metric=a.get("anomaly_type", "anomaly"),
                entity_type=a.get("entity_type", "transaction"),
                entity_id=a.get("entity_id"),
                current_value_minor=actual_m,
                baseline_value_minor=expected_m,
                delta_value_minor=diff_m,
                delta_percent=round((diff_m / float(expected_m) * 100.0), 1) if expected_m > 0 else 0.0,
                severity=sev_map.get(sev, "warning"),
                confidence=a.get("confidence", "moderate"),
                impact_score=min(1.0, (diff_m / float(max(1, total_curr_minor))) * 3.5),
                unusualness_score=min(1.0, a.get("robust_score", 3.0) / 6.0),
                actionability_score=0.9,
                novelty_score=novelty,
                final_rank_score=0.0,
                drilldown_filter=a.get("drilldown_filter", {}),
                evidence={
                    "normal_range_lower": a.get("normal_range_lower", 0),
                    "normal_range_upper": a.get("normal_range_upper", 0),
                    "robust_score": a.get("robust_score", 0)
                },
                generated_at=now_str,
                insight_key=a_id,
                currency=a.get("currency") or currency
            ))

        # 3. Rules from Forecast & Budgets
        budget_m = forecast_data.get("budget_minor")
        proj_m = forecast_data.get("projected_expense_minor", 0)
        fc_key = f"forecast_risk:{month}"

        if budget_m and proj_m > budget_m and not InsightHistoryTracker.is_dismissed(fc_key):
            over_m = proj_m - budget_m
            over_pct = round(over_m / float(budget_m) * 100.0, 1)
            novelty = InsightHistoryTracker.compute_novelty_score(fc_key, over_m)

            candidates.append(Insight(
                id=f"forecast_overrun_{month}",
                insight_type="FORECAST",
                title=f"Projected to exceed budget by {over_pct}%",
                summary=f"At current pace, projected spending is {format_money(proj_m, currency)}, which is {format_money(over_m, currency)} over your monthly budget.",
                metric="budget_variance",
                entity_type="budget",
                entity_id=None,
                current_value_minor=proj_m,
                baseline_value_minor=budget_m,
                delta_value_minor=over_m,
                delta_percent=over_pct,
                severity="critical" if over_pct > 15 else "warning",
                confidence=forecast_data.get("confidence", "moderate"),
                impact_score=min(1.0, (over_m / float(budget_m)) * 2.5),
                unusualness_score=0.7,
                actionability_score=0.95,
                novelty_score=novelty,
                final_rank_score=0.0,
                drilldown_filter={"view": "forecast", "month": month},
                evidence={
                    "projected": float(minor_to_major(proj_m, currency)),
                    "budget": float(minor_to_major(budget_m, currency)),
                    "overrun": float(minor_to_major(over_m, currency)),
                    "method": forecast_data.get("method")
                },
                generated_at=now_str,
                insight_key=fc_key,
                currency=currency
            ))

        # 4. Rules from Category Budgets Overrun
        for c in forecast_data.get("category_forecasts", []):
            if c.get("is_over_budget"):
                var_m = c.get("projected_variance_minor", 0)
                cid = c.get("category_id")
                c_name = c.get("name")
                b_key = f"cat_budget_risk:{cid}"

                if var_m > threshold_15 and not InsightHistoryTracker.is_dismissed(b_key):
                    novelty = InsightHistoryTracker.compute_novelty_score(b_key, var_m)
                    c_proj_m = c.get("projected_minor", 0)
                    c_bud_m = c.get("budget_minor", 0)
                    candidates.append(Insight(
                        id=f"cat_overrun_{cid}_{month}",
                        insight_type="BUDGET",
                        title=f"{c_name} at risk of exceeding budget",
                        summary=f"{c_name} is projected to reach {format_money(c_proj_m, currency)}, exceeding its {format_money(c_bud_m, currency)} budget.",
                        metric="category_budget",
                        entity_type="category",
                        entity_id=cid,
                        current_value_minor=c_proj_m,
                        baseline_value_minor=c_bud_m,
                        delta_value_minor=var_m,
                        delta_percent=round(var_m / float(c.get("budget_minor", 1)) * 100.0, 1),
                        severity="warning",
                        confidence="moderate",
                        impact_score=min(1.0, (var_m / float(max(1, total_curr_minor))) * 3.0),
                        unusualness_score=0.6,
                        actionability_score=0.9,
                        novelty_score=novelty,
                        final_rank_score=0.0,
                        drilldown_filter={"category_id": cid, "month": month},
                        evidence={
                            "projected": c.get("projected"),
                            "budget": c.get("budget"),
                            "variance": c.get("projected_variance")
                        },
                        generated_at=now_str,
                        insight_key=b_key,
                        currency=currency
                    ))

        return candidates
