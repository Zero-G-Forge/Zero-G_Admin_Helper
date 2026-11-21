## =====================================================================
## MODULE: login_service/login_log.py
## DESCRIPTION: Failed login log for the login service.
## Saved in ZAH-DB so it survives a ZAH-BOT restart. Without a database
## (local testing) it is kept in memory and cleared on restart.
## Only the time, username, address and reason are saved, never the password.
## =====================================================================

# region Imports

from datetime import datetime, timezone

## Reuse the database helpers from user_store, so only one place opens ZAH-DB.
from user_store import _database_enabled, _open_database

# endregion


# region Constants

## Entries older than this many days are deleted, so the table never grows forever.
KEEP_DAYS = 30

## Longest username or address saved. Stops anyone filling the table with huge junk.
MAX_TEXT_LEN = 64

## Test entries when there is no database: a list of {"failed_at", "username", "source", "reason"}.
local_failed_logins = []

# endregion


# region Database Table

## Creates the failed_logins table once. "IF NOT EXISTS" makes it safe on every start.
## There is no link to the users table on purpose: wrong usernames get logged too.
## The index on failed_at keeps the "delete old entries" step quick.

def ensure_login_log_table():
    if not _database_enabled():
        print("[WARN] LoginLog: No database configured, keeping the failed login log in memory")
        return False

    try:
        with _open_database() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS failed_logins (
                    id         BIGSERIAL PRIMARY KEY,
                    failed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                    username   TEXT NOT NULL,
                    source     TEXT NOT NULL,
                    reason     TEXT NOT NULL
                )
            """)
            connection.execute("CREATE INDEX IF NOT EXISTS failed_logins_time ON failed_logins (failed_at)")
        print("[SUCCESS] LoginLog: Failed login table is ready")
        return True

    except Exception as e:

        ## Only the error type is printed, so nothing from DATABASE_URL can leak into the log.
        print(f"[ERROR] LoginLog: Could not prepare failed login table ({type(e).__name__})")
        return False

# endregion


# region Log Entries

## Saves one failed login. reason is "wrong password" or "locked out".
## A logging problem never stops the login service; it just prints an error.

def log_failed_login(username, source, reason):
    try:

        ## Lowercase like the users table, cut to MAX_TEXT_LEN, and "(blank)" for an empty name.
        username = str(username or "").strip().lower()[:MAX_TEXT_LEN] or "(blank)"
        source = str(source or "").strip()[:MAX_TEXT_LEN] or "(unknown)"

        if _database_enabled():
            with _open_database() as connection:
                connection.execute(
                    "INSERT INTO failed_logins (username, source, reason) VALUES (%s, %s, %s)",
                    (username, source, reason),
                )

                ## Delete entries older than KEEP_DAYS while the connection is open.
                connection.execute(
                    "DELETE FROM failed_logins WHERE failed_at < now() - make_interval(days => %s)",
                    (KEEP_DAYS,),
                )

        else:
            local_failed_logins.append({
                "failed_at": datetime.now(timezone.utc),
                "username": username,
                "source": source,
                "reason": reason,
            })

        return True

    except Exception as e:
        print(f"[ERROR] LoginLog: Could not save failed login ({type(e).__name__})")
        return False

# endregion


# region Reading The Log

## Biggest number of entries one request can ask for. Stops anyone asking for millions.
MAX_LIST_LIMIT = 200

## Returns the newest failed logins first, as a list of dicts:
## {"failed_at": "2026-11-21T08:15:00+00:00", "username", "source", "reason"}.
## Times are turned into text (ISO format) so they can go straight into a JSON reply.
## Any problem returns an empty list (fails closed), never an error page.

def list_failed_logins(limit=50):
    try:
        
        ## int() turns "50" into 50; then it is kept between 1 and MAX_LIST_LIMIT.
        limit = max(1, min(int(limit), MAX_LIST_LIMIT))

        if _database_enabled():
            with _open_database() as connection:
                rows = connection.execute(
                    "SELECT failed_at, username, source, reason FROM failed_logins ORDER BY failed_at DESC LIMIT %s",
                    (limit,),
                ).fetchall()

        else:
            
            ## The memory list is oldest first, so it is flipped to put the newest on top.
            rows = [(e["failed_at"], e["username"], e["source"], e["reason"]) for e in reversed(local_failed_logins)][:limit]
            
        return [
            {"failed_at": failed_at.isoformat(), "username": username, "source": source, "reason": reason}
            for failed_at, username, source, reason in rows
        ]
    
    except Exception as e:
        print(f"[ERROR] LoginLog: Could not read failed logins ({type(e).__name__})")
        return []

# endregion
