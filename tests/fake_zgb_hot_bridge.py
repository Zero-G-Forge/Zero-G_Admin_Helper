# fake_zgb_hot_bridge.py
"""
Local fake of the ZeroGBridge 1.5 loader for ZeroGBridge Portal tests.

Binds 127.0.0.1 on a random port. Speaks auth:<token>, hot:{json}
(status / reload / rollback) and plys. Replies start with a UTF-8 BOM and
are mixed with METRIC noise, like the real bridge. Never touches a real server.
"""

import json
import socket
import threading

STATUS_TEMPLATE = {
    "type": "HOT", "cmd": "status", "ok": True,
    "loader": {"release": "1.5.0", "assemblyVersion": "1.5.1116.1228", "contract": 1},
    "core": {
        "loaded": True,
        "version": {"id": "1.5.1116.1341_db04e1f8", "release": "1.5.1",
                    "assemblyVersion": "1.5.1116.1341", "sha256": "db04e1f8d048",
                    "importedUtc": "2026-11-16T21:28:14.2218702Z", "sizeBytes": 152576,
                    "good": True, "lastError": None},
        "isolation": "AppDomain", "domain": "ZGB-Core-2",
        "loadedUtc": "2026-11-16T22:05:58.7627368Z", "uptimeSeconds": 119,
    },
    "lastGood": "1.5.1116.1341_db04e1f8", "reloadInProgress": False, "hotReloadEnabled": True,
    "autoReloadOnDrop": False, "dropFolder": "Updates", "pendingDrop": False, "liveCoreDomains": 1,
    "lastReload": {"timeUtc": "2026-11-16T22:05:58.9491996Z", "trigger": "command", "action": "reload",
                   "from": "1.5.1116.1341_db04e1f8", "to": "1.5.1116.1341_db04e1f8", "ok": True,
                   "error": None, "message": None, "durationMs": 650},
    "history": [
        {"timeUtc": "2026-11-16T21:28:15.0130567Z", "trigger": "boot", "action": "boot", "from": None,
         "to": "1.5.1116.1341_db04e1f8", "ok": True, "error": None, "message": None, "durationMs": 676},
        {"timeUtc": "2026-11-16T22:05:58.9491996Z", "trigger": "command", "action": "reload",
         "from": "1.5.1116.1341_db04e1f8", "to": "1.5.1116.1341_db04e1f8", "ok": True,
         "error": None, "message": None, "durationMs": 650},
    ],
    "diagnostics": {"players": 49, "online": 1, "playerFactions": 19,
                    "serverView": {"online": 1, "runningPlayfields": 1}, "structures": 31,
                    "updateTicking": True},
}

PLAYERS = {
    "type": "PLAYER_CACHE", "status": "ok", "players": 2,
    "player_list": [
        {"name": "E21L", "steamId": "1", "entityId": 101, "factionId": 5, "status": "Online",
         "faction": "Forge", "playfield": "Akua", "last_seen": "now"},
        {"name": "Clovis-d", "steamId": "2", "entityId": 102, "factionId": 6, "status": "Offline",
         "faction": "Solace", "playfield": "Omicron", "last_seen": "2026-11-16 15:24"},
    ],
}


class FakeHotBridge:
    def __init__(self, token="fake-portal-token"):
        self.token = token
        self.port = 0
        self.received = []          # every command line after auth
        self.auth_attempts = 0
        self._stop = threading.Event()
        self._listener = None

    def start(self):
        lst = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lst.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        lst.bind(("127.0.0.1", 0))
        lst.listen(8)
        lst.settimeout(0.2)
        self._listener = lst
        self.port = lst.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()
        return self

    def stop(self):
        self._stop.set()
        try:
            self._listener.close()
        except Exception:
            pass

    def profile(self, token=None, name="Fake Server"):
        return {"input_ip": "127.0.0.1", "input_port": "9", "bridge_port": str(self.port),
                "input_pass": self.token if token is None else token, "server_name": name}

    def hot_commands(self):
        out = []
        for line in self.received:
            if line.startswith("hot:"):
                out.append(json.loads(line[4:]))
        return out

    def _accept(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    @staticmethod
    def _send(conn, payload):
        conn.sendall(b"\xef\xbb\xbf" + (json.dumps(payload) + "\n").encode("utf-8"))

    def _handle(self, conn):
        conn.settimeout(5)
        f = conn.makefile("rb")
        try:
            first = f.readline().decode("utf-8").strip()
            self.auth_attempts += 1
            if first != f"auth:{self.token}":
                self._send(conn, {"type": "AUTH", "status": "Denied", "message": "Invalid Credentials"})
                return
            self._send(conn, {"type": "AUTH", "status": "Authenticated"})
            while not self._stop.is_set():
                raw = f.readline()
                if not raw:
                    return
                line = raw.decode("utf-8").strip()
                self.received.append(line)
                conn.sendall(b"METRIC cpu=3\n")
                if line == "plys":
                    self._send(conn, PLAYERS)
                elif line.startswith("hot:"):
                    body = json.loads(line[4:])
                    cmd = body.get("cmd")
                    if cmd == "status":
                        reply = dict(STATUS_TEMPLATE)
                    elif cmd == "reload":
                        reply = {"type": "HOT", "cmd": "reload", "ok": True,
                                 "result": "reloaded" if body.get("force") else "unchanged",
                                 "from": "1.5.1116.1341_db04e1f8", "to": "1.5.1116.1341_db04e1f8",
                                 "durationMs": 600}
                    elif cmd == "rollback":
                        reply = {"type": "HOT", "cmd": "rollback", "ok": True, "result": "rolledBack",
                                 "from": "1.5.1116.1341_db04e1f8", "to": "1.5.1116.1200_aaaa"}
                    else:
                        reply = {"type": "HOT", "ok": False, "error": "unknown cmd"}
                    # A reply for some other request first: the client must match req_id.
                    self._send(conn, {"type": "HOT", "req_id": "someone-else", "ok": False})
                    reply["req_id"] = body.get("req_id")
                    self._send(conn, reply)
        except (OSError, ValueError):
            return
        finally:
            try:
                conn.close()
            except Exception:
                pass
