## =====================================================================
## MODULE: features/login/password_hashing.py
## DESCRIPTION: Turns a password into a salted scrypt hash, and checks a
## typed password against a saved hash. The real password is never stored.
## =====================================================================

# region Imports

## hashlib.scrypt is Python's built-in slow password hash; secrets makes random salt;
## hmac.compare_digest compares safely (same time whether it matches early or late).
import hashlib
import hmac
import secrets

# endregion


# region Constants

## scrypt cost settings. Higher N = slower to guess. These are common safe values.
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
## Salt = random bytes mixed in, so two identical passwords never give the same hash.
SALT_BYTES = 16

# endregion


# region Hashing Helpers

## Returns (salt_hex, hash_hex) for a new password. Both are plain text, safe to save to a file.
def hash_password(password_text):
    if not password_text:
        print("[ERROR] PasswordHashing: Empty password not allowed")
        return None
    try:
        salt = secrets.token_bytes(SALT_BYTES)
        password_hash = hashlib.scrypt(
            password_text.encode("utf-8"), salt=salt,
            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
        )
        ## .hex() turns raw bytes into readable letters and numbers for the JSON file.
        return salt.hex(), password_hash.hex()
    except Exception as e:
        print(f"[ERROR] PasswordHashing: Could not hash password: {e}")
        return None


## Returns True only if the typed password makes the same hash with the saved salt.
def check_password(password_text, salt_hex, hash_hex):
    if not password_text or not salt_hex or not hash_hex:
        return False
    try:
        test_hash = hashlib.scrypt(
            password_text.encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
        )
        return hmac.compare_digest(test_hash.hex(), hash_hex)
    except Exception as e:
        print(f"[ERROR] PasswordHashing: Could not check password: {e}")
        return False

# endregion