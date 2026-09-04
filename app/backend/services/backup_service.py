import os
import json
import zipfile
import csv
import io
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from app.backend.config import DB_PATH, BACKUPS_DIR, EXPORTS_DIR
from app.backend.database.connection import get_db_connection

class BackupService:
    @staticmethod
    def create_backup() -> Dict[str, Any]:
        """Creates a .financebackup zip file containing finance.db and metadata."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_filename = f"FinScope_Backup_{timestamp}.financebackup"
        backup_filepath = BACKUPS_DIR / backup_filename

        metadata = {
            "app": "FinScope",
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "db_size_bytes": os.path.getsize(DB_PATH) if DB_PATH.exists() else 0
        }

        with zipfile.ZipFile(backup_filepath, "w", zipfile.ZIP_DEFLATED) as zf:
            if DB_PATH.exists():
                zf.write(DB_PATH, arcname="finance.db")
            zf.writestr("metadata.json", json.dumps(metadata, indent=2))

        return {
            "success": True,
            "filename": backup_filename,
            "filepath": str(backup_filepath),
            "size_bytes": os.path.getsize(backup_filepath),
            "created_at": metadata["created_at"]
        }

    @staticmethod
    def list_backups() -> List[Dict[str, Any]]:
        backups = []
        for file in BACKUPS_DIR.glob("*.financebackup"):
            backups.append({
                "filename": file.name,
                "filepath": str(file),
                "size_bytes": file.stat().st_size,
                "created_at": datetime.fromtimestamp(file.stat().st_mtime).isoformat()
            })
        backups.sort(key=lambda x: x["created_at"], reverse=True)
        return backups

    @staticmethod
    def restore_backup(backup_path_str: str) -> Dict[str, Any]:
        """Creates a safety backup of current data, then extracts and restores the chosen backup."""
        backup_file = Path(backup_path_str)
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path_str}")

        # 1. Create safety backup first
        safety_name = f"Safety_PreRestore_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.financebackup"
        shutil.copyfile(DB_PATH, BACKUPS_DIR / safety_name)

        # 2. Extract and restore
        with zipfile.ZipFile(backup_file, "r") as zf:
            if "finance.db" not in zf.namelist():
                raise ValueError("Invalid backup: finance.db missing from archive")
            zf.extract("finance.db", path=DB_PATH.parent)

        return {
            "success": True,
            "safety_backup": safety_name,
            "restored_from": backup_file.name
        }

    @staticmethod
    def export_csv() -> str:
        """Exports all transactions to a CSV file in exports directory."""
        filename = f"FinScope_Transactions_{datetime.now().strftime('%Y-%m-%d')}.csv"
        filepath = EXPORTS_DIR / filename

        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    t.id, t.transaction_date, t.transaction_time, t.transaction_type,
                    t.amount, t.merchant_name, c.name as category, a.name as account,
                    t.essentiality, t.payment_method, t.description, t.note
                FROM transactions t
                LEFT JOIN categories c ON t.category_id = c.id
                LEFT JOIN accounts a ON t.account_id = a.id
                ORDER BY t.transaction_date DESC, t.id DESC
            """)
            rows = cur.fetchall()

        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "ID", "Date", "Time", "Type", "Amount", "Merchant",
                "Category", "Account", "Essentiality", "Payment Method", "Description", "Note"
            ])
            for r in rows:
                writer.writerow(list(r))

        return str(filepath)

    @staticmethod
    def get_storage_health() -> Dict[str, Any]:
        """Provides database statistics, transaction count, date ranges, and backup status."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*), MIN(transaction_date), MAX(transaction_date) FROM transactions")
            tx_count, min_date, max_date = cur.fetchone()

            cur.execute("SELECT COUNT(*) FROM accounts")
            acc_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM categories")
            cat_count = cur.fetchone()[0]

        db_size = os.path.getsize(DB_PATH) if DB_PATH.exists() else 0
        backups = BackupService.list_backups()
        last_backup = backups[0]["created_at"] if backups else "Never"

        return {
            "db_path": str(DB_PATH),
            "db_size_bytes": db_size,
            "db_size_formatted": f"{db_size / (1024 * 1024):.2f} MB" if db_size >= 1024 * 1024 else f"{db_size / 1024:.1f} KB",
            "transaction_count": tx_count or 0,
            "account_count": acc_count or 0,
            "category_count": cat_count or 0,
            "date_range": f"{min_date} to {max_date}" if min_date else "No data yet",
            "backup_count": len(backups),
            "last_backup": last_backup,
            "status": "Healthy"
        }
