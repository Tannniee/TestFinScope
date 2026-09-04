from typing import List, Dict, Any, Optional
from app.backend.database.connection import get_db_connection

class BudgetRepository:
    @staticmethod
    def get_by_month(month: str) -> List[Dict[str, Any]]:
        """
        Returns all budgets for a given month (YYYY-MM), joined with actual net expense spend
        (expenses minus refunds).
        """
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    b.id,
                    b.category_id,
                    b.amount_minor,
                    ROUND(CAST(b.amount_minor AS REAL) / 100.0, 2) as budget_amount,
                    b.start_date,
                    c.name as category_name,
                    c.color as category_color,
                    c.icon as category_icon,
                    ROUND(
                        CAST(
                            COALESCE(
                                SUM(
                                    CASE 
                                        WHEN t.transaction_type = 'expense' THEN t.amount_minor
                                        WHEN t.transaction_type = 'refund' THEN -t.amount_minor
                                        ELSE 0
                                    END
                                ), 0
                            ) AS REAL
                        ) / 100.0, 2
                    ) as spent_amount
                FROM categories c
                LEFT JOIN budgets b ON b.category_id = c.id AND b.start_date = ?
                LEFT JOIN transactions t ON t.category_id = c.id 
                    AND t.transaction_type IN ('expense', 'refund')
                    AND t.transaction_date LIKE ?
                WHERE c.type = 'expense' AND c.is_archived = 0
                GROUP BY c.id, b.id
                ORDER BY b.amount_minor DESC, c.name ASC
            """, (month, f"{month}%"))
            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def set_budget(category_id: int, month: str, amount: float) -> int:
        amount_minor = int(round(float(amount) * 100))
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO budgets (category_id, start_date, amount_minor, period_type)
                VALUES (?, ?, ?, 'monthly')
                ON CONFLICT(category_id, start_date) DO UPDATE SET
                    amount_minor = excluded.amount_minor
            """, (category_id, month, amount_minor))
            conn.commit()
            return cur.lastrowid

    @staticmethod
    def delete_budget(budget_id: int) -> bool:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM budgets WHERE id = ?", (budget_id,))
            conn.commit()
            return cur.rowcount > 0
