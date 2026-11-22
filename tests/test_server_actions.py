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
    assert not any("InGameMessage" in command for command in bridge.sent)


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
    assert 'api:Request_InGameMessage_AllPlayers {"msg": "Restart in 15 minutes"}' in bridge.sent

# endregion


# region Chat Page

def _chat_reply(seq_start=1):
    return {"type": "CHAT_LOG", "ok": True, "count": 3, "last_seq": seq_start + 2, "kept": 500, "messages": [
        {"seq": seq_start, "time": "2026-11-22T18:00:00Z", "channel": "Global", "senderType": "Player",
         "senderId": 1001, "senderName": "", "senderFactionId": 100, "recipientId": 0, "recipientFactionId": 0, "text": "hello all"},
        {"seq": seq_start + 1, "time": "2026-11-22T18:01:00Z", "channel": "Faction", "senderType": "Player",
         "senderId": 1002, "senderName": "", "senderFactionId": 101, "recipientId": 0, "recipientFactionId": 101, "text": "you cheater"},
        {"seq": seq_start + 2, "time": "2026-11-22T18:02:00Z", "channel": "SinglePlayer", "senderType": "Player",
         "senderId": 1003, "senderName": "", "senderFactionId": 0, "recipientId": 0, "recipientFactionId": 0, "text": "admin help"}]}


def test_chat_page_reads_sends_and_warns(monkeypatch, tmp_path):
    from features.chat import chat_store, chat_page
    from PyQt6.QtCore import Qt
    monkeypatch.setattr(chat_store, "WATCH_WORDS_FILE", str(tmp_path / "words.json"))
    monkeypatch.setattr(chat_store, "CHAT_HISTORY", [])
    monkeypatch.setattr(chat_store, "LAST_SEQ", {"value": 0})
    players = {"type": "PLAYER_CACHE", "player_list": [{"entityId": "1001", "name": "Alice"}, {"entityId": "1002", "name": "Bob"}]}
    bridge = install(monkeypatch, tmp_path, {"chat:recent": _chat_reply(), "plys": players,
                                             "con:say": {"type": "CONSOLE_RESULT", "status": "ok"},
                                             "api:Request_InGameMessage": {"type": "API_RESULT", "status": "ok"}})
    qapp = get_qapp()
    page = chat_page.create_page()
    cockpit = host(page, role="moderator")
    settle(qapp)
    assert len(chat_store.CHAT_HISTORY) == 3 and chat_store.LAST_SEQ["value"] == 3
    assert page.lst_messages.count() == 1 and "Alice" in page.lst_messages.item(0).text()

    ## Global SEND uses con:say through the Safety Flow, with quotes removed.
    page.txt_reply.setText("server's restart soon")
    assert page.btn_send.isEnabled()
    page._on_send_clicked()
    settle(qapp)
    assert any(cmd == "con:say 'servers restart soon'" for cmd in bridge.sent)

    ## Faction SEND needs a picked message, then goes to that faction.
    page._on_tab_clicked("faction")
    page.txt_reply.setText("calm down")
    assert not page.btn_send.isEnabled()
    page.lst_messages.item(0).setSelected(True)
    assert page.btn_send.isEnabled()
    page._on_send_clicked()
    settle(qapp)
    assert 'api:Request_InGameMessage_Faction {"id": 101, "msg": "calm down"}' in bridge.sent

    ## Private SEND answers the sender.
    page._on_tab_clicked("private")
    page.lst_messages.item(0).setSelected(True)
    page.txt_reply.setText("on my way")
    page._on_send_clicked()
    settle(qapp)
    assert 'api:Request_InGameMessage_SinglePlayer {"id": 1003, "msg": "on my way"}' in bridge.sent

    ## A watch word makes a hit; WARN sends a private message to that player.
    page.txt_watch_word.setText("cheat")
    page._on_watch_add()
    assert page.lst_hits.count() == 1
    page.lst_hits.setCurrentRow(0)
    monkeypatch.setattr(chat_page.QInputDialog, "getText", staticmethod(lambda *a, **k: ("stop that", True)))
    page._on_warn_clicked()
    settle(qapp)
    assert 'api:Request_InGameMessage_SinglePlayer {"id": 1002, "msg": "stop that"}' in bridge.sent
    assert not page.btn_mute.isEnabled() and not page.tab_buttons["discord"].isEnabled()

    ## Switching the word off clears the hit.
    page._on_watch_toggled(0, False)
    assert page.lst_hits.count() == 0
    cockpit.close()


