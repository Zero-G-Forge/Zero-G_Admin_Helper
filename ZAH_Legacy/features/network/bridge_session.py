# bridge_session.py
"""
One ZeroGBridge TCP session.

The bridge listens on port 30500. The first line has to be auth:<token>\\r\\n.
A JSON AUTH object comes back: status Authenticated keeps the socket open,
Denied or Required closes it. Later lines are commands such as plys, gents,
and alert:{json}, each answered with one JSON line.
"""

import json
import socket


# Keep the GUI thread from sitting on a dead host. The cockpit logs this value.
BRIDGE_LOGIN_TIMEOUT = 5.0


class BridgeAuthError(Exception):
    """ZeroGBridge refused the auth:<token> handshake."""

    def __init__(self, status, message=""):
        self.status = status or "Denied"
        detail = message or self.status
        super().__init__(f"{self.status}: {detail}")


def login_failure_message(host, port, err):
    """Short reason shown in the server-login dialog and the [ERROR] log."""
    label = f"{host}:{port}"
    if isinstance(err, BridgeAuthError):
        return f"Authentication was rejected for {label}."
    if isinstance(err, (TimeoutError, socket.timeout)):
        return f"Could not reach {label}: connection timed out"
    if isinstance(err, (ConnectionRefusedError, socket.gaierror)):
        return f"Could not reach {label}: host unreachable"
    text = str(err).lower()
    if "timed out" in text:
        return f"Could not reach {label}: connection timed out"
    if "refused" in text or "unreachable" in text or "no route" in text:
        return f"Could not reach {label}: host unreachable"
    return f"Could not reach {label}: {err}"


def close_bridge_socket(sock):
    """Closes a ZeroGBridge socket. A missing or already-closed socket is ignored."""
    if sock is None:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass
    try:
        sock.close()
    except Exception:
        pass


def send_bridge_command(sock, command_str):
    """Sends one command with the \\r\\n line ending the bridge's reader expects."""
    if not sock:
        return
    formatted_cmd = str(command_str).strip() + "\r\n"
    sock.sendall(formatted_cmd.encode("utf-8"))


def _read_auth_line(sock, timeout):
    """
    Reads a single newline-terminated reply one byte at a time so the bytes
    after the AUTH line stay in the socket for the telemetry reader.
    """
    sock.settimeout(timeout)
    pieces = []
    while True:
        chunk = sock.recv(1)
        if not chunk:
            break
        if chunk == b"\n":
            break
        pieces.append(chunk)
        if len(pieces) > 8192:
            break
    if not pieces:
        raise BridgeAuthError("Closed", "Bridge closed the connection during auth.")
    return b"".join(pieces).decode("utf-8", errors="replace").strip().lstrip("\ufeff").strip()


def open_authenticated_socket(host, port, token, timeout=BRIDGE_LOGIN_TIMEOUT):
    """
    Opens a TCP session and completes auth:<token>.
    Returns the open socket after an Authenticated reply. Any other result
    closes the socket and raises BridgeAuthError.
    """
    print(f"[BridgeSession] -INFO- Connecting to ZeroGBridge socket at {host}:{port}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect((str(host), int(port)))
        auth_token = token if token is not None else ""
        sock.sendall(f"auth:{auth_token}\r\n".encode("utf-8"))
        print("[BridgeSession] -STATUS- Transmitted socket auth handshake.")

        raw_line = _read_auth_line(sock, timeout)
        try:
            payload = json.loads(raw_line) if raw_line else {}
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        status = str(payload.get("status", ""))
        if payload.get("type") == "AUTH" and status == "Authenticated":
            print(f"[BridgeSession] -STATUS- Authentication accepted on {host}:{port}.")
            sock.settimeout(timeout)
            return sock

        message = str(payload.get("message", "Authentication failed"))
        print(f"[BridgeSession] -WARN- Authentication {status or 'failed'} on {host}:{port}.")
        raise BridgeAuthError(status or "Denied", message)
    except BridgeAuthError as err:
        close_bridge_socket(sock)
        print(f"[ERROR] {login_failure_message(host, port, err)}")
        raise
    except Exception as err:
        close_bridge_socket(sock)
        print(f"[ERROR] {login_failure_message(host, port, err)}")
        raise


def switch_authenticated_socket(current_sock, host, port, token, timeout=BRIDGE_LOGIN_TIMEOUT):
    """
    Closes the current ZeroGBridge session first, then authenticates to host:port.
    The closed socket is not reused. On auth failure the new socket is closed too.
    """
    print(f"[BridgeSession] -INFO- Closing current ZeroGBridge session before switch to {host}:{port}.")
    close_bridge_socket(current_sock)
    return open_authenticated_socket(host, port, token, timeout=timeout)
