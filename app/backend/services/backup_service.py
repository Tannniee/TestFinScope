import os
import json
import zipfile
import csv
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from app.backend.config import DB_PATH, BACKUPS_DIR, EXPORTS_DIR, DATA_DIR
from app.backend.database.connection import get_db_connection

class BackupService:
    @staticmethod
    def create_backup(is_safety_snapshot: bool = False) -> Dict[str, Any]:
        """
        Creates a verified .financebackup zip archive using SQLite Connection.backup().
        Flushes and copies any uncheckpointed WAL frames safely.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        prefix = "Safety_PreRestore_" if is_safety_snapshot else "FinScope_Backup_"
        backup_filename = f"{prefix}{timestamp}.financebackup"
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        backup_filepath = BACKUPS_DIR / backup_filename
        temp_db_path = BACKUPS_DIR / f"temp_snapshot_{timestamp}.db"

        try:
            # 1. Open source and destination connections, perform SQLite live backup
            with get_db_connection() as src_conn:
                dest_conn = sqlite3.connect(str(temp_db_path))
                try:
                    src_conn.backup(dest_conn)
                finally:
                    dest_conn.close()

            # 2. Run integrity check on the snapshot database
            test_conn = sqlite3.connect(str(temp_db_path))
            try:
                cur = test_conn.cursor()
                cur.execute("PRAGMA integrity_check;")
                result = cur.fetchone()[0]
                if result != "ok":
                    raise ValueError(f"Snapshot integrity check failed: {result}")

                cur.execute("SELECT COUNT(*) FROM transactions")
                tx_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM accounts")
                acc_count = cur.fetchone()[0]
            finally:
                test_conn.close()

            metadata = {
                "app": "FinScope",
                "format_version": 2,
                "created_at": datetime.now().isoformat(),
                "is_safety_snapshot": is_safety_snapshot,
                "transaction_count": tx_count,
                "account_count": acc_count,
                "db_size_bytes": os.path.getsize(temp_db_path)
            }

            # 3. Package verified snapshot into .financebackup ZIP archive
            with zipfile.ZipFile(backup_filepath, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(temp_db_path, arcname="finance.db")
                zf.writestr("metadata.json", json.dumps(metadata, indent=2))

            return {
                "success": True,
                "filename": backup_filename,
                "filepath": str(backup_filepath),
                "size_bytes": os.path.getsize(backup_filepath),
                "created_at": metadata["created_at"],
                "transaction_count": tx_count
            }

        finally:
            if temp_db_path.exists():
                try:
                    os.remove(temp_db_path)
                except OSError:
                    pass

    @staticmethod
    def list_backups() -> List[Dict[str, Any]]:
        backups = []
        for file in BACKUPS_DIR.glob("*.financebackup"):
            try:
                # Read metadata if possible
                created_at = datetime.fromtimestamp(file.stat().st_mtime).isoformat()
                tx_count = None
                with zipfile.ZipFile(file, "r") as zf:
                    if "metadata.json" in zf.namelist():
                        meta = json.loads(zf.read("metadata.json").decode("utf-8"))
                        created_at = meta.get("created_at", created_at)
                        tx_count = meta.get("transaction_count")
            except Exception:
                created_at = datetime.fromtimestamp(file.stat().st_mtime).isoformat()
                tx_count = None

            backups.append({
                "filename": file.name,
                "filepath": str(file),
                "size_bytes": file.stat().st_size,
                "created_at": created_at,
                "transaction_count": tx_count
            })

        backups.sort(key=lambda x: x["created_at"], reverse=True)
        return backups

    @staticmethod
    def restore_backup(backup_path_str: str) -> Dict[str, Any]:
        """
        Creates a safety backup first, validates the target backup integrity,
        and restores the database safely.
        """
        backup_file = Path(backup_path_str)
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path_str}")

        # 1. Create safety backup snapshot using proper backup archive format
        safety_res = BackupService.create_backup(is_safety_snapshot=True)

        temp_extract_db = BACKUPS_DIR / f"temp_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        try:
            # 2. Verify zip structure
            with zipfile.ZipFile(backup_file, "r") as zf:
                if "finance.db" not in zf.namelist():
                    raise ValueError("Invalid backup archive: finance.db missing")
                with open(temp_extract_db, "wb") as f:
                    f.write(zf.read("finance.db"))

            # 3. Validate extracted database with integrity check before replacing active DB
            check_conn = sqlite3.connect(str(temp_extract_db))
            try:
                cur = check_conn.cursor()
                cur.execute("PRAGMA integrity_check;")
                status = cur.fetchone()[0]
                if status != "ok":
                    raise ValueError(f"Corrupted backup database: {status}")
            finally:
                check_conn.close()

            # 4. Remove active WAL and SHM files to avoid state collision
            wal_file = DB_PATH.parent / f"{DB_PATH.name}-wal"
            shm_file = DB_PATH.parent / f"{DB_PATH.name}-shm"
            if wal_file.exists():
                try:
                    os.remove(wal_file)
                except OSError:
                    pass
            if shm_file.exists():
                try:
                    os.remove(shm_file)
                except OSError:
                    pass

            # 5. Overwrite live DB file
            with open(temp_extract_db, "rb") as src, open(DB_PATH, "wb") as dst:
                dst.write(src.read())

            return {
                "success": True,
                "safety_backup": safety_res["filename"],
                "restored_from": backup_file.name
            }

        finally:
            if temp_extract_db.exists():
                try:
                    os.remove(temp_extract_db)
                except OSError:
                    pass

    @staticmethod
    def export_csv() -> str:
        """Exports all transactions to a CSV file in exports directory."""
        filename = f"FinScope_Transactions_{datetime.now().strftime('%Y-%m-%d')}.csv"
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        filepath = EXPORTS_DIR / filename

        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    t.id, t.transaction_date, t.transaction_time, t.transaction_type,
                    ROUND(CAST(t.amount_minor AS REAL) / 100.0, 2) as amount,
                    t.merchant_name, c.name as category, a.name as account,
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
            cur.execute("PRAGMA integrity_check;")
            integrity = cur.fetchone()[0]

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
            "data_dir": str(DATA_DIR),
            "db_size_bytes": db_size,
            "db_size_formatted": f"{db_size / (1024 * 1024):.2f} MB" if db_size >= 1024 * 1024 else f"{db_size / 1024:.1f} KB",
            "transaction_count": tx_count or 0,
            "account_count": acc_count or 0,
            "category_count": cat_count or 0,
            "date_range": f"{min_date} to {max_date}" if min_date else "No data yet",
            "backup_count": len(backups),
            "last_backup": last_backup,
            "integrity": integrity,
            "status": "Healthy" if integrity == "ok" else "Integrity Warning"
        }
