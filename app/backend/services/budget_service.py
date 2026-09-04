import calendar
from datetime import datetime, date
from typing import Dict, Any, List
from app.backend.repositories.budget_repo import BudgetRepository

class BudgetService:
    @staticmethod
    def get_monthly_budget_status(month: str, account_id: Optional[int] = None) -> Dict[str, Any]:
        """Calculates budget pacing and month-end projections for all budgeted categories."""
        raw_items = BudgetRepository.get_by_month(month, account_id=account_id)
        
        # Calculate time pacing
        now = datetime.now()
        curr_year, curr_month = now.year, now.month
        target_year, target_month = map(int, month.split("-"))
        total_days = calendar.monthrange(target_year, target_month)[1]

        if target_year < curr_year or (target_year == curr_year and target_month < curr_month):
            days_elapsed = total_days
        elif target_year > curr_year or (target_year == curr_year and target_month > curr_month):
            days_elapsed = 0
        else:
            days_elapsed = min(now.day, total_days)

        elapsed_pct = round((days_elapsed / total_days) * 100.0, 1) if total_days > 0 else 0.0

        total_budget = 0.0
        total_spent = 0.0
        categories_result = []

        for item in raw_items:
            b_amount = item["budget_amount"] if item["budget_amount"] is not None else 0.0
            spent = round(item["spent_amount"], 2)

            if b_amount > 0:
                total_budget += b_amount
                total_spent += spent

                remaining = round(b_amount - spent, 2)
                consumed_pct = round((spent / b_amount) * 100.0, 1)

                # Month-end projection
                if days_elapsed > 0:
                    projected_spend = round((spent / days_elapsed) * total_days, 2)
                else:
                    projected_spend = spent

                projected_diff = round(projected_spend - b_amount, 2)

                # Determine pacing status
                if consumed_pct >= 100.0:
                    status = "over_budget"
                    status_label = "Over Budget"
                elif consumed_pct > (elapsed_pct + 15.0):
                    status = "watch"
                    status_label = "Spending Fast"
                else:
                    status = "on_track"
                    status_label = "On Track"

                categories_result.append({
                    "id": item["id"],
                    "category_id": item["category_id"],
                    "category_name": item["category_name"],
                    "category_color": item["category_color"],
                    "category_icon": item["category_icon"],
                    "budget": round(b_amount, 2),
                    "spent": spent,
                    "remaining": remaining,
                    "consumed_pct": consumed_pct,
                    "projected": projected_spend,
                    "projected_diff": projected_diff,
                    "status": status,
                    "status_label": status_label
                })
            else:
                # Unbudgeted category with spend
                if spent > 0:
                    categories_result.append({
                        "id": None,
                        "category_id": item["category_id"],
                        "category_name": item["category_name"],
                        "category_color": item["category_color"],
                        "category_icon": item["category_icon"],
                        "budget": 0.0,
                        "spent": spent,
                        "remaining": 0.0,
                        "consumed_pct": 0.0,
                        "projected": spent,
                        "projected_diff": spent,
                        "status": "unbudgeted",
                        "status_label": "No Budget Set"
                    })

        overall_consumed_pct = round((total_spent / total_budget * 100.0), 1) if total_budget > 0 else 0.0
        overall_remaining = round(total_budget - total_spent, 2)

        return {
            "month": month,
            "account_id": account_id,
            "days_elapsed": days_elapsed,
            "total_days": total_days,
            "elapsed_pct": elapsed_pct,
            "summary": {
                "total_budget": round(total_budget, 2),
                "total_spent": round(total_spent, 2),
                "remaining": overall_remaining,
                "consumed_pct": overall_consumed_pct,
                "is_over": total_spent > total_budget
            },
            "items": categories_result
        }
