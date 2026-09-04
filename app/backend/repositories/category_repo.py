from typing import List, Dict, Any, Optional
from app.backend.database.connection import get_db_connection

class CategoryRepository:
    @staticmethod
    def get_all(include_archived: bool = False, cat_type: Optional[str] = None) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            query = "SELECT * FROM categories WHERE 1=1"
            params = []
            if not include_archived:
                query += " AND is_archived = 0"
            if cat_type:
                query += " AND type = ?"
                params.append(cat_type)
            query += " ORDER BY type ASC, name ASC"
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def get_by_id(category_id: int) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM categories WHERE id = ?", (category_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_name(name: str) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM categories WHERE name = ? COLLATE NOCASE", (name,))
            row = cur.fetchone()
            return dict(row) if row else None

    @staticmethod
    def create(name: str, cat_type: str = "expense", icon: str = "tag", color: str = "#5B8CFF", parent_category_id: Optional[int] = None) -> int:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO categories (name, type, icon, color, parent_category_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, cat_type, icon, color, parent_category_id)
            )
            conn.commit()
            return cur.lastrowid

    @staticmethod
    def update(category_id: int, **fields) -> bool:
        allowed = {"name", "type", "icon", "color", "parent_category_id", "is_archived"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False

        set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [category_id]

        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(f"UPDATE categories SET {set_clause} WHERE id = ?", values)
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def delete(category_id: int) -> bool:
        with get_db_connection() as conn:
            cur = conn.cursor()
            # Set category_id = NULL in transactions first or soft delete
            cur.execute("SELECT COUNT(*) FROM transactions WHERE category_id = ?", (category_id,))
            if cur.fetchone()[0] > 0:
                cur.execute("UPDATE categories SET is_archived = 1 WHERE id = ?", (category_id,))
            else:
                cur.execute("DELETE FROM categories WHERE id = ?", (category_id,))
            conn.commit()
            return True
