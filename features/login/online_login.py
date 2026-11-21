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

# endregion


# region Constants

## The service's web address. ZAH_LOGIN_URL can override it for local tests,
## e.g. http://127.0.0.1:8765. The default is the ZAH-BOT HTTPS address.
LOGIN_SERVICE_URL = os.environ.get(
    "ZAH_LOGIN_URL", "https://90dqyqxomv.apps.bot-hosting.cloud"
)

## How many seconds to wait for the service before giving up.
LOGIN_TIMEOUT_SEC = 5

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
            return "ok", {"role": reply_data["role"], "token": reply_data["token"]}
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
            return "ok", {"username": reply_data["username"], "role": reply_data["role"]}
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



# endregion