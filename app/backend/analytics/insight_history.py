import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any, List
from app.backend.database.connection import get_db_connection

class InsightHistoryTracker:
    """
    Manages persistent memory of generated insights.
    Tracks times shown, novelty score decay, material change resets, and dismissals.
    """

    @staticmethod
    def get_insight_record(insight_key: str) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, insight_key, entity_type, entity_id, first_seen, last_seen,
                       times_shown, last_value_minor, last_rank, dismissed
                FROM insight_history
                WHERE insight_key = ?
            """, (insight_key,))
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)

    @staticmethod
    def is_dismissed(insight_key: str) -> bool:
        record = InsightHistoryTracker.get_insight_record(insight_key)
        return bool(record and record.get("dismissed", 0) == 1)

    @staticmethod
    def compute_novelty_score(insight_key: str, current_value_minor: int = 0) -> float:
        """
        Computes dynamic novelty score [0.1, 1.0]:
        - Brand new insight: 1.0
        - Shown 1 time: 0.85
        - Shown 2 times: 0.70
        - Shown 3 times: 0.50
        - Shown >= 4 times: 0.30
        - Material change reset: if value changed by >= 20% compared to last_value_minor, reset to 0.90!
        """
        record = InsightHistoryTracker.get_insight_record(insight_key)
        if not record:
            return 1.0

        if record.get("dismissed", 0) == 1:
            return 0.0

        times_shown = record.get("times_shown", 1)
        last_val = record.get("last_value_minor", 0)

        # Check for material change reset (>= 20% shift)
        if last_val > 0 and current_value_minor > 0:
            pct_shift = abs(current_value_minor - last_val) / float(last_val)
            if pct_shift >= 0.20:
                return 0.90

        if times_shown <= 1:
            return 0.85
        elif times_shown == 2:
            return 0.70
        elif times_shown == 3:
            return 0.50
        else:
            return 0.30

    @staticmethod
    def record_insights_shown(insights: List[Dict[str, Any]], month: str):
        """Records or updates history for top ranked insights that were displayed."""
        now_str = datetime.now().isoformat()
        with get_db_connection() as conn:
            cur = conn.cursor()
            for idx, item in enumerate(insights):
                key = item.get("insight_key") or f"{item.get('type')}:{item.get('title')}"
                entity_type = item.get("type", "general")
                entity_id = str(item.get("entity_id", ""))
                val_minor = int(item.get("impact_minor", 0))
                rank = idx + 1

                cur.execute("SELECT id, times_shown FROM insight_history WHERE insight_key = ?", (key,))
                existing = cur.fetchone()
                if existing:
                    cur.execute("""
                        UPDATE insight_history
                        SET last_seen = ?,
                            times_shown = times_shown + 1,
                            last_value_minor = ?,
                            last_rank = ?,
                            updated_at = ?
                        WHERE id = ?
                    """, (month, val_minor, rank, now_str, existing["id"]))
                else:
                    cur.execute("""
                        INSERT INTO insight_history (
                            insight_key, entity_type, entity_id, first_seen, last_seen,
                            times_shown, last_value_minor, last_rank, dismissed, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, 0, ?, ?)
                    """, (key, entity_type, entity_id, month, month, val_minor, rank, now_str, now_str))
            conn.commit()

    @staticmethod
    def dismiss_insight(insight_key: str) -> bool:
        """Marks an insight as dismissed so it will not clutter the feed."""
        now_str = datetime.now().isoformat()
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM insight_history WHERE insight_key = ?", (insight_key,))
            existing = cur.fetchone()
            if existing:
                cur.execute("""
                    UPDATE insight_history
                    SET dismissed = 1, updated_at = ?
                    WHERE id = ?
                """, (now_str, existing["id"]))
            else:
                cur.execute("""
                    INSERT INTO insight_history (
                        insight_key, entity_type, entity_id, first_seen, last_seen,
                        times_shown, last_value_minor, last_rank, dismissed, created_at, updated_at
                    ) VALUES (?, 'dismissed', '', ?, ?, 1, 0, 0, 1, ?, ?)
                """, (insight_key, now_str, now_str, now_str, now_str))
            conn.commit()
            return True
