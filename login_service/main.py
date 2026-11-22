## =====================================================================
## MODULE: login_service/main.py
## DESCRIPTION: ZAH online login service (runs on bot-hosting ZAH-BOT later).
## Answers small JSON requests over HTTP. Part 5b-1: health check only.
## =====================================================================

# region Imports

import json
import os
import secrets
import time

## user_store.py sits in the same folder, so it can be imported by name.
from user_store import check_user, ensure_users_table

## session_store keeps the "Keep me logged in" sessions
## (ZAH-DB, or memory when testing).
from session_store import (ensure_sessions_table, create_session, check_session, delete_session, REMEMBER_CHOICES,)

## rate_limiter counts failed logins and locks out guessing.
from rate_limiter import is_locked_out, record_failure, record_success

## login_log saves every failed login in ZAH-DB (or memory when testing).
from login_log import ensure_login_log_table, log_failed_login, list_failed_logins

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# endregion


# region Constants

## bot-hosting gives the port in the SERVER_PORT setting; 25109 is ZAH-BOT's port.
## Locally it falls back to 8765 so testing never needs the real port.
SERVICE_PORT = int(os.environ.get("SERVER_PORT", "8765"))

## "127.0.0.1" = only this computer can reach it (safe for local testing).
## On bot-hosting this becomes "0.0.0.0" through the SERVICE_HOST setting.
SERVICE_HOST = os.environ.get("SERVICE_HOST", "127.0.0.1")

## How long a session token stays valid (8 hours, in seconds).
SESSION_LIFETIME_SEC = 8 * 60 * 60

## Biggest login request accepted (4 KB). Stops anyone sending huge junk.
MAX_BODY_BYTES = 4096

## Active sessions in memory: {token: {"username", "role", "expires_at"}}.
## They are cleared if the service restarts, so everyone signs in again (safe default).
active_sessions = {}

## Developer key for Ray's offline developer login (a ZAH-BOT Environment secret, never in code).
## Empty or too short means it's switched off, so the route stays owners-only (fails closed).
DEV_LOG_KEY = os.environ.get("ZAH_DEV_KEY", "")
DEV_KEY_MIN_LEN = 32

# endregion


# region Request Handler

