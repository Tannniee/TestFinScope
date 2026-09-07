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
    def get_or_create_merchant_in_conn(
        conn,
        raw_name: str,
        category_id: Optional[int] = None,
        account_id: Optional[int] = None,
        essentiality: Optional[str] = None
    ) -> int:
        """Finds or creates a canonical merchant on an existing DB connection (FSC-M15)."""
        canonical_name = normalize_merchant_name(raw_name)
        if not canonical_name:
            return 0

        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO merchants (name, default_category_id, preferred_account_id, default_essentiality)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO NOTHING
            """,
            (canonical_name, category_id, account_id, essentiality or "discretionary")
        )
        cur.execute("SELECT id, default_category_id, preferred_account_id, default_essentiality FROM merchants WHERE name = ?", (canonical_name,))
        row = cur.fetchone()
        if not row:
            return 0
        m_id = row["id"]

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
            cur.execute(f"UPDATE merchants SET {', '.join(updates)} WHERE id = ?", params)
        return m_id

    @staticmethod
    def get_or_create_merchant(
        raw_name: str,
        category_id: Optional[int] = None,
        account_id: Optional[int] = None,
        essentiality: Optional[str] = None
    ) -> int:
        """Finds or creates a canonical merchant and updates its smart defaults."""
        with get_db_connection() as conn:
            m_id = MerchantService.get_or_create_merchant_in_conn(
                conn, raw_name, category_id, account_id, essentiality
            )
            conn.commit()
            return m_id

    @staticmethod
    def learn_defaults_in_conn(
        conn,
        merchant_name_or_id: Any,
        category_id: Optional[int] = None,
        account_id: Optional[int] = None,
        essentiality: Optional[str] = None,
        overwrite: bool = True
    ) -> bool:
        """
        Learns or updates defaults for a merchant inside an existing connection/transaction (P0-05).
        """
        cur = conn.cursor()
        if isinstance(merchant_name_or_id, int):
            cur.execute("SELECT id, default_category_id, preferred_account_id, default_essentiality FROM merchants WHERE id = ?", (merchant_name_or_id,))
        else:
            cname = normalize_merchant_name(str(merchant_name_or_id))
            if not cname:
                return False
            cur.execute("SELECT id, default_category_id, preferred_account_id, default_essentiality FROM merchants WHERE name = ?", (cname,))
        row = cur.fetchone()
        if not row:
            if isinstance(merchant_name_or_id, str):
                m_id = MerchantService.get_or_create_merchant_in_conn(conn, merchant_name_or_id, category_id, account_id, essentiality)
                return m_id > 0
            return False

        m_id = row["id"]
        updates = []
        params = []
        if category_id is not None and (overwrite or not row["default_category_id"]):
            updates.append("default_category_id = ?")
            params.append(category_id)
        if account_id is not None and (overwrite or not row["preferred_account_id"]):
            updates.append("preferred_account_id = ?")
            params.append(account_id)
        if essentiality is not None and (overwrite or not row["default_essentiality"]):
            updates.append("default_essentiality = ?")
            params.append(essentiality)

        if updates:
            params.append(m_id)
            cur.execute(f"UPDATE merchants SET {', '.join(updates)} WHERE id = ?", params)
            return cur.rowcount > 0
        return True

    @staticmethod
    def learn_defaults(
        merchant_name_or_id: Any,
        category_id: Optional[int] = None,
        account_id: Optional[int] = None,
        essentiality: Optional[str] = None,
        overwrite: bool = True
    ) -> bool:
        """
        Learns or updates defaults for a merchant (FSC-M14).
        If overwrite is True (e.g. user manually confirmed/updated in review queue),
        authoritatively sets the specified defaults.
        """
        with get_db_connection() as conn:
            res = MerchantService.learn_defaults_in_conn(
                conn, merchant_name_or_id, category_id, account_id, essentiality, overwrite
            )
            conn.commit()
            return res

    @staticmethod
    def suggest_merchants(query: str, limit: int = 6) -> List[Dict[str, Any]]:
        """
        Returns autocomplete suggestions for payees with smart category,
        account, and essentiality defaults based on merchant rules and history.
        """
        if not query or len(query.strip()) < 1:
            return []

        clean_q = query.strip()[:100]
        like_pattern = f"%{clean_q}%"

        with get_db_connection() as conn:
            cur = conn.cursor()

            # 1. Search in merchants table
            safe_limit = max(1, min(limit or 10, 50))
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
            """, (like_pattern, f"{clean_q}%", safe_limit))

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
                    "default_category_id": cat_id,
                    "category_name": cat_name,
                    "category_color": cat_color,
                    "category_icon": cat_icon,
                    "account_id": r["preferred_account_id"],
                    "preferred_account_id": r["preferred_account_id"],
                    "account_name": r["account_name"],
                    "essentiality": r["default_essentiality"] or "discretionary",
                    "default_essentiality": r["default_essentiality"] or "discretionary",
                    "confidence": confidence,
                    "transaction_count": total_hist
                })

            return results

    @staticmethod
    def get_recent_payees(limit: int = 5) -> List[Dict[str, Any]]:
        """Returns recently used distinct payees for quick one-click capture."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            safe_limit = max(1, min(limit or 5, 50))
            cur.execute("""
                WITH ranked AS (
                    SELECT 
                        t.merchant_name,
                        t.category_id,
                        t.account_id,
                        t.essentiality,
                        t.amount_minor,
                        t.transaction_date as last_used,
                        t.id,
                        COUNT(*) OVER (PARTITION BY t.merchant_name) as transaction_count,
                        ROW_NUMBER() OVER (
                            PARTITION BY t.merchant_name
                            ORDER BY
                                t.transaction_date DESC,
                                t.transaction_time DESC,
                                t.id DESC
                        ) AS rn
                    FROM active_transactions t
                    WHERE t.transaction_type = 'expense'
                      AND t.merchant_name IS NOT NULL
                      AND TRIM(t.merchant_name) != ''
                )
                SELECT 
                    r.merchant_name,
                    r.category_id,
                    r.account_id,
                    r.essentiality,
                    r.amount_minor,
                    r.last_used,
                    r.transaction_count,
                    c.name as category_name,
                    c.color as category_color,
                    c.icon as category_icon
                FROM ranked r
                LEFT JOIN categories c ON r.category_id = c.id
                WHERE r.rn = 1
                ORDER BY r.last_used DESC, r.id DESC
                LIMIT ?
            """, (safe_limit,))

            items = []
            for r in cur.fetchall():
                items.append({
                    "merchant_id": None,
                    "id": None,
                    "name": r["merchant_name"],
                    "merchant_name": r["merchant_name"],
                    "category_id": r["category_id"],
                    "default_category_id": r["category_id"],
                    "category_name": r["category_name"],
                    "category_color": r["category_color"],
                    "category_icon": r["category_icon"],
                    "account_id": r["account_id"],
                    "preferred_account_id": r["account_id"],
                    "essentiality": r["essentiality"],
                    "default_essentiality": r["essentiality"],
                    "confidence": "high",
                    "transaction_count": r["transaction_count"],
                    "amount": round(r["amount_minor"] / 100.0, 2)
                })
            return items

# Module-level convenience aliases
get_or_create_merchant = MerchantService.get_or_create_merchant
suggest_merchants = MerchantService.suggest_merchants
get_recent_payees = MerchantService.get_recent_payees
