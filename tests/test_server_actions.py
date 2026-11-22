## =====================================================================
## TEST: tests/test_server_actions.py
## The Safety Flow (preview, CONFIRM, countdown, Cancel), the fail-closed role table, the audit log,
## and the Players page wiring. All sends go to a fake bridge in this file; no network is used.
## =====================================================================

# region Imports

import json

import pytest

from tests.page_helpers import get_qapp, host, install, settle
from features.shared import server_actions
from features.shared.server_actions import SafetyFlowDialog

# endregion


@pytest.fixture(scope="session")
def qapp():
    return get_qapp()


# region Safety Flow

def test_start_needs_the_exact_word(qapp):
    dialog = SafetyFlowDialog("t", "con:kick 1 'x'")
    for typed, expected in (("confirm", False), ("CONFIRMED", False), ("CONFIRM", True), (" CONFIRM ", True)):
        dialog.txt_confirm.setText(typed)
        assert dialog.btn_start.isEnabled() is expected


def test_countdown_accepts_and_cancel_rejects(qapp, monkeypatch):
    monkeypatch.setattr(server_actions, "SAFETY_DELAY_SEC", 2)
    dialog = SafetyFlowDialog("t", "x")
    dialog.txt_confirm.setText("CONFIRM")
    dialog._start_countdown()
    assert dialog.timer.isActive() and dialog.result() == 0
    dialog._tick()
    assert dialog.timer.isActive()
    dialog._tick()
    assert dialog.result() == 1
    second = SafetyFlowDialog("t", "x")
    second.txt_confirm.setText("CONFIRM")
    second._start_countdown()
    second._cancel()
    assert not second.timer.isActive() and second.result() == 0


def test_default_delay_is_15_seconds():
    assert server_actions.SAFETY_DELAY_SEC == 15 and server_actions.CONFIRM_WORD == "CONFIRM"

# endregion


# region Role Table and Gate

@pytest.mark.parametrize("role, action, allowed", [
    ("moderator", "player_kick", True), ("moderator", "player_ban", False), ("admin", "player_ban", True),
    ("admin", "playfield_wipe", False), ("owner", "playfield_wipe", True), ("developer", "player_kick", True),
    ("developer", "not_a_real_action", False), (None, "player_message", False),
])
def test_role_table(qapp, role, action, allowed):
    from PyQt6.QtWidgets import QWidget
    page = QWidget()
    host(page, role)
    assert server_actions.user_may(page, action) is allowed


def test_no_cockpit_means_no(qapp):
    from PyQt6.QtWidgets import QWidget
    assert server_actions.user_may(QWidget(), "player_message") is False


