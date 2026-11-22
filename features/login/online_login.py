## =====================================================================
## MODULE: features/login/online_login.py
## DESCRIPTION: Asks the online login service if a username and password are right.
## Used for every user except the owner, who signs in offline.
## =====================================================================

# region Imports

import os
import json
import urllib.request
import urllib.error

## data_path gives the full path to a file in ZAH's data/ folder
from features.paths import data_path

# endregion


# region Constants

## The service's web address. ZAH_LOGIN_URL can override it for local tests,
## e.g. http://127.0.0.1:8765. The default is the ZAH-BOT HTTPS address.
LOGIN_SERVICE_URL = os.environ.get(
    "ZAH_LOGIN_URL", "https://90dqyqxomv.apps.bot-hosting.cloud"
)

## How many seconds to wait for the service before giving up.
LOGIN_TIMEOUT_SEC = 5

## Ray's developer key file, in data/ (git-ignored and never bundled in builds).
DEV_KEY_FILE = "dev_key.txt"

# endregion


# region Online Login Check

def check_online_login(username, password_text, remember=None):
    ## Returns a tuple: (result, details).
    ##   ("ok", {"role": ..., "token": ...})  login accepted
    ##   ("denied", None)                     wrong username or password
    ##   ("offline", None)                    service could not be reached
    ##   ("locked", None)                     too many failed attempts, wait and try again
    ## Anything strange counts as "not signed in" (fail closed).
    login_fields = {"username": username, "password": password_text}

    ## remember is only sent when the box was ticked; without it the service gives the normal 8-hour login.
    if remember:
        login_fields["remember"] = remember
    login_body = json.dumps(login_fields).encode("utf-8")
    login_request = urllib.request.Request(
        LOGIN_SERVICE_URL.rstrip("/") + "/login",
        data=login_body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(login_request, timeout=LOGIN_TIMEOUT_SEC) as reply:
            reply_data = json.loads(reply.read().decode("utf-8"))
        ## A 200 reply must hold both a role and a token, or it is not trusted.
        if (isinstance(reply_data, dict) and reply_data.get("status") == "ok"
                and reply_data.get("role") and reply_data.get("token")):
            print(f"[SUCCESS] OnlineLogin: Service accepted {username}")
            ## live_file_editing is True only when the service says exactly true (an older service sends nothing).
            return "ok", {"role": reply_data["role"], "token": reply_data["token"],
                          "live_file_editing": reply_data.get("live_file_editing") is True}
        print("[WARNING] OnlineLogin: Service sent an unexpected reply")
        return "denied", None
    except urllib.error.HTTPError as e:
        ## HTTPError means the service answered, but said no (401, 400...).

        ## 429 = too many failed tries; the service is locking this name out for a while.
        if e.code == 429:
            print("[WARNING] OnlineLogin: Service says too many tries (429)")
            return "locked", None
        print(f"[WARNING] OnlineLogin: Service refused login ({e.code})")
        return "denied", None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        ## URLError, TimeoutError and OSError mean no answer at all (no internet, service down).
        ## The password is never logged, only the reason.
        print(f"[ERROR] OnlineLogin: Service unreachable: {e}")
        return "offline", None

## Asks the service if a saved "Keep me logged in" token is still good.
## Returns the same kind of tuple as check_online_login:
##   ("ok", {"username": ..., "role": ...})  token still good
##   ("denied", None)                         expired, unknown, or the user was removed
##   ("offline", None)                        service could not be reached
def check_saved_session(session_token):
    session_body = json.dumps({"token": session_token}).encode("utf-8")
    session_request = urllib.request.Request(
        LOGIN_SERVICE_URL.rstrip("/") + "/session",
        data=session_body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(session_request, timeout=LOGIN_TIMEOUT_SEC) as reply:
            reply_data = json.loads(reply.read().decode("utf-8"))

        ## Like a login, a 200 reply must hold both a username and a role, or it is not trusted.
        if (isinstance(reply_data, dict) and reply_data.get("status") == "ok"
                and reply_data.get("username") and reply_data.get("role")):
            print(f"[SUCCESS] OnlineLogin: Saved login still good for {reply_data['username']}")
            return "ok", {"username": reply_data["username"], "role": reply_data["role"],
                          "live_file_editing": reply_data.get("live_file_editing") is True}
        print("[WARNING] OnlineLogin: Service sent an unexpected session reply")
        return "denied", None
    except urllib.error.HTTPError as e:

        ## 401 here means the saved login ran out or was removed; the user just signs in again.
        print(f"[INFO] OnlineLogin: Saved login no longer valid ({e.code})")
        return "denied", None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:

        ## No answer at all. The token is never logged, only the reason.
        print(f"[ERROR] OnlineLogin: Service unreachable for saved login: {e}")
        return "offline", None

## Tells the service to end a token, so it can never be used again (LOGOUT).
## Returns True if the service answered. False is not a problem: the saved file is deleted anyway.
def end_online_session(session_token):
    logout_body = json.dumps({"token": session_token}).encode("utf-8")
    logout_request = urllib.request.Request(
        LOGIN_SERVICE_URL.rstrip("/") + "/logout",
        data=logout_body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(logout_request, timeout=LOGIN_TIMEOUT_SEC):
            pass
        print("[SUCCESS] OnlineLogin: Service ended the saved login")
        return True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:

        ## HTTPError is a kind of URLError, so a refusal lands here too. The token is never logged.
        print(f"[WARNING] OnlineLogin: Could not end the saved login on the service: {e}")
        return False

## Reads the developer key, or returns None if there's no key file (every install except Ray's).
## The key itself is never printed.
def load_dev_key():
    try:
        with open(data_path(DEV_KEY_FILE), "r", encoding="utf-8") as file_handle:
            dev_key = file_handle.read().strip()
        return dev_key or None
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"[ERROR] OnlineLogin: Could not read the developer key file: {e}")
        return None

## Asks the service for the newest failed logins (owners only).
## Returns the same kind of tuple as the others:
##   ("ok", [ {"failed_at", "username", "source", "reason"}, more entries ])  list received
##   ("denied", None)                                                        not an owner, or the token ran out
##   ("offline", None)                                                       service could not be reached

def fetch_failed_logins(session_token, limit=50, dev_key=None):

    ## The developer login has no token, so it sends its key instead. The service accepts either.
    fetch_fields = {"token": session_token, "limit": limit}
    if dev_key:
        fetch_fields["dev_key"] = dev_key
    fetch_body = json.dumps(fetch_fields).encode("utf-8")
    fetch_request = urllib.request.Request(
        LOGIN_SERVICE_URL.rstrip("/") + "/failed_logins",
        data=fetch_body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(fetch_request, timeout=LOGIN_TIMEOUT_SEC) as reply:
            reply_data = json.loads(reply.read().decode("utf-8"))

        ## A 200 reply must hold a real list, or it is not trusted.
        if (isinstance(reply_data, dict) and reply_data.get("status") == "ok"
                and isinstance(reply_data.get("entries"), list)):
            print(f"[SUCCESS] OnlineLogin: Got {len(reply_data['entries'])} failed login entries")
            return "ok", reply_data["entries"]
        print("[WARNING] OnlineLogin: Service sent an unexpected failed login reply")
        return "denied", None
    except urllib.error.HTTPError as e:

        ## 403 means this login is not an owner, or its token ran out. The token is never logged.
        print(f"[WARNING] OnlineLogin: Service refused the failed login list ({e.code})")
        return "denied", None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:

        ## No answer at all (no internet, service down).
        print(f"[ERROR] OnlineLogin: Service unreachable for failed login list: {e}")
        return "offline", None

## Sends one user manager request and returns ("ok", reply), ("denied", message) or ("offline", None).
## The message is the service's own reason, like "you can't remove or demote your own account".
## The token, key and password are never printed.
def _send_user_request(route, fields, session_token, dev_key):
    fields["token"] = session_token
    if dev_key:
        fields["dev_key"] = dev_key
    user_request = urllib.request.Request(
        LOGIN_SERVICE_URL.rstrip("/") + route,
        data=json.dumps(fields).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(user_request, timeout=LOGIN_TIMEOUT_SEC) as reply:
            reply_data = json.loads(reply.read().decode("utf-8"))
        if isinstance(reply_data, dict) and reply_data.get("status") == "ok":
            return "ok", reply_data
        return "denied", "unexpected reply"
    except urllib.error.HTTPError as e:

        ## Refused (403, 400 or 404). Read the service's reason if it sent one.
        try:
            refused_message = json.loads(e.read().decode("utf-8")).get("message", "refused")
        except Exception:
            refused_message = "refused"
        print(f"[WARNING] OnlineLogin: Service refused {route} ({e.code})")
        return "denied", refused_message
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:

        ## No answer at all (no internet, service down).
        print(f"[ERROR] OnlineLogin: Service unreachable for {route}: {e}")
        return "offline", None

## Gets the login users: ("ok", [ {"username", "role", "created_at"}, more users ]), or ("denied" / "offline", None).
def fetch_users(session_token, dev_key=None):
    fetch_result, reply_data = _send_user_request("/users", {}, session_token, dev_key)
    if fetch_result == "ok" and isinstance(reply_data, dict) and isinstance(reply_data.get("users"), list):
        return "ok", reply_data["users"]
    return ("offline" if fetch_result == "offline" else "denied"), None

## Adds a user or resets their password (with a password), or changes only the role (password left blank).
## server_name and server_address are the server this user belongs to. Blank means UNASSIGNED.
def save_user(session_token, username, role, password="", dev_key=None, server_name="", server_address=""):
    save_fields = {"username": username, "role": role, "password": password,
                   "server_name": server_name, "server_address": server_address}
    save_result, reply_data = _send_user_request("/users/save", save_fields, session_token, dev_key)
    return save_result, (None if save_result == "ok" else reply_data)

## Turns Live file editing on or off for a user (owners and the developer only; the service checks).
## ("ok", None), ("denied", reason), or ("offline", None).
def set_live_files(session_token, username, enabled, dev_key=None):
    live_result, reply_data = _send_user_request("/users/live_files", {"username": username, "enabled": bool(enabled)},
                                                 session_token, dev_key)
    return live_result, (None if live_result == "ok" else reply_data)

## Removes a user.
def remove_user(session_token, username, dev_key=None):
    remove_result, reply_data = _send_user_request("/users/delete", {"username": username}, session_token, dev_key)
    return remove_result, (None if remove_result == "ok" else reply_data)

# endregion