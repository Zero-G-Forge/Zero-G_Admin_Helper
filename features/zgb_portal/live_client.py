# live_client.py
"""
Short-lived, authenticated ZeroGBridge requests for the ZeroGBridge Portal.

Each request opens its own TCP session to the bridge (reusing ZAH's
bridge_session.open_authenticated_socket for the auth:<token> handshake),
sends one command line, waits for the matching JSON reply and closes.
That keeps the portal off the dashboard's telemetry socket, so the two
never read each other's replies.

Run these from a worker thread (see run_async); they block.

The AuthToken is only ever written to the socket. It is never logged,
printed, shown, or put into an exception message.
"""

from __future__ import annotations

import json
import socket
import time
import uuid

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from .bridge_session import (
    BridgeAuthError,
    close_bridge_socket,
    open_authenticated_socket,
    send_bridge_command,
)
from .server_config import bridge_port_of

DEFAULT_TIMEOUT = 8.0
RELOAD_TIMEOUT = 30.0


class PortalBridgeError(Exception):
    """A portal request failed. kind is one of: config, offline, auth, timeout, protocol, closed."""

    def __init__(self, kind: str, message: str):
        self.kind = kind
        super().__init__(message)


def profile_endpoint(profile: dict) -> tuple[str, int]:
    host = str((profile or {}).get("input_ip", "")).strip()
    try:
        port = int(bridge_port_of(profile))
    except (TypeError, ValueError):
        port = 30500
    return host, port


def _scrub(text: str, token: str) -> str:
    text = str(text)
    if token and token in text:
        text = text.replace(token, "***")
    return text


def bridge_request(profile: dict, command: str, want_type: str, req_id: str | None = None,
                   timeout: float = DEFAULT_TIMEOUT) -> dict:
    """
    Opens a session, authenticates, sends `command`, and returns the first JSON
    reply whose type is `want_type` (and whose req_id matches, when given).
    Unrelated lines (METRIC, telemetry, bad JSON) are skipped.
    """
    host, port = profile_endpoint(profile)
    token = str((profile or {}).get("input_pass", "") or "")
    if not host:
        raise PortalBridgeError("config", "No active server is set in ZAH.")
    if not token:
        raise PortalBridgeError("config", "The active server has no bridge password saved.")

    try:
        sock = open_authenticated_socket(host, port, token, timeout=min(timeout, 8.0))
    except BridgeAuthError:
        raise PortalBridgeError("auth", f"Auth failed on {host}:{port}.") from None
    except (TimeoutError, socket.timeout):
        raise PortalBridgeError("timeout", f"{host}:{port} did not answer in time.") from None
    except OSError as err:
        raise PortalBridgeError("offline", f"Could not reach {host}:{port} ({err.__class__.__name__}).") from None

    try:
        send_bridge_command(sock, command)
        deadline = time.monotonic() + timeout
        reader = sock.makefile("rb")
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PortalBridgeError("timeout", f"No {want_type} reply from {host}:{port}.")
            sock.settimeout(max(0.2, min(remaining, 5.0)))
            try:
                raw = reader.readline()
            except (TimeoutError, socket.timeout):
                continue
            if not raw:
                raise PortalBridgeError("closed", f"{host}:{port} closed the connection.")
            try:
                payload = json.loads(raw.decode("utf-8-sig").strip())
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(payload, dict) or payload.get("type") != want_type:
                continue
            if req_id is not None and payload.get("req_id") not in (None, req_id):
                continue
            return payload
    except PortalBridgeError:
        raise
    except OSError as err:
        raise PortalBridgeError("offline", _scrub(f"Connection to {host}:{port} failed ({err.__class__.__name__}).", token)) from None
    finally:
        close_bridge_socket(sock)


def hot_request(profile: dict, cmd: str, timeout: float = DEFAULT_TIMEOUT, **extra) -> dict:
    req_id = f"zah-{cmd}-{uuid.uuid4().hex[:8]}"
    body = {"cmd": cmd, "req_id": req_id}
    body.update(extra)
    return bridge_request(profile, "hot:" + json.dumps(body), "HOT", req_id=req_id, timeout=timeout)


def fetch_status(profile: dict) -> dict:
    return hot_request(profile, "status")


