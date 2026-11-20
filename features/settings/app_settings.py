## ==========================================
## ZERO-G ADMIN HELPER - APP SETTINGS
## Loads and saves ZAH's own settings in data/app_settings.json.
## Any problem reading the file falls back to the safe defaults.
## ==========================================

## region: Imports

import json
import os

from features.paths import DATA_DIR

## endregion


## region: Constants

## data/ is git-ignored, so these settings stay on this PC only.
APP_SETTINGS_FILE = os.path.join(DATA_DIR, "app_settings.json")

## The safe starting values. bridge_auto_connect is False so ZAH never
## contacts the server unless the owner turns it on.
DEFAULT_SETTINGS = {
    "bridge_auto_connect": False,
}

## endregion


## region: Load & Save

## Returns every setting as a dictionary. Missing keys get their default value,
## so an old file from an earlier version still works.
def load_app_settings():
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(APP_SETTINGS_FILE, "r", encoding="utf-8") as file_handle:
            saved = json.load(file_handle)
        ## Only known keys are kept, and each must be the same type as its default.
        for key, default_value in DEFAULT_SETTINGS.items():
            if isinstance(saved.get(key), type(default_value)):
                settings[key] = saved[key]
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[ERROR] AppSettings: Could not read settings, using defaults: {e}")
    return settings

## Changes one setting and writes the file. Returns True if it saved.
def save_app_setting(key, value):
    if key not in DEFAULT_SETTINGS or not isinstance(value, type(DEFAULT_SETTINGS[key])):
        print(f"[ERROR] AppSettings: Refused unknown or wrong-type setting '{key}'")
        return False
    try:
        settings = load_app_settings()
        settings[key] = value
        with open(APP_SETTINGS_FILE, "w", encoding="utf-8") as file_handle:
            json.dump(settings, file_handle, indent=2)
        print(f"[SUCCESS] AppSettings: Saved {key} = {value}")
        return True
    except Exception as e:
        print(f"[ERROR] AppSettings: Could not save {key}: {e}")
        return False

## endregion