def test_refused_role_sends_nothing(qapp, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QWidget
    bridge = install(monkeypatch, tmp_path)
    page = QWidget()
    host(page, "moderator")
    assert server_actions.run_server_action(page, "player_ban", "t", "con:ban 1 1d") is False
    settle(qapp)
    assert bridge.sent == [] and bridge.asked == []


def test_cancel_sends_nothing_but_is_audited(qapp, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QWidget
    bridge = install(monkeypatch, tmp_path, safety_answer=False)
    page = QWidget()
    host(page, "admin")
    assert server_actions.run_server_action(page, "player_ban", "t", "con:ban 1 1d") is False
    settle(qapp)
    assert bridge.sent == []
    rows = server_actions.read_audit()
    assert rows[0]["ok"] is False and rows[0]["detail"] == "cancelled before sending"


def test_send_then_audit(qapp, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QWidget
    bridge = install(monkeypatch, tmp_path, {"con:": {"type": "CONSOLE_RESULT", "status": "ok"}})
    page = QWidget()
    host(page, "admin")
    results = []
    server_actions.run_server_action(page, "player_ban", "t", "con:ban 1 1d", lambda ok, reply: results.append(ok))
    settle(qapp)
    assert bridge.sent == ["con:ban 1 1d"] and results == [True]
    row = json.loads(open(server_actions.AUDIT_FILE).read().splitlines()[-1])
    assert row["action"] == "player_ban" and row["command"] == "con:ban 1 1d" and row["ok"] is True


def test_command_list_stops_at_first_refusal(qapp, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QWidget
    bridge = install(monkeypatch, tmp_path, {"api:bad": {"type": "ERROR", "message": "no"}})
    page = QWidget()
    host(page, "admin")
    results = []
    server_actions.run_server_action(page, "player_loadout", "t", ["api:good", "api:bad", "api:never"],
                                     lambda ok, reply: results.append(ok))
    settle(qapp)
    assert bridge.sent == ["api:good", "api:bad"] and results == [False]


@pytest.mark.parametrize("reply, ok", [
    ({"type": "API_RESULT", "status": "ok"}, True), ({"type": "API_RESULT", "status": "timeout"}, False),
    ({"type": "ERROR", "status": "ok"}, False), ({"type": "RESPONSE", "status": "Sent"}, True),
    ({"type": "ALERT_ACK", "status": "failed"}, False), ({"type": "FILES", "ok": False}, False), (None, False),
])
def test_reply_ok(reply, ok):
    assert server_actions.reply_ok(reply) is ok

# endregion


# region Players Page

PLAYERS = {"type": "PLAYER_CACHE", "player_list": [
    {"name": "Zed", "entityId": "2002", "status": "Offline", "faction": "AAA", "playfield": "Akua", "ping": 0, "steamId": "s2"},
    {"name": "Amy", "entityId": "1001", "status": "Online", "faction": "BBB", "playfield": "Omicron", "ping": 40, "steamId": "s1"}]}
INFO = {"type": "API_RESULT", "status": "ok", "data": {"health": 50, "healthMax": 100, "oxygen": 10, "oxygenMax": 40,
                                                        "food": 0, "foodMax": 0}}
INVENTORY = {"type": "API_RESULT", "status": "ok", "data": {"playerId": 1001, "toolbelt": [{"id": 10, "count": 5, "slotIdx": 0}],
                                                             "bag": [{"id": 20, "count": 1, "slotIdx": 3}]}}


def players_page(qapp, monkeypatch, tmp_path, role="admin", safety_answer=True):
    from features.players.players_page import PlayersPage
    from features.shared import loadouts
    monkeypatch.setattr(loadouts, "TEMPLATES_FILE", str(tmp_path / "loadouts.json"))
    bridge = install(monkeypatch, tmp_path, {"plys": PLAYERS, "api:Request_Player_Info": INFO,
                                             "api:Request_Player_GetInventory": INVENTORY}, safety_answer)
    page = PlayersPage()
    host(page, role)
    settle(qapp)
    page.tbl_players.selectRow(0)
    settle(qapp)
    return page, bridge


def test_players_list_detail_and_inventory(qapp, monkeypatch, tmp_path):
    page, bridge = players_page(qapp, monkeypatch, tmp_path)
    assert page.tbl_players.item(0, 0).text() == "Amy" and page.tbl_players.item(1, 0).text() == "Zed"
    assert page.lbl_player_name.text() == "AMY" and page.stat_bars["HEALTH"].value() == 50
    assert page.stat_bars["OXYGEN"].value() == 25 and page.stat_bars["FOOD"].value() == 0
    assert page.tbl_inventory.rowCount() == 2
    assert 'api:Request_Player_Info {"id":1001}' in bridge.sent


def test_god_mode_stays_off(qapp, monkeypatch, tmp_path):
    from features.players.players_page import GOD_MODE_TIP
    page, bridge = players_page(qapp, monkeypatch, tmp_path, "developer")
    assert not page.action_buttons["GOD MODE"].isEnabled() and page.action_buttons["GOD MODE"].toolTip() == GOD_MODE_TIP


def test_moderator_can_kick_not_ban(qapp, monkeypatch, tmp_path):
    page, bridge = players_page(qapp, monkeypatch, tmp_path, "moderator")
    assert page.action_buttons["KICK"].isEnabled() and not page.action_buttons["BAN"].isEnabled()
    assert not page.btn_inventory_save.isEnabled()


def test_kick_and_ban_commands(qapp, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QInputDialog
    page, bridge = players_page(qapp, monkeypatch, tmp_path, "admin")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("griefing 'base'", True)))
    page._on_kick_clicked()
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("7d", True)))
    page._on_ban_clicked()
    settle(qapp)
    assert "con:kick 1001 'griefing base'" in bridge.sent and "con:ban 1001 7d" in bridge.sent


def test_cancelled_safety_flow_sends_nothing(qapp, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QInputDialog
    page, bridge = players_page(qapp, monkeypatch, tmp_path, "admin", safety_answer=False)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("hello", True)))
    page._on_message_clicked()
    settle(qapp)
    assert not any(command.startswith("msg:") for command in bridge.sent)


