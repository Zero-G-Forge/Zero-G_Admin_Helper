## =====================================================================
## TESTS: tests/test_bridge_request_many.py
## bridge_request_many (several commands over ONE authenticated session), read_bridge_many, send_many.
## A tiny local fake bridge on 127.0.0.1 stands in for ZeroGBridge, so nothing can reach a real server.
## =====================================================================

# region Imports

import json
import os
import socket
import sys
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from features.shared import server_actions
from features.zgb_portal import live_client
from tests.page_helpers import get_qapp, install, settle

# endregion


# region Fake Bridge

## Accepts connections; counts logins; answers each command line from a table {command prefix: reply dict or None}.
## A None reply means "never answer" (to test the timeout). "hot:" lines are answered with a HOT reply that echoes req_id.
class FakeBridge:
    def __init__(self, replies, token="secret-token"):
        self.replies = replies
        self.token = token
        self.logins = 0
        self.commands = []
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(8)
        self.port = self.server.getsockname()[1]
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def profile(self, token=None):
        return {"input_ip": "127.0.0.1", "bridge_port": str(self.port), "input_pass": self.token if token is None else token}

    def _accept(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        reader = conn.makefile("rb")
        try:
            first = reader.readline().decode().strip()
            if first != "auth:" + self.token:
                conn.sendall(b'{"type":"AUTH","status":"Denied"}\n')
                return
            self.logins += 1
            conn.sendall(b'{"type":"AUTH","status":"Authenticated"}\n')
            for raw in reader:
                line = raw.decode().strip()
                self.commands.append(line)
                ## Unrelated telemetry lines the client must skip.
                conn.sendall(b'{"type":"METRIC","fps":"30"}\n')
                for prefix, reply in self.replies.items():
                    if line.startswith(prefix):
                        if reply is None:
                            break
                        if line.startswith("hot:"):
                            reply = dict(reply, req_id=json.loads(line[4:])["req_id"])
                        conn.sendall((json.dumps(reply) + "\n").encode())
                        break
        except OSError:
            pass
        finally:
            conn.close()

    def close(self):
        self.server.close()


@pytest.fixture
def bridge():
    fake = FakeBridge({
        "plys": {"type": "PLAYER_CACHE", "player_list": [{"name": "A", "status": "Online"}]},
        "api:Request_Dedi_Stats": {"type": "API_RESULT", "status": "ok", "data": {"fps": 30}},
        "hot:": {"type": "HOT", "ok": True, "cmd": "status"},
        "silent": None,
    })
    yield fake
    fake.close()

# endregion


# region bridge_request_many

def test_many_commands_use_one_login_and_keep_order(bridge):
    items = [live_client.hot_item("status"), ("plys", "PLAYER_CACHE"), ("api:Request_Dedi_Stats", ("API_RESULT", "ERROR"))]
    replies = live_client.bridge_request_many(bridge.profile(), items)
    assert [r["type"] for r in replies] == ["HOT", "PLAYER_CACHE", "API_RESULT"]
    assert replies[1]["player_list"][0]["name"] == "A"
    assert bridge.logins == 1 and len(bridge.commands) == 3


def test_many_returns_same_shape_as_single_requests(bridge):
    single = live_client.bridge_request(bridge.profile(), "plys", "PLAYER_CACHE")
    many = live_client.bridge_request_many(bridge.profile(), [("plys", "PLAYER_CACHE")])
    assert many == [single]


def test_one_silent_command_times_out_but_the_rest_still_answer(bridge, monkeypatch):
    replies = live_client.bridge_request_many(bridge.profile(), [("silent", "NEVER"), ("plys", "PLAYER_CACHE")], timeout=0.6)
    assert isinstance(replies[0], live_client.PortalBridgeError) and replies[0].kind == "timeout"
    assert replies[1]["type"] == "PLAYER_CACHE"
    assert bridge.logins == 1


def test_many_login_failures_raise_and_never_show_the_token(bridge):
    with pytest.raises(live_client.PortalBridgeError) as caught:
        live_client.bridge_request_many(bridge.profile(token="wrong-token"), [("plys", "PLAYER_CACHE")])
    assert caught.value.kind == "auth" and "wrong-token" not in str(caught.value)
    with pytest.raises(live_client.PortalBridgeError) as caught:
        live_client.bridge_request_many({"input_ip": "", "input_pass": "x"}, [("plys", "PLAYER_CACHE")])
    assert caught.value.kind == "config"
    with pytest.raises(live_client.PortalBridgeError) as caught:
        live_client.bridge_request_many({"input_ip": "127.0.0.1", "input_pass": ""}, [("plys", "PLAYER_CACHE")])
    assert caught.value.kind == "config"


def test_short_sockets_close_with_close_only(bridge, monkeypatch):
    calls = []
    real = live_client.close_short_socket
    monkeypatch.setattr(live_client, "close_short_socket", lambda sock: calls.append("close") or real(sock))
    shutdowns = []
    real_shutdown = socket.socket.shutdown
    monkeypatch.setattr(socket.socket, "shutdown", lambda self, how: shutdowns.append(how) or real_shutdown(self, how))
    live_client.bridge_request_many(bridge.profile(), [("plys", "PLAYER_CACHE")])
    live_client.bridge_request(bridge.profile(), "plys", "PLAYER_CACHE")
    assert calls == ["close", "close"] and shutdowns == []

# endregion


# region send_many and read_bridge_many

def test_send_many_uses_the_stand_in_one_command_at_a_time(monkeypatch, tmp_path):
    fake = install(monkeypatch, tmp_path, {"boom": lambda command: (_ for _ in ()).throw(ConnectionError("down")),
                                           "plys": {"type": "PLAYER_CACHE", "player_list": []}})
    results = server_actions.send_many([("plys", "PLAYER_CACHE"), ("boom", "X")])
    assert fake.sent == ["plys", "boom"]
    assert results[0]["type"] == "PLAYER_CACHE" and isinstance(results[1], ConnectionError)


def test_read_bridge_many_sends_each_answer_to_its_own_handler(monkeypatch, tmp_path):
    install(monkeypatch, tmp_path, {"plys": {"type": "PLAYER_CACHE", "player_list": []},
                                    "boom": lambda command: (_ for _ in ()).throw(ConnectionError("down"))})
    qapp = get_qapp()
    got = []
    server_actions.read_bridge_many([
        ("plys", "PLAYER_CACHE", lambda reply: got.append(("plys", reply["type"])), lambda message: got.append(("plys-err", message))),
        ("boom", "X", lambda reply: got.append(("boom", reply)), lambda message: got.append(("boom-err", message)))])
    settle(qapp)
    assert ("plys", "PLAYER_CACHE") in got and ("boom-err", "down") in got and len(got) == 2


def test_read_bridge_many_whole_login_failure_reaches_every_error_handler(monkeypatch):
    def broken(requests, profile=None):
        raise live_client.PortalBridgeError("offline", "Could not reach it.")
    monkeypatch.setattr(server_actions, "send_many", broken)
    qapp = get_qapp()
    got = []
    server_actions.read_bridge_many([("plys", "PLAYER_CACHE", lambda r: got.append("ok"), lambda m: got.append(m)),
                                     ("gents", "ENTITY_LIST", lambda r: got.append("ok"), lambda m: got.append(m))])
    settle(qapp)
    assert got == ["Could not reach it.", "Could not reach it."]

# endregion


# region Server Monitor

def test_server_monitor_polls_all_three_over_one_login(monkeypatch):
    from features.multi_server import server_monitor
    asked = []
    status = {"core": {"version": {"release": "1.6.15"}}, "loader": {"release": "1.5.1"}}
    plys = {"type": "PLAYER_CACHE", "player_list": [{"name": "A", "status": "Online"}]}
    stats = {"type": "API_RESULT", "status": "ok", "data": {"fps": 30, "mem": 2048, "uptime": 3600}}
    monkeypatch.setattr(server_monitor, "MANY_FUNCTION", lambda profile: asked.append(profile) or [status, plys, stats])
    result = server_monitor.poll_server({"server_name": "Alpha", "input_ip": "127.0.0.1", "bridge_port": "1"})
    assert len(asked) == 1 and result["online"] and result["core"] == "1.6.15"
    assert result["players_online"] == 1 and result["fps"] == 30


def test_server_monitor_one_bad_read_keeps_the_others(monkeypatch):
    from features.multi_server import server_monitor
    status = {"core": {"version": {"release": "1.6.15"}}, "loader": {"release": "1.5.1"}}
    stats = {"type": "API_RESULT", "status": "ok", "data": {"fps": 30}}
    monkeypatch.setattr(server_monitor, "MANY_FUNCTION",
                        lambda profile: [status, live_client.PortalBridgeError("timeout", "slow"), stats])
    result = server_monitor.poll_server({"server_name": "Alpha", "input_ip": "127.0.0.1", "bridge_port": "1"})
    assert result["online"] and result["players_online"] is None and result["fps"] == 30


def test_server_monitor_login_failure_means_offline(monkeypatch):
    from features.multi_server import server_monitor
    def down(profile):
        raise live_client.PortalBridgeError("offline", "down")
    monkeypatch.setattr(server_monitor, "MANY_FUNCTION", down)
    result = server_monitor.poll_server({"server_name": "Alpha", "input_ip": "127.0.0.1", "bridge_port": "1"})
    assert not result["online"]

# endregion
