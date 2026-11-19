## =====================================================================
## paths.py
## DESCRIPTION: Central file locations: app root, data/ and assets/.
## =====================================================================
"""
Single source of truth for Admin Helper file locations.

Every data/ and assets/ path resolves from the app root (the folder that
contains ZAH.py), never from the current working directory, so the app works
no matter where it is launched from, e.g.
    cd /mnt/Zero-G_Files/Zero-G_Forge && Zero-G_Admin_Helper/.venv/bin/python Zero-G_Admin_Helper/ZAH.py
"""

## region: Imports

import os

## endregion

## region: Folder Constants

## features/paths.py -> features/ -> app root (folder with ZAH.py)
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
## data/ holds files the program writes at runtime; assets/ holds images and stylesheets.
DATA_DIR = os.path.join(APP_ROOT, "data")
ASSETS_DIR = os.path.join(APP_ROOT, "assets")

## endregion


## region: Path Helpers

def ensure_data_dir() -> str:
    """Creates data/ under the app root if it is missing and returns its path."""
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR


def data_path(*parts: str) -> str:
    """Absolute path inside data/ (data/ is created if missing)."""
    ensure_data_dir()
    return os.path.join(DATA_DIR, *parts)


def asset_path(*parts: str) -> str:
    """Absolute path inside assets/."""
    return os.path.join(ASSETS_DIR, *parts)

## endregion