def test_chat_store_handles_bridge_reload(monkeypatch):
    from features.chat import chat_store
    monkeypatch.setattr(chat_store, "CHAT_HISTORY", [])
    monkeypatch.setattr(chat_store, "LAST_SEQ", {"value": 0})
    chat_store.add_messages(_chat_reply(40))
    assert chat_store.LAST_SEQ["value"] == 42
    chat_store.add_messages({"type": "CHAT_LOG", "messages": [], "last_seq": 0})
    assert chat_store.LAST_SEQ["value"] == 0

# endregion


# region Factions Page

def test_factions_page_reads_lists_and_alliances(monkeypatch, tmp_path):
    from features.factions import factions_page
    factions = {"type": "API_RESULT", "status": "ok", "data": {"factions": [
        {"origin": 1, "factionId": 100, "name": "Some Old Farts", "abbrev": "SOF"},
        {"origin": 1, "factionId": 101, "name": "RSL-BRS", "abbrev": "RSL"},
        {"origin": 1, "factionId": 1, "name": "Human", "abbrev": "Hum"}]}}
    players = {"type": "PLAYER_CACHE", "player_list": [
        {"entityId": "5", "name": "Alice", "factionId": 100, "role": "Owner", "status": "Online"},
        {"entityId": "6", "name": "Bob", "factionId": 100, "role": "Member", "status": "Offline"}]}
    alliances = {"type": "API_RESULT", "status": "ok", "data": {"alliances": [(100 << 16) | 101]}}
    bridge = install(monkeypatch, tmp_path, {"api:Request_Get_Factions": factions, "plys": players,
                                             "api:Request_AlliancesAll": alliances})
    qapp = get_qapp()
    page = factions_page.create_page()
    cockpit = host(page, role="moderator")
    settle(qapp)
    assert page.lst_factions.count() == 3
    item = next(page.lst_factions.item(i) for i in range(3) if "Some Old Farts" in page.lst_factions.item(i).text())
    assert "2 members" in item.text()
    item.setSelected(True)
    assert page.tbl_members.rowCount() == 2 and page.tbl_members.item(0, 0).text() == "Alice"
    assert "Human" in page.lbl_faction_origin.text()
    assert page.relations_rows_layout.count() == 1
    assert all(not button.isEnabled() for button in page.action_buttons)
    assert not any(not cmd.startswith(("api:Request_Get_Factions", "plys", "api:Request_AlliancesAll")) for cmd in bridge.sent)
    cockpit.close()

# endregion


# region Structures Page

def test_structures_page_filters_teleports_and_destroys(monkeypatch, tmp_path):
    from features.structures import structures_page
    entities = {"type": "ENTITY_LIST", "status": "Synced", "count": 2, "entities": [
        {"id": 3001, "name": "Home Base", "type": "BA", "faction": "SOF", "playfield": "Akua", "pos": "10.0, 20.0, 30.0",
         "powered": True, "blocks": 1234, "devices": 50},
        {"id": 3002, "name": "Hauler", "type": "CV", "faction": "RSL", "playfield": "Omicron", "pos": "1.0, 2.0, 3.0",
         "powered": None, "blocks": None, "devices": None}]}
    players = {"type": "PLAYER_CACHE", "player_list": [
        {"entityId": "1001", "name": "Alice", "status": "Online", "playfield": "Omicron"},
        {"entityId": "--", "name": "Ghost", "status": "Offline"}]}
    bridge = install(monkeypatch, tmp_path, {"gents": entities, "plys": players,
                                             "api:Request_Entity": {"type": "API_RESULT", "status": "ok"}})
    qapp = get_qapp()
    page = structures_page.create_page()
    cockpit = host(page, role="admin")
    settle(qapp)
    assert page.tbl_structures.rowCount() == 2 and page.lbl_structure_count.text() == "2 STRUCTURES"
    page._on_filter_clicked("CV")
    assert page.tbl_structures.rowCount() == 1 and page.tbl_structures.item(0, 1).text() == "Hauler"
    page._on_filter_clicked("ALL")
    page.tbl_structures.selectRow(0)
    assert page.lbl_structure_blocks.text() == "BLOCKS:  1234"
    assert page.action_buttons["DESTROY"].isEnabled() and not page.action_buttons["SET FACTION"].isEnabled()
    monkeypatch.setattr(structures_page.QInputDialog, "getItem", staticmethod(lambda *a, **k: ("Alice  (Omicron)", True)))
    page._on_teleport_clicked()
    settle(qapp)
    moves = [cmd for cmd in bridge.sent if cmd.startswith("api:Request_Entity_ChangePlayfield")]
    assert moves and '"id":1001' in moves[0] and '"playfield":"Akua"' in moves[0] and '"y":35.0' in moves[0]
    page._on_destroy_clicked()
    settle(qapp)
    assert 'api:Request_Entity_Destroy {"id": 3001}' in bridge.sent
    cockpit.close()


