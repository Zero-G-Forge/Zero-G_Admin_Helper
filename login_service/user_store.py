## =====================================================================
## MODULE: login_service/user_store.py
## DESCRIPTION: User accounts for the login service. Part 5b uses a local
## JSON test file; part 5c swaps this for PostgreSQL with the same functions.
## Passwords are stored only as salted scrypt hashes.
## =====================================================================

## region: Imports

import hashlib
import hmac
import json
import os
import secrets

## endregion


## region: Constants

## The test file sits next to this script. *.json is git-ignored, so it is never pushed.
USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users_local.json")

## Same scrypt settings as ZAH's owner login.
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1

## The roles a user can have. Anything else is refused.
ALLOWED_ROLES = ("owner", "admin", "moderator")

## endregion


## region: Hashing

def _make_hash(password_text, salt):
    return hashlib.scrypt(password_text.encode("utf-8"), salt=salt,
                          n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P).hex()

## endregion


## region: User File

## Reads every user as {username: {salt, password_hash, role}}. A missing file means no users yet.
def _load_users():
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as file_handle:
            return json.load(file_handle)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"[ERROR] UserStore: Could not read users file: {e}")
        return {}


## Adds or replaces one user. Usernames are saved in lower case so "Ray" and "ray" are the same.
def add_user(username, password_text, role):
    username = str(username or "").strip().lower()
    if not username or not password_text or len(password_text) < 8:
        print("[ERROR] UserStore: Username and an 8+ character password are required")
        return False
    if role not in ALLOWED_ROLES:
        print(f"[ERROR] UserStore: Unknown role '{role}'")
        return False
    try:
        users = _load_users()
        salt = secrets.token_bytes(16)
        users[username] = {"salt": salt.hex(), "password_hash": _make_hash(password_text, salt), "role": role}
        with open(USERS_FILE, "w", encoding="utf-8") as file_handle:
            json.dump(users, file_handle, indent=2)
        print(f"[SUCCESS] UserStore: Saved user {username} ({role})")
        return True
    except Exception as e:
        print(f"[ERROR] UserStore: Could not save user: {e}")
        return False


## Returns the user's role if username and password match, otherwise None. Fails closed.
def check_user(username, password_text):
    try:
        user_record = _load_users().get(str(username or "").strip().lower())
        if not user_record or not password_text:
            return None
        test_hash = _make_hash(password_text, bytes.fromhex(user_record["salt"]))
        if hmac.compare_digest(test_hash, user_record["password_hash"]):
            return user_record.get("role")
        return None
    except Exception as e:
        print(f"[ERROR] UserStore: Could not check user: {e}")
        return None

## endregion