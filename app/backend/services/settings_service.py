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
    def set_setting(key: str, value: str):
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value))
            )
            conn.commit()

    @staticmethod
    def update_settings(settings: Dict[str, str]):
        with get_db_connection() as conn:
            for k, v in settings.items():
                conn.execute(
                    "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (k, str(v))
                )
            conn.commit()
