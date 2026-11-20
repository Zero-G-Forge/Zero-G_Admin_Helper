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
            if self.path != "/login":
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

            username = str(login_data.get("username", "")).strip()
            role = check_user(username, login_data.get("password", ""))

            ## 401 = not allowed. The same message for a wrong user or wrong password,
            ## so nobody can use it to find out which usernames exist.
            if role is None:
                print(f"[WARNING] LoginService: Failed login for {username or '(blank)'}")
                self._send_json(401, {"status": "error", "message": "wrong username or password"})
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