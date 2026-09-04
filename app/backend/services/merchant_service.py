"""
Merchant Intelligence & Canonicalisation Service for FinScope CORE.
Provides:
- Merchant Name Normalisation (cleaning store codes, casing, suffixes)
- Canonical Merchant Registry & Rule Engine
- Merchant Memory: Learn default category, account, and essentiality based on transaction history
- Fast Autocomplete with Confidence Scoring
"""

import re
from typing import Dict, Any, List, Optional
from app.backend.database.connection import get_db_connection

def normalize_merchant_name(raw: str) -> str:
    """Cleans up raw payee strings (e.g. 'WOOLWORTHS 1234' -> 'Woolworths')."""
    if not raw:
        return ""
    text = raw.strip()
    # Strip common bank transaction noise like 'POS WDL', 'DEBIT PURCHASE', 'DIRECT DEBIT'
    text = re.sub(r'^(POS\s+WDL|DEBIT\s+PURCHASE|DIRECT\s+DEBIT)\s+', '', text, flags=re.IGNORECASE)
    # Strip asterisks e.g. UBER *EATS -> UBER EATS
    text = text.replace('*', ' ')
    # Remove trailing digits/store numbers e.g. "Store 1234", "STORE #49", " #456", " 9876"
    text = re.sub(r'\s+(STORE\s*#?\s*\d+|BRANCH\s*#?\s*\d+|#\s*\d+|\d{3,}).*$', '', text, flags=re.IGNORECASE)
    # Strip common city / country trailing suffixes like SYDNEY, MELBOURNE, BRISBANE, AU, AUS
    text = re.sub(r'\s+(SYDNEY|MELBOURNE|BRISBANE|PERTH|ADELAIDE|AU|AUS)$', '', text, flags=re.IGNORECASE)
    # Collapse multiple whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # If all uppercase or all lowercase, apply title case
    if text.isupper() or text.islower():
        text = text.title()
    # Brand casing overrides
    if text.lower() == "mcdonalds":
        text = "McDonalds"
    elif text.lower() == "mcdonald's":
        text = "McDonald's"
    return text

