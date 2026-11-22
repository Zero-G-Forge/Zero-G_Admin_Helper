## =====================================================================
## MODULE: features/server_files/file_client.py
## DESCRIPTION: Talks to ZeroGBridge's read-only files: commands (files:info, files:list, files:get).
## It opens its own short session (so it never mixes with the dashboard's telemetry socket), logs in,
## and sends one command at a time with the required pause between commands.
## Every wait has a timeout. The bridge password (input_pass) is only written to the socket,
## never printed, logged or put into an error message.
## =====================================================================

# region Imports

import json
import socket
import time
import uuid

from features.zgb_portal.bridge_session import (
    BridgeAuthError,
    close_bridge_socket,
    open_authenticated_socket,
    send_bridge_command,
)

# endregion


# region Constants

## Seconds to wait for one reply, and for connecting and logging in.
REPLY_TIMEOUT_SEC = 20.0
LOGIN_TIMEOUT_SEC = 8.0

## The bridge rules ask for about half a second between commands.
COMMAND_GAP_SEC = 0.5

## A reply line bigger than this is treated as broken. A files:get reply is about 256 KB, so this leaves room.
MAX_REPLY_BYTES = 2 * 1024 * 1024

## The protocol number ZAH understands. The bridge reports its own in files:info.
SUPPORTED_PROTOCOL = 1

# endregion


# region Errors

## One error type for every download problem. kind tells the caller what went wrong:
## config (no server or password saved), offline, auth, timeout, closed, unsupported (old bridge),
## protocol (reply made no sense) and refused (the bridge said no).
class ServerFilesError(Exception):

    def __init__(self, kind, message):
        self.kind = kind
        super().__init__(message)

# endregion


# region Session

## One open, logged-in session. Use it with "with", so the socket is always closed:
##   with ServerFilesSession(profile) as session:
##       info = session.request("info")
class ServerFilesSession:

    def __init__(self, profile):
        self.profile = profile if isinstance(profile, dict) else {}
        self.sock = None
        self.reader = None
        self.last_send_time = 0.0
        ## Text used in messages. The port is not secret; the password is never stored here.
        self.label = ""

    # region Open and Close

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        ## Returning False lets any error continue to the caller.
        return False

    def open(self):
        host = str(self.profile.get("input_ip", "")).strip()
        token = str(self.profile.get("input_pass", "") or "")
        try:
            port = int(str(self.profile.get("bridge_port", "30500")).strip() or "30500")
        except ValueError:
            port = 30500
        self.label = f"{host}:{port}"
        if not host:
            raise ServerFilesError("config", "No active server is saved in ZAH.")
        if not token:
            raise ServerFilesError("config", "The active server has no bridge password saved.")
        try:
            self.sock = open_authenticated_socket(host, port, token, timeout=LOGIN_TIMEOUT_SEC)
        except BridgeAuthError:
            raise ServerFilesError("auth", "The server rejected the bridge login.") from None
        except (TimeoutError, socket.timeout):
            raise ServerFilesError("timeout", "The server did not answer in time.") from None
        except OSError as e:
            raise ServerFilesError("offline", f"Could not reach the server ({type(e).__name__}).") from None
        self.reader = self.sock.makefile("rb")

    def close(self):
        close_bridge_socket(self.sock)
        self.sock = None
        self.reader = None

    # endregion

    # region Requests

    ## Sends "files:<sub>:<json>" and returns the matching FILES reply as a dictionary.
    ## Raises ServerFilesError("unsupported") when the bridge does not know the command yet.
    def request(self, sub_command, payload=None):
        if self.sock is None:
            raise ServerFilesError("closed", "The connection is not open.")

        body = dict(payload or {})
        request_id = f"zah-files-{uuid.uuid4().hex[:8]}"
        body["req_id"] = request_id
        command = f"files:{sub_command}:{json.dumps(body, separators=(',', ':'))}"

        ## Keep the half-second gap between commands.
        wait = COMMAND_GAP_SEC - (time.monotonic() - self.last_send_time)
        if wait > 0:
            time.sleep(wait)
        try:
            send_bridge_command(self.sock, command)
        except OSError as e:
            raise ServerFilesError("closed", f"Lost the connection to the server ({type(e).__name__}).") from None
        self.last_send_time = time.monotonic()

        deadline = time.monotonic() + REPLY_TIMEOUT_SEC
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ServerFilesError("timeout", "The server did not reply in time.")
            self.sock.settimeout(max(0.2, min(remaining, 5.0)))
            try:
                raw_line = self.reader.readline(MAX_REPLY_BYTES)
            except (TimeoutError, socket.timeout):
                continue
            except OSError as e:
                raise ServerFilesError("closed", f"Lost the connection to the server ({type(e).__name__}).") from None
            if not raw_line:
                raise ServerFilesError("closed", "The server closed the connection.")
            if not raw_line.endswith(b"\n"):
                raise ServerFilesError("protocol", "A reply from the server was cut off or too large.")
            try:
                reply = json.loads(raw_line.decode("utf-8-sig").strip())
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(reply, dict):
                continue

            reply_type = reply.get("type")
            if reply_type == "FILES":
                ## A reply for another request id is skipped; only ours counts.
                if reply.get("req_id") not in (None, request_id):
                    continue
                if reply.get("ok") is not True:
                    raise ServerFilesError("refused", f"The server refused the request: {reply.get('error', 'unknown')}.")
                return reply

            ## An old bridge does not know files: and answers with its generic acknowledgement or an ERROR line.
            if reply_type in ("RESPONSE", "ERROR"):
                raise ServerFilesError("unsupported", "This server's ZeroGBridge does not have the file commands yet. "
                                                      "Ask the owner to update the bridge.")

            ## Anything else (METRIC telemetry and similar) is not an answer to this request.
            continue

    # endregion

# endregion
