## =====================================================================
## MODULE: features/server_files/download_settings.py
## DESCRIPTION: Remembers, per server, which scenario and save the Settings download
## should pull, and which file types to include. Local only (data/download_settings.json).
## Fail closed: a missing or bad file, or a bad name, falls back to the server-reported pair
## and to every allowed type. Nothing here talks to the server.
## =====================================================================

# region Imports

import json
import os
from typing import TypeGuard

# endregion


# region Constants

DOWNLOAD_SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "download_settings.json")

## File-type groups the picker can include or skip. "yaml" covers both .yaml and .yml.
## "blueprints" is the Prefabs .epb files (core 1.6.6 or later).
FILE_TYPE_KEYS = ("ecf", "yaml", "csv", "images", "blueprints")
FILE_TYPE_EXTENSIONS = {
    "ecf": (".ecf",),
    "yaml": (".yaml", ".yml"),
    "csv": (".csv",),
    "images": (".jpg", ".jpeg", ".png"),
    "blueprints": (".epb",),
}

DEFAULT_TYPES = {key: True for key in FILE_TYPE_KEYS}

## Used only when they appear in the server's catalog list, and only when there is no
## saved choice and no detected origin. The two pickers stay independent.
PREFERRED_SCENARIO = "Ascension-Reborn"
PREFERRED_SAVE = "Zero-G Server - Season 4"

# endregion


# region Name and Type Checks

## Same rules as the bridge's IsPlainFolderName: no separators, no ".." or ".", no control
## characters, no Windows reserved punctuation. Spaces inside the name are allowed.
def is_plain_folder_name(name) -> TypeGuard[str]:
    if not isinstance(name, str):
        return False
    text = name.strip()
    if not text or text in (".", "..") or len(text) > 255:
        return False
    if any(ord(char) < 0x20 for char in text):
        return False
    if any(char in text for char in "/\\:*?\"<>|"):
        return False
    return True


## Extensions to download for a types dictionary. Missing keys default to on, so a
## newly added type is not silently skipped. Unknown keys are ignored.
def allowed_extensions(types):
    chosen = set()
    source = types if isinstance(types, dict) else {}
    for key, extensions in FILE_TYPE_EXTENSIONS.items():
        flag = source.get(key, True)
        if flag is True:
            chosen.update(extensions)
    return chosen


def types_from_saved(types):
    cleaned = dict(DEFAULT_TYPES)
    if not isinstance(types, dict):
        return cleaned
    for key in FILE_TYPE_KEYS:
        if isinstance(types.get(key), bool):
            cleaned[key] = types[key]
    return cleaned

# endregion



## First name that is actually in the catalog list. Used by the Settings combos so a
## saved choice, a detected origin, and the preferred defaults are all optional.
def first_available_name(names, *preferences):
    catalog = list(names) if names else []
    for value in preferences:
        if isinstance(value, str) and value in catalog:
            return value
    return catalog[0] if catalog else ""

# region Load and Save

def _empty_store():
    return {"servers": {}}


def load_download_settings():
    store = _empty_store()
    try:
        with open(DOWNLOAD_SETTINGS_FILE, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        if not isinstance(saved, dict):
            return store
        servers = saved.get("servers")
        if not isinstance(servers, dict):
            return store
        cleaned = {}
        for name, row in servers.items():
            if not isinstance(name, str) or not name.strip() or not isinstance(row, dict):
                continue
            entry: dict = {"types": types_from_saved(row.get("types"))}
            scenario = row.get("scenario")
            save = row.get("save")
            if is_plain_folder_name(scenario):
                entry["scenario"] = scenario.strip()
            if is_plain_folder_name(save):
                entry["save"] = save.strip()
            cleaned[name] = entry
        store["servers"] = cleaned
    except FileNotFoundError:
        pass
    except Exception as exc:
        print(f"[ERROR] DownloadSettings: Could not read settings, using defaults: {exc}")
    return store


def load_server_download_settings(server_name):
    if not isinstance(server_name, str) or not server_name.strip():
        return {"types": dict(DEFAULT_TYPES)}
    return load_download_settings()["servers"].get(server_name, {"types": dict(DEFAULT_TYPES)})


def save_server_download_settings(server_name, scenario=None, save=None, types=None):
    if not isinstance(server_name, str) or not server_name.strip():
        return False
    if scenario is not None and not is_plain_folder_name(scenario):
        print("[ERROR] DownloadSettings: Refused a scenario name that is not a plain folder name.")
        return False
    if save is not None and not is_plain_folder_name(save):
        print("[ERROR] DownloadSettings: Refused a save name that is not a plain folder name.")
        return False
    try:
        store = load_download_settings()
        entry = dict(store["servers"].get(server_name, {}))
        entry["types"] = types_from_saved(types if types is not None else entry.get("types"))
        if scenario is not None:
            entry["scenario"] = scenario.strip()
        if save is not None:
            entry["save"] = save.strip()
        store["servers"][server_name] = entry
        folder = os.path.dirname(DOWNLOAD_SETTINGS_FILE)
        os.makedirs(folder, exist_ok=True)
        with open(DOWNLOAD_SETTINGS_FILE, "w", encoding="utf-8") as handle:
            json.dump(store, handle, indent=2)
        return True
    except Exception as exc:
        print(f"[ERROR] DownloadSettings: Could not save settings: {exc}")
        return False


## Selection handed to the download worker. None means "use the server-reported pair
## and every file type" (the old behaviour, and the fail-closed fallback).
def selection_for_download(server_name, picker_ready, scenario, save, types):
    if not picker_ready:
        return None
    if not is_plain_folder_name(scenario) or not is_plain_folder_name(save):
        return None
    chosen_types = types_from_saved(types)
    if not any(chosen_types.values()):
        return None
    return {
        "server_name": server_name if isinstance(server_name, str) else "",
        "scenario": scenario.strip(),
        "save": save.strip(),
        "types": chosen_types,
    }

# endregion
