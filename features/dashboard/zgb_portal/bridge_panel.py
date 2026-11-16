#!/usr/bin/env python3
"""Bridge tab of the ZeroGBridge Portal: API catalog + IronPython editor.

Viewer only, fake data. Nothing here talks to a live server.
Example scripts use IronPython 3.4 syntax (no f-strings).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .data_source import Script

from PyQt6.QtCore import Qt, QRegularExpression
from PyQt6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QHeaderView,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Colors stay in lockstep with hot_reload_panel.py
COLOR_OK = "#00ff88"
COLOR_FAIL = "#ff3355"
COLOR_WARN = "#ffaa33"
COLOR_CYAN = "#00d4ff"
COLOR_TEXT = "#e0e0e0"
COLOR_DIM = "#7aa0b0"


# ---------------------------------------------------------------------------
# Syntax highlighter (IronPython 3.4 / Python 3 subset)
# ---------------------------------------------------------------------------

class PythonHighlighter(QSyntaxHighlighter):
    """Lightweight Python highlighter for the mock editor."""

    KEYWORDS = (
        "and as assert break class continue def del elif else except "
        "exec finally for from global if import in is lambda not or "
        "pass print raise return try while with yield True False None"
    ).split()

    BUILTINS = (
        "bridge log abs all any bool dict enumerate float int len "
        "list print range str sum tuple type hasattr getattr "
        "min max sorted zip"
    ).split()

    def __init__(self, document):
        super().__init__(document)
        self.rules: list[tuple[QRegularExpression, QTextCharFormat]] = []

        def fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Weight.Bold)
            if italic:
                f.setFontItalic(True)
            return f

        kw = fmt(COLOR_CYAN, bold=True)
        for word in self.KEYWORDS:
            self.rules.append((QRegularExpression(rf"\b{word}\b"), kw))

        bi = fmt("#c79bff")
        for word in self.BUILTINS:
            self.rules.append((QRegularExpression(rf"\b{word}\b"), bi))

        self.rules.append((QRegularExpression(r"\bdef\s+(\w+)"), fmt("#ffffff", bold=True)))
        self.rules.append((QRegularExpression(r"\b[0-9]+\b"), fmt(COLOR_WARN)))
        self.rules.append((QRegularExpression(r"#[^\n]*"), fmt(COLOR_DIM, italic=True)))

        self._string = fmt(COLOR_OK)
        self._string_re = QRegularExpression(r"(\"[^\"\\]*(\\.[^\"\\]*)*\"|'[^'\\]*(\\.[^'\\]*)*')")

    def highlightBlock(self, text: str) -> None:
        for regex, form in self.rules:
            it = regex.globalMatch(text)
            while it.hasNext():
                m = it.next()
                # For the def-name rule, highlight the name (capture 1) when present
                if m.lastCapturedIndex() >= 1 and regex.pattern().startswith(r"\bdef"):
                    self.setFormat(m.capturedStart(1), m.capturedLength(1), form)
                else:
                    self.setFormat(m.capturedStart(), m.capturedLength(), form)
        it = self._string_re.globalMatch(text)
        while it.hasNext():
            m = it.next()
            self.setFormat(m.capturedStart(), m.capturedLength(), self._string)


# ---------------------------------------------------------------------------
# Fake API catalog
# ---------------------------------------------------------------------------

@dataclass
class Param:
    key: str
    label: str
    kind: str = "text"  # text, int, combo, check
    default: Any = ""
    options: list[str] | None = None


@dataclass
class ApiCommand:
    category: str
    name: str
    call: str
    summary: str
    params: list[Param] = field(default_factory=list)
    runner: Callable[[dict], str] | None = None
    simulates: str | None = None  # event name, if this is a simulated hook


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(row: list[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

    line = "  ".join("-" * w for w in widths)
    parts = [fmt_row(headers), line]
    parts.extend(fmt_row(r) for r in rows)
    return "\n".join(parts)


def _ok(call: str, body: str) -> str:
    return "OK  {0}\n\n{1}".format(call, body)


PLAYERS_ALL = [
    ["KaiVoss", "Online", "Vanguard", "Akua Orbit", "12h"],
    ["Rhea", "Online", "Solace", "Akua", "4h"],
    ["Dorne", "Offline", "Vanguard", "Omicron", "41h"],
    ["Nessa", "Offline", "Solace", "Akua", "9h"],
]


def _run_list_players(v: dict) -> str:
    rows = [r for r in PLAYERS_ALL if (r[1] == "Online" if v.get("online_only") else True)]
    body = "{0} player(s) on Zero-G Reborn (GTX)\n\n{1}".format(
        len(rows),
        _table(["Name", "Status", "Faction", "Playfield", "Playtime"], rows),
    )
    return _ok("bridge.players.list(online_only={0})".format(v.get("online_only")), body)


def _run_get_player(v: dict) -> str:
    name = (v.get("name") or "KaiVoss").strip()
    match = next((r for r in PLAYERS_ALL if r[0].lower() == name.lower()), None)
    if not match:
        return "FAILED  bridge.players.get({0!r})\n\nNo player named {0} in the cache.".format(name)
    body = (
        "Name:        {0}\n"
        "Status:      {1}\n"
        "SteamId:     76561198000001\n"
        "EntityId:    2041\n"
        "Faction:     {2}  (origin 1, has a real player)\n"
        "Playfield:   {3}\n"
        "Position:    124.0, 88.2, -41.5\n"
        "Credits:     18,450\n"
        "Playtime:    {4}"
    ).format(*match)
    return _ok("bridge.players.get({0!r})".format(name), body)


def _run_kick(v: dict) -> str:
    name = v.get("name") or "KaiVoss"
    reason = v.get("reason") or "Admin request"
    return _ok(
        "bridge.players.kick({0!r}, reason={1!r})".format(name, reason),
        "Sent kick to {0}. They will be disconnected on the next tick.\nReason: {1}".format(name, reason),
    )


def _run_ban(v: dict) -> str:
    name = v.get("name") or "Dorne"
    hours = v.get("hours") or 24
    reason = v.get("reason") or "Rule break"
    return _ok(
        "bridge.players.ban({0!r}, hours={1}, reason={2!r})".format(name, hours, reason),
        "Ban recorded for {0} ({1} hour(s)).\nReason: {2}".format(name, hours, reason),
    )


def _run_credits(v: dict) -> str:
    name = v.get("name") or "Rhea"
    amount = v.get("amount") or 500
    return _ok(
        "bridge.players.set_credits({0!r}, {1})".format(name, amount),
        "Credits for {0} set to {1:,}. Previous balance 18,450.".format(name, int(amount)),
    )


def _run_message_player(v: dict) -> str:
    name = v.get("name") or "KaiVoss"
    text = v.get("message") or "Please meet us at the station."
    return _ok(
        "bridge.players.message({0!r}, {1!r})".format(name, text),
        "Private message queued for {0}:\n  {1}".format(name, text),
    )


def _run_list_factions(v: dict) -> str:
    rows = [
        ["100", "Vanguard", "1 (player)", "4 members", "KaiVoss"],
        ["101", "Solace", "1 (player)", "2 members", "Rhea"],
        ["118", "Dorne", "1 (private)", "1 member", "Dorne"],
    ]
    if v.get("origin") == "private only":
        rows = [r for r in rows if "private" in r[2]]
    body = (
        "{0} faction(s) after NPC filter (origin 0/1 with a real player; "
        "Zirax and other origin 2+ dropped).\n\n{1}"
    ).format(len(rows), _table(["Id", "Name", "Origin", "Members", "Leader"], rows))
    return _ok("bridge.factions.list(origin={0!r})".format(v.get("origin")), body)


def _run_get_faction(v: dict) -> str:
    key = v.get("name_or_id") or "Vanguard"
    return _ok(
        "bridge.factions.get({0!r})".format(key),
        "Id:        100\nName:      Vanguard\nOrigin:    1 (player faction)\n"
        "Members:   KaiVoss, Dorne, plus 2 offline\nHonor:     1,200\nPoints:    44",
    )


def _run_faction_points(v: dict) -> str:
    name = v.get("name_or_id") or "Vanguard"
    points = v.get("points") or 50
    return _ok(
        "bridge.factions.set_points({0!r}, {1})".format(name, points),
        "Vanguard points set to {0} (was 44).".format(points),
    )


def _run_list_playfields(v: dict) -> str:
    rows = [
        ["Akua", "Planet", "Loaded", "1 player, 6 structures"],
        ["Akua Orbit", "Space", "Loaded", "1 player, 2 structures"],
        ["Omicron", "Planet", "Unloaded", "0 players"],
        ["Masperon", "Planet", "Unloaded", "0 players"],
    ]
    if v.get("loaded_only"):
        rows = [r for r in rows if r[2] == "Loaded"]
    return _ok(
        "bridge.playfields.list(loaded_only={0})".format(v.get("loaded_only")),
        "{0} playfield(s)\n\n{1}".format(
            len(rows), _table(["Name", "Type", "State", "Contents"], rows)
        ),
    )


def _run_get_playfield(v: dict) -> str:
    name = v.get("name") or "Akua"
    return _ok(
        "bridge.playfields.get({0!r})".format(name),
        "Name:       {0}\nType:       Planet\nState:      Loaded\n"
        "Size:       4 km\nPlayers:    Rhea\nStructures: 6 (4 BA, 1 SV, 1 HV)".format(name),
    )


def _run_load_playfield(v: dict) -> str:
    name = v.get("name") or "Omicron"
    return _ok(
        "bridge.playfields.load({0!r})".format(name),
        "Load requested for {0}. The playfield will come up on the next tick.".format(name),
    )


def _run_list_structures(v: dict) -> str:
    rows = [
        ["88102", "Vanguard Station", "BA", "Vanguard", "Akua"],
        ["88117", "Rhea's Rover", "HV", "Solace", "Akua"],
        ["88201", "Orbit Dock", "BA", "Vanguard", "Akua Orbit"],
        ["88214", "Skiff", "SV", "Solace", "Akua Orbit"],
    ]
    typ = v.get("type") or "All"
    pf = (v.get("playfield") or "All").strip()
    if typ != "All":
        rows = [r for r in rows if r[2] == typ]
    if pf and pf != "All":
        rows = [r for r in rows if r[4].lower() == pf.lower()]
    return _ok(
        "bridge.structures.list(type={0!r}, playfield={1!r})".format(typ, pf),
        "{0} structure(s)\n\n{1}".format(
            len(rows), _table(["EntityId", "Name", "Type", "Faction", "Playfield"], rows)
        ),
    )


def _run_get_structure(v: dict) -> str:
    eid = v.get("entity_id") or "88102"
    return _ok(
        "bridge.structures.get({0})".format(eid),
        "EntityId:   {0}\nName:       Vanguard Station\nType:       BA\n"
        "Faction:    Vanguard\nPlayfield:  Akua\nPosition:   210.4, 12.0, -88.1\n"
        "Core:       Intact\nFuel:       74%".format(eid),
    )


def _run_set_struct_faction(v: dict) -> str:
    eid = v.get("entity_id") or "88102"
    fac = v.get("faction") or "Vanguard"
    return _ok(
        "bridge.structures.set_faction({0}, {1!r})".format(eid, fac),
        "Structure {0} faction set to {1}.".format(eid, fac),
    )


def _run_give_item(v: dict) -> str:
    name = v.get("player") or "Rhea"
    item = v.get("item") or "OxygenBottle"
    count = v.get("count") or 3
    return _ok(
        "bridge.items.give({0!r}, item={1!r}, count={2})".format(name, item, count),
        "Gave {0} x {1} to {2}. Inventory updated.".format(count, item, name),
    )


def _run_remove_item(v: dict) -> str:
    name = v.get("player") or "Rhea"
    item = v.get("item") or "OxygenBottle"
    count = v.get("count") or 1
    return _ok(
        "bridge.items.remove({0!r}, item={1!r}, count={2})".format(name, item, count),
        "Removed {0} x {1} from {2}.".format(count, item, name),
    )


def _run_inventory(v: dict) -> str:
    name = v.get("player") or "KaiVoss"
    rows = [
        ["InterstellarCore", "1", "Backpack"],
        ["OxygenBottle", "4", "Backpack"],
        ["EmergencyRations", "8", "Backpack"],
        ["ProjectileRifle", "1", "Toolbar"],
    ]
    return _ok(
        "bridge.items.inventory({0!r})".format(name),
        "Inventory for {0}\n\n{1}".format(
            name, _table(["Item", "Count", "Slot"], rows)
        ),
    )


def _run_global_chat(v: dict) -> str:
    msg = v.get("message") or "Welcome to Zero-G Reborn."
    return _ok(
        "bridge.chat.send(to='global', message={0!r})".format(msg),
        "Global chat sent:\n  [SRV] {0}".format(msg),
    )


def _run_faction_chat(v: dict) -> str:
    fac = v.get("faction") or "Vanguard"
    msg = v.get("message") or "Form up at the station."
    return _ok(
        "bridge.chat.send(to='faction', faction={0!r}, message={1!r})".format(fac, msg),
        "Faction chat sent to {0}:\n  [{0}] {1}".format(fac, msg),
    )


def _run_announce(v: dict) -> str:
    msg = v.get("message") or "The server will save in 5 minutes."
    secs = v.get("seconds") or 15
    return _ok(
        "bridge.alerts.announce({0!r}, seconds={1})".format(msg, secs),
        "Announcement shown to all players for {0}s:\n  {1}".format(secs, msg),
    )


def _run_alert(v: dict) -> str:
    target = v.get("to") or "All"
    title = v.get("title") or "Notice"
    body = v.get("body") or "Type /help if you need an admin."
    return _ok(
        "bridge.alerts.send(to={0!r}, title={1!r})".format(target, title),
        "Alert queued for {0}.\nTitle: {1}\nBody:  {2}".format(target, title, body),
    )


def _run_tp_coords(v: dict) -> str:
    name = v.get("player") or "KaiVoss"
    pf = v.get("playfield") or "Akua"
    x, y, z = v.get("x") or 0, v.get("y") or 50, v.get("z") or 0
    return _ok(
        "bridge.teleport.player({0!r}, playfield={1!r}, pos=({2}, {3}, {4}))".format(
            name, pf, x, y, z
        ),
        "Queued teleport of {0} to {1} at {2}, {3}, {4}.".format(name, pf, x, y, z),
    )


def _run_tp_player(v: dict) -> str:
    src = v.get("player") or "Rhea"
    dst = v.get("target") or "KaiVoss"
    return _ok(
        "bridge.teleport.player_to_player({0!r}, {1!r})".format(src, dst),
        "Queued teleport of {0} to {1}'s position.".format(src, dst),
    )


def _run_tp_structure(v: dict) -> str:
    name = v.get("player") or "Rhea"
    eid = v.get("entity_id") or "88102"
    return _ok(
        "bridge.teleport.player_to_structure({0!r}, {1})".format(name, eid),
        "Queued teleport of {0} to structure {1} (Vanguard Station, Akua).".format(name, eid),
    )


def _run_list_hooks(v: dict) -> str:
    rows = [
        ["player_joined", "greet_on_join.py", "ON"],
        ["player_died", "death_notice.py", "ON"],
        ["player_joined", "starter_kit.py", "OFF"],
        ["player_left", "(none)", "—"],
        ["player_chat", "(none)", "—"],
    ]
    return _ok(
        "bridge.events.hooks()",
        "Registered script hooks\n\n{0}".format(
            _table(["Event", "Script", "State"], rows)
        ),
    )


def _sim_header(event: str, detail: str) -> str:
    return (
        "OK  simulate {0}\n\n"
        "Fired a mock {0} event on the game thread.\n{1}\n"
        "Enabled scripts with this hook ran under their time limits."
    ).format(event, detail)


def build_catalog() -> list[ApiCommand]:
    return [
        ApiCommand("Players", "List players", "bridge.players.list",
                   "List players in the cache. One-person factions with a real player are included.",
                   [Param("online_only", "Online only", "check", True)], _run_list_players),
        ApiCommand("Players", "Get player", "bridge.players.get",
                   "Look up one player by name, Steam ID, or entity ID.",
                   [Param("name", "Player name", "text", "KaiVoss")], _run_get_player),
        ApiCommand("Players", "Kick player", "bridge.players.kick",
                   "Disconnect a player. They can rejoin afterward.",
                   [Param("name", "Player name", "text", "KaiVoss"),
                    Param("reason", "Reason", "text", "Admin request")], _run_kick),
        ApiCommand("Players", "Ban player", "bridge.players.ban",
                   "Ban a player for a number of hours (0 = permanent in this mock).",
                   [Param("name", "Player name", "text", "Dorne"),
                    Param("hours", "Hours", "int", 24),
                    Param("reason", "Reason", "text", "Rule break")], _run_ban),
        ApiCommand("Players", "Set credits", "bridge.players.set_credits",
                   "Set a player's credit balance.",
                   [Param("name", "Player name", "text", "Rhea"),
                    Param("amount", "Credits", "int", 500)], _run_credits),
        ApiCommand("Players", "Message player", "bridge.players.message",
                   "Send a private in-game message.",
                   [Param("name", "Player name", "text", "KaiVoss"),
                    Param("message", "Message", "text", "Please meet us at the station.")],
                   _run_message_player),
        ApiCommand("Factions", "List factions", "bridge.factions.list",
                   "List player and private factions that have a real player. NPC factions stay out.",
                   [Param("origin", "Origin filter", "combo", "player + private",
                          ["player + private", "private only", "all cached"])], _run_list_factions),
        ApiCommand("Factions", "Get faction", "bridge.factions.get",
                   "Look up one faction by name or id.",
                   [Param("name_or_id", "Name or id", "text", "Vanguard")], _run_get_faction),
        ApiCommand("Factions", "Set faction points", "bridge.factions.set_points",
                   "Set a faction's points value.",
                   [Param("name_or_id", "Name or id", "text", "Vanguard"),
                    Param("points", "Points", "int", 50)], _run_faction_points),
        ApiCommand("Playfields", "List playfields", "bridge.playfields.list",
                   "List playfields known to the server, optionally only loaded ones.",
                   [Param("loaded_only", "Loaded only", "check", True)], _run_list_playfields),
        ApiCommand("Playfields", "Get playfield", "bridge.playfields.get",
                   "Details for one playfield.",
                   [Param("name", "Playfield", "text", "Akua")], _run_get_playfield),
        ApiCommand("Playfields", "Load playfield", "bridge.playfields.load",
                   "Request that a playfield be loaded.",
                   [Param("name", "Playfield", "text", "Omicron")], _run_load_playfield),
        ApiCommand("Structures", "List structures", "bridge.structures.list",
                   "List bases and vessels, filterable by type and playfield.",
                   [Param("type", "Type", "combo", "All", ["All", "BA", "CV", "SV", "HV"]),
                    Param("playfield", "Playfield", "text", "All")], _run_list_structures),
        ApiCommand("Structures", "Get structure", "bridge.structures.get",
                   "Details for one structure by entity id.",
                   [Param("entity_id", "Entity id", "text", "88102")], _run_get_structure),
        ApiCommand("Structures", "Set structure faction", "bridge.structures.set_faction",
                   "Assign a structure to a faction.",
                   [Param("entity_id", "Entity id", "text", "88102"),
                    Param("faction", "Faction", "text", "Vanguard")], _run_set_struct_faction),
        ApiCommand("Items", "Give item", "bridge.items.give",
                   "Add an item stack to a player's inventory.",
                   [Param("player", "Player name", "text", "Rhea"),
                    Param("item", "Item id", "text", "OxygenBottle"),
                    Param("count", "Count", "int", 3)], _run_give_item),
        ApiCommand("Items", "Remove item", "bridge.items.remove",
                   "Remove an item stack from a player's inventory.",
                   [Param("player", "Player name", "text", "Rhea"),
                    Param("item", "Item id", "text", "OxygenBottle"),
                    Param("count", "Count", "int", 1)], _run_remove_item),
        ApiCommand("Items", "List inventory", "bridge.items.inventory",
                   "List a player's inventory and toolbar.",
                   [Param("player", "Player name", "text", "KaiVoss")], _run_inventory),
        ApiCommand("Chat / Alerts", "Send global chat", "bridge.chat.send",
                   "Post a line to global game chat.",
                   [Param("message", "Message", "text", "Welcome to Zero-G Reborn.")],
                   _run_global_chat),
        ApiCommand("Chat / Alerts", "Send faction chat", "bridge.chat.send",
                   "Post a line to one faction's chat.",
                   [Param("faction", "Faction", "text", "Vanguard"),
                    Param("message", "Message", "text", "Form up at the station.")],
                   _run_faction_chat),
        ApiCommand("Chat / Alerts", "Send announcement", "bridge.alerts.announce",
                   "Show a timed announcement to everyone.",
                   [Param("message", "Message", "text", "The server will save in 5 minutes."),
                    Param("seconds", "Seconds on screen", "int", 15)], _run_announce),
        ApiCommand("Chat / Alerts", "Send alert", "bridge.alerts.send",
                   "Send a titled alert to one player or to everyone.",
                   [Param("to", "To", "combo", "All", ["All", "KaiVoss", "Rhea"]),
                    Param("title", "Title", "text", "Notice"),
                    Param("body", "Body", "text", "Type /help if you need an admin.")],
                   _run_alert),
        ApiCommand("Teleport", "Teleport to coordinates", "bridge.teleport.player",
                   "Move a player to a playfield and position.",
                   [Param("player", "Player name", "text", "KaiVoss"),
                    Param("playfield", "Playfield", "text", "Akua"),
                    Param("x", "X", "int", 0),
                    Param("y", "Y", "int", 50),
                    Param("z", "Z", "int", 0)], _run_tp_coords),
        ApiCommand("Teleport", "Teleport to player", "bridge.teleport.player_to_player",
                   "Move one player to another player's position.",
                   [Param("player", "Player name", "text", "Rhea"),
                    Param("target", "Target player", "text", "KaiVoss")], _run_tp_player),
        ApiCommand("Teleport", "Teleport to structure", "bridge.teleport.player_to_structure",
                   "Move a player to a structure.",
                   [Param("player", "Player name", "text", "Rhea"),
                    Param("entity_id", "Entity id", "text", "88102")], _run_tp_structure),
        ApiCommand("Events", "List event hooks", "bridge.events.hooks",
                   "Show which scripts are bound to player and server events.",
                   [], _run_list_hooks),
        ApiCommand("Events", "Simulate: player joined", "simulate player_joined",
                   "Fire a mock join event so you can test scripts such as greet_on_join.py.",
                   [Param("name", "Player name", "text", "KaiVoss"),
                    Param("playfield", "Playfield", "text", "Akua Orbit")],
                   None, simulates="player_joined"),
        ApiCommand("Events", "Simulate: player left", "simulate player_left",
                   "Fire a mock leave event.",
                   [Param("name", "Player name", "text", "Rhea")],
                   None, simulates="player_left"),
        ApiCommand("Events", "Simulate: player died", "simulate player_died",
                   "Fire a mock death event so you can test scripts such as death_notice.py.",
                   [Param("name", "Player name", "text", "KaiVoss"),
                    Param("cause", "Cause", "text", "explosion"),
                    Param("playfield", "Playfield", "text", "Akua Orbit")],
                   None, simulates="player_died"),
        ApiCommand("Events", "Simulate: player chat", "simulate player_chat",
                   "Fire a mock chat event.",
                   [Param("name", "Player name", "text", "Rhea"),
                    Param("message", "Message", "text", "Anyone at the station?")],
                   None, simulates="player_chat"),
        ApiCommand("Server", "Get status", "bridge.server.status",
                   "Snapshot of the mock server.",
                   [], lambda v: _ok(
                       "bridge.server.status()",
                       "Server:     Zero-G Reborn (GTX)\n"
                       "Players:    2 online\n"
                       "Uptime:     14h 22m\n"
                       "Loader:     1.0.0  (port 30500 held)\n"
                       "Core:       1.4.2\n"
                       "Scripts:    2 enabled, 1 disabled",
                   )),
        ApiCommand("Server", "Save world", "bridge.server.save",
                   "Request a world save. Does not restart the server.",
                   [], lambda v: _ok(
                       "bridge.server.save()",
                       "Save requested. The dedicated process will flush the world on the next tick.",
                   )),
    ]


# ---------------------------------------------------------------------------
# Example IronPython scripts
# ---------------------------------------------------------------------------

# Example scripts now live in <ZAH>/Examples/ZGB_Portal/scripts/ and are
# loaded through the portal data source (data_source.py).


# ---------------------------------------------------------------------------
# Bridge panel
# ---------------------------------------------------------------------------

class BridgePanel(QWidget):
    """API catalog + IronPython script editor, all simulated."""

    def __init__(self, parent=None, capture_mode: bool = False, source=None):
        super().__init__(parent)
        if source is None:
            from .data_source import SampleDataSource
            source = SampleDataSource()
        self.source = source
        self.setObjectName("HotReloadCanvas")
        self.capture_mode = capture_mode
        self.catalog = build_catalog()
        self.commands = {(c.category, c.name): c for c in self.catalog}
        self.current_cmd: ApiCommand | None = None
        self.param_widgets: dict[str, QWidget] = {}
        self.scripts: list[Script] = self.source.scripts()
        self.current_script: Script | None = None
        self._suppress_script_change = False

        self._init_ui()
        self._select_command("Players", "List players")
        self._select_script("greet_on_join.py")
        self._script_log("IronPython 3.4 engine ready (mock). Two scripts are live, one is disabled.", "dim")
        self._script_log("Loaded greet_on_join.py  hook=player_joined  limit=50 ms  LIVE.", "ok")

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("ZeroGBridge  —  Game & Server API")
        title.setObjectName("PopupHeaderLabel")
        subtitle = QLabel(
            "Browse what the Empyrion ModAPI and the server expose, run a command with fake "
            "results, or write an IronPython (.py) script and push it live with no restart."
        )
        subtitle.setObjectName("SubtitleLabel")
        subtitle.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, stretch=1)
        self.badge = QLabel("ENGINE READY")
        self.badge.setObjectName("StatusBadge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setFixedHeight(28)
        header.addWidget(self.badge, alignment=Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self._build_catalog_frame())
        self.splitter.addWidget(self._build_script_frame())
        self.splitter.setSizes([360, 450])
        root.addWidget(self.splitter, stretch=1)

        self.footer = QLabel("Mock mode. Commands and scripts do not touch a live server.")
        self.footer.setObjectName("PopupFooterLabel")
        root.addWidget(self.footer)

    # ----- catalog ---------------------------------------------------------

    def _build_catalog_frame(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("TelemetryPanel")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(10)

        left = QVBoxLayout()
        hdr = QLabel("API CATALOG")
        hdr.setObjectName("SectionHeader")
        left.addWidget(hdr)
        self.tree = QTreeWidget()
        self.tree.setObjectName("ApiTree")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self._fill_tree()
        self.tree.currentItemChanged.connect(self._on_tree_changed)
        left.addWidget(self.tree)
        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setFixedWidth(250)
        layout.addWidget(left_w)

        mid = QVBoxLayout()
        mid_hdr = QLabel("COMMAND")
        mid_hdr.setObjectName("SectionHeader")
        mid.addWidget(mid_hdr)
        self.cmd_title = QLabel("List players")
        self.cmd_title.setObjectName("FieldValue")
        mid.addWidget(self.cmd_title)
        self.cmd_call = QLabel("bridge.players.list")
        self.cmd_call.setObjectName("SubtitleLabel")
        mid.addWidget(self.cmd_call)
        self.cmd_summary = QLabel("")
        self.cmd_summary.setObjectName("SubtitleLabel")
        self.cmd_summary.setWordWrap(True)
        mid.addWidget(self.cmd_summary)

        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self.form.setContentsMargins(0, 6, 0, 6)
        self.form.setHorizontalSpacing(10)
        self.form.setVerticalSpacing(6)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        mid.addWidget(self.form_host)

        run_row = QHBoxLayout()
        self.btn_run = QPushButton("Run")
        self.btn_run.setObjectName("ExecuteButton")
        self.btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run.setFixedWidth(120)
        self.btn_run.clicked.connect(self._on_run_command)
        run_row.addWidget(self.btn_run)
        run_row.addStretch()
        mid.addLayout(run_row)
        mid.addStretch()
        mid_w = QWidget()
        mid_w.setLayout(mid)
        mid_w.setFixedWidth(320)
        layout.addWidget(mid_w)

        right = QVBoxLayout()
        rh = QLabel("RESULT")
        rh.setObjectName("SectionHeader")
        right.addWidget(rh)
        self.result = QTextEdit()
        self.result.setObjectName("ConsoleDisplay")
        self.result.setReadOnly(True)
        self.result.setPlaceholderText("Run a command to see a simulated result…")
        right.addWidget(self.result)
        right_w = QWidget()
        right_w.setLayout(right)
        layout.addWidget(right_w, stretch=1)
        return frame

    def _fill_tree(self) -> None:
        self.tree.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        for cmd in self.catalog:
            if cmd.category not in groups:
                cat = QTreeWidgetItem([cmd.category])
                cat.setFlags(cat.flags() | Qt.ItemFlag.ItemIsEnabled)
                # keep it selectable so keyboard nav works, but we ignore category runs
                font = cat.font(0)
                font.setBold(True)
                cat.setFont(0, font)
                cat.setForeground(0, QColor(COLOR_CYAN))
                self.tree.addTopLevelItem(cat)
                groups[cmd.category] = cat
            item = QTreeWidgetItem([cmd.name])
            item.setData(0, Qt.ItemDataRole.UserRole, (cmd.category, cmd.name))
            item.setForeground(0, QColor(COLOR_TEXT))
            groups[cmd.category].addChild(item)
        self.tree.expandAll()

    def _on_tree_changed(self, current: QTreeWidgetItem, _previous: QTreeWidgetItem) -> None:
        if current is None:
            return
        data = current.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        category, name = data
        self._select_command(category, name, from_tree=True)

    def _select_command(self, category: str, name: str, from_tree: bool = False) -> None:
        cmd = self.commands.get((category, name))
        if not cmd:
            return
        self.current_cmd = cmd
        if not from_tree:
            # locate the item
            for i in range(self.tree.topLevelItemCount()):
                cat = self.tree.topLevelItem(i)
                for j in range(cat.childCount()):
                    child = cat.child(j)
                    if child.data(0, Qt.ItemDataRole.UserRole) == (category, name):
                        self.tree.setCurrentItem(child)
                        break
        self.cmd_title.setText(cmd.name)
        self.cmd_call.setText(cmd.call)
        self.cmd_summary.setText(cmd.summary)
        self._rebuild_form(cmd)

    def _rebuild_form(self, cmd: ApiCommand) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self.param_widgets = {}
        for p in cmd.params:
            label = QLabel(p.label)
            label.setObjectName("FieldLabel")
            if p.kind == "check":
                w = QCheckBox("")
                w.setChecked(bool(p.default))
            elif p.kind == "combo":
                w = QComboBox()
                w.addItems(p.options or [])
                if p.default in (p.options or []):
                    w.setCurrentText(str(p.default))
            elif p.kind == "int":
                w = QSpinBox()
                w.setRange(-1000000, 1000000)
                w.setValue(int(p.default or 0))
            else:
                w = QLineEdit()
                w.setObjectName("CommandInput")
                w.setText(str(p.default or ""))
            self.form.addRow(label, w)
            self.param_widgets[p.key] = w

    def _param_values(self) -> dict:
        values: dict[str, Any] = {}
        for key, w in self.param_widgets.items():
            if isinstance(w, QCheckBox):
                values[key] = w.isChecked()
            elif isinstance(w, QComboBox):
                values[key] = w.currentText()
            elif isinstance(w, QSpinBox):
                values[key] = w.value()
            elif isinstance(w, QLineEdit):
                values[key] = w.text()
        return values

    def _on_run_command(self) -> None:
        cmd = self.current_cmd
        if not cmd:
            return
        values = self._param_values()
        if cmd.simulates:
            text = self._simulate_event(cmd.simulates, values)
        elif cmd.runner:
            text = cmd.runner(values)
        else:
            text = "No runner wired for this command in the mock."
        self.result.setPlainText(text)
        kind = "ok" if text.startswith("OK") else "fail"
        self.footer.setText("Ran {0}  —  {1}.".format(cmd.call, "OK" if kind == "ok" else "failed"))

    # ----- scripts ---------------------------------------------------------

    def _build_script_frame(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("ControlPanel")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(10)

        left = QVBoxLayout()
        hdr = QLabel("SCRIPTS")
        hdr.setObjectName("SectionHeader")
        left.addWidget(hdr)
        self.script_list = QTableWidget(0, 3)
        self.script_list.setObjectName("PlayerRegistryTable")
        self.script_list.setHorizontalHeaderLabels(["Script", "State", "Limit"])
        self.script_list.verticalHeader().setVisible(False)
        self.script_list.verticalHeader().setDefaultSectionSize(24)
        self.script_list.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.script_list.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.script_list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.script_list.setShowGrid(False)
        self.script_list.setCornerButtonEnabled(False)
        self.script_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        hdr = self.script_list.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._refresh_script_list()
        self.script_list.itemSelectionChanged.connect(self._on_script_row)
        left.addWidget(self.script_list)
        hint = QLabel("IronPython 3.4  ·  pure Python only")
        hint.setObjectName("SubtitleLabel")
        left.addWidget(hint)
        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setFixedWidth(300)
        layout.addWidget(left_w)

        right = QVBoxLayout()
        eh = QLabel("EDITOR")
        eh.setObjectName("SectionHeader")
        right.addWidget(eh)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("ScriptEditor")
        self.editor.setTabStopDistance(16 * 4)
        font = QFont("Courier Prime")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(10)
        self.editor.setFont(font)
        self.highlighter = PythonHighlighter(self.editor.document())
        right.addWidget(self.editor, stretch=3)

        controls = QHBoxLayout()
        self.chk_enabled = QCheckBox("Enabled")
        self.chk_enabled.toggled.connect(self._on_enabled_toggled)
        controls.addWidget(self.chk_enabled)

        lim_lbl = QLabel("Time limit")
        lim_lbl.setObjectName("FieldLabel")
        controls.addWidget(lim_lbl)
        self.spin_limit = QSpinBox()
        self.spin_limit.setRange(5, 500)
        self.spin_limit.setSuffix(" ms")
        self.spin_limit.setValue(50)
        self.spin_limit.setMinimumWidth(110)
        self.spin_limit.valueChanged.connect(self._on_limit_changed)
        controls.addWidget(self.spin_limit)
        controls.addStretch()

        self.btn_test = QPushButton("Run / Test")
        self.btn_test.setObjectName("ExecuteButton")
        self.btn_test.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test.clicked.connect(self._on_test_script)
        self.btn_push = QPushButton("Push live (hot-reload)")
        self.btn_push.setObjectName("DangerButton")
        self.btn_push.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_push.clicked.connect(self._on_push_live)
        controls.addWidget(self.btn_test)
        controls.addWidget(self.btn_push)
        right.addLayout(controls)

        oh = QLabel("SCRIPT OUTPUT")
        oh.setObjectName("SectionHeader")
        right.addWidget(oh)
        self.script_out = QTextEdit()
        self.script_out.setObjectName("ConsoleDisplay")
        self.script_out.setReadOnly(True)
        self.script_out.setMinimumHeight(90)
        right.addWidget(self.script_out, stretch=2)

        right_w = QWidget()
        right_w.setLayout(right)
        layout.addWidget(right_w, stretch=1)
        return frame

    def _refresh_script_list(self, keep: str | None = None) -> None:
        keep = keep or (self.current_script.name if self.current_script else None)
        self._suppress_script_change = True
        self.script_list.setRowCount(0)
        select = 0
        for i, s in enumerate(self.scripts):
            self.script_list.insertRow(i)
            state = "ON LIVE" if (s.enabled and s.live) else ("ON" if s.enabled else "OFF")
            color = COLOR_OK if s.enabled else COLOR_DIM
            values = [s.name, state, "{0} ms".format(s.time_limit_ms)]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, s.name)
                item.setForeground(QColor(color if col == 1 else COLOR_TEXT))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if col > 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.script_list.setItem(i, col, item)
            if s.name == keep:
                select = i
        self.script_list.selectRow(select)
        self._suppress_script_change = False

    def _on_script_row(self) -> None:
        if self._suppress_script_change:
            return
        row = self.script_list.currentRow()
        if row < 0 or row >= len(self.scripts):
            return
        self._store_editor()
        self._select_script(self.scripts[row].name, from_list=True)

    def _select_script(self, name: str, from_list: bool = False) -> None:
        script = next((s for s in self.scripts if s.name == name), None)
        if not script:
            return
        self.current_script = script
        if not from_list:
            for i in range(self.script_list.rowCount()):
                item = self.script_list.item(i, 0)
                if item and item.data(Qt.ItemDataRole.UserRole) == name:
                    self._suppress_script_change = True
                    self.script_list.selectRow(i)
                    self._suppress_script_change = False
                    break
        self.editor.setPlainText(script.source)
        self.editor.moveCursor(QTextCursor.MoveOperation.Start)
        self.chk_enabled.blockSignals(True)
        self.chk_enabled.setChecked(script.enabled)
        self.chk_enabled.blockSignals(False)
        self.spin_limit.blockSignals(True)
        self.spin_limit.setValue(script.time_limit_ms)
        self.spin_limit.blockSignals(False)

    def _store_editor(self) -> None:
        if self.current_script is not None:
            self.current_script.source = self.editor.toPlainText()

    def _on_enabled_toggled(self, checked: bool) -> None:
        if not self.current_script:
            return
        self.current_script.enabled = checked
        self._refresh_script_list(self.current_script.name)
        state = "enabled" if checked else "disabled"
        self._script_log("{0} {1}. Push live to apply it on the server.".format(
            self.current_script.name, state
        ), "cyan")

    def _on_limit_changed(self, value: int) -> None:
        if not self.current_script:
            return
        self.current_script.time_limit_ms = value
        self._refresh_script_list(self.current_script.name)

    def _script_log(self, message: str, kind: str = "info") -> None:
        color = {
            "info": COLOR_TEXT,
            "ok": COLOR_OK,
            "fail": COLOR_FAIL,
            "warn": COLOR_WARN,
            "dim": COLOR_DIM,
            "cyan": COLOR_CYAN,
        }.get(kind, COLOR_TEXT)
        html = '<span style="color:{0};">{1}</span>'.format(color, _escape(message))
        self.script_out.append(html)
        self.script_out.moveCursor(QTextCursor.MoveOperation.End)

    def _on_test_script(self) -> None:
        self._store_editor()
        script = self.current_script
        if not script:
            return
        hook = script.hook
        # Default test fixtures
        if hook == "player_joined":
            values = {"name": "KaiVoss", "playfield": "Akua Orbit"}
        elif hook == "player_died":
            values = {"name": "KaiVoss", "cause": "explosion", "playfield": "Akua Orbit"}
        else:
            values = {"name": "Rhea"}
        self._run_script_test(script, hook, values, prefix="TEST")

    def _on_push_live(self) -> None:
        self._store_editor()
        script = self.current_script
        if not script:
            return
        # Confirm is handled by the parent ConfirmDialog when not capturing.
        from .hot_reload_panel import ConfirmDialog

        body = (
            "Push {0} live to Zero-G Reborn (GTX)?\n\n"
            "The script will hot-reload inside the running core. The loader keeps "
            "port 30500 open, and the server does not restart. Enabled: {1}. "
            "Time limit: {2} ms."
        ).format(script.name, "yes" if script.enabled else "no", script.time_limit_ms)
        if not self.capture_mode:
            dlg = ConfirmDialog("Confirm push live", body, "Push live", parent=self)
            if dlg.exec() != dlg.DialogCode.Accepted:
                self._script_log("Push cancelled.", "dim")
                return
        script.live = True
        self._refresh_script_list(script.name)
        self._script_log(
            "Pushed {0} — loader swapped the script, hook {1} re-bound. No restart.".format(
                script.name, script.hook
            ),
            "ok",
        )
        self.footer.setText("Pushed {0} live. Hook {1} is bound. No restart.".format(
            script.name, script.hook
        ))
        self.badge.setText("SCRIPT LIVE")

    def _simulate_event(self, event: str, values: dict) -> str:
        name = values.get("name") or "KaiVoss"
        playfield = values.get("playfield") or "Akua Orbit"
        cause = values.get("cause") or "unknown"
        chat = values.get("message") or ""
        if event == "player_joined":
            detail = "player.Name = {0}\nplayer.Playfield = {1}".format(name, playfield)
        elif event == "player_died":
            detail = "player.Name = {0}\nplayer.Playfield = {1}\nevent.Cause = {2}".format(
                name, playfield, cause
            )
        elif event == "player_left":
            detail = "player.Name = {0}".format(name)
        else:
            detail = "player.Name = {0}\nmessage = {1!r}".format(name, chat)
        ran = 0
        for script in self.scripts:
            if script.hook == event and script.enabled:
                self._run_script_test(script, event, values, prefix="EVENT")
                ran += 1
        extra = "\n{0} enabled script(s) handled this event. See SCRIPT OUTPUT.".format(ran)
        return _sim_header(event, detail) + extra

    def _run_script_test(self, script: Script, event: str, values: dict, prefix: str) -> None:
        name = values.get("name") or "KaiVoss"
        playfield = values.get("playfield") or "Akua Orbit"
        cause = values.get("cause") or "unknown"
        limit = script.time_limit_ms
        elapsed = 4 if "starter" not in script.name else 7
        self._script_log("[{0}] {1}  event={2}  limit={3} ms".format(
            prefix, script.name, event, limit
        ), "cyan")
        if not script.enabled and prefix == "EVENT":
            self._script_log("    skipped (disabled)", "dim")
            return
        # Very small interpreter of the known example scripts, not a real Python eval.
        src = script.source
        if event == "player_joined" and "on_player_joined" in src:
            if "starter_kit" in script.name and "0h" in src:
                self._script_log("    player.Stats.Playtime is 12h — starter kit skipped.", "dim")
            else:
                welcome = "Welcome to Zero-G Reborn, {0}! You are in {1}.".format(name, playfield)
                if "bridge.chat.send" in src:
                    self._script_log("    [bridge.chat.send] global: {0}".format(welcome), "info")
                if "bridge.alerts.send" in src:
                    self._script_log("    [bridge.alerts.send] to={0} title=Welcome".format(name), "info")
                if "log.info" in src:
                    self._script_log("    [log.info] Greeted {0} on join in {1}".format(name, playfield), "ok")
        elif event == "player_died" and "on_player_died" in src:
            msg = "{0} was lost ({1}) in {2}.".format(name, cause, playfield)
            self._script_log("    [bridge.chat.send] faction=Vanguard: {0}".format(msg), "info")
            self._script_log("    [log.info] {0}".format(msg), "ok")
        elif event == "player_left":
            self._script_log("    (no handler body in {0})".format(script.name), "dim")
        elif event == "player_chat":
            self._script_log("    (no handler body in {0})".format(script.name), "dim")
        else:
            self._script_log("    No handler for {0} in {1}.".format(event, script.name), "warn")
        if elapsed > limit:
            self._script_log("[{0}] STOPPED — exceeded {1} ms time limit.".format(prefix, limit), "fail")
        else:
            self._script_log("[{0}] Finished in {1} ms (limit {2} ms). OK".format(
                prefix, elapsed, limit
            ), "ok")

    # ----- capture helpers -------------------------------------------------

    def prepare_catalog_shot(self) -> None:
        self._select_command("Players", "List players")
        self._on_run_command()
        self._select_script("greet_on_join.py")

    def prepare_editor_shot(self) -> None:
        self.splitter.setSizes([200, 620])
        self.script_out.setMaximumHeight(120)
        self.editor.setMinimumHeight(280)
        self._select_script("greet_on_join.py")
        # Clear test noise then run a clean test so the output pane shows the example.
        self.script_out.clear()
        self._script_log("IronPython 3.4 engine ready (mock).", "dim")
        self._on_test_script()
        self.editor.moveCursor(QTextCursor.MoveOperation.Start)
        self.footer.setText("Tested greet_on_join.py against a mock player_joined event. OK in 4 ms.")


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
