import re
from typing import List, Dict, Any, Optional
from app.backend.database.connection import get_db_connection
from app.backend.domain.validators import validate_hex_color

def validate_category_icon(icon: Optional[str]) -> str:
    """Validates category icon name format against Lucide icon token rules and falls back to 'tag' (FSC-L04)."""
    if not icon or not isinstance(icon, str):
        return "tag"
    clean = icon.strip().lower()
    if re.match(r'^[a-z0-9-]+$', clean) and len(clean) <= 50:
        return clean
    return "tag"

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
        if not name or not name.strip():
            raise ValueError("Category name cannot be empty.")
        if cat_type not in ("expense", "income", "transfer"):
            raise ValueError(f"Invalid category type: '{cat_type}'.")
        clean_color = validate_hex_color(color)
        clean_icon = validate_category_icon(icon)
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO categories (name, type, icon, color, parent_category_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name.strip(), cat_type, clean_icon, clean_color, parent_category_id)
            )
            conn.commit()
            return cur.lastrowid

    @staticmethod
    def update(category_id: int, **fields) -> bool:
        allowed = {"name", "type", "icon", "color", "parent_category_id", "is_archived"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False

        if "name" in updates:
            if not updates["name"] or not str(updates["name"]).strip():
                raise ValueError("Category name cannot be empty.")
            updates["name"] = str(updates["name"]).strip()

        if "type" in updates and updates["type"] not in ("expense", "income", "transfer"):
            raise ValueError(f"Invalid category type: '{updates['type']}'.")

        if "color" in updates:
            updates["color"] = validate_hex_color(updates["color"])

        if "icon" in updates:
            updates["icon"] = validate_category_icon(updates["icon"])

        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, type FROM categories WHERE id = ?", (category_id,))
            row = cur.fetchone()
            if not row:
                return False

            if "type" in updates and updates["type"] != row["type"]:
                cur.execute("SELECT COUNT(*) FROM transactions WHERE category_id = ?", (category_id,))
                tx_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM budgets WHERE category_id = ?", (category_id,))
                b_count = cur.fetchone()[0]
                if tx_count > 0 or b_count > 0:
                    raise ValueError("Cannot change category type when historical transactions or budgets exist.")

            set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
            values = list(updates.values()) + [category_id]
            cur.execute(f"UPDATE categories SET {set_clause} WHERE id = ?", values)
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def delete(category_id: int) -> bool:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM categories WHERE id = ?", (category_id,))
            if not cur.fetchone():
                return False
            # Set category_id = NULL in transactions first or soft delete
            cur.execute("SELECT COUNT(*) FROM transactions WHERE category_id = ?", (category_id,))
            if cur.fetchone()[0] > 0:
                cur.execute("UPDATE categories SET is_archived = 1 WHERE id = ?", (category_id,))
            else:
                cur.execute("DELETE FROM categories WHERE id = ?", (category_id,))
            conn.commit()
            return True
