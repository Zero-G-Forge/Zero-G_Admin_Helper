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
    ##   ("denied", None)                      wrong username or password
    ##   ("offline", None)                     service could not be reached
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
        print(f"[WARNING] OnlineLogin: Service refused login ({e.code})")
        return "denied", None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        ## URLError, TimeoutError and OSError mean no answer at all (no internet, service down).
        ## The password is never logged, only the reason.
        print(f"[ERROR] OnlineLogin: Service unreachable: {e}")
        return "offline", None

# endregion