## =====================================================================
## MODULE: features/login/offline_remember.py
## DESCRIPTION: "Keep me logged in" for the offline developer login (Ray only).
## Saves a signed note in data/offline_session.json. The signature uses data/remember.key,
## a random key made on this PC, so the note can't be edited or written by hand.
## =====================================================================

# region Imports

import hashlib
import hmac
import json
import os
import secrets
import time

from features.paths import data_path

# endregion


# region Constants

OFFLINE_SESSION_FILE = "offline_session.json"
REMEMBER_KEY_FILE = "remember.key"
OWNER_LOGIN_FILE = "owner_login.json"

## The same choices as the online service. None means Unlimited.
REMEMBER_SECONDS = {
    "8h": 8 * 60 * 60,
    "12h": 12 * 60 * 60,
    "1d": 24 * 60 * 60,
    "7d": 7 * 24 * 60 * 60,
    "unlimited": None,
}

# endregion


# region Helpers

## Reads the signing key, or makes a new random one the first time. Returns bytes, or None on a problem.
def _get_remember_key():
    key_path = data_path(REMEMBER_KEY_FILE)
    try:
        with open(key_path, "rb") as file_handle:
            remember_key = file_handle.read()
        if len(remember_key) >= 32:
            return remember_key
        print("[ERROR] OfflineRemember: Signing key looks wrong")
        return None
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[ERROR] OfflineRemember: Could not read signing key: {e}")
        return None

    ## No key yet: token_bytes(32) makes 32 random bytes that can't be guessed.
    try:
        remember_key = secrets.token_bytes(32)
        with open(key_path, "wb") as file_handle:
            file_handle.write(remember_key)
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
        print("[INFO] OfflineRemember: New signing key made")
        return remember_key
    except Exception as e:
        print(f"[ERROR] OfflineRemember: Could not make signing key: {e}")
        return None

## Returns (username, password_hash) from the offline owner login, or None.
def _read_owner_record():
    try:
        with open(data_path(OWNER_LOGIN_FILE), "r", encoding="utf-8") as file_handle:
            owner_record = json.load(file_handle)
        owner_username = str(owner_record.get("username", "")).lower()
        password_hash = str(owner_record.get("password_hash", ""))
        if owner_username and password_hash:
            return owner_username, password_hash
        return None
    except Exception as e:
        print(f"[ERROR] OfflineRemember: Could not read owner login: {e}")
        return None

## HMAC = a signature only someone with the key can make. Changing any part of the text changes the signature completely.
def _make_signature(remember_key, username, expires_at, password_hash):
    signed_text = f"{username}|{expires_at}|{password_hash}"
    return hmac.new(remember_key, signed_text.encode("utf-8"), hashlib.sha256).hexdigest()

# endregion


# region Save, Check & Clear

## Saves the signed note after a good offline login. Returns True if it saved.
def save_offline_remember(username, remember_choice):
    try:
        if remember_choice not in REMEMBER_SECONDS:
            print("[ERROR] OfflineRemember: Unknown remember choice")
            return False
        remember_key = _get_remember_key()
        owner_info = _read_owner_record()
        if remember_key is None or owner_info is None:
            return False
        owner_username, password_hash = owner_info
        if str(username).strip().lower() != owner_username:
            return False

        remember_seconds = REMEMBER_SECONDS[remember_choice]
        expires_at = None if remember_seconds is None else int(time.time()) + remember_seconds
        signature = _make_signature(remember_key, owner_username, expires_at, password_hash)
        note_path = data_path(OFFLINE_SESSION_FILE)
        with open(note_path, "w", encoding="utf-8") as file_handle:
            json.dump({"username": owner_username, "expires_at": expires_at, "signature": signature}, file_handle)
        try:
            os.chmod(note_path, 0o600)
        except OSError:
            pass
        print(f"[SUCCESS] OfflineRemember: Developer login saved ({remember_choice})")
        return True
    except Exception as e:
        print(f"[ERROR] OfflineRemember: Could not save developer login: {e}")
        return False

## Returns the username if the note is real and not expired, or None (fail closed).
def check_offline_remember():
    try:
        with open(data_path(OFFLINE_SESSION_FILE), "r", encoding="utf-8") as file_handle:
            saved_note = json.load(file_handle)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"[ERROR] OfflineRemember: Could not read saved developer login: {e}")
        return None
    try:
        remember_key = _get_remember_key()
        owner_info = _read_owner_record()
        if remember_key is None or owner_info is None or not isinstance(saved_note, dict):
            return None
        owner_username, password_hash = owner_info
        expires_at = saved_note.get("expires_at")
        expected = _make_signature(remember_key, owner_username, expires_at, password_hash)

        ## compare_digest checks the whole signature in the same time whether it matches or not, so it can't be guessed bit by bit.
        if saved_note.get("username") != owner_username or not hmac.compare_digest(str(saved_note.get("signature", "")), expected):
            print("[WARNING] OfflineRemember: Saved developer login is not valid, removing it")
            clear_offline_remember()
            return None
        if expires_at is not None and time.time() > expires_at:
            print("[INFO] OfflineRemember: Saved developer login ran out")
            clear_offline_remember()
            return None
        return owner_username
    except Exception as e:
        print(f"[ERROR] OfflineRemember: Could not check saved developer login: {e}")
        return None

## Deletes the note. Used on LOGOUT, and when the note is bad or ran out.
def clear_offline_remember():
    try:
        os.remove(data_path(OFFLINE_SESSION_FILE))
        print("[INFO] OfflineRemember: Saved developer login removed")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[ERROR] OfflineRemember: Could not remove saved developer login: {e}")

# endregion