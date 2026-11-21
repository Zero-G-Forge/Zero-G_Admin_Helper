## =====================================================================
## MODULE: login_service/session_store.py
## DESCRIPTION: "Keep me logged in" sessions for the login service.
## Saved in ZAH-DB so they survive a ZAH-BOT restart. Without a database
## (local testing) they are kept in memory and cleared on restart.
## Only a SHA-256 fingerprint of each token is stored, never the token itself.
## =====================================================================

# region Imports

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

## Reuse the database helpers from user_store, so only one place opens ZAH-DB.
from user_store import _database_enabled, _open_database, _db_get_user, _load_users

# endregion


# region Constants

## The "Keep me logged in" choices, in seconds. None means Unlimited (no expiry).
## Anything not in this list is refused, so a client can't make up its own length.
REMEMBER_CHOICES = {
    "8h": 8 * 60 * 60,
    "12h": 12 * 60 * 60,
    "1d": 24 * 60 * 60,
    "7d": 7 * 24 * 60 * 60,
    "unlimited": None,
}

## Test sessions when there is no database: {token_hash: {"username", "expires_at"}}.
local_sessions = {}

# endregion


# region Token Fingerprint

## SHA-256 turns the token into a fingerprint. The same token always gives the same
## fingerprint, but the fingerprint can't be turned back into the token.
## So even someone who reads the database can't sign in with what's stored there.

def _token_hash(session_token):
    return hashlib.sha256(str(session_token).encode("utf-8")).hexdigest()

# endregion


# region Database Table

## Creates the sessions table once. "IF NOT EXISTS" makes it safe on every start,
## and it never changes the users table.
## expires_at is left empty (NULL) for Unlimited.
## ON DELETE CASCADE: if a user is deleted, their sessions are deleted with them.

def ensure_sessions_table():
    if not _database_enabled():
        print("[WARN] SessionStore: No database configured, keeping sessions in memory")
        return False

    try:
        with _open_database() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash  TEXT PRIMARY KEY,
                    username    TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
                    expires_at  TIMESTAMPTZ,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
        print("[SUCCESS] SessionStore: Sessions table is ready")
        return True

    except Exception as e:

        ## Only the error type is printed, so nothing from DATABASE_URL can leak into the log.
        print(f"[ERROR] SessionStore: Could not prepare sessions table ({type(e).__name__})")
        return False

# endregion


# region Sessions

## Makes a new remembered session and returns its token, or None if it can't (fails closed).
## remember must be one of the REMEMBER_CHOICES keys; anything else is refused.

def create_session(username, remember):
    if remember not in REMEMBER_CHOICES:
        print(f"[ERROR] SessionStore: Unknown remember choice '{remember}'")
        return None

    try:
        username = str(username or "").strip().lower()

        ## token_urlsafe(32) makes a long random pass that can't be guessed.
        ## Only its fingerprint is saved here; the token itself goes back to ZAH once.
        session_token = secrets.token_urlsafe(32)
        token_hash = _token_hash(session_token)

        ## The expiry is "now + the chosen time" in UTC, or None for Unlimited.
        lifetime_sec = REMEMBER_CHOICES[remember]
        expires_at = None if lifetime_sec is None else datetime.now(timezone.utc) + timedelta(seconds=lifetime_sec)

        if _database_enabled():
            with _open_database() as connection:
                connection.execute(
                    "INSERT INTO sessions (token_hash, username, expires_at) VALUES (%s, %s, %s)",
                    (token_hash, username, expires_at),
                )

        else:
            local_sessions[token_hash] = {"username": username, "expires_at": expires_at}

        print(f"[SUCCESS] SessionStore: Remembered session for {username} ({remember})")
        return session_token

    except Exception as e:
        print(f"[ERROR] SessionStore: Could not create session ({type(e).__name__})")
        return None


## Returns {"username", "role"} for a good, unexpired token, or None (fails closed).
## The role is read fresh from users, so a changed role or a deleted user counts right away.

def check_session(session_token):
    try:
        if not session_token:
            return None
        token_hash = _token_hash(session_token)

        if _database_enabled():

            ## Only a row whose expiry is empty (Unlimited) or still in the future counts.
            with _open_database() as connection:
                row = connection.execute(
                    """
                    SELECT username FROM sessions
                    WHERE token_hash = %s AND (expires_at IS NULL OR expires_at > now())
                    """,
                    (token_hash,),
                ).fetchone()
            username = row[0] if row else None
            user_record = _db_get_user(username) if username else None

        else:
            session = local_sessions.get(token_hash)
            if session is None:
                return None
            expires_at = session["expires_at"]
            if expires_at is not None and expires_at <= datetime.now(timezone.utc):
                return None
            username = session["username"]
            user_record = _load_users().get(username)

        ## No user (deleted, or never there) means no session.
        if not user_record:
            return None
        return {"username": username, "role": user_record.get("role")}

    except Exception as e:
        print(f"[ERROR] SessionStore: Could not check session ({type(e).__name__})")
        return None


## Deletes a session so its token can never be used again. Returns True if it worked.

def delete_session(session_token):
    try:
        token_hash = _token_hash(session_token)

        if _database_enabled():
            with _open_database() as connection:
                connection.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash,))

        else:
            local_sessions.pop(token_hash, None)

        print("[INFO] SessionStore: Session ended")
        return True

    except Exception as e:
        print(f"[ERROR] SessionStore: Could not delete session ({type(e).__name__})")
        return False

# endregion