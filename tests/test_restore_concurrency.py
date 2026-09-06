import time
import zipfile
import threading
import sqlite3
import pytest
from pathlib import Path
from app.backend import config
from app.backend.database.maintenance import maintenance_coordinator
from app.backend.services.backup_service import BackupService

def test_maintenance_coordinator_exclusivity():
    """
    FSC-H01: When exclusive() lock is held, operation() waits and cannot run concurrently.
    When operation() is active, exclusive() waits until all operations complete.
    """
    events = []

    def long_operation():
        with maintenance_coordinator.operation():
            events.append("op_start")
            time.sleep(0.05)
            events.append("op_end")

    def exclusive_task():
        time.sleep(0.01)  # start slightly after operation
        with maintenance_coordinator.exclusive():
            events.append("exclusive_start")
            time.sleep(0.02)
            events.append("exclusive_end")

    t1 = threading.Thread(target=long_operation)
    t2 = threading.Thread(target=exclusive_task)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # exclusive_start must happen strictly after op_end
    assert events.index("exclusive_start") > events.index("op_end")


def test_concurrent_backups_unique_filenames(tmp_path, monkeypatch):
    """
    FSC-M01: Concurrent backup requests produce unique collision-free archive filenames.
    """
    test_data = tmp_path / "fin_data"
    test_data.mkdir()
    monkeypatch.setenv("FINSCOPE_DATA_DIR", str(test_data))
    config.set_data_dir(test_data)

    from app.backend.database.connection import init_db
    init_db()

    results = []
    errors = []

    def do_backup():
        try:
            res = BackupService.create_backup()
            results.append(res["filename"])
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=do_backup) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Errors occurred during backup: {errors}"
    assert len(results) == 5
    assert len(set(results)) == 5, f"Filenames should be unique, got: {results}"


def test_restore_rejects_oversized_uncompressed_member(tmp_path, monkeypatch):
    """
    FSC-M02: Restore rejects archives whose uncompressed finance.db member exceeds limits.
    """
    import app.backend.services.backup_service as bs
    monkeypatch.setattr(bs, "MAX_UNCOMPRESSED_BACKUP_BYTES", 100)

    test_data = tmp_path / "fin_data"
    test_data.mkdir()
    monkeypatch.setenv("FINSCOPE_DATA_DIR", str(test_data))
    config.set_data_dir(test_data)

    from app.backend.database.connection import init_db
    init_db()

    malicious_zip = config.BACKUPS_DIR / "bomb.financebackup"
    config.BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(malicious_zip, "w") as zf:
        zf.writestr("metadata.json", '{"format_version": 2, "schema_version": 1}')
        zf.writestr("finance.db", b"x" * 200)

    with pytest.raises(ValueError, match="exceeds maximum uncompressed limit"):
        BackupService.restore_backup(str(malicious_zip))
