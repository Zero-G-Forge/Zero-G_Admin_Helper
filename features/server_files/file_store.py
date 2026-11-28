## =====================================================================
## MODULE: features/server_files/file_store.py
## DESCRIPTION: Where the downloaded server files live on this PC, and the checks that keep every
## write inside that folder. Layout, mirroring the server:
##   data/server_files/<scenario name>/scenario/<path on the server>
##   data/server_files/<scenario name>/save/<path on the server>
##   data/server_files/<scenario name>/_manifest.json   (what was pulled, used to skip unchanged files)
## data/ is git-ignored, so the copies never reach GitHub.
## =====================================================================

# region Imports

import json
import os
import re
from datetime import datetime
from typing import Any

from features.paths import DATA_DIR

# endregion


# region Constants

## Folder inside data/ that holds one sub-folder per scenario.
SERVER_FILES_DIR = os.path.join(DATA_DIR, "server_files")

## The two roots the bridge offers. Each becomes a sub-folder of the scenario's local folder.
ROOT_NAMES = ("scenario", "save")

## Name of the file that remembers what was pulled.
MANIFEST_NAME = "_manifest.json"

# endregion


# region Folder Names

## Turns a scenario name from the server into a safe local folder name.
## Letters, digits, space, dash, underscore and dot stay; anything else becomes an underscore.
## An empty or dots-only result becomes "unknown_scenario", so the name can never climb out of data/server_files.
def safe_folder_name(name):
    text = re.sub(r"[^A-Za-z0-9 ._-]", "_", str(name or "")).strip(" .")
    if not text:
        return "unknown_scenario"
    return text


## Full path of the local folder for one scenario.
def scenario_folder(scenario_name):
    return os.path.join(SERVER_FILES_DIR, safe_folder_name(scenario_name))

# endregion


# region Safe Paths

## Returns the full local path for a server-relative path, or None when the path is unsafe.
## The server is trusted, but a bug or a hostile server must still never write outside the download folder:
## so absolute paths, drive letters, "..", empty parts and odd characters are refused, and the final path
## must be inside base_folder.
def local_target_path(base_folder, relative_path):
    if not isinstance(relative_path, str) or not relative_path or len(relative_path) > 260:
        return None
    if any(ord(ch) < 32 or ch in ':*?"<>|' for ch in relative_path):
        return None
    text = relative_path.replace("\\", "/")
    if text.startswith("/"):
        return None
    parts = text.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    base_full = os.path.abspath(base_folder)
    target_full = os.path.abspath(os.path.join(base_full, *parts))
    ## commonpath raises ValueError for different drives on Windows; that also means "not inside".
    try:
        if os.path.commonpath([base_full, target_full]) != base_full or target_full == base_full:
            return None
    except ValueError:
        return None
    return target_full

# endregion


# region Manifest

## Reads the manifest of one scenario folder. A missing or damaged file gives an empty manifest.
def load_manifest(folder) -> dict[str, Any]:
    try:
        with open(os.path.join(folder, MANIFEST_NAME), "r", encoding="utf-8") as file_handle:
            manifest = json.load(file_handle)
        if isinstance(manifest, dict) and isinstance(manifest.get("files"), dict):
            return manifest
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[ERROR] ServerFileStore: Could not read manifest in {folder}: {e}")
    return {"files": {}}


## Writes the manifest. Returns True if it saved.
def save_manifest(folder, manifest):
    try:
        os.makedirs(folder, exist_ok=True)
        temp_path = os.path.join(folder, MANIFEST_NAME + ".part")
        with open(temp_path, "w", encoding="utf-8") as file_handle:
            json.dump(manifest, file_handle, indent=1)
        ## replace() swaps the finished file in at once, so a crash never leaves a half-written manifest.
        os.replace(temp_path, os.path.join(folder, MANIFEST_NAME))
        return True
    except Exception as e:
        print(f"[ERROR] ServerFileStore: Could not save manifest in {folder}: {e}")
        return False

# endregion


# region Time Text

## Current local time as ISO text with its time zone, for saving in app_settings.
def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


## ISO text from app_settings -> text for the LAST PULLED label, e.g. 2026-11-22 10:30 CST.
## Anything unreadable shows "never" (fail closed, never a guess).
def format_last_pulled(iso_text):
    try:
        moment = datetime.fromisoformat(str(iso_text)).astimezone()
        return moment.strftime("%Y-%m-%d %H:%M %Z").strip()
    except (TypeError, ValueError):
        return "never"

# endregion
