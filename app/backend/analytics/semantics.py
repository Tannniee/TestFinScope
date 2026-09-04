"""
Canonical Financial Semantics Layer for FinScope.
Ensures single source of truth for:
- Income
- Gross Expense
- Refunds (offset expense)
- Transfers (completely isolated from P&L / savings rate)
- Cash In / Cash Out
- Net Spending vs Net Cash Flow
All monetary calculations in exact integer minor units (cents).
"""

from typing import Dict, Any, List

def calculate_net_spending(gross_expense_minor: int, refund_minor: int) -> int:
    """Net Spending = Gross Expense - Refunds. Never negative."""
    return max(0, gross_expense_minor - refund_minor)

def calculate_net_cash_flow(cash_in_minor: int, cash_out_minor: int) -> int:
    """Net Cash Flow = Cash In - Cash Out."""
    return cash_in_minor - cash_out_minor

def calculate_savings(income_minor: int, net_spending_minor: int) -> int:
    """Savings = Income - Net Spending."""
    return income_minor - net_spending_minor

def calculate_savings_rate(income_minor: int, net_spending_minor: int) -> float:
    """Savings Rate = (Income - Net Spending) / Income * 100."""
    if income_minor <= 0:
        return 0.0
    return round(((income_minor - net_spending_minor) / income_minor) * 100.0, 2)

def is_spending_transaction(tx_type: str) -> bool:
    return tx_type in ("expense", "refund")

def is_income_transaction(tx_type: str) -> bool:
    return tx_type == "income"

def is_transfer_transaction(tx_type: str) -> bool:
    return tx_type == "transfer"

def is_refund_transaction(tx_type: str) -> bool:
    return tx_type == "refund"

def classify_transaction_pnl_effect(tx_type: str, amount_minor: int) -> Dict[str, int]:
    """
    Returns the exact minor units effect across all financial semantics dimensions:
    - income_minor
    - gross_expense_minor
    - refund_minor
    - cash_in_minor
    - cash_out_minor
    - net_spending_minor
    """
    abs_amt = abs(amount_minor)
    if tx_type == "income":
        return {
            "income_minor": abs_amt,
            "gross_expense_minor": 0,
            "refund_minor": 0,
            "cash_in_minor": abs_amt,
            "cash_out_minor": 0,
            "net_spending_minor": 0
        }
    elif tx_type == "expense":
        return {
            "income_minor": 0,
            "gross_expense_minor": abs_amt,
            "refund_minor": 0,
            "cash_in_minor": 0,
            "cash_out_minor": abs_amt,
            "net_spending_minor": abs_amt
        }
    elif tx_type == "refund":
        return {
            "income_minor": 0,
            "gross_expense_minor": 0,
            "refund_minor": abs_amt,
            "cash_in_minor": abs_amt,
            "cash_out_minor": 0,
            "net_spending_minor": -abs_amt
        }
    elif tx_type == "transfer":
        # Pure asset movement, excluded from P&L
        return {
            "income_minor": 0,
            "gross_expense_minor": 0,
            "refund_minor": 0,
            "cash_in_minor": 0,
            "cash_out_minor": 0,
            "net_spending_minor": 0
        }
    return {
        "income_minor": 0,
        "gross_expense_minor": 0,
        "refund_minor": 0,
        "cash_in_minor": 0,
        "cash_out_minor": 0,
        "net_spending_minor": 0
    }
