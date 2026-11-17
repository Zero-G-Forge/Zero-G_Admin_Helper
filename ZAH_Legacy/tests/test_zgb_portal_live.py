# test_zgb_portal_live.py
"""ZeroGBridge Portal live data against a local fake bridge. Never a real server."""

import socket
import time

import pytest
from PyQt6.QtWidgets import QApplication

from features.dashboard.zgb_portal import ZeroGBridgePortal
from features.dashboard.zgb_portal import hot_reload_panel
from features.dashboard.zgb_portal.data_source import (
    LiveDataSource,
    SampleDataSource,
    format_players,
    parse_status,
)
from features.dashboard.zgb_portal.live_client import (
    PortalBridgeError,
    fetch_players,
    fetch_status,
    send_reload,
    wait_for_tasks,
)
from tests.fake_zgb_hot_bridge import FakeHotBridge


@pytest.fixture
def bridge():
    fake = FakeHotBridge().start()
    yield fake
    fake.stop()


def _pump(predicate, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    QApplication.processEvents()
    return predicate()


def _closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_status_and_players_parse(bridge):
    prof = bridge.profile()
    payload = fetch_status(prof)
    assert payload["type"] == "HOT" and payload["req_id"].startswith("zah-status-")
    state = parse_status(payload, prof)
    assert state.connection == "Online"
    assert state.server_name == "Fake Server"
    assert state.loader_version.startswith("1.5.0")
    assert state.core_release == "1.5.1"
    assert state.core_version == "1.5.1116.1341"
    assert state.core_domain == "ZGB-Core-2"
    assert state.players_online == 1
    assert state.port == bridge.port
    assert state.loaded_since.utcoffset().total_seconds() == -6 * 3600   # America/Chicago (CST)
    assert state.last_ok and "650 ms" in state.last_result
    # history newest first
    assert [h.note.split(" ")[0] for h in state.history] == ["reload", "boot"]
    text = format_players(fetch_players(prof), online_only=True)
    assert "E21L" in text and "Clovis-d" not in text


def test_auth_failure_is_reported_without_token(bridge):
    secret = "wrong-secret-value"
    with pytest.raises(PortalBridgeError) as err:
        fetch_status(bridge.profile(token=secret))
    assert err.value.kind == "auth"
    assert secret not in str(err.value)


def test_unreachable_server_is_offline():
    prof = {"input_ip": "127.0.0.1", "bridge_port": str(_closed_port()), "input_pass": "x"}
    with pytest.raises(PortalBridgeError) as err:
        fetch_status(prof)
    assert err.value.kind in ("offline", "timeout")


def test_portal_live_shows_status(qapp, bridge):
    del qapp
    portal = ZeroGBridgePortal(profile_provider=bridge.profile)
    try:
        assert isinstance(portal.source, LiveDataSource)
        portal.show()
        loader = portal.loader
        assert _pump(lambda: loader.state.connection == "Online")
        assert loader.lbl_core.text().startswith("1.5.1")
        assert loader.lbl_hold.text() == "ZGB-Core-2"
        assert loader.lbl_players.text() == "1"
        assert "CST" in loader.lbl_since.text()
        assert loader.history.rowCount() == 2
        assert loader.btn_reload.isEnabled()
        assert not loader.btn_browse.isEnabled()
        assert not loader.btn_sim_drop.isEnabled()
        assert "Updates" in loader.btn_browse.toolTip()
        assert not portal.bridge.btn_push.isEnabled()
        assert "fake-portal-token" not in loader.log.toPlainText()
        # read-only so far: no reload / rollback sent
        assert [c["cmd"] for c in bridge.hot_commands()] == ["status"]
    finally:
        portal.close()
        wait_for_tasks()


def test_live_reload_needs_confirmation(qapp, bridge, monkeypatch):
    del qapp
    portal = ZeroGBridgePortal(profile_provider=bridge.profile)
    try:
        portal.show()
        loader = portal.loader
        assert _pump(lambda: loader.state.connection == "Online")

        asked = []

        def deny(title, body, action):
            asked.append(body)
            return False

        monkeypatch.setattr(loader, "_confirm", deny)
        loader.btn_reload.click()
        wait_for_tasks()
        QApplication.processEvents()
        assert asked and "Fake Server" in asked[0] and "1 player is currently online" in asked[0]
        assert [c["cmd"] for c in bridge.hot_commands()].count("reload") == 0

        monkeypatch.setattr(loader, "_confirm", lambda *a: True)
        loader.chk_force.setChecked(True)
        loader.btn_reload.click()
        assert _pump(lambda: "Reload result: reloaded" in loader.log.toPlainText())
        reloads = [c for c in bridge.hot_commands() if c["cmd"] == "reload"]
        assert len(reloads) == 1 and reloads[0].get("force") is True

        monkeypatch.setattr(loader, "_confirm", lambda *a: False)
        loader.btn_rollback_prev.click()
        wait_for_tasks()
        QApplication.processEvents()
        assert not [c for c in bridge.hot_commands() if c["cmd"] == "rollback"]
    finally:
        portal.close()
        wait_for_tasks()


def test_portal_offline_and_auth_failed_states(qapp, bridge):
    del qapp
    dead = {"input_ip": "127.0.0.1", "bridge_port": str(_closed_port()), "input_pass": "x",
            "server_name": "Dead"}
    portal = ZeroGBridgePortal(profile_provider=lambda: dead)
    try:
        portal.show()
        assert _pump(lambda: portal.loader.state.connection == "Offline")
        assert portal.loader.badge.text() == "OFFLINE"
        assert not portal.loader.btn_reload.isEnabled()
    finally:
        portal.close()
        wait_for_tasks()

    portal = ZeroGBridgePortal(profile_provider=lambda: bridge.profile(token="nope"))
    try:
        portal.show()
        assert _pump(lambda: portal.loader.state.connection == "Auth failed")
        assert portal.loader.badge.text() == "AUTH FAILED"
    finally:
        portal.close()
        wait_for_tasks()


def test_source_toggle_and_bridge_tab_live_reads(qapp, bridge):
    del qapp
    portal = ZeroGBridgePortal(profile_provider=bridge.profile)
    try:
        portal.show()
        assert _pump(lambda: portal.loader.state.connection == "Online")
        assert portal._refresh_timer.isActive()
        assert portal._refresh_timer.interval() == hot_reload_panel.LIVE_REFRESH_MS

        b = portal.bridge
        b._select_command("Players", "Kick player")
        assert not b.btn_run.isEnabled()
        b._select_command("Players", "List players")
        assert b.btn_run.isEnabled()
        b.btn_run.click()
        assert _pump(lambda: "E21L" in b.result.toPlainText())
        b._select_command("Server", "Get status")
        b.btn_run.click()
        assert _pump(lambda: "ZGB-Core-2" in b.result.toPlainText())

        portal.source_picker.setCurrentIndex(1)   # Examples
        assert isinstance(portal.source, SampleDataSource)
        assert not portal._refresh_timer.isActive()
        assert "EXAMPLES" in portal.subtitle.text()
        assert portal.loader.state.core_version == "1.4.2"
        assert portal.bridge.btn_push.isEnabled()

        portal.hide()
        assert not portal._refresh_timer.isActive()
        cmds = [c["cmd"] for c in bridge.hot_commands()]
        assert "reload" not in cmds and "rollback" not in cmds
    finally:
        portal.close()
        wait_for_tasks()


def _fill(panel, name, message):
    from PyQt6.QtWidgets import QLineEdit
    for key, w in panel.param_widgets.items():
        if key == "name":
            w.setText(name)
        elif key == "message":
            w.setText(message)
    QApplication.processEvents()


def test_message_player_live(qapp, bridge, monkeypatch):
    del qapp
    portal = ZeroGBridgePortal(profile_provider=bridge.profile)
    try:
        portal.show()
        assert _pump(lambda: portal.loader.state.connection == "Online")
        b = portal.bridge
        b._select_command("Players", "Message player")
        # Live form starts empty (no sample name) and Run stays off until both fields are filled.
        assert not b.btn_run.isEnabled()
        _fill(b, "E21L", "")
        assert not b.btn_run.isEnabled()
        _fill(b, "", "Testing Message system")
        assert not b.btn_run.isEnabled()
        _fill(b, "E21L", "Testing Message system")
        assert b.btn_run.isEnabled()

        # Cancel: the player lookup (plys) is fine, but no alert line is sent.
        asked = []
        monkeypatch.setattr(b, "_confirm_message", lambda server, player, text: asked.append((server, player, text)) or False)
        b.btn_run.click()
        assert _pump(lambda: "Cancelled" in b.result.toPlainText())
        assert asked and asked[0][0] == "Fake Server"
        assert asked[0][1]["name"] == "E21L" and asked[0][2] == "Testing Message system"
        assert bridge.alerts() == []
        assert b.btn_run.isEnabled()

        # Confirm: exactly one alert:{"target":"player"} with the entity id from plys.
        monkeypatch.setattr(b, "_confirm_message", lambda *a: True)
        b.btn_run.click()
        assert _pump(lambda: "ALERT_ACK status=sent" in b.result.toPlainText())
        alerts = bridge.alerts()
        assert len(alerts) == 1
        a = alerts[0]
        assert a["target"] == "player" and a["id"] == "101" and a["text"] == "Testing Message system"
        assert a["req_id"].startswith("zah-msg-")
        assert set(a) == {"req_id", "target", "id", "text"}
        assert bridge.token not in b.result.toPlainText()

        # Unknown player: lookup fails, nothing is sent, no confirm shown.
        monkeypatch.setattr(b, "_confirm_message", lambda *a: pytest.fail("confirm must not open"))
        _fill(b, "Nobody", "hi")
        b.btn_run.click()
        assert _pump(lambda: "No player named Nobody" in b.result.toPlainText())
        assert len(bridge.alerts()) == 1
        assert not [c for c in bridge.hot_commands() if c["cmd"] in ("reload", "rollback")]
    finally:
        portal.close()
        wait_for_tasks()


def test_confirm_message_dialog_text(qapp, bridge, monkeypatch):
    del qapp
    from features.dashboard.zgb_portal import bridge_panel as bp
    seen = {}

    class FakeDialog:
        class DialogCode:
            Accepted = 1

        def __init__(self, title, body, action, parent=None):
            seen.update(title=title, body=body, action=action)

        def exec(self):
            return 0

    monkeypatch.setattr(hot_reload_panel, "ConfirmDialog", FakeDialog)
    portal = ZeroGBridgePortal(profile_provider=bridge.profile)
    try:
        ok = portal.bridge._confirm_message("Fake Server", {"name": "Clovis-d", "entityId": 102, "status": "Offline"}, "hello")
        assert ok is False
        assert "Fake Server" in seen["body"] and "Clovis-d" in seen["body"] and "hello" in seen["body"]
        assert "not online" in seen["body"]
    finally:
        portal.close()
        wait_for_tasks()
