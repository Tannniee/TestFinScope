import os
import json
import zipfile
import csv
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from app.backend import config
from app.backend.database.connection import get_db_connection
from app.backend.database.migrations_runner import MAX_SUPPORTED_SCHEMA_VERSION, run_migrations

logger = logging.getLogger(__name__)

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
        config.BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        backup_filepath = config.BACKUPS_DIR / backup_filename
        temp_db_path = config.BACKUPS_DIR / f"temp_snapshot_{timestamp}.db"

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

                cur.execute("SELECT MAX(version) FROM schema_migrations")
                schema_row = cur.fetchone()
                schema_version = schema_row[0] if schema_row and schema_row[0] is not None else 1
            finally:
                test_conn.close()

            metadata = {
                "app": "FinScope",
                "format_version": 2,
                "schema_version": schema_version,
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
        for file in config.BACKUPS_DIR.glob("*.financebackup"):
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
        Creates a safety backup first, validates format/schema compatibility and integrity,
        swaps validated DB into live DB, verifies post-restore health, and automatically
        rolls back live DB from safety backup if any failure occurs post-swap (AUD-008).
        """
        backup_file = Path(backup_path_str).resolve()
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path_str}")

        if backup_file.suffix != ".financebackup":
            raise ValueError("Invalid backup file extension; expected .financebackup")

        # Path traversal guard: ensure path is within BACKUPS_DIR
        backups_dir_resolved = config.BACKUPS_DIR.resolve()
        try:
            backup_file.relative_to(backups_dir_resolved)
        except ValueError:
            raise ValueError("Path traversal rejected: Backup file must be located within the backups directory.")

        # 1. Pre-validate archive structure and metadata before any modifications
        try:
            with zipfile.ZipFile(backup_file, "r") as zf:
                if "finance.db" not in zf.namelist():
                    raise ValueError("Invalid backup archive: finance.db missing")
                if "metadata.json" in zf.namelist():
                    try:
                        meta = json.loads(zf.read("metadata.json").decode("utf-8"))
                        fmt_ver = meta.get("format_version", 1)
                        if fmt_ver > 2:
                            raise ValueError(f"Unsupported backup format version ({fmt_ver}). Please upgrade FinScope.")
                        sch_ver = meta.get("schema_version")
                        if sch_ver and sch_ver > MAX_SUPPORTED_SCHEMA_VERSION:
                            raise ValueError(
                                f"Backup schema version ({sch_ver}) is newer than application supported version ({MAX_SUPPORTED_SCHEMA_VERSION}). "
                                "Please upgrade FinScope before restoring this backup."
                            )
                    except json.JSONDecodeError:
                        raise ValueError("Corrupted backup metadata: invalid JSON")
        except zipfile.BadZipFile:
            raise ValueError("Corrupted backup archive: Not a valid ZIP file")

        # 2. Create safety backup snapshot of live database
        safety_res = BackupService.create_backup(is_safety_snapshot=True)
        safety_backup_path = Path(safety_res["filepath"])

        temp_extract_db = config.BACKUPS_DIR / f"temp_restore_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.db"
        live_db_swapped = False

        try:
            # 3. Extract database to temp file for pre-swap validation
            with zipfile.ZipFile(backup_file, "r") as zf:
                with open(temp_extract_db, "wb") as f:
                    f.write(zf.read("finance.db"))

            # 4. Validate extracted database with integrity check and schema verification
            check_conn = sqlite3.connect(str(temp_extract_db))
            try:
                cur = check_conn.cursor()
                cur.execute("PRAGMA integrity_check;")
                status = cur.fetchone()[0]
                if status != "ok":
                    raise ValueError(f"Corrupted backup database: {status}")

                cur.execute("SELECT MAX(version) FROM schema_migrations")
                row = cur.fetchone()
                if not row or row[0] is None:
                    raise ValueError("Corrupted backup database: Missing schema migrations table")

                db_schema_version = row[0]
                if db_schema_version > MAX_SUPPORTED_SCHEMA_VERSION:
                    raise ValueError(
                        f"Database schema version ({db_schema_version}) is newer than supported version ({MAX_SUPPORTED_SCHEMA_VERSION})."
                    )

                # Upgrade extracted db to latest migrations if it is from an older schema version
                run_migrations(check_conn)
            finally:
                check_conn.close()

            # 5. Swap validated database into live database using SQLite native backup API
            live_db_swapped = True
            src_conn = sqlite3.connect(str(temp_extract_db))
            try:
                dest_conn = sqlite3.connect(str(config.DB_PATH))
                try:
                    src_conn.backup(dest_conn)
                    dest_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                finally:
                    dest_conn.close()
            finally:
                src_conn.close()

            # 6. Post-restore integrity verification on live database
            post_conn = sqlite3.connect(str(config.DB_PATH))
            try:
                post_cur = post_conn.cursor()
                post_cur.execute("PRAGMA integrity_check;")
                post_status = post_cur.fetchone()[0]
                if post_status != "ok":
                    raise ValueError(f"Post-restore check failed: {post_status}")
            finally:
                post_conn.close()

            return {
                "success": True,
                "safety_backup": safety_res["filename"],
                "safety_backup_path": safety_res["filepath"],
                "pre_restore_safety_backup": safety_res["filepath"],
                "restored_from": backup_file.name
            }

        except Exception as e:
            logger.exception("Restore failed: %s.", e)
            # Automatic Rollback if failure occurred after live DB was modified (AUD-008)
            if live_db_swapped:
                logger.warning("Attempting automatic live database rollback from safety snapshot: %s", safety_backup_path)
                rollback_temp_db = config.BACKUPS_DIR / f"temp_rollback_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.db"
                try:
                    with zipfile.ZipFile(safety_backup_path, "r") as szf:
                        with open(rollback_temp_db, "wb") as rf:
                            rf.write(szf.read("finance.db"))
                    r_src = sqlite3.connect(str(rollback_temp_db))
                    try:
                        r_dest = sqlite3.connect(str(config.DB_PATH))
                        try:
                            r_src.backup(r_dest)
                            r_dest.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                        finally:
                            r_dest.close()
                    finally:
                        r_src.close()
                    logger.info("Live database successfully rolled back to pre-restore state.")
                except Exception as rb_err:
                    logger.critical("CRITICAL: Failed to rollback live database from safety backup: %s", rb_err)
                finally:
                    if rollback_temp_db.exists():
                        try:
                            os.remove(rollback_temp_db)
                        except OSError:
                            pass
            raise

        finally:
            if temp_extract_db.exists():
                try:
                    os.remove(temp_extract_db)
                except OSError:
                    pass

    @staticmethod
    def export_csv(
        month: Optional[str] = None,
        account_id: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> str:
        """Exports active transactions to CSV with optional scoping filters."""
        suffix = f"_{month}" if month else ""
        if account_id:
            suffix += f"_acc{account_id}"
        filename = f"FinScope_Transactions{suffix}_{datetime.now().strftime('%Y-%m-%d')}.csv"
        config.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        filepath = config.EXPORTS_DIR / filename

        query = """
            SELECT 
                t.id, t.transaction_date, t.transaction_time, t.transaction_type,
                ROUND(CAST(t.amount_minor AS REAL) / 100.0, 2) as amount,
                t.merchant_name, c.name as category, a.name as account,
                t.essentiality, t.payment_method, t.description, t.note
            FROM active_transactions t
            LEFT JOIN categories c ON t.category_id = c.id
            LEFT JOIN accounts a ON t.account_id = a.id
            WHERE 1=1
        """
        params = []
        if month:
            query += " AND t.transaction_date LIKE ?"
            params.append(f"{month}%")
        if start_date:
            query += " AND t.transaction_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND t.transaction_date <= ?"
            params.append(end_date)
        if account_id:
            query += " AND t.account_id = ?"
            params.append(account_id)
        query += " ORDER BY t.transaction_date DESC, t.id DESC"

        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
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

        db_size = os.path.getsize(config.DB_PATH) if config.DB_PATH.exists() else 0
        backups = BackupService.list_backups()
        last_backup = backups[0]["created_at"] if backups else "Never"

        return {
            "db_path": str(config.DB_PATH),
            "data_dir": str(config.DATA_DIR),
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