class LoginRequestHandler(BaseHTTPRequestHandler):

    ## Sends one JSON reply with a status code (200 = OK, 404 = not found, and so on).
    def _send_json(self, status_code, reply_data):
        reply_bytes = json.dumps(reply_data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply_bytes)))
        self.end_headers()
        self.wfile.write(reply_bytes)

    ## The address the request came from. Behind bot-hosting's proxy, the real address is the first one in X-Forwarded-For.
    def _client_source(self):
        forwarded_for = self.headers.get("X-Forwarded-For", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return self.client_address[0]

    ## Returns the role for a login token, or None if it is unknown or expired (fails closed).
    ## Normal logins live in active_sessions; "Keep me logged in" logins live in ZAH-DB (check_session).
    def _token_role(self, token):
        token = str(token or "")
        if not token:
            return None
        session = active_sessions.get(token)
        if session is not None:
            if session["expires_at"] > time.time():
                return session["role"]

            ## Expired: forget it so it can't be used again.
            active_sessions.pop(token, None)
            return None
        session_info = check_session(token)
        return session_info["role"] if session_info else None

    ## True only if the developer key is switched on and the sent key matches it exactly.
    ## compare_digest takes the same time whether the key is close or not, so it can't be guessed one letter at a time.
    def _dev_key_ok(self, sent_key):
        if len(DEV_LOG_KEY) < DEV_KEY_MIN_LEN:
            return False
        return secrets.compare_digest(str(sent_key or ""), DEV_LOG_KEY)

    ## do_GET runs for every GET request; self.path is the address part, like "/health".
    def do_GET(self):
        try:
            if self.path == "/health":
                self._send_json(200, {"status": "ok", "service": "zah-login"})
            else:
                self._send_json(404, {"status": "error", "message": "not found"})
        except Exception as e:
            print(f"[ERROR] LoginService: GET failed: {e}")
            self._send_json(500, {"status": "error", "message": "server error"})

    ## do_POST runs for POST requests. ZAH sends {"username": ..., "password": ...} to /login.
    def do_POST(self):
        try:
            if self.path not in ("/login", "/session", "/logout", "/failed_logins"):
                self._send_json(404, {"status": "error", "message": "not found"})
                return

            ## Content-Length says how many bytes the request body has; too big or missing is refused.
            body_length = int(self.headers.get("Content-Length", "0"))
            if body_length <= 0 or body_length > MAX_BODY_BYTES:
                self._send_json(400, {"status": "error", "message": "bad request"})
                return

            ## Junk that is not JSON (or not a {...} object) is the client's fault: 400, not 500.
            try:
                login_data = json.loads(self.rfile.read(body_length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                login_data = None
            if not isinstance(login_data, dict):
                self._send_json(400, {"status": "error", "message": "bad request"})
                return

            ## /session: ZAH asks "is this saved token still good, and who is it?" 401 for expired, unknown or deleted users. The role comes fresh from users.
            if self.path == "/session":
                session_info = check_session(
                    login_data.get("token", ""))
                if session_info is None:
                    self._send_json(401, {"status": "error", "message": "session expired or unknown"})
                    return
                self._send_json(200, {"status": "ok", "username": session_info["username"], "role": session_info["role"]})
                return

            ## /logout: ends the token everywhere it might live, so it can never be used again. It answers ok even for an unknown token, so nobody can test tokens.
            if self.path == "/logout":
                logout_token = str(login_data.get("token", ""))
                active_sessions.pop(logout_token, None)
                delete_session(logout_token)
                self._send_json(200, {"status": "ok"})
                return

            ## /failed_logins: owners only. ZAH sends its login token, and the newest failed logins come back.
            ## 403 = not allowed. A bad token and a non-owner get the same reply, so nobody can test tokens.
            if self.path == "/failed_logins":
                if self._token_role(login_data.get("token")) != "owner" and not self._dev_key_ok(login_data.get("dev_key")):
                    self._send_json(403, {"status": "error", "message": "not allowed"})
                    return
                self._send_json(200, {"status": "ok", "entries": list_failed_logins(login_data.get("limit", 50))})
                return

            username = str(login_data.get("username", "")).strip()
            source = self._client_source()

            ## 429 = too many tries. Checked before the password, so a locked account can't be guessed at all.
            if is_locked_out(username, source):
                print(f"[WARNING] LoginService: Too many failed logins for {username or '(blank)'}, refused")
                log_failed_login(username, source, "locked out")
                self._send_json(429, {"status": "error", "message": "too many tries, wait and try again"})
                return

            role = check_user(username, login_data.get("password", ""))

            ## 401 = not allowed. The same message for a wrong user or wrong password,
            ## so nobody can use it to find out which usernames exist.
            if role is None:
                print(f"[WARNING] LoginService: Failed login for {username or '(blank)'}")
                record_failure(username, source)
                log_failed_login(username, source, "wrong password")
                self._send_json(401, {"status": "error", "message": "wrong username or password"})
                return

            ## Good login: clear this username's failed tries.
            record_success(username)

            ## "Keep me logged in": a remember choice saves the session (ZAH-DB) for that long. A made-up choice is refused; no choice keeps the normal 8-hour login.
            remember = login_data.get("remember")
            if remember:
                if remember not in REMEMBER_CHOICES:
                    self._send_json(400, {"status": "error", "message": "bad remember choice"})
                    return
                session_token = create_session(username, remember)
                if session_token is None:
                    self._send_json(500, { "status": "error", "message": "server error"})
                    return
                print(f"[SUCCESS] LoginService: {username.lower()}"
                      f" signed in ({role}, remembered {remember})")
                self._send_json(200, {"status": "ok", "token": session_token, "role": role, "remember": remember})
                return

            ## token_urlsafe(32) makes a long random pass that cannot be guessed.
            session_token = secrets.token_urlsafe(32)
            active_sessions[session_token] = {
                "username": username.lower(),
                "role": role,
                "expires_at": time.time() + SESSION_LIFETIME_SEC,
            }
            print(f"[SUCCESS] LoginService: {username.lower()} signed in ({role})")
            self._send_json(200, {"status": "ok", "token": session_token,
                                  "role": role, "expires_in": SESSION_LIFETIME_SEC})
        except Exception as e:
            print(f"[ERROR] LoginService: Login request failed: {e}")
            self._send_json(500, {"status": "error", "message": "server error"})

    ## Replaces the built-in request log with the ZAH log style (no passwords ever appear here).
    def log_message(self, format_text, *args):
        print(f"[INFO] LoginService: {self.command} {self.path.split('?')[0]}")

# endregion


# region Start Up

def main():
    print(f"[INFO] LoginService: Starting on {SERVICE_HOST}:{SERVICE_PORT}")

    ## Make sure ZAH-DB has its users table before any login comes in.
    ## With no DATABASE_URL (local testing), this just prints a WARN and the JSON file is used.
    ensure_users_table()

    ## Then the sessions table (after users, because
    ## each session points at a user).
    ensure_sessions_table()

    ## Then the failed login log table.
    ensure_login_log_table()

    ## ThreadingHTTPServer answers several requests at once, so one slow client can't block others.
    server = ThreadingHTTPServer((SERVICE_HOST, SERVICE_PORT), LoginRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[INFO] LoginService: Stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

# endregion