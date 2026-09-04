from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

@dataclass
class ReconciliationResult:
    """
    Deterministic audit verification result for financial and analytical calculations.
    Ensures zero floating-point drift and enforces mathematical identities down to the exact cent.
    """
    name: str
    expected_minor: int
    actual_minor: int
    difference_minor: int
    passed: bool
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "expected_minor": self.expected_minor,
            "expected": round(self.expected_minor / 100.0, 2),
            "actual_minor": self.actual_minor,
            "actual": round(self.actual_minor / 100.0, 2),
            "difference_minor": self.difference_minor,
            "difference": round(self.difference_minor / 100.0, 2),
            "passed": self.passed,
            "details": self.details
        }

def reconcile_period_totals(
    gross_expense_minor: int,
    refund_minor: int,
    net_spending_minor: int
) -> ReconciliationResult:
    """
    Verifies that Net Spending = Gross Expense - Refunds (clamped to 0).
    Identity: Net Spending === max(0, Gross Expense - Refund)
    """
    expected = max(0, gross_expense_minor - refund_minor)
    diff = net_spending_minor - expected
    passed = (diff == 0)

    return ReconciliationResult(
        name="period_net_spending",
        expected_minor=expected,
        actual_minor=net_spending_minor,
        difference_minor=diff,
        passed=passed,
        details={
            "gross_expense_minor": gross_expense_minor,
            "refund_minor": refund_minor
        }
    )

def reconcile_category_totals(
    category_items: List[Dict[str, Any]],
    net_spending_minor: int
) -> ReconciliationResult:
    """
    Verifies that the sum of net category amounts equals the total net spending.
    """
    cat_sum_minor = sum(c.get("net_cat_minor", c.get("amount_minor", 0)) for c in category_items)
    diff = net_spending_minor - cat_sum_minor
    # We allow exact match
    passed = (diff == 0)

    return ReconciliationResult(
        name="category_net_totals",
        expected_minor=net_spending_minor,
        actual_minor=cat_sum_minor,
        difference_minor=diff,
        passed=passed,
        details={
            "category_count": len(category_items)
        }
    )

def reconcile_change_decomposition(
    net_delta_minor: int,
    frequency_effect_minor: int,
    ticket_effect_minor: int,
    refund_effect_minor: int
) -> ReconciliationResult:
    """
    Verifies What Changed v2.1 exact identity:
    Net Delta === Frequency Effect + Ticket Effect + Refund Effect
    """
    effects_sum = frequency_effect_minor + ticket_effect_minor + refund_effect_minor
    diff = net_delta_minor - effects_sum
    passed = (diff == 0)

    return ReconciliationResult(
        name="change_decomposition",
        expected_minor=net_delta_minor,
        actual_minor=effects_sum,
        difference_minor=diff,
        passed=passed,
        details={
            "frequency_effect_minor": frequency_effect_minor,
            "ticket_effect_minor": ticket_effect_minor,
            "refund_effect_minor": refund_effect_minor
        }
    )

def reconcile_forecast_components(
    actual_to_date_minor: int,
    recurring_minor: int,
    variable_minor: int,
    irregular_minor: int,
    expected_refund_minor: int,
    total_projected_minor: Optional[int] = None,
    total_minor: Optional[int] = None
) -> ReconciliationResult:
    """
    Verifies Forecast V2 components identity:
    Total Projected === Actual + Future Recurring + Variable + Irregular - Expected Refund
    """
    tot_minor = total_projected_minor if total_projected_minor is not None else (total_minor or 0)
    expected = actual_to_date_minor + recurring_minor + variable_minor + irregular_minor - expected_refund_minor
    expected = max(0, expected)
    diff = tot_minor - expected
    passed = (diff == 0)

    return ReconciliationResult(
        name="forecast_components",
        expected_minor=expected,
        actual_minor=tot_minor,
        difference_minor=diff,
        passed=passed,
        details={
            "actual_to_date_minor": actual_to_date_minor,
            "recurring_minor": recurring_minor,
            "variable_minor": variable_minor,
            "irregular_minor": irregular_minor,
            "expected_refund_minor": expected_refund_minor
        }
    )
