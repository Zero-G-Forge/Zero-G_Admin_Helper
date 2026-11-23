## ==========================================
## ZERO-G ADMIN HELPER - FACTIONS PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Factions.jpg:
## FACTION LIST on the left, FACTION DETAIL with its member table in the middle,
## RELATIONS with SET RELATION and RENAME on the right.
## Layout only for now: there is no faction data source yet, so everything shows "--" or "nothing yet".
## SET RELATION and RENAME stay greyed out; both change the server and get their own step with Ray's OK.
## Wired (Nov 22, 2026), read-only: factions from api:Request_Get_Factions, members from plys,
## alliances from api:Request_AlliancesAll. SET RELATION and RENAME stay off (see RELATION_TIP and RENAME_TIP).
## Nov 23, 2026: members are matched by factionId (the plys faction tag can be a leftover name).
## Club ranks come from plys role (IPlayer.FactionRole). Founder is shown as Owner. Unknown
## roles show "--" rather than a default Member. Request_Player_Info is rejected for offline
## players, so a rank is only known after the player has been seen online.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QGridLayout, QPushButton,
                             QTableWidget, QHeaderView, QAbstractItemView, QListWidget, QListWidgetItem,
                             QTableWidgetItem)

## Read-only bridge reads.
from features.shared import server_actions
from features.shared.faction_display import format_faction_role

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

# endregion


# region Constants

## Columns of the member table in FACTION DETAIL, as in the mockup.
MEMBER_COLUMNS = ["NAME", "ROLE", "STATUS"]

## Buttons under RELATIONS, in mockup order.
FACTION_ACTIONS = ["SET RELATION", "RENAME"]

## Why both buttons stay off.
RELATION_TIP = "Not possible from the server: the game's alliances command only works in a player's own console, and the mod API has no request to change relations."
RENAME_TIP = "Not possible from the server: the mod API and the server console have no command to rename a faction."


## Eleon packs one alliance as two faction ids in one number: (first << 16) | second.
def decode_alliance(value):
    try:
        if isinstance(value, dict):
            return int(value.get("faction1") or value.get("factionId1") or 0), int(value.get("faction2") or value.get("factionId2") or 0)
        number = int(value)
        return number >> 16, number & 0xFFFF
    except (TypeError, ValueError):
        return 0, 0

# endregion


# region FactionsPage Class

class FactionsPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("FactionsPage")

        ## Read data: faction rows, player rows and alliance pairs.
        self.factions = []
        self.players = []
        self.alliances = []
        self.setup_widgets()
        self._wire_live_data()

    def setup_widgets(self):

        ## 3 equal columns, one card each.
        page_grid = QGridLayout(self)
        page_grid.setContentsMargins(4, 4, 4, 4)
        page_grid.setHorizontalSpacing(14)
        page_grid.setVerticalSpacing(14)

        # region Faction List

        ## Each faction will be a row with its emblem, name, member count and a coloured bar.
        list_card, list_layout = make_card("FACTION LIST")
        self.faction_box = QFrame()
        self.faction_box.setObjectName("DashInnerBox")
        self.faction_box_layout = QVBoxLayout(self.faction_box)
        self.faction_box_layout.setContentsMargins(12, 8, 12, 8)
        self.lbl_factions_empty = QLabel("No faction data yet.")
        self.lbl_factions_empty.setObjectName("DashEmptyLabel")
        self.faction_box_layout.addWidget(self.lbl_factions_empty)
        self.lst_factions = QListWidget()
        self.lst_factions.setObjectName("FactionList")
        self.lst_factions.setStyleSheet("QListWidget#FactionList { background: transparent; border: none; color: #d8e6f0; }")
        self.faction_box_layout.addWidget(self.lst_factions, stretch=1)
        self.faction_box_layout.addStretch()
        list_layout.addWidget(self.faction_box, stretch=1)
        page_grid.addWidget(list_card, 0, 0)

        # endregion

        # region Faction Detail

        ## Centred name, origin and founded lines, then the member table.
        detail_card, detail_layout = make_card("FACTION DETAIL")
        detail_layout.addStretch(1)
        self.lbl_faction_name = QLabel("NO FACTION SELECTED")
        self.lbl_faction_name.setObjectName("FactionNameLabel")
        self.lbl_faction_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        spread_letters(self.lbl_faction_name, 1.5)
        detail_layout.addWidget(self.lbl_faction_name)
        self.lbl_faction_origin = QLabel("ORIGIN:  --")
        self.lbl_faction_founded = QLabel("FOUNDED:  --")
        for lbl_info in (self.lbl_faction_origin, self.lbl_faction_founded):
            lbl_info.setObjectName("FactionInfoLabel")
            lbl_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
            detail_layout.addWidget(lbl_info)
        detail_layout.addStretch(1)

        self.tbl_members = QTableWidget(0, len(MEMBER_COLUMNS))
        self.tbl_members.setObjectName("DashTable")
        self.tbl_members.setHorizontalHeaderLabels(MEMBER_COLUMNS)
        self.tbl_members.verticalHeader().setVisible(False)
        self.tbl_members.setShowGrid(False)
        self.tbl_members.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_members.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tbl_members.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        detail_layout.addWidget(self.tbl_members, stretch=2)
        page_grid.addWidget(detail_card, 0, 1)

        # endregion

        # region Relations

        ## Each relation will be a row with the other faction and an ALLIED / NEUTRAL / HOSTILE badge.
        relations_card, relations_layout = make_card("RELATIONS")
        self.relations_box = QFrame()
        self.relations_box.setObjectName("DashInnerBox")
        self.relations_box_layout = QVBoxLayout(self.relations_box)
        self.relations_box_layout.setContentsMargins(12, 8, 12, 8)
        self.lbl_relations_empty = QLabel("Pick a faction to see its relations.")
        self.lbl_relations_empty.setObjectName("DashEmptyLabel")
        self.relations_box_layout.addWidget(self.lbl_relations_empty)
        self.relations_rows_layout = QVBoxLayout()
        self.relations_box_layout.addLayout(self.relations_rows_layout)
        self.relations_box_layout.addStretch()
        relations_layout.addWidget(self.relations_box, stretch=1)

        ## Wide outlined cyan buttons at the bottom, greyed out for now.
        self.action_buttons = []
        for action_text in FACTION_ACTIONS:
            btn_action = QPushButton(action_text)
            btn_action.setObjectName("DashActionButton")
            btn_action.setMinimumHeight(44)
            btn_action.setEnabled(False)
            btn_action.setToolTip(RELATION_TIP if action_text == "SET RELATION" else RENAME_TIP)
            spread_letters(btn_action, 1.5)
            relations_layout.addWidget(btn_action)
            self.action_buttons.append(btn_action)
        page_grid.addWidget(relations_card, 0, 2)

        # endregion

        ## Equal column widths, like the mockup.
        for column_index in range(3):
            page_grid.setColumnStretch(column_index, 1)

    # endregion

    # region Live Data

    def _wire_live_data(self):
        try:
            self.lst_factions.itemSelectionChanged.connect(self.show_detail)
        except Exception as e:
            print(f"[ERROR] FactionsPage: Could not wire live data: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        try:
            self.refresh_live()
        except Exception as e:
            print(f"[ERROR] FactionsPage: Refresh on show failed: {e}")

    def refresh_live(self):
        """Three read-only reads; each answer redraws what it fills."""
        try:
            if not server_actions.bridge_is_connected(self):
                self.lbl_factions_empty.setText("Connect to the server to see factions.")
                return
            server_actions.read_bridge('api:Request_Get_Factions {"id":1}', ("API_RESULT", "ERROR"), self._on_factions_read,
                                       lambda message: print(f"[ERROR] FactionsPage: Factions read failed: {message}"))
            server_actions.read_bridge("plys", "PLAYER_CACHE", self._on_players_read,
                                       lambda message: print(f"[ERROR] FactionsPage: plys failed: {message}"))
            server_actions.read_bridge("api:Request_AlliancesAll", ("API_RESULT", "ERROR"), self._on_alliances_read,
                                       lambda message: print(f"[ERROR] FactionsPage: Alliances read failed: {message}"))
        except Exception as e:
            print(f"[ERROR] FactionsPage: Refresh failed: {e}")

    def _on_factions_read(self, reply):
        try:
            data = (reply or {}).get("data") or {}
            self.factions = [row for row in (data.get("factions") or []) if isinstance(row, dict)]
            self.show_factions()
        except Exception as e:
            print(f"[ERROR] FactionsPage: Could not read factions: {e}")

    def _on_players_read(self, reply):
        try:
            self.players = [row for row in ((reply or {}).get("player_list") or []) if isinstance(row, dict)]
            self.show_factions()
        except Exception as e:
            print(f"[ERROR] FactionsPage: Could not read players: {e}")

    def _on_alliances_read(self, reply):
        try:
            data = (reply or {}).get("data") or {}
            pairs = [decode_alliance(value) for value in (data.get("alliances") or [])]
            self.alliances = [pair for pair in pairs if pair[0] and pair[1]]
            self.show_detail()
        except Exception as e:
            print(f"[ERROR] FactionsPage: Could not read alliances: {e}")

    def members_of(self, faction_id):
        """Players whose plys factionId is this faction. The leftover faction tag is not used."""
        return [row for row in self.players if str(row.get("factionId")) == str(faction_id)]

    def faction_name(self, faction_id):
        for row in self.factions:
            if str(row.get("factionId")) == str(faction_id):
                return str(row.get("name", faction_id))
        return f"Faction {faction_id}"

    def show_factions(self):
        try:
            picked = self._picked_faction()
            self.lst_factions.blockSignals(True)
            self.lst_factions.clear()
            for row in sorted(self.factions, key=lambda faction: str(faction.get("name", "")).lower()):
                item = QListWidgetItem(f"{row.get('name', '?')}  [{row.get('abbrev', '')}]   {len(self.members_of(row.get('factionId')))} members")
                item.setData(Qt.ItemDataRole.UserRole, row)
                self.lst_factions.addItem(item)
                if picked is not None and row.get("factionId") == picked.get("factionId"):
                    item.setSelected(True)
            self.lst_factions.blockSignals(False)
            self.lbl_factions_empty.setVisible(not self.factions)
            if not self.factions:
                self.lbl_factions_empty.setText("No faction data yet.")
            self.show_detail()
        except Exception as e:
            print(f"[ERROR] FactionsPage: Could not show factions: {e}")

    def _picked_faction(self):
        items = self.lst_factions.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else None

    def show_detail(self):
        """Fills FACTION DETAIL and RELATIONS for the picked faction."""
        try:
            while self.relations_rows_layout.count():
                old_item = self.relations_rows_layout.takeAt(0)
                if old_item.widget() is not None:
                    old_item.widget().deleteLater()
            faction = self._picked_faction()
            self.tbl_members.setRowCount(0)
            if faction is None:
                self.lbl_faction_name.setText("NO FACTION SELECTED")
                self.lbl_faction_origin.setText("ORIGIN:  --")
                self.lbl_relations_empty.setText("Pick a faction to see its relations.")
                self.lbl_relations_empty.setVisible(True)
                return
            faction_id = faction.get("factionId")
            self.lbl_faction_name.setText(f"{str(faction.get('name', '?')).upper()}  [{faction.get('abbrev', '')}]")
            self.lbl_faction_origin.setText(f"ORIGIN:  {self.faction_name(faction.get('origin'))}   ·   ID {faction_id}")

            ## The game does not report a founding date, so FOUNDED stays "--".
            self.lbl_faction_founded.setText("FOUNDED:  --")
            for member in sorted(self.members_of(faction_id), key=lambda row: (row.get("status") != "Online", str(row.get("name", "")).lower())):
                row_index = self.tbl_members.rowCount()
                self.tbl_members.insertRow(row_index)
                for column_index, value in enumerate((member.get("name", "?"), format_faction_role(member.get("role")), member.get("status", "--"))):
                    self.tbl_members.setItem(row_index, column_index, QTableWidgetItem(str(value)))
            allies = [second if first == faction_id else first for first, second in self.alliances if faction_id in (first, second)]
            for ally_id in allies:
                lbl_relation = QLabel(f"{self.faction_name(ally_id)}   ALLIED")
                lbl_relation.setObjectName("FactionInfoLabel")
                self.relations_rows_layout.addWidget(lbl_relation)
            self.lbl_relations_empty.setText("No alliances for this faction.")
            self.lbl_relations_empty.setVisible(not allies)
        except Exception as e:
            print(f"[ERROR] FactionsPage: Could not show detail: {e}")

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return FactionsPage()

# endregion