def fetch_players(profile: dict) -> dict:
    return bridge_request(profile, "plys", "PLAYER_CACHE")


def send_reload(profile: dict, force: bool = False) -> dict:
    """Sends hot reload. Only call after the user confirmed it in the portal."""
    extra = {"force": True} if force else {}
    return hot_request(profile, "reload", timeout=RELOAD_TIMEOUT, **extra)


def send_rollback(profile: dict, core_id: str | None = None) -> dict:
    """Sends hot rollback. Only call after the user confirmed it in the portal."""
    extra = {"id": core_id} if core_id else {}
    return hot_request(profile, "rollback", timeout=RELOAD_TIMEOUT, **extra)


def build_player_alert(entity_id, text: str, req_id: str) -> str:
    """
    The bridge's single-player message line, exactly as AlertService parses it:
      alert:{"req_id":"..","target":"player","id":"<entityId or steamId>","text":".."}
    (ZeroGBridge/Network/AlertService.cs, Handle(); routed by Core/ModMain.cs HandleLine).
    prio/duration are left out so the bridge defaults apply (prio 0, 10 s). Text is capped at 200.
    """
    body = {"req_id": req_id, "target": "player", "id": str(entity_id), "text": str(text)[:200]}
    return "alert:" + json.dumps(body)


def send_player_alert(profile: dict, entity_id, text: str) -> dict:
    """Sends one in-game message to one player. Only call after the user confirmed it."""
    req_id = f"zah-msg-{uuid.uuid4().hex[:8]}"
    return bridge_request(profile, build_player_alert(entity_id, text, req_id), "ALERT_ACK", req_id=req_id)


def resolve_player(players_payload: dict, name_or_id: str) -> dict:
    """
    Finds one player in a PLAYER_CACHE reply by exact name (case-insensitive),
    entityId or steamId. Raises PortalBridgeError('not_found' / 'ambiguous').
    """
    key = str(name_or_id or "").strip()
    rows = [p for p in (players_payload or {}).get("player_list") or [] if isinstance(p, dict)]
    by_id = [p for p in rows if key and key in (str(p.get("entityId", "")), str(p.get("steamId", "")))]
    if len(by_id) == 1:
        return by_id[0]
    by_name = [p for p in rows if str(p.get("name", "")).strip().lower() == key.lower()]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        raise PortalBridgeError("ambiguous", f"More than one player is named {key}. Use the entity id instead.")
    raise PortalBridgeError("not_found", f"No player named {key} in the bridge's player cache.")


# ---------------------------------------------------------------------------
# Worker-thread helper so the GUI never blocks
# ---------------------------------------------------------------------------

class _TaskSignals(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str, str)


class _BridgeTask(QRunnable):
    def __init__(self, fn, signals: _TaskSignals):
        super().__init__()
        self.fn = fn
        self.signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self.fn()
        except PortalBridgeError as err:
            self._emit_failed(err.kind, str(err))
        except Exception as err:  # never let a worker crash the app
            self._emit_failed("error", f"{err.__class__.__name__}: {err}")
        else:
            try:
                self.signals.succeeded.emit(result)
            except RuntimeError:
                pass

    def _emit_failed(self, kind: str, message: str) -> None:
        try:
            self.signals.failed.emit(kind, message)
        except RuntimeError:
            pass


_IN_FLIGHT: set[_TaskSignals] = set()


def run_async(fn, on_ok, on_error) -> None:
    """Runs fn() on Qt's thread pool. on_ok(result) / on_error(kind, message) run on the GUI thread."""
    signals = _TaskSignals()
    signals.succeeded.connect(on_ok)
    signals.failed.connect(on_error)
    # Release the signals object on the GUI thread once it has delivered.
    signals.succeeded.connect(lambda *_: _IN_FLIGHT.discard(signals))
    signals.failed.connect(lambda *_: _IN_FLIGHT.discard(signals))
    _IN_FLIGHT.add(signals)
    QThreadPool.globalInstance().start(_BridgeTask(fn, signals))


def wait_for_tasks(timeout_ms: int = 15000) -> bool:
    """Tests and shutdown: wait for in-flight portal requests."""
    return QThreadPool.globalInstance().waitForDone(timeout_ms)