class MerchantService:
    @staticmethod
    def get_or_create_merchant(
        raw_name: str,
        category_id: Optional[int] = None,
        account_id: Optional[int] = None,
        essentiality: Optional[str] = None
    ) -> int:
        """Finds or creates a canonical merchant and updates its smart defaults."""
        canonical_name = normalize_merchant_name(raw_name)
        if not canonical_name:
            return 0

        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, default_category_id, preferred_account_id, default_essentiality FROM merchants WHERE name = ?", (canonical_name,))
            row = cur.fetchone()

            if row:
                m_id = row["id"]
                # Update defaults if provided
                updates = []
                params = []
                if category_id and not row["default_category_id"]:
                    updates.append("default_category_id = ?")
                    params.append(category_id)
                if account_id and not row["preferred_account_id"]:
                    updates.append("preferred_account_id = ?")
                    params.append(account_id)
                if essentiality and row["default_essentiality"] == "discretionary" and essentiality == "essential":
                    updates.append("default_essentiality = ?")
                    params.append(essentiality)

                if updates:
                    params.append(m_id)
                    conn.execute(f"UPDATE merchants SET {', '.join(updates)} WHERE id = ?", params)
                    conn.commit()
                return m_id
            else:
                cur.execute(
                    """
                    INSERT INTO merchants (name, default_category_id, preferred_account_id, default_essentiality)
                    VALUES (?, ?, ?, ?)
                    """,
                    (canonical_name, category_id, account_id, essentiality or "discretionary")
                )
                conn.commit()
                return cur.lastrowid

    @staticmethod
    def suggest_merchants(query: str, limit: int = 6) -> List[Dict[str, Any]]:
        """
        Returns autocomplete suggestions for payees with smart category,
        account, and essentiality defaults based on merchant rules and history.
        """
        if not query or len(query.strip()) < 1:
            return []

        clean_q = query.strip()
        like_pattern = f"%{clean_q}%"

        with get_db_connection() as conn:
            cur = conn.cursor()

            # 1. Search in merchants table
            cur.execute("""
                SELECT 
                    m.id,
                    m.name,
                    m.default_category_id,
                    m.preferred_account_id,
                    m.default_essentiality,
                    c.name as category_name,
                    c.color as category_color,
                    c.icon as category_icon,
                    a.name as account_name
                FROM merchants m
                LEFT JOIN categories c ON m.default_category_id = c.id
                LEFT JOIN accounts a ON m.preferred_account_id = a.id
                WHERE m.name LIKE ?
                ORDER BY 
                    CASE WHEN m.name LIKE ? THEN 0 ELSE 1 END,
                    m.name ASC
                LIMIT ?
            """, (like_pattern, f"{clean_q}%", limit))

            rows = cur.fetchall()
            results = []

            for r in rows:
                m_id = r["id"]
                # Query active expense transaction history for statistical confidence
                cur.execute("""
                    SELECT category_id, COUNT(*) as cnt
                    FROM active_transactions
                    WHERE merchant_name = ? 
                      AND category_id IS NOT NULL
                      AND transaction_type = 'expense'
                    GROUP BY category_id
                    ORDER BY cnt DESC
                """, (r["name"],))
                hist_rows = cur.fetchall()

                cat_id = r["default_category_id"]
                cat_name = r["category_name"]
                cat_color = r["category_color"]
                cat_icon = r["category_icon"]
                total_hist = sum(hr["cnt"] for hr in hist_rows) if hist_rows else 0

                confidence = "low"
                if r["default_category_id"]:
                    confidence = "high"
                elif hist_rows:
                    top_cnt = hist_rows[0]["cnt"]
                    if top_cnt / total_hist >= 0.8 and total_hist >= 3:
                        confidence = "high"
                    elif total_hist >= 2:
                        confidence = "moderate"

                    # If no explicit default set, use top historical category
                    if not cat_id and hist_rows[0]["category_id"]:
                        top_cid = hist_rows[0]["category_id"]
                        cur.execute("SELECT name, color, icon FROM categories WHERE id = ?", (top_cid,))
                        c_info = cur.fetchone()
                        if c_info:
                            cat_id = top_cid
                            cat_name = c_info["name"]
                            cat_color = c_info["color"]
                            cat_icon = c_info["icon"]

                results.append({
                    "merchant_id": m_id,
                    "id": m_id,
                    "name": r["name"],
                    "merchant_name": r["name"],
                    "category_id": cat_id,
                    "category_name": cat_name,
                    "category_color": cat_color,
                    "category_icon": cat_icon,
                    "account_id": r["preferred_account_id"],
                    "preferred_account_id": r["preferred_account_id"],
                    "account_name": r["account_name"],
                    "essentiality": r["default_essentiality"] or "discretionary",
                    "confidence": confidence,
                    "transaction_count": total_hist
                })

            return results

    @staticmethod
    def get_recent_payees(limit: int = 5) -> List[Dict[str, Any]]:
        """Returns recently used distinct payees for quick one-click capture."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    t.merchant_name,
                    t.category_id,
                    t.account_id,
                    t.essentiality,
                    t.amount_minor,
                    c.name as category_name,
                    c.color as category_color,
                    c.icon as category_icon,
                    MAX(t.transaction_date) as last_used,
                    COUNT(*) as transaction_count
                FROM active_transactions t
                JOIN categories c ON t.category_id = c.id
                WHERE t.transaction_type = 'expense'
                  AND t.merchant_name != ''
                GROUP BY t.merchant_name
                ORDER BY last_used DESC
                LIMIT ?
            """, (limit,))

            items = []
            for r in cur.fetchall():
                items.append({
                    "merchant_id": None,
                    "id": None,
                    "name": r["merchant_name"],
                    "merchant_name": r["merchant_name"],
                    "category_id": r["category_id"],
                    "category_name": r["category_name"],
                    "category_color": r["category_color"],
                    "category_icon": r["category_icon"],
                    "account_id": r["account_id"],
                    "preferred_account_id": r["account_id"],
                    "essentiality": r["essentiality"],
                    "confidence": "high",
                    "transaction_count": r["transaction_count"],
                    "amount": round(r["amount_minor"] / 100.0, 2)
                })
            return items

# Module-level convenience aliases
get_or_create_merchant = MerchantService.get_or_create_merchant
suggest_merchants = MerchantService.suggest_merchants
get_recent_payees = MerchantService.get_recent_payees
