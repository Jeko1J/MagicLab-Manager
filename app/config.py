from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "MagicLab Manager"
APP_VERSION = "1.3.1"
ORGANIZATION_NAME = "Magic Lab Detailing"


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


ROOT_DIR = Path(os.environ.get("MAGICLAB_ROOT", application_root())).resolve()
DATA_DIR = ROOT_DIR / "data"
BACKUP_DIR = ROOT_DIR / "backups"
EXPORT_DIR = ROOT_DIR / "exports"
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", application_root())) / "app" / "resources"
DB_PATH = DATA_DIR / "magiclab.db"
INSPECTION_PHOTO_DIR = DATA_DIR / "inspection_photos"


def ensure_directories() -> None:
    for directory in (DATA_DIR, BACKUP_DIR, EXPORT_DIR, INSPECTION_PHOTO_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def database_url(path: Path | None = None) -> str:
    db_path = (path or DB_PATH).resolve()
    return f"sqlite:///{db_path.as_posix()}"
