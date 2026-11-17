# mock_bridge.py
"""
Local stand-in for the ZeroGBridge TCP listener.

Speaks the same first steps the C# bridge does: auth:<token> then one JSON
line per command (plys, gents, METRIC, alert). It binds 127.0.0.1 on an
ephemeral port so tests never touch a live game server.
"""

import json
import socket
import threading
import time


class MockBridge:
    """Tiny auth-gated bridge bound to localhost."""

    def __init__(self, token, host="127.0.0.1", port=0, silent=False):
        self.token = token
        self.host = host
        self.port = port
        # Accept the TCP connection and never send a reply. Used to force a client timeout.
        self.silent = silent
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._clients = []
        self._listener = None
        self._thread = None

    def start(self):
        """Binds an ephemeral port and starts accepting clients."""
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self.port))
        listener.listen(8)
        listener.settimeout(0.2)
        self._listener = listener
        self.port = listener.getsockname()[1]
        self._thread = threading.Thread(target=self._accept_loop, name="mock-bridge", daemon=True)
        self._thread.start()
        print(f"[MockBridge] -INFO- Listening on {self.host}:{self.port}")
        return self

    def stop(self):
        """Closes the listener and every client socket."""
        self._stop.set()
        if self._listener is not None:
            try:
                self._listener.close()
            except Exception:
                pass
        with self._lock:
            clients = list(self._clients)
        for record in clients:
            try:
                record["conn"].close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def authenticated_count(self):
        with self._lock:
            return sum(1 for record in self._clients if record["authed"])

    def commands(self):
        with self._lock:
            found = []
            for record in self._clients:
                found.extend(record["commands"])
            return found

    def wait_until_all_closed(self, timeout=2.0):
        """True once every accepted client has disconnected."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._clients and all(record["closed"] for record in self._clients):
                    return True
            time.sleep(0.05)
        return False

    def wait_for_command(self, command, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if command in self.commands():
                return True
            time.sleep(0.05)
        return False

    def wait_until_authenticated(self, count=1, timeout=3.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.authenticated_count() >= count:
                return True
            time.sleep(0.05)
        return False

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, _addr = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            record = {"conn": conn, "authed": False, "closed": False, "commands": []}
            with self._lock:
                self._clients.append(record)
            try:
                conn.settimeout(0.5)
            except OSError:
                record["closed"] = True
                continue
            threading.Thread(target=self._handle, args=(conn, record), daemon=True).start()

    def _send(self, conn, payload):
        line = json.dumps(payload) + "\n"
        try:
            conn.sendall(line.encode("utf-8"))
        except OSError:
            pass

    def _handle(self, conn, record):
        buf = b""
        authed = False
        try:
            conn.settimeout(0.5)
        except OSError:
            record["closed"] = True
            return
        try:
            if self.silent:
                print("[MockBridge] -INFO- Holding the client open with no reply.")
                while not self._stop.is_set():
                    time.sleep(0.05)
                return
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    text = raw.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    if not authed:
                        if text.lower().startswith("auth:"):
                            submitted = text[5:].strip()
                            if self.token and submitted == self.token:
                                authed = True
                                record["authed"] = True
                                print("[MockBridge] -STATUS- Client authenticated.")
                                self._send(conn, {
                                    "type": "AUTH",
                                    "status": "Authenticated",
                                    "message": "Access Granted",
                                })
                            else:
                                print("[MockBridge] -WARN- Client authentication denied.")
                                self._send(conn, {
                                    "type": "AUTH",
                                    "status": "Denied",
                                    "message": "Invalid Credentials",
                                })
                                return
                        else:
                            self._send(conn, {
                                "type": "AUTH",
                                "status": "Required",
                                "message": "Authentication Required. Submit auth:<password>",
                            })
                            return
                    else:
                        record["commands"].append(text)
                        self._reply_command(conn, text)
        finally:
            record["closed"] = True
            try:
                conn.close()
            except Exception:
                pass

    def _reply_command(self, conn, text):
        lower = text.lower()
        if lower == "plys":
            self._send(conn, {
                "type": "PLAYER_CACHE",
                "status": "Synced",
                "players": 0,
                "player_list": [],
            })
        elif lower == "gents":
            self._send(conn, {
                "type": "ENTITY_LIST",
                "status": "Synced",
                "entities": [],
            })
        elif lower == "metric":
            self._send(conn, {
                "type": "METRIC",
                "cpu": 0,
                "ram": "0%",
                "fps": 0,
                "heap": "0MB",
                "players": 0,
                "uptime": "00h:00m",
            })
        elif lower.startswith("alert:"):
            self._send(conn, {"type": "ALERT_ACK", "status": "sent"})
        else:
            self._send(conn, {"type": "RESPONSE", "status": "Success", "message": "ok"})
