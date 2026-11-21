## =====================================================================
## MODULE: features/login/saved_session.py
## DESCRIPTION: Keeps the "Keep me logged in" token in data/session.json.
## Only the token is saved, never a password. data/ is git-ignored, so it never gets pushed.
## =====================================================================

# region Imports

import json
import os

from features.paths import DATA_DIR

# endregion


# region Constants

SESSION_FILE = os.path.join(DATA_DIR, "session.json")

# endregion


# region Save, Load & Clear

## Writes the token to the file. Returns True if it saved.
def save_session_token(session_token):
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as file_handle:
            json.dump({"token": session_token}, file_handle)

        ## 0o600 = only your own user account can read the file. Windows ignores most of this, so a failure is not an error.
        try:
            os.chmod(SESSION_FILE, 0o600)
        except OSError:
            pass
        print("[SUCCESS] SavedSession: Login saved on this PC")
        return True
    except Exception as e:
        print(f"[ERROR] SavedSession: Could not save login: {e}")
        return False

## Returns the saved token, or None if there is no file or it looks wrong (fail closed).
def load_session_token():
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as file_handle:
            saved = json.load(file_handle)
        session_token = saved.get("token") if isinstance(saved, dict) else None
        if isinstance(session_token, str) and session_token:
            return session_token
        return None
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"[ERROR] SavedSession: Could not read saved login: {e}")
        return None

## Deletes the file. Used on LOGOUT and when the service says the token is no good.
def clear_session_token():
    try:
        os.remove(SESSION_FILE)
        print("[INFO] SavedSession: Saved login removed")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[ERROR] SavedSession: Could not remove saved login: {e}")

# endregion