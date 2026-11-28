## ==========================================
## ZERO-G ADMIN HELPER - DASHBOARD PAGE
## The page ZAH always lands on. Layout follows .scratchpad/.conceptual/Concept_11-17/Dashboard.jpg:
## top row PLAYERS / ACTIVE ALERTS / UPTIME cards, then NEEDS ATTENTION and ONLINE PLAYERS,
## then RECENT EVENTS and QUICK ACTIONS.
## First version: only real data is shown. Anything without a data source yet shows "--" or "Nothing yet".
## QUICK ACTIONS stay greyed out; SAVE and BACKUP are real server actions and get their own step later.
## Wired (Nov 22, 2026): PLAYERS and ONLINE PLAYERS from plys, UPTIME from api:Request_Dedi_Stats, ACTIVE ALERTS
## and NEEDS ATTENTION from the plys cheat flags (all read-only, every 15 s while open). ANNOUNCE sends
## api:Request_InGameMessage_AllPlayers through the Safety Flow. SAVE and BACKUP stay off (see SAVE_TIP and BACKUP_TIP).
## ==========================================

# region Imports

from datetime import datetime
from typing import Any

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
                             QTableWidget, QHeaderView, QAbstractItemView, QTableWidgetItem, QInputDialog)

## Read-only bridge reads and the Safety Flow for ANNOUNCE.
from features.shared import server_actions

## Qt calls that may return None, wrapped once.
from features.shared.qt_types import horizontal_header, vertical_header, layout_item_widget

# endregion


# region Constants

## Columns of the ONLINE PLAYERS table, as in the mockup.
PLAYER_COLUMNS = ["NAME", "FACTION", "PLAYFIELD", "PING"]

## How many lines RECENT EVENTS keeps. Older lines drop off the bottom.
RECENT_EVENT_LIMIT = 6

## The three QUICK ACTIONS buttons, in mockup order.
QUICK_ACTIONS = ["ANNOUNCE", "SAVE", "BACKUP"]

## Why SAVE and BACKUP stay off.
SAVE_TIP = "Not possible from the bridge: the game has no save-only command (it autosaves; saveandexit stops the server)."
BACKUP_TIP = "Not possible while the server runs: a safe backup needs the server stopped (that is a restart)."

## Seconds between read-only refreshes while the page is open.
REFRESH_SEC = 15


## True when plys marks a player as cheating (cheat on, or flagged as a cheater).
def is_flagged(player):
    return str(player.get("cheat", "Off")).lower() not in ("off", "", "--") or str(player.get("cheater", "No")).lower() == "yes"


