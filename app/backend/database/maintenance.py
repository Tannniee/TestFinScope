import threading
from contextlib import contextmanager

class MaintenanceCoordinator:
    """
    Coordinates process-level exclusive access for database maintenance,
    live backup restores, and destructive resets (FSC-H01).
    Standard API operations execute within operation(), while maintenance
    tasks acquire exclusive() lock.
    """
    def __init__(self):
        self._condition = threading.Condition()
        self._active_ops = 0
        self._maintenance = False

    @contextmanager
    def operation(self):
        """Used by live API operations to ensure no maintenance task is mutating the database file."""
        with self._condition:
            while self._maintenance:
                self._condition.wait()
            self._active_ops += 1
        try:
            yield
        finally:
            with self._condition:
                self._active_ops -= 1
                self._condition.notify_all()

    @contextmanager
    def exclusive(self):
        """Used by restore_backup and destructive database reset to gain exclusive access."""
        with self._condition:
            self._maintenance = True
            while self._active_ops > 0:
                self._condition.wait()
        try:
            yield
        finally:
            with self._condition:
                self._maintenance = False
                self._condition.notify_all()

    @property
    def is_maintenance(self) -> bool:
        with self._condition:
            return self._maintenance

    @property
    def active_ops_count(self) -> int:
        with self._condition:
            return self._active_ops

maintenance_coordinator = MaintenanceCoordinator()
