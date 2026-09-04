import os
import sys
from pathlib import Path

# Base project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Data directory: default to local data folder for full portability & privacy
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

# Allow override via environment variable if desired
DATA_DIR = Path(os.environ.get("FINSCOPE_DATA_DIR", DEFAULT_DATA_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "finance.db"
SETTINGS_PATH = DATA_DIR / "settings.json"
BACKUPS_DIR = DATA_DIR / "backups"
EXPORTS_DIR = DATA_DIR / "exports"

BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Frontend directory
FRONTEND_DIR = PROJECT_ROOT / "app" / "frontend"
