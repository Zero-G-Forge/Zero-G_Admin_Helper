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

## psycopg is the PostgreSQL driver. If it isn't installed, the store stays
## on the JSON file instead of crashing the whole service.
try:
    import psycopg
except ImportError:
    psycopg = None

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

## The database address comes only from the environment (a Secret on ZAH-BOT).
## It holds the password, so it is never written in code or printed.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

## endregion


## region: Hashing

def _make_hash(password_text, salt):
    return hashlib.scrypt(password_text.encode("utf-8"), salt=salt,
                          n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P).hex()

## endregion


## region: Database
## True only when the driver is installed and a DATABASE_URL was given.
def _database_enabled():
    return psycopg is not None and bool(DATABASE_URL)

## Opens a new connection to ZAH-DB. connect_timeout stops a dead database
## from freezing a login for long.
## The None check tells Pylance psycopg is loaded here, and fails closed if it isn't.
def _open_database():
    if psycopg is None:
        raise RuntimeError("psycopg is not installed")
    return psycopg.connect(DATABASE_URL, connect_timeout=5)

## Creates the users table once. "IF NOT EXISTS" makes it safe to run on every start.
## The columns match the JSON file: username, salt, password_hash, role.
## The CHECK line makes the database itself refuse any role outside the allowed three.
def ensure_users_table():
    if not _database_enabled():
        print("[WARN] UserStore: No database configured, using the local users file")
        return False
    try:
        with _open_database() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username      TEXT PRIMARY KEY,
                    salt          TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role          TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'moderator')),
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
        print("[SUCCESS] UserStore: Users table is ready")
        return True
    except Exception as e:
        ## The message from psycopg doesn't include the password, but the error class name is enough here.
        print(f"[ERROR] UserStore: Could not prepare users table ({type(e).__name__})")
        return False
## endregion


## region: Database Users
## Reads one user row as {salt, password_hash, role}, or None if there's no such user.
## The %s placeholder lets psycopg pass the name safely, so a username can never run as SQL.
def _db_get_user(username):
    with _open_database() as connection:
        row = connection.execute(
            "SELECT salt, password_hash, role FROM users WHERE username = %s",
            (username,),
        ).fetchone()
    if row is None:
        return None
    return {"salt": row[0], "password_hash": row[1], "role": row[2]}

## Adds a user, or replaces them if the name already exists (same behavior as the JSON file).
## Leaving the "with" block commits the change.
def _db_save_user(username, salt_hex, password_hash, role):
    with _open_database() as connection:
        connection.execute(
            """
            INSERT INTO users (username, salt, password_hash, role)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (username) DO UPDATE
            SET salt = EXCLUDED.salt, password_hash = EXCLUDED.password_hash, role = EXCLUDED.role
            """,
            (username, salt_hex, password_hash, role),
        )
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
        salt = secrets.token_bytes(16)
        password_hash = _make_hash(password_text, salt)
        ## With a database configured, save there (making the table first if needed).
        if _database_enabled():
            if not ensure_users_table():
                return False
            _db_save_user(username, salt.hex(), password_hash, role)
        ## Without one, keep using the local JSON file.
        else:
            users = _load_users()
            users[username] = {"salt": salt.hex(), "password_hash": password_hash, "role": role}
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
        ## If a database is configured, only the database counts. When it's down, the
        ## error lands in the except below and the login is refused. It never falls back to the file.
        lookup_name = str(username or "").strip().lower()
        user_record = _db_get_user(lookup_name) if _database_enabled() else _load_users().get(lookup_name)
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