def test_structures_page_moderator_cannot_destroy(monkeypatch, tmp_path):
    from features.structures import structures_page
    entities = {"type": "ENTITY_LIST", "entities": [{"id": 1, "name": "B", "type": "BA", "playfield": "Akua", "pos": "0, 0, 0"}]}
    install(monkeypatch, tmp_path, {"gents": entities})
    qapp = get_qapp()
    page = structures_page.create_page()
    cockpit = host(page, role="moderator")
    settle(qapp)
    page.tbl_structures.selectRow(0)
    assert not page.action_buttons["DESTROY"].isEnabled() and not page.action_buttons["TELEPORT TO"].isEnabled()
    cockpit.close()

# endregion


# region Playfields Page

def test_playfields_page_cards_and_owner_actions(monkeypatch, tmp_path):
    from features.playfields import playfields_page
    monkeypatch.setattr(playfields_page, "RESTART_GAP_SEC", 0.0)
    playfields = {"type": "PLAYFIELD_LIST", "playfields": [
        {"name": "Akua", "playfieldType": "Planet", "loaded": True},
        {"name": "Akua", "loaded": True, "source": "server"},
        {"name": "Zero-G [Sun Right]", "playfieldType": "Space", "loaded": True},
        {"name": "Omicron", "loaded": False}]}
    players = {"type": "PLAYER_CACHE", "player_list": [{"name": "A", "status": "Online", "playfield": "Akua"}]}
    stats = {"type": "API_RESULT", "status": "ok", "data": {"structs": 7}}
    bridge = install(monkeypatch, tmp_path, {"getplayfields": playfields, "plys": players, "api:Request_Playfield_Stats": stats,
                                             "con:": {"type": "CONSOLE_RESULT", "status": "ok"},
                                             "loadpf:": {"type": "API_RESULT", "status": "ok"}})
    qapp = get_qapp()
    page = playfields_page.create_page()
    cockpit = host(page, role="owner")
    settle(qapp)
    assert list(page.card_checks) == ["Akua", "Zero-G [Sun Right]"]
    assert "3 known playfields" in page.lbl_map_empty.text() and "2 loaded" in page.lbl_map_empty.text()
    assert not page.bulk_buttons["UNLOAD"].isEnabled()
    page.card_checks["Zero-G [Sun Right]"].setChecked(True)
    assert page.bulk_buttons["UNLOAD"].isEnabled() and "1 SELECTED" in page.lbl_bulk_title.text()
    page._on_unload_clicked()
    settle(qapp)
    assert 'con:stoppf "Zero-G [Sun Right]"' in bridge.sent
    page.card_checks["Akua"].setChecked(True)
    page._on_restart_clicked()
    settle(qapp)
    assert "con:stoppf Akua" in bridge.sent and "loadpf:Akua|600" in bridge.sent
    monkeypatch.setattr(playfields_page.QInputDialog, "getItem", staticmethod(lambda *a, **k: ("deposit", True)))
    page._on_wipe_clicked()
    settle(qapp)
    assert "con:wipe Akua deposit" in bridge.sent
    cockpit.close()


def test_playfields_page_admin_is_not_owner(monkeypatch, tmp_path):
    from features.playfields import playfields_page
    install(monkeypatch, tmp_path, {"getplayfields": {"type": "PLAYFIELD_LIST", "playfields": [{"name": "Akua", "loaded": True}]},
                                    "plys": {"type": "PLAYER_CACHE", "player_list": []}})
    qapp = get_qapp()
    page = playfields_page.create_page()
    cockpit = host(page, role="admin")
    settle(qapp)
    page.card_checks["Akua"].setChecked(True)
    assert not any(button.isEnabled() for button in page.bulk_buttons.values())
    cockpit.close()

# endregion
