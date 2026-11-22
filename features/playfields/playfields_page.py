## ==========================================
## ZERO-G ADMIN HELPER - PLAYFIELDS PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Playfields.jpg:
## the playfield map on top left, BULK ACTIONS (UNLOAD / RESTART PLAYFIELD / WIPE) on top right,
## and a row of playfield cards (name, players, structures) along the bottom.
## Layout only for now: there is no playfield data source yet, so the map and cards show "nothing yet".
## All bulk actions stay greyed out; each one changes the server and gets its own step with Ray's OK.
## Wired (Nov 22, 2026): playfields from the read-only getplayfields:all, players per playfield from plys, and
## structure counts from api:Request_Playfield_Stats. UNLOAD (con:stoppf), RESTART PLAYFIELD (con:stoppf, then
## loadpf:) and WIPE (con:wipe) work on the ticked cards, owner only, through the Safety Flow.
## The star map stays a summary: the bridge does not send sector coordinates.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
                             QCheckBox, QInputDialog)

## Read-only bridge reads and the Safety Flow.
from features.shared import server_actions

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

# endregion


# region Constants

## BULK ACTIONS buttons: (text, CSS object name). Cyan UNLOAD, amber RESTART PLAYFIELD, red WIPE.
BULK_ACTIONS = [
    ("UNLOAD", "DashActionButton"),
    ("RESTART PLAYFIELD", "AlertBanButton"),
    ("WIPE", "ChatWarnButton"),
]

## Action key in server_actions.ACTION_ROLES for each bulk button (all owner only).
BULK_ACTION_KEYS = {"UNLOAD": "playfield_unload", "RESTART PLAYFIELD": "playfield_restart", "WIPE": "playfield_wipe"}

## What the game's wipe command can clear. It takes effect after the next server restart.
WIPE_TARGETS = ["deposit", "poi", "terrain", "player", "all"]

## Most playfield cards shown in the bottom row.
MAX_CARDS = 12

## Seconds RESTART PLAYFIELD waits between stopping and loading, so the old process is gone first.
RESTART_GAP_SEC = 20.0

## Seconds a restarted playfield is asked to stay loaded (loadpf:<name>|<seconds>).
RESTART_KEEP_SEC = 600


## A playfield name for a console line: quoted when it has spaces, with quotes removed.
def console_name(name):
    clean = str(name).replace('"', "").replace("'", "").strip()
    return f'"{clean}"' if " " in clean else clean

# endregion


# region PlayfieldsPage Class

class PlayfieldsPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("PlayfieldsPage")

        ## How many playfield cards are ticked. BULK ACTIONS works on these.
        self.selected_count = 0
        self.bulk_buttons = {}

        ## Read data, the card tick boxes by playfield name, and structure counts by playfield name.
        self.playfields = []
        self.players = []
        self.card_checks = {}
        self.structure_counts = {}
        self.setup_widgets()
        self._wire_live_data()

    def setup_widgets(self):

        ## Top row: map (wide) and bulk actions. Bottom row: the playfield cards across the full width.
        page_grid = QGridLayout(self)
        page_grid.setContentsMargins(4, 4, 4, 4)
        page_grid.setHorizontalSpacing(14)
        page_grid.setVerticalSpacing(14)

        # region Playfield Map

        ## The star map with a marker per playfield gets drawn here in a later step.
        map_card, map_layout = make_card()
        self.map_box = QFrame()
        self.map_box.setObjectName("DashInnerBox")
        map_box_layout = QVBoxLayout(self.map_box)
        self.lbl_map_empty = QLabel("No playfield data yet.")
        self.lbl_map_empty.setObjectName("DashEmptyLabel")
        self.lbl_map_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        map_box_layout.addWidget(self.lbl_map_empty)
        map_layout.addWidget(self.map_box, stretch=1)
        page_grid.addWidget(map_card, 0, 0)

        # endregion

        # region Bulk Actions

        ## The title shows how many cards are ticked, e.g. "BULK ACTIONS (2 SELECTED)".
        bulk_card, bulk_layout = make_card(self._bulk_title())
        self.lbl_bulk_title = bulk_card.findChild(QLabel, "DashCardTitle")
        bulk_layout.setSpacing(12)
        for action_text, action_style in BULK_ACTIONS:
            btn_bulk = QPushButton(action_text)
            btn_bulk.setObjectName(action_style)
            btn_bulk.setMinimumHeight(54)
            btn_bulk.setEnabled(False)
            btn_bulk.setToolTip("Tick one or more playfield cards first.")
            spread_letters(btn_bulk, 1.5)
            bulk_layout.addWidget(btn_bulk)
            self.bulk_buttons[action_text] = btn_bulk
        bulk_layout.addStretch()
        page_grid.addWidget(bulk_card, 0, 1)

        # endregion

        # region Playfield Cards

        ## One small card per playfield goes in this row: tick box, name, players and a structures bar.
        cards_card, cards_layout = make_card("PLAYFIELDS")
        self.cards_row = QHBoxLayout()
        self.cards_row.setSpacing(14)
        self.lbl_cards_empty = QLabel("No playfields loaded yet.")
        self.lbl_cards_empty.setObjectName("DashEmptyLabel")
        self.cards_row.addWidget(self.lbl_cards_empty)
        self.cards_row.addStretch()
        cards_layout.addLayout(self.cards_row)
        cards_layout.addStretch()
        page_grid.addWidget(cards_card, 1, 0, 1, 2)

        # endregion

        ## Column widths roughly match the mockup: 5 : 2.
        page_grid.setColumnStretch(0, 5)
        page_grid.setColumnStretch(1, 2)

        ## The map row is taller than the cards row.
        page_grid.setRowStretch(0, 3)
        page_grid.setRowStretch(1, 2)

    ## Title text for the BULK ACTIONS card, with the current selected count.
    def _bulk_title(self):
        return f"BULK ACTIONS ({self.selected_count} SELECTED)"

    # endregion

    # region Live Data

    def _wire_live_data(self):
        try:
            self.bulk_buttons["UNLOAD"].clicked.connect(self._on_unload_clicked)
            self.bulk_buttons["RESTART PLAYFIELD"].clicked.connect(self._on_restart_clicked)
            self.bulk_buttons["WIPE"].clicked.connect(self._on_wipe_clicked)
        except Exception as e:
            print(f"[ERROR] PlayfieldsPage: Could not wire live data: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        try:
            self.refresh_live()
        except Exception as e:
            print(f"[ERROR] PlayfieldsPage: Refresh on show failed: {e}")

    def refresh_live(self):
        try:
            if not server_actions.bridge_is_connected(self):
                self.lbl_map_empty.setText("Connect to the server to see playfields.")
                return
            server_actions.read_bridge("getplayfields:all", ("PLAYFIELD_LIST", "ERROR"), self._on_playfields_read,
                                       lambda message: print(f"[ERROR] PlayfieldsPage: getplayfields failed: {message}"))
            server_actions.read_bridge("plys", "PLAYER_CACHE", self._on_players_read,
                                       lambda message: print(f"[ERROR] PlayfieldsPage: plys failed: {message}"))
        except Exception as e:
            print(f"[ERROR] PlayfieldsPage: Refresh failed: {e}")

    def _on_playfields_read(self, reply):
        try:
            self.playfields = [row for row in ((reply or {}).get("playfields") or []) if isinstance(row, dict) and row.get("name")]
            for row in self.loaded_playfields()[:MAX_CARDS]:
                name = str(row["name"])
                server_actions.read_bridge(server_actions.api_command("Request_Playfield_Stats", {"pstr": name}), ("API_RESULT", "ERROR"),
                                           lambda answer, pf_name=name: self._on_stats_read(pf_name, answer), lambda message: None)
            self.show_playfields()
        except Exception as e:
            print(f"[ERROR] PlayfieldsPage: Could not read playfields: {e}")

    def _on_players_read(self, reply):
        try:
            self.players = [row for row in ((reply or {}).get("player_list") or []) if isinstance(row, dict)]
            self.show_playfields()
        except Exception as e:
            print(f"[ERROR] PlayfieldsPage: Could not read players: {e}")

    def _on_stats_read(self, playfield_name, reply):
        try:
            data = (reply or {}).get("data") or {}
            for key in ("structs", "structures", "structureCount"):
                if isinstance(data.get(key), int):
                    self.structure_counts[playfield_name] = data[key]
                    break
            self.show_playfields()
        except Exception as e:
            print(f"[ERROR] PlayfieldsPage: Could not read stats: {e}")

    def loaded_playfields(self):
        seen = set()
        loaded = []
        for row in self.playfields:
            if row.get("loaded") and str(row["name"]).lower() not in seen:
                seen.add(str(row["name"]).lower())
                loaded.append(row)
        return sorted(loaded, key=lambda row: str(row["name"]).lower())

    def players_on(self, playfield_name):
        return sum(1 for row in self.players if row.get("status") == "Online" and str(row.get("playfield", "")).lower() == playfield_name.lower())

    def show_playfields(self):
        """Redraws the summary and the cards, keeping the ticks."""
        try:
            ticked = set(self.selected_names())
            loaded = self.loaded_playfields()
            known = len({str(row["name"]).lower() for row in self.playfields})
            with_players = sum(1 for row in loaded if self.players_on(str(row["name"])))
            self.lbl_map_empty.setText(f"{known:,} known playfields   ·   {len(loaded)} loaded   ·   {with_players} with players online\n\n"
                                       "The star map needs sector coordinates, which the bridge does not send." if self.playfields else "No playfield data yet.")
            while self.cards_row.count():
                old_item = self.cards_row.takeAt(0)
                if old_item.widget() is not None and old_item.widget() is not self.lbl_cards_empty:
                    old_item.widget().deleteLater()
            self.card_checks = {}
            for row in loaded[:MAX_CARDS]:
                name = str(row["name"])
                card = QFrame()
                card.setObjectName("DashInnerBox")
                card_layout = QVBoxLayout(card)
                chk_card = QCheckBox(name)
                chk_card.setChecked(name in ticked)
                chk_card.toggled.connect(lambda checked: self._refresh_bulk())
                card_layout.addWidget(chk_card)
                structures = self.structure_counts.get(name)
                lbl_card = QLabel(f"{row.get('playfieldType', '')}\nPLAYERS:  {self.players_on(name)}\nSTRUCTURES:  {'--' if structures is None else structures}")
                lbl_card.setObjectName("FactionInfoLabel")
                card_layout.addWidget(lbl_card)
                self.cards_row.addWidget(card)
                self.card_checks[name] = chk_card
            if len(loaded) > MAX_CARDS:
                lbl_more = QLabel(f"+{len(loaded) - MAX_CARDS} more loaded")
                lbl_more.setObjectName("DashEmptyLabel")
                self.cards_row.addWidget(lbl_more)
            self.cards_row.addWidget(self.lbl_cards_empty)
            self.lbl_cards_empty.setVisible(not loaded)
            self.cards_row.addStretch()
            self._refresh_bulk()
        except Exception as e:
            print(f"[ERROR] PlayfieldsPage: Could not show playfields: {e}")

    def selected_names(self):
        return [name for name, chk_card in self.card_checks.items() if chk_card.isChecked()]

    def _refresh_bulk(self):
        try:
            self.selected_count = len(self.selected_names())
            if self.lbl_bulk_title is not None:
                self.lbl_bulk_title.setText(self._bulk_title())
            for action_text, btn_bulk in self.bulk_buttons.items():
                reason = server_actions.block_reason(self, BULK_ACTION_KEYS[action_text]) or ("" if self.selected_count else "Tick one or more playfield cards first.")
                btn_bulk.setEnabled(reason == "")
                btn_bulk.setToolTip(reason or {"UNLOAD": "Stops the ticked playfields (players on them are moved out by the game).",
                                               "RESTART PLAYFIELD": "Stops, then loads the ticked playfields again.",
                                               "WIPE": "Marks parts of the ticked playfields to be wiped at the next server restart."}[action_text])
        except Exception as e:
            print(f"[ERROR] PlayfieldsPage: Could not refresh bulk actions: {e}")

    # endregion

    # region Bulk Actions

    def _after_bulk(self, label):
        def done(ok, reply):
            print(f"[{'SUCCESS' if ok else 'ERROR'}] PlayfieldsPage: {label}: {server_actions.reply_text(reply)}")
            self.refresh_live()
        return done

    def _who_is_on(self, names):
        count = sum(self.players_on(name) for name in names)
        return f" {count} player(s) online on them now." if count else " Nobody is online on them now."

    def _on_unload_clicked(self):
        try:
            names = self.selected_names()
            if not names:
                return
            server_actions.run_server_action(self, "playfield_unload", "Unload playfields",
                                             [f"con:stoppf {console_name(name)}" for name in names], self._after_bulk("Unload"),
                                             explanation="Stops: " + ", ".join(names) + "." + self._who_is_on(names))
        except Exception as e:
            print(f"[ERROR] PlayfieldsPage: Unload failed: {e}")

    def _on_restart_clicked(self):
        try:
            names = self.selected_names()
            if not names:
                return
            commands = []
            for name in names:
                commands.append(f"con:stoppf {console_name(name)}")
                commands.append(f"loadpf:{name}|{RESTART_KEEP_SEC}")
            server_actions.run_server_action(self, "playfield_restart", "Restart playfields", commands, self._after_bulk("Restart"),
                                             explanation=f"Stops, waits {int(RESTART_GAP_SEC)} s, and loads again: " + ", ".join(names) + "."
                                                         + self._who_is_on(names), gap_sec=RESTART_GAP_SEC)
        except Exception as e:
            print(f"[ERROR] PlayfieldsPage: Restart failed: {e}")

    def _on_wipe_clicked(self):
        try:
            names = self.selected_names()
            if not names:
                return
            target, accepted = QInputDialog.getItem(self, "Wipe", "What to wipe (applies after the next server restart):", WIPE_TARGETS, 0, False)
            if not accepted or target not in WIPE_TARGETS:
                return
            server_actions.run_server_action(self, "playfield_wipe", "Wipe playfields",
                                             [f"con:wipe {console_name(name)} {target}" for name in names], self._after_bulk("Wipe"),
                                             explanation=f"Wipes '{target}' on: " + ", ".join(names) + ". The game applies it at the next server restart; ZAH does not restart anything.")
        except Exception as e:
            print(f"[ERROR] PlayfieldsPage: Wipe failed: {e}")

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return PlayfieldsPage()

# endregion
