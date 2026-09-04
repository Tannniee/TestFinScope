"""
Candidate Insight Rules Generator for FinScope.
Generates candidate insights from analytical modules:
- What Changed? drivers (frequency vs ticket effects)
- Rolling historical norm deviations
- Transaction & category anomalies
- Budget & forecast risk projections
- Positive financial achievements
"""

import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
from app.backend.analytics.models import Insight

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

        # 1. Rules from What Changed? drivers
        drivers = changes_data.get("drivers", [])
        total_delta_minor = changes_data.get("total_delta_minor", 0)

        for d in drivers:
            delta = d["delta_minor"]
            share = d.get("share_of_increase", 0.0)
            name = d["name"]
            cid = d["entity_id"]

            # Significant category increase
            if delta > 2000 and share >= 0.20:  # > $20 and >= 20% of increase
                freq_eff = d.get("frequency_effect_minor", 0)
                ticket_eff = d.get("ticket_effect_minor", 0)
                pct_share = round(share * 100)

                driver_narrative = ""
                if freq_eff > ticket_eff and freq_eff > 0:
                    driver_narrative = "mainly driven by more frequent purchases"
                elif ticket_eff > 0:
                    driver_narrative = "mainly driven by higher average purchase sizes"
                else:
                    driver_narrative = "reflecting higher spending volume"

                candidates.append(Insight(
                    id=f"change_{cid}_{month}",
                    insight_type="CHANGE",
                    title=f"{name} drove {pct_share}% of spending increase",
                    summary=f"{name} increased by {round(delta / 100.0, 2)}, {driver_narrative}.",
                    metric="net_spending",
                    entity_type="category",
                    entity_id=cid,
                    current_value_minor=d["current_minor"],
                    baseline_value_minor=d["previous_minor"],
                    delta_value_minor=delta,
                    delta_percent=round((delta / d["previous_minor"] * 100.0), 1) if d["previous_minor"] > 0 else 100.0,
                    severity="warning" if delta > 5000 else "info",
                    confidence="high",
                    impact_score=min(1.0, (delta / max(1, total_curr_minor)) * 3.0),
                    unusualness_score=0.6,
                    actionability_score=0.85,
                    novelty_score=0.8,
                    final_rank_score=0.0,
                    drilldown_filter={"category_id": cid, "month": month},
                    evidence={
                        "category": name,
                        "current": round(d["current_minor"] / 100.0, 2),
                        "previous": round(d["previous_minor"] / 100.0, 2),
                        "delta": round(delta / 100.0, 2),
                        "share_of_increase": f"{pct_share}%",
                        "frequency_effect": round(freq_eff / 100.0, 2),
                        "ticket_effect": round(ticket_eff / 100.0, 2)
                    },
                    generated_at=now_str
                ))

            # Significant reduction (achievement)
            elif delta < -3000:
                pct_drop = round(abs(delta) / d["previous_minor"] * 100.0) if d["previous_minor"] > 0 else 0
                candidates.append(Insight(
                    id=f"achieve_{cid}_{month}",
                    insight_type="ACHIEVEMENT",
                    title=f"{name} spending dropped {pct_drop}%",
                    summary=f"You reduced {name} spending by {round(abs(delta) / 100.0, 2)} compared to last month.",
                    metric="net_spending",
                    entity_type="category",
                    entity_id=cid,
                    current_value_minor=d["current_minor"],
                    baseline_value_minor=d["previous_minor"],
                    delta_value_minor=delta,
                    delta_percent=-float(pct_drop),
                    severity="success",
                    confidence="high",
                    impact_score=min(1.0, (abs(delta) / max(1, total_curr_minor)) * 2.5),
                    unusualness_score=0.5,
                    actionability_score=0.5,
                    novelty_score=0.7,
                    final_rank_score=0.0,
                    drilldown_filter={"category_id": cid, "month": month},
                    evidence={
                        "category": name,
                        "current": round(d["current_minor"] / 100.0, 2),
                        "previous": round(d["previous_minor"] / 100.0, 2),
                        "savings": round(abs(delta) / 100.0, 2)
                    },
                    generated_at=now_str
                ))

        # 2. Weekend Shift insight
        weekend_delta = changes_data.get("weekend_delta_minor", 0)
        if total_delta_minor > 0 and weekend_delta > 0:
            weekend_share = (weekend_delta / total_delta_minor)
            if weekend_share >= 0.50 and weekend_delta > 2000:
                pct_w = round(weekend_share * 100)
                candidates.append(Insight(
                    id=f"weekend_shift_{month}",
                    insight_type="BEHAVIOUR",
                    title=f"{pct_w}% of spending increase occurred on weekends",
                    summary=f"Weekend spending increased by {round(weekend_delta / 100.0, 2)}, outpacing weekday changes.",
                    metric="weekend_spend",
                    entity_type="overview",
                    entity_id=None,
                    current_value_minor=weekend_delta,
                    baseline_value_minor=0,
                    delta_value_minor=weekend_delta,
                    delta_percent=float(pct_w),
                    severity="info",
                    confidence="moderate",
                    impact_score=min(1.0, (weekend_delta / max(1, total_curr_minor)) * 2.0),
                    unusualness_score=0.7,
                    actionability_score=0.75,
                    novelty_score=0.8,
                    final_rank_score=0.0,
                    drilldown_filter={"month": month},
                    evidence={
                        "weekend_increase": round(weekend_delta / 100.0, 2),
                        "share_of_total_increase": f"{pct_w}%"
                    },
                    generated_at=now_str
                ))

        # 3. Rules from Anomalies
        for a in anomalies_data:
            a_type = a.get("anomaly_type")
            score = a.get("robust_score", 0.0)
            amt = a.get("actual_minor", 0)
            med = a.get("expected_median_minor", 0)
            diff = amt - med

            if a_type == "transaction_amount":
                candidates.append(Insight(
                    id=f"anom_tx_{a['entity_id']}",
                    insight_type="ANOMALY",
                    title=a["title"],
                    summary=a["explanation"],
                    metric="transaction_amount",
                    entity_type="transaction",
                    entity_id=a["entity_id"],
                    current_value_minor=amt,
                    baseline_value_minor=med,
                    delta_value_minor=diff,
                    delta_percent=round((diff / med * 100.0), 1) if med > 0 else 0.0,
                    severity="warning" if a["severity"] == "strong" else "info",
                    confidence=a.get("confidence", "moderate"),
                    impact_score=min(1.0, (diff / max(1, total_curr_minor)) * 3.5),
                    unusualness_score=min(1.0, score / 5.0),
                    actionability_score=0.7,
                    novelty_score=0.9,
                    final_rank_score=0.0,
                    drilldown_filter=a.get("drilldown_filter", {}),
                    evidence={
                        "merchant_or_desc": a["entity_name"],
                        "actual": a["actual"],
                        "expected_median": a["expected_median"],
                        "normal_range": f"{a['normal_range_lower']}–{a['normal_range_upper']}"
                    },
                    generated_at=now_str
                ))

            elif a_type == "recurring_jump":
                candidates.append(Insight(
                    id=f"anom_rec_{a['entity_id']}",
                    insight_type="RECURRING",
                    title=a["title"],
                    summary=a["explanation"],
                    metric="recurring_bill",
                    entity_type="transaction",
                    entity_id=a["entity_id"],
                    current_value_minor=amt,
                    baseline_value_minor=med,
                    delta_value_minor=diff,
                    delta_percent=round((diff / med * 100.0), 1) if med > 0 else 0.0,
                    severity="warning",
                    confidence="high",
                    impact_score=min(1.0, (diff / max(1, total_curr_minor)) * 3.0),
                    unusualness_score=0.85,
                    actionability_score=0.95,
                    novelty_score=0.9,
                    final_rank_score=0.0,
                    drilldown_filter=a.get("drilldown_filter", {}),
                    evidence={
                        "bill": a["entity_name"],
                        "previous_rate": a["expected_median"],
                        "new_rate": a["actual"],
                        "difference": round(diff / 100.0, 2)
                    },
                    generated_at=now_str
                ))

            elif a_type == "category_monthly":
                candidates.append(Insight(
                    id=f"anom_cat_{a['entity_id']}_{month}",
                    insight_type="ANOMALY",
                    title=a["title"],
                    summary=a["explanation"],
                    metric="category_spend",
                    entity_type="category",
                    entity_id=a["entity_id"],
                    current_value_minor=amt,
                    baseline_value_minor=med,
                    delta_value_minor=diff,
                    delta_percent=round((diff / med * 100.0), 1) if med > 0 else 0.0,
                    severity="warning",
                    confidence=a.get("confidence", "moderate"),
                    impact_score=min(1.0, (diff / max(1, total_curr_minor)) * 3.0),
                    unusualness_score=min(1.0, score / 4.0),
                    actionability_score=0.8,
                    novelty_score=0.8,
                    final_rank_score=0.0,
                    drilldown_filter=a.get("drilldown_filter", {}),
                    evidence={
                        "category": a["entity_name"],
                        "actual": a["actual"],
                        "6m_median": a["expected_median"],
                        "typical_range": f"{a['normal_range_lower']}–{a['normal_range_upper']}"
                    },
                    generated_at=now_str
                ))

        # 4. Rules from Forecasting & Budget Risk
        proj_var = forecast_data.get("projected_variance_minor")
        if proj_var and proj_var > 3000:  # Projected > $30 over budget
            over_amt = round(proj_var / 100.0, 2)
            candidates.append(Insight(
                id=f"forecast_budget_risk_{month}",
                insight_type="BUDGET",
                title=f"Projected to exceed budget by {over_amt}",
                summary=f"At the current spending pace and upcoming bills, you are on track to spend {over_amt} over your budget.",
                metric="projected_expense",
                entity_type="budget",
                entity_id=None,
                current_value_minor=forecast_data.get("projected_expense_minor", 0),
                baseline_value_minor=forecast_data.get("budget_minor", 0),
                delta_value_minor=proj_var,
                delta_percent=round(proj_var / max(1, forecast_data.get("budget_minor", 1)) * 100.0, 1),
                severity="critical" if proj_var > 10000 else "warning",
                confidence=forecast_data.get("confidence", "moderate"),
                impact_score=min(1.0, (proj_var / max(1, total_curr_minor)) * 3.0),
                unusualness_score=0.7,
                actionability_score=0.95,
                novelty_score=0.85,
                final_rank_score=0.0,
                drilldown_filter={"month": month},
                evidence={
                    "budget": forecast_data.get("budget"),
                    "projected": forecast_data.get("projected_expense"),
                    "overrun": over_amt,
                    "likely_range": f"{forecast_data.get('lower_bound')}–{forecast_data.get('upper_bound')}"
                },
                generated_at=now_str
            ))

        return candidates
