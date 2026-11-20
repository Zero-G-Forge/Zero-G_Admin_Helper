## =====================================================================
## MODULE: features/login/owner_login.py
## DESCRIPTION: Saves and checks the offline owner login (Ray only).
## Only a salted scrypt hash is stored in data/owner_login.json (git-ignored);
## the real password is never written anywhere.
## =====================================================================

# region Imports

import json
from features.paths import data_path
from features.login.password_hashing import hash_password, check_password

# endregion


# region Constants

OWNER_LOGIN_FILE = "owner_login.json"

# endregion


# region Owner Login Helpers

## Writes a new owner login. Returns True on success. Overwrites any older owner login.
def save_owner_login(username, password_text):
    username = str(username or "").strip()
    if not username:
        print("[ERROR] OwnerLogin: Username is required")
        return False

    hashed = hash_password(password_text)
    if hashed is None:
        return False
    salt_hex, hash_hex = hashed

    try:
        owner_record = {"username": username, "salt": salt_hex, "password_hash": hash_hex}
        ## indent=2 makes the file readable if it is ever opened by hand.
        with open(data_path(OWNER_LOGIN_FILE), "w", encoding="utf-8") as file_handle:
            json.dump(owner_record, file_handle, indent=2)
        print(f"[SUCCESS] OwnerLogin: Owner login saved for {username}")
        return True
    except Exception as e:
        print(f"[ERROR] OwnerLogin: Could not save owner login: {e}")
        return False


## Returns True only if the username matches and the password matches the saved hash.
## Any problem (no file, broken file) returns False, so a failure never lets anyone in.
def check_owner_login(username, password_text):
    try:
        with open(data_path(OWNER_LOGIN_FILE), "r", encoding="utf-8") as file_handle:
            owner_record = json.load(file_handle)
    except FileNotFoundError:
        print("[WARNING] OwnerLogin: No owner login set up yet")
        return False
    except Exception as e:
        print(f"[ERROR] OwnerLogin: Could not read owner login: {e}")
        return False

    ## Usernames are compared without caring about upper/lower case.
    if str(username or "").strip().lower() != str(owner_record.get("username", "")).lower():
        return False
    return check_password(password_text, owner_record.get("salt"), owner_record.get("password_hash"))

# endregion