def test_inventory_edit_and_apply(qapp, monkeypatch, tmp_path):
    page, bridge = players_page(qapp, monkeypatch, tmp_path, "admin")
    page.tbl_inventory.item(0, 3).setText("9")
    page.tbl_inventory.item(1, 3).setText("0")
    assert page.edited_inventory() == {"playerId": 1001, "toolbelt": [{"id": 10, "count": 9, "slotIdx": 0}], "bag": []}
    page._on_inventory_save()
    settle(qapp)
    assert any(command.startswith('api:Request_Player_SetInventory {"playerId":1001') for command in bridge.sent)
    page.tbl_inventory.item(0, 3).setText("x")
    assert page.edited_inventory() is None


def test_warp_uses_teleport_or_change_playfield(qapp, monkeypatch, tmp_path):
    from features.players import players_page as module
    page, bridge = players_page(qapp, monkeypatch, tmp_path, "admin")
    monkeypatch.setattr(module, "ask_warp_target", lambda parent, current: ("Omicron", 1.0, 2.0, 3.0))
    page._on_warp_clicked()
    monkeypatch.setattr(module, "ask_warp_target", lambda parent, current: ("Akua", 0.0, 0.0, 0.0))
    page._on_warp_clicked()
    settle(qapp)
    assert any(c.startswith('api:Request_Entity_Teleport {"id":1001,"pos":{"x":1.0') for c in bridge.sent)
    assert any(c.startswith('api:Request_Entity_ChangePlayfield {"id":1001,"playfield":"Akua"') for c in bridge.sent)


def test_loadout_needs_items_then_sends_one_additem_each(qapp, monkeypatch, tmp_path):
    from features.shared import loadouts
    page, bridge = players_page(qapp, monkeypatch, tmp_path, "admin")
    assert not page.loadout_buttons[0].isEnabled()
    loadouts.add_to_template("STARTER", 101, "Pistol", 1)
    loadouts.add_to_template("STARTER", 102, "Ammo", 50)
    page._refresh_buttons()
    assert page.loadout_buttons[0].isEnabled()
    page._on_loadout_clicked("STARTER")
    settle(qapp)
    adds = [c for c in bridge.sent if c.startswith("api:Request_Player_AddItem")]
    assert adds == ['api:Request_Player_AddItem {"id":1001,"item":{"id":101,"count":1}}',
                    'api:Request_Player_AddItem {"id":1001,"item":{"id":102,"count":50}}']


def test_offline_bridge_reads_nothing(qapp, monkeypatch, tmp_path):
    from features.players.players_page import PlayersPage
    bridge = install(monkeypatch, tmp_path)
    page = PlayersPage()
    host(page, "developer", connected=False)
    settle(qapp)
    assert bridge.sent == [] and not page.action_buttons["KICK"].isEnabled()

# endregion


# region Dashboard

def test_dashboard_live_and_announce(qapp, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QInputDialog
    from features.dashboard.dashboard_page import DashboardPage, SAVE_TIP, format_uptime
    players = {"type": "PLAYER_CACHE", "player_list": [
        {"name": "Amy", "status": "Online", "faction": "BBB", "playfield": "Omicron", "ping": 40, "cheat": "Off", "cheater": "No"},
        {"name": "Bob", "status": "Online", "faction": "--", "playfield": "Akua", "ping": 9, "cheat": "On", "cheater": "No"},
        {"name": "Cid", "status": "Offline", "cheat": "Off", "cheater": "No"}]}
    bridge = install(monkeypatch, tmp_path, {"plys": players,
                                             "api:Request_Dedi_Stats": {"type": "API_RESULT", "status": "ok", "data": {"uptime": 90061}}})
    page = DashboardPage()
    host(page, "moderator")
    settle(qapp)
    assert page.lbl_players_value.text() == "2 / 3" and page.tbl_players.rowCount() == 2
    assert page.lbl_alerts_value.text() == "1" and "Bob" in page.lbl_attention_empty.text()
    assert page.lbl_uptime_value.text() == format_uptime(90061) == "1d 01h 01m"
    assert not page.quick_action_buttons[1].isEnabled() and page.quick_action_buttons[1].toolTip() == SAVE_TIP
    assert page.quick_action_buttons[0].isEnabled()
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Restart in 15 minutes", True)))
    page._on_announce_clicked()
    settle(qapp)
    assert "broadcast:Restart in 15 minutes" in bridge.sent

# endregion
