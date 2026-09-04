import calendar
from datetime import datetime, date
from typing import List, Dict, Any, Optional
from app.backend.database.connection import get_db_connection

class RecurringService:
    """
    Recurring Rules & Bills Lifecycle Service.
    Tracks fixed subscriptions, rent, salaries, utilities, and evaluates upcoming bills for forecasting.
    """

    @staticmethod
    def get_all(account_id: Optional[int] = None, active_only: bool = False) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            query = """
                SELECT 
                    r.id, r.name, r.transaction_type, r.amount_minor,
                    ROUND(CAST(r.amount_minor AS REAL) / 100.0, 2) as amount,
                    r.category_id, c.name as category_name, c.color as category_color, c.icon as category_icon,
                    r.account_id, a.name as account_name,
                    r.frequency, r.next_due_date, r.active, r.created_at
                FROM recurring_rules r
                LEFT JOIN categories c ON r.category_id = c.id
                LEFT JOIN accounts a ON r.account_id = a.id
                WHERE 1=1
            """
            params = []
            if account_id:
                query += " AND r.account_id = ?"
                params.append(account_id)
            if active_only:
                query += " AND r.active = 1"
            query += " ORDER BY r.name ASC"

            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    @classmethod
    def create(cls, data: Dict[str, Any]) -> int:
        """Convenience method accepting dictionary payload for rule creation."""
        return cls.create_rule(
            name=data["name"],
            amount=data["amount"],
            transaction_type=data.get("transaction_type", "expense"),
            category_id=data.get("category_id"),
            account_id=data.get("account_id"),
            frequency=data.get("frequency", "monthly"),
            next_due_date=data.get("next_due_date")
        )

    @staticmethod
    def create_rule(
        name: str,
        amount: float,
        transaction_type: str = "expense",
        category_id: Optional[int] = None,
        account_id: Optional[int] = None,
        frequency: str = "monthly",
        next_due_date: Optional[str] = None
    ) -> int:
        amount_minor = int(round(float(amount) * 100))
        if amount_minor <= 0:
            raise ValueError("Amount must be strictly positive.")

        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO recurring_rules (
                    name, transaction_type, amount_minor, category_id,
                    account_id, frequency, next_due_date, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """, (name, transaction_type, amount_minor, category_id, account_id, frequency, next_due_date))
            conn.commit()
            return cur.lastrowid

    @staticmethod
    def update_rule(rule_id: int, **fields) -> bool:
        allowed = {"name", "transaction_type", "category_id", "account_id", "frequency", "next_due_date", "active"}
        updates = {k: v for k, v in fields.items() if k in allowed}

        if "amount" in fields:
            updates["amount_minor"] = int(round(float(fields["amount"]) * 100))

        if not updates:
            return False

        set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [rule_id]

        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(f"UPDATE recurring_rules SET {set_clause} WHERE id = ?", values)
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def delete_rule(rule_id: int) -> bool:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM recurring_rules WHERE id = ?", (rule_id,))
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def get_upcoming_bills_for_month(
        month: str,
        account_id: Optional[int] = None,
        elapsed_day: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Evaluates active recurring rules against actual transactions in `month`.
        Marks each rule as 'paid' or 'upcoming'.
        """
        year, m_int = map(int, month.split("-"))
        total_days = calendar.monthrange(year, m_int)[1]
        now = datetime.now()
        if elapsed_day is None:
            if year == now.year and m_int == now.month:
                elapsed_day = min(total_days, now.day)
            elif year < now.year or (year == now.year and m_int < now.month):
                elapsed_day = total_days
            else:
                elapsed_day = 0

        rules = RecurringService.get_all(account_id=account_id, active_only=True)

        with get_db_connection() as conn:
            cur = conn.cursor()
            # Fetch active transactions in this month to check if bill has been paid
            cur.execute("""
                SELECT merchant_name, description, amount_minor, transaction_date, category_id, account_id, transaction_type
                FROM active_transactions
                WHERE transaction_date LIKE ?
            """, (f"{month}%",))
            month_txs = cur.fetchall()

        bills = []
        for r in rules:
            rule_name = r["name"].lower()
            amt_minor = r["amount_minor"]
            rule_acc = r.get("account_id")
            rule_type = r.get("transaction_type") or "expense"

            # Match by name or category + amount similarity, strictly enforcing type and account (AUD-005)
            is_paid = False
            paid_date = None
            for tx in month_txs:
                # Invariant 1: Transaction type must match rule type (e.g. refund/income cannot pay expense rule)
                if tx["transaction_type"] != rule_type:
                    continue
                # Invariant 2: Account must match if rule is scoped to an account
                if rule_acc is not None and tx["account_id"] != rule_acc:
                    continue

                tx_desc = (tx["merchant_name"] or tx["description"] or "").lower()
                if (rule_name in tx_desc or tx_desc in rule_name) or (tx["amount_minor"] == amt_minor and tx["category_id"] == r["category_id"]):
                    is_paid = True
                    paid_date = tx["transaction_date"]
                    break

            due_day = 15  # Default mid-month if no next_due_date
            if r["next_due_date"]:
                try:
                    due_day = int(r["next_due_date"].split("-")[-1])
                except (ValueError, IndexError):
                    due_day = 15

            due_date = f"{month}-{min(due_day, total_days):02d}"
            status = "paid" if is_paid else ("upcoming" if due_day > elapsed_day else "overdue")

            bills.append({
                "rule_id": r["id"],
                "name": r["name"],
                "transaction_type": r["transaction_type"],
                "amount": r["amount"],
                "amount_minor": amt_minor,
                "category_id": r["category_id"],
                "category_name": r["category_name"],
                "category_color": r["category_color"],
                "account_id": r["account_id"],
                "account_name": r["account_name"],
                "due_date": due_date,
                "due_day": due_day,
                "is_paid": is_paid,
                "paid_date": paid_date,
                "status": status
            })

        return bills

    # Convenience alias
    get_upcoming_bills = get_upcoming_bills_for_month

