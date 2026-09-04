import os
import sys
import subprocess
from pathlib import Path

# Base project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Data directory resolution:
# 1. Respect explicit environment variable FINSCOPE_DATA_DIR if set (e.g. for testing / portable mode)
# 2. On Windows, default to %LOCALAPPDATA%\FinScope
# 3. On other platforms, default to ~/.local/share/FinScope or ./data
env_override = os.environ.get("FINSCOPE_DATA_DIR")
if env_override:
    DATA_DIR = Path(env_override)
else:
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            DATA_DIR = Path(local_app_data) / "FinScope"
        else:
            DATA_DIR = PROJECT_ROOT / "data"
    else:
        DATA_DIR = Path.home() / ".local" / "share" / "FinScope"

DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "finance.db"
SETTINGS_PATH = DATA_DIR / "settings.json"
BACKUPS_DIR = DATA_DIR / "backups"
EXPORTS_DIR = DATA_DIR / "exports"
ATTACHMENTS_DIR = DATA_DIR / "attachments"
LOGS_DIR = DATA_DIR / "logs"

BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Frontend directory
FRONTEND_DIR = PROJECT_ROOT / "app" / "frontend"

def open_data_folder():
    """Opens the user data folder in the operating system file explorer."""
    path_str = str(DATA_DIR)
    if sys.platform == "win32":
        os.startfile(path_str)
    elif sys.platform == "darwin":
        subprocess.run(["open", path_str])
    else:
        subprocess.run(["xdg-open", path_str])
    return path_str