## "3d 04h 12m" style text from seconds.
def format_uptime(seconds):
    seconds = int(max(0, seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    return f"{days}d {hours:02d}h {rest // 60:02d}m" if days else f"{hours:02d}h {rest // 60:02d}m"

# endregion


# region Helpers

## Qt stylesheets can't set letter-spacing, so the wide uppercase look is set on the font here.
def spread_letters(widget, spacing_px):
    widget_font = widget.font()
    widget_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing_px)
    widget.setFont(widget_font)

## One rounded navy glass card with an optional title, styled by DashCard in ZAH_main.css.
## Returns (card, layout) so the caller can add its own widgets under the title.
## The card is typed Any because pages hang their own attributes on it (e.g. the server cards).
def make_card(title_text="") -> tuple[Any, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("DashCard")
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(18, 14, 18, 14)
    card_layout.setSpacing(8)
    if title_text:
        lbl_title = QLabel(title_text)
        lbl_title.setObjectName("DashCardTitle")
        spread_letters(lbl_title, 1.5)
        card_layout.addWidget(lbl_title)
    return card, card_layout

# endregion


# region DashboardPage Class

class DashboardPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("DashboardPage")

        ## True once this page is listening to the cockpit's bridge_status_changed signal.
        self.is_listening = False

        ## The last bridge state written to RECENT EVENTS, so the same news isn't added twice.
        self.last_bridge_state = None
        self.setup_widgets()
        self._wire_live_data()

    def setup_widgets(self):

        ## The page is a 3-row grid. Row 0 has three equal cards; rows 1 and 2 have two cards each.
        page_grid = QGridLayout(self)
        page_grid.setContentsMargins(4, 4, 4, 4)
        page_grid.setHorizontalSpacing(14)
        page_grid.setVerticalSpacing(14)

        # region Stat Cards

        ## Top row: big value with a small coloured label under it. 6 grid columns, 2 per card.
        self.lbl_players_value, players_card = self._make_stat_card("-- / --", "PLAYERS", "DashStatLabel")
        self.lbl_alerts_value, alerts_card = self._make_stat_card("--", "ACTIVE ALERTS", "DashStatLabelAlert")
        self.lbl_uptime_value, uptime_card = self._make_stat_card("--", "UPTIME", "DashStatLabel", label_first=True)
        page_grid.addWidget(players_card, 0, 0, 1, 2)
        page_grid.addWidget(alerts_card, 0, 2, 1, 2)
        page_grid.addWidget(uptime_card, 0, 4, 1, 2)

        # endregion

        # region Needs Attention

        ## Alert cards with an ACK button go here once ALERTS & ANTI-CHEAT has data.
        attention_card, attention_layout = make_card("NEEDS ATTENTION")
        self.lbl_attention_empty = QLabel("Nothing needs attention yet.")
        self.lbl_attention_empty.setObjectName("DashEmptyLabel")
        attention_layout.addWidget(self.lbl_attention_empty)
        attention_layout.addStretch()
        page_grid.addWidget(attention_card, 1, 0, 1, 3)

        # endregion

        # region Online Players

        ## The table has the mockup's columns. Rows get filled once the bridge sends the player list.
        players_card, players_layout = make_card("ONLINE PLAYERS")
        self.tbl_players = QTableWidget(0, len(PLAYER_COLUMNS))
        self.tbl_players.setObjectName("DashTable")
        self.tbl_players.setHorizontalHeaderLabels(PLAYER_COLUMNS)
        vertical_header(self.tbl_players).setVisible(False)
        self.tbl_players.setShowGrid(False)
        self.tbl_players.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_players.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        horizontal_header(self.tbl_players).setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        players_layout.addWidget(self.tbl_players)
        self.lbl_players_empty = QLabel("No player data yet.")
        self.lbl_players_empty.setObjectName("DashEmptyLabel")
        players_layout.addWidget(self.lbl_players_empty)
        page_grid.addWidget(players_card, 1, 3, 1, 3)

        # endregion

        # region Recent Events

        ## Newest first, with the local time. For now it lists ZAH's own news, like the bridge connecting.
        events_card, events_layout = make_card("RECENT EVENTS")
        self.events_box = QFrame()
        self.events_box.setObjectName("DashInnerBox")
        self.events_box_layout = QVBoxLayout(self.events_box)
        self.events_box_layout.setContentsMargins(12, 8, 12, 8)
        self.events_box_layout.setSpacing(4)
        self.events_box_layout.addStretch()
        events_layout.addWidget(self.events_box)
        page_grid.addWidget(events_card, 2, 0, 1, 3)

        # endregion

        # region Quick Actions

        ## Big outlined buttons, greyed out until each one is built and approved in its own step.
        actions_card, actions_layout = make_card("QUICK ACTIONS")
        action_row = QHBoxLayout()
        action_row.setSpacing(14)
        self.quick_action_buttons = []
        for action_text in QUICK_ACTIONS:
            btn_action = QPushButton(action_text)
            btn_action.setObjectName("DashActionButton")
            btn_action.setMinimumHeight(64)
            btn_action.setEnabled(False)
            btn_action.setToolTip("Coming in a later step.")
            spread_letters(btn_action, 2.0)
            action_row.addWidget(btn_action)
            self.quick_action_buttons.append(btn_action)
        actions_layout.addLayout(action_row)
        actions_layout.addStretch()
        page_grid.addWidget(actions_card, 2, 3, 1, 3)

        # endregion

        ## The stat row stays short; the two lower rows share the rest of the height.
        page_grid.setRowStretch(0, 0)
        page_grid.setRowStretch(1, 3)
        page_grid.setRowStretch(2, 2)

        ## The first event is ZAH opening this page.
        self.add_event("DASHBOARD OPENED")

    ## Builds one top-row card. Returns (value_label, card) so the value can be updated later.
    ## label_first puts the small label above the value, like UPTIME in the mockup.
    def _make_stat_card(self, value_text, label_text, label_name, label_first=False):
        card, card_layout = make_card()
        lbl_value = QLabel(value_text)
        lbl_value.setObjectName("DashStatValue")
        lbl_label = QLabel(label_text)
        lbl_label.setObjectName(label_name)
        spread_letters(lbl_label, 1.5)
        if label_first:
            card_layout.addWidget(lbl_label)
            card_layout.addWidget(lbl_value)
        else:
            card_layout.addWidget(lbl_value)
            card_layout.addWidget(lbl_label)
        card_layout.addStretch()
        return lbl_value, card

    # endregion


    # region Live Updates

    ## Qt calls showEvent each time the page appears.
    def showEvent(self, event):
        super().showEvent(event)
        self.setup_listening()
        self.refresh_status()
        self.refresh_live()

    ## Connects to the cockpit's signal once, so the page updates live while it is open.
    ## Qt drops the link by itself when this page is closed and deleted.
    def setup_listening(self):
        if self.is_listening:
            return
        cockpit = self.window()
        signal = getattr(cockpit, "bridge_status_changed", None)
        if signal is None:
            return
        signal.connect(self._on_bridge_status_changed)
        self.is_listening = True

    ## Reads the bridge state from the cockpit and adds a RECENT EVENTS line when it changes.
    ## Fails closed: no bridge news means no line, never a guess.
    def refresh_status(self):
        try:
            cockpit = self.window()
            server_name = getattr(cockpit, "bridge_server_name", None)
            is_connected = getattr(cockpit, "bridge_connected", None)
            if server_name is None or is_connected is None:
                return
            bridge_state = (str(server_name), bool(is_connected))
            if bridge_state == self.last_bridge_state:
                return
            self.last_bridge_state = bridge_state
            state_text = "BRIDGE CONNECTED" if is_connected else "BRIDGE DISCONNECTED"
            self.add_event(f"{state_text} ({str(server_name).upper()})")
        except Exception as e:
            print(f"[ERROR] DashboardPage: Failed to refresh status: {e}")

    ## Runs every time the cockpit sends bridge_status_changed.
    def _on_bridge_status_changed(self, server_name, is_connected):
        self.refresh_status()
        self.refresh_live()

    def _wire_live_data(self):
        """ANNOUNCE, the two off buttons, and the read-only refresh timer."""
        try:
            self.quick_action_buttons[0].clicked.connect(self._on_announce_clicked)
            self.quick_action_buttons[1].setToolTip(SAVE_TIP)
            self.quick_action_buttons[2].setToolTip(BACKUP_TIP)
            self.refresh_timer = QTimer(self)
            self.refresh_timer.setInterval(REFRESH_SEC * 1000)
            self.refresh_timer.timeout.connect(self.refresh_live)
        except Exception as e:
            print(f"[ERROR] DashboardPage: Could not wire live data: {e}")

    def hideEvent(self, event):
        super().hideEvent(event)
        try:
            self.refresh_timer.stop()
        except Exception:
            pass

    def refresh_live(self):
        """Reads plys and dedistats (both read-only) and sets ANNOUNCE for the signed-in role."""
        try:
            if not self.refresh_timer.isActive():
                self.refresh_timer.start()
            reason = server_actions.block_reason(self, "announce")
            self.quick_action_buttons[0].setEnabled(reason == "")
            self.quick_action_buttons[0].setToolTip(reason or "HUD message to every player (Safety Flow).")
            if not server_actions.bridge_is_connected(self):
                return
            server_actions.read_bridge_many([
                ("plys", "PLAYER_CACHE", self._on_players_read, lambda message: None),
                ("api:Request_Dedi_Stats", ("API_RESULT", "ERROR"), self._on_stats_read, lambda message: None)])
        except Exception as e:
            print(f"[ERROR] DashboardPage: Live refresh failed: {e}")

    def _on_players_read(self, reply):
        try:
            rows = [row for row in (reply or {}).get("player_list") or [] if isinstance(row, dict)]
            online = [row for row in rows if str(row.get("status")) == "Online"]
            self.lbl_players_value.setText(f"{len(online)} / {len(rows)}")
            self.tbl_players.setRowCount(len(online))
            for row_number, player in enumerate(online):
                for column, key in enumerate(("name", "faction", "playfield", "ping")):
                    self.tbl_players.setItem(row_number, column, QTableWidgetItem(str(player.get(key, "--"))))
            self.lbl_players_empty.setVisible(not online)
            self.lbl_players_empty.setText("Nobody is online." if not online else "")
            flagged = [row for row in rows if is_flagged(row)]
            self.lbl_alerts_value.setText(str(len(flagged)))
            self.lbl_attention_empty.setText("\n".join(f"CHEAT FLAG: {row.get('name', '?')} ({row.get('playfield', '--')})"
                                                       for row in flagged[:6]) or "Nothing needs attention.")
            update_badge = getattr(self.window(), "update_alert_badge", None)
            if callable(update_badge):
                update_badge(len(flagged))
        except Exception as e:
            print(f"[ERROR] DashboardPage: Could not show players: {e}")

    def _on_stats_read(self, reply):
        try:
            stats = reply.get("data") if isinstance(reply, dict) and reply.get("status") == "ok" else None
            if isinstance(stats, dict) and stats.get("uptime") is not None:
                self.lbl_uptime_value.setText(format_uptime(float(stats["uptime"])))
        except Exception as e:
            print(f"[ERROR] DashboardPage: Could not show uptime: {e}")

    def _on_announce_clicked(self):
        try:
            text, accepted = QInputDialog.getText(self, "Announce", "HUD message to every player:")
            text = text.strip()
            if not accepted or not text:
                return
            server_actions.run_server_action(
                self, "announce", "Announce to every player", server_actions.message_all_command(text),
                lambda ok, reply: self.add_event(f"ANNOUNCE {'SENT' if ok else 'FAILED'}: {text[:40]}"))
        except Exception as e:
            print(f"[ERROR] DashboardPage: Announce failed: {e}")

    ## Adds one line to the top of RECENT EVENTS, e.g. "03:10:22 - BRIDGE CONNECTED".
    def add_event(self, event_text):
        try:
            lbl_event = QLabel(f"{datetime.now().strftime('%H:%M:%S')}  -  {event_text}")
            lbl_event.setObjectName("DashEventLabel")
            self.events_box_layout.insertWidget(0, lbl_event)

            ## The layout holds the event labels plus one stretch at the end, so count only the labels.
            while self.events_box_layout.count() - 1 > RECENT_EVENT_LIMIT:
                oldest_item = self.events_box_layout.takeAt(self.events_box_layout.count() - 2)
                old_widget = layout_item_widget(oldest_item)
                if old_widget is not None:
                    old_widget.deleteLater()
        except Exception as e:
            print(f"[ERROR] DashboardPage: Could not add event: {e}")

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return DashboardPage()

# endregion
