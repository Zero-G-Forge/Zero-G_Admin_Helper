## =====================================================================
## MODULE: login_service/rate_limiter.py
## DESCRIPTION: Slows down password guessing on /login.
## Counts failed logins per username and per address, in memory. Too many inside the window = refused for a while.
## A restart clears the counts (fine for a small service).
## =====================================================================

# region Imports

import threading
import time

# endregion


# region Constants

## The window failed tries are counted in (15 minutes, in seconds).
FAIL_WINDOW_SEC = 15 * 60

## Failed tries allowed for one username inside the window before it is locked.
MAX_FAILS_PER_USER = 5

## Failed tries allowed from one address inside the window. Higher, because several admins may share one address.
MAX_FAILS_PER_SOURCE = 20

# endregion


# region Fail Counters

## {key: [time of each failed try]}. Keys look like "user:manta" or "source:1.2.3.4".
failed_tries = {}

## ThreadingHTTPServer answers several requests at once, so the lock stops two threads changing the counts at the same moment.
counter_lock = threading.Lock()

## Drops tries older than the window and returns how many are left for this key. Only call it while holding counter_lock.
def _recent_fail_count(counter_key, now):
    recent = [fail_time for fail_time in failed_tries.get(counter_key, []) if now - fail_time < FAIL_WINDOW_SEC]
    if recent:
        failed_tries[counter_key] = recent
    else:
        failed_tries.pop(counter_key, None)
    return len(recent)

## True if this username or address has failed too many times lately. Checked BEFORE the password.
def is_locked_out(username, source):
    now = time.time()
    with counter_lock:
        user_fails = _recent_fail_count(f"user:{username.lower()}", now)
        source_fails = _recent_fail_count(f"source:{source}", now)
    return user_fails >= MAX_FAILS_PER_USER or source_fails >= MAX_FAILS_PER_SOURCE

## Counts one failed login for both the username and the address.
def record_failure(username, source):
    now = time.time()
    with counter_lock:
        failed_tries.setdefault(f"user:{username.lower()}", []).append(now)
        failed_tries.setdefault(f"source:{source}", []).append(now)

        ## Housekeeping: if junk usernames pile up, old entries are swept out so memory can't grow forever.
        if len(failed_tries) > 10000:
            for old_key in list(failed_tries):
                _recent_fail_count(old_key, now)

## A good login clears that username's count. The address count stays, so one good login can't hide guessing.
def record_success(username):
    with counter_lock:
        failed_tries.pop(f"user:{username.lower()}", None)

# endregion