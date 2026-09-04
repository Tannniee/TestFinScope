from typing import Dict, Any, Optional
from app.backend.database.connection import get_db_connection

class SettingsService:
    @staticmethod
    def get_all_settings() -> Dict[str, str]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM app_settings")
            return {row["key"]: row["value"] for row in cur.fetchall()}

    @staticmethod
    def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
            row = cur.fetchone()
            return row["value"] if row else default

    @staticmethod
    def set_setting(key: str, value: str, force: bool = False):
        if key == "currency":
            SettingsService.update_settings({"currency": value}, force=force)
            return
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value))
            )
            conn.commit()

    @staticmethod
    def update_settings(settings: Dict[str, str], force: bool = False):
        new_curr = settings.get("currency")
        with get_db_connection() as conn:
            cur = conn.cursor()
            if new_curr and not force:
                cur.execute("SELECT value FROM app_settings WHERE key = 'currency'")
                row = cur.fetchone()
                curr_val = row["value"] if row else "USD"
                if new_curr != curr_val:
                    # Check if any active transactions exist in database
                    cur.execute("SELECT COUNT(*) FROM active_transactions")
                    if cur.fetchone()[0] > 0:
                        raise ValueError("Base currency cannot be changed after financial transactions have been recorded.")
                    # Also update existing account currencies if clean slate
                    cur.execute("UPDATE accounts SET currency = ?", (new_curr,))

            for k, v in settings.items():
                conn.execute(
                    "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (k, str(v))
                )
            conn.commit()
