## ==========================================
## ZERO-G ADMIN HELPER - STRUCTURES PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Structures.jpg:
## STRUCTURES table with ALL / BA / CV / SV / HV filters on the left, a structure count bar under it,
## STRUCTURE DETAIL with TELEPORT TO, SET FACTION and DESTROY on the right.
## Layout only for now: there is no structure data source yet, so everything shows "--" or "nothing yet".
## All three detail buttons stay greyed out; each one changes the server and gets its own step with Ray's OK.
## Wired (Nov 22, 2026): the table comes from the read-only gents list (every 30 s while open), filtered here.
## TELEPORT TO moves a picked online player next to the structure (api:Request_Entity_Teleport or
## api:Request_Entity_ChangePlayfield); DESTROY sends api:Request_Entity_Destroy. Both go through the Safety Flow.
## SET FACTION stays off (see SET_FACTION_TIP).
## ==========================================

# region Imports

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
                             QButtonGroup, QTableWidget, QHeaderView, QAbstractItemView, QTableWidgetItem,
                             QInputDialog)

## Read-only bridge reads and the Safety Flow.
from features.shared import server_actions

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

## Qt calls that may return None, wrapped once.
from features.shared.qt_types import horizontal_header, vertical_header

# endregion


# region Constants

## Type filters in mockup order: ALL, then the Empyrion structure types
## (BA = base, CV = capital vessel, SV = small vessel, HV = hover vessel).
STRUCTURE_FILTERS = ["ALL", "BA", "CV", "SV", "HV"]

## Columns of the STRUCTURES table, as in the mockup.
STRUCTURE_COLUMNS = ["TYPE", "NAME", "OWNER", "FACTION", "BLOCKS", "PLAYFIELD", "STATUS"]

## Detail buttons: (text, CSS object name). DESTROY is red.
STRUCTURE_ACTIONS = [
    ("TELEPORT TO", "DashActionButton"),
    ("SET FACTION", "DashActionButton"),
    ("DESTROY", "ChatWarnButton"),
]

## Why SET FACTION stays off.
SET_FACTION_TIP = "Not possible from the server: the mod API has no request to change a structure's faction."

## Seconds between structure list reads while the page is open.
REFRESH_SEC = 30

## TELEPORT TO puts the player this many metres above the structure's centre, so they do not land inside it.
TELEPORT_LIFT = 15.0


## "x, y, z" text from the bridge -> (x, y, z) numbers, or None.
def parse_position(text):
    try:
        parts = [float(part.strip()) for part in str(text).split(",")]
        return tuple(parts) if len(parts) == 3 else None
    except ValueError:
        return None

# endregion


# region StructuresPage Class

class StructuresPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("StructuresPage")

        ## The filter picked now. ALL is picked first, like the mockup.
        self.active_filter = "ALL"
        self.filter_buttons = {}

        ## Rows from gents, and the rows the table shows now (after the filter).
        self.structures = []
        self.shown_structures = []
        self.setup_widgets()
        self._wire_live_data()

    def setup_widgets(self):

        ## 2 columns: the table card with the count bar under it, and the detail card spanning both rows.
        page_grid = QGridLayout(self)
        page_grid.setContentsMargins(4, 4, 4, 4)
        page_grid.setHorizontalSpacing(14)
        page_grid.setVerticalSpacing(14)

        # region Structures Table

        table_card, table_layout = make_card("STRUCTURES")

        ## Filter row: small outlined buttons in an exclusive group, so only one is lit at a time.
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        for filter_text in STRUCTURE_FILTERS:
            btn_filter = QPushButton(filter_text)
            btn_filter.setObjectName("StructFilterButton")
            btn_filter.setCheckable(True)
            btn_filter.setMinimumSize(56, 28)

            ## The lambda passes this filter's text to _on_filter_clicked.
            btn_filter.clicked.connect(lambda checked, key=filter_text: self._on_filter_clicked(key))
            self.filter_group.addButton(btn_filter)
            self.filter_buttons[filter_text] = btn_filter
            filter_row.addWidget(btn_filter)
        filter_row.addStretch()
        self.filter_buttons[self.active_filter].setChecked(True)
        table_layout.addLayout(filter_row)

        ## Rows get filled once the bridge sends the structure list. Clicking a row will fill STRUCTURE DETAIL.
        self.tbl_structures = QTableWidget(0, len(STRUCTURE_COLUMNS))
        self.tbl_structures.setObjectName("DashTable")
        self.tbl_structures.setHorizontalHeaderLabels(STRUCTURE_COLUMNS)
        vertical_header(self.tbl_structures).setVisible(False)
        self.tbl_structures.setShowGrid(False)
        self.tbl_structures.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_structures.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_structures.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        horizontal_header(self.tbl_structures).setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table_layout.addWidget(self.tbl_structures, stretch=1)
        self.lbl_structures_empty = QLabel("No structure data yet.")
        self.lbl_structures_empty.setObjectName("DashEmptyLabel")
        table_layout.addWidget(self.lbl_structures_empty)
        page_grid.addWidget(table_card, 0, 0)

        # endregion

        # region Count Bar

        ## Thin card under the table with the total, e.g. "1,284 STRUCTURES". "--" until there is data.
        count_card, count_layout = make_card()
        count_layout.setContentsMargins(18, 8, 18, 8)
        self.lbl_structure_count = QLabel("-- STRUCTURES")
        self.lbl_structure_count.setObjectName("StructCountLabel")
        self.lbl_structure_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        spread_letters(self.lbl_structure_count, 1.5)
        count_layout.addWidget(self.lbl_structure_count)
        page_grid.addWidget(count_card, 1, 0)

        # endregion

        # region Structure Detail

        ## Preview box on top (the structure picture goes here later), then the info lines and buttons.
        detail_card, detail_layout = make_card("STRUCTURE DETAIL")
        self.preview_box = QFrame()
        self.preview_box.setObjectName("DashInnerBox")
        self.preview_box.setMinimumHeight(140)
        preview_layout = QVBoxLayout(self.preview_box)
        self.lbl_preview_empty = QLabel("No structure selected.")
        self.lbl_preview_empty.setObjectName("DashEmptyLabel")
        self.lbl_preview_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self.lbl_preview_empty)
        detail_layout.addWidget(self.preview_box, stretch=1)

        self.lbl_structure_id = QLabel("ID:  --")
        self.lbl_structure_owner = QLabel("OWNER:  --")
        self.lbl_structure_blocks = QLabel("BLOCKS:  --")
        self.lbl_structure_devices = QLabel("DEVICES:  --")
        for lbl_info in (self.lbl_structure_id, self.lbl_structure_owner,
                         self.lbl_structure_blocks, self.lbl_structure_devices):
            lbl_info.setObjectName("PlayerInfoLabel")
            detail_layout.addWidget(lbl_info)
        detail_layout.addStretch()

        self.action_buttons = {}
        for action_text, action_style in STRUCTURE_ACTIONS:
            btn_action = QPushButton(action_text)
            btn_action.setObjectName(action_style)
            btn_action.setMinimumHeight(36)
            btn_action.setEnabled(False)
            btn_action.setToolTip(SET_FACTION_TIP if action_text == "SET FACTION" else "Pick a structure first.")
            spread_letters(btn_action, 1.5)
            detail_layout.addWidget(btn_action)
            self.action_buttons[action_text] = btn_action
        page_grid.addWidget(detail_card, 0, 1, 2, 1)

        # endregion

        ## Column widths roughly match the mockup: 5 : 2.
        page_grid.setColumnStretch(0, 5)
        page_grid.setColumnStretch(1, 2)

        ## The table takes all the height; the count bar stays thin.
        page_grid.setRowStretch(0, 1)
        page_grid.setRowStretch(1, 0)

    # endregion


    # region Filters

    ## Lights the clicked filter. The table will show only that type once there is structure data.
    def _on_filter_clicked(self, filter_text):
        self.active_filter = filter_text
        if filter_text in self.filter_buttons:
            self.filter_buttons[filter_text].setChecked(True)
        self.show_structures()

    # endregion

    # region Live Data

    def _wire_live_data(self):
        try:
            self.tbl_structures.itemSelectionChanged.connect(self.show_detail)
            self.action_buttons["TELEPORT TO"].clicked.connect(self._on_teleport_clicked)
            self.action_buttons["DESTROY"].clicked.connect(self._on_destroy_clicked)
            self.refresh_timer = QTimer(self)
            self.refresh_timer.setInterval(REFRESH_SEC * 1000)
            self.refresh_timer.timeout.connect(self.refresh_live)
        except Exception as e:
            print(f"[ERROR] StructuresPage: Could not wire live data: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        try:
            self.refresh_live()
            self.refresh_timer.start()
        except Exception as e:
            print(f"[ERROR] StructuresPage: Refresh on show failed: {e}")

    def hideEvent(self, event):
        super().hideEvent(event)
        try:
            self.refresh_timer.stop()
        except Exception:
            pass

    def refresh_live(self):
        try:
            if not server_actions.bridge_is_connected(self):
                self.lbl_structures_empty.setText("Connect to the server to see structures.")
                self.lbl_structures_empty.setVisible(True)
                return
            server_actions.read_bridge("gents", ("ENTITY_LIST", "ERROR"), self._on_structures_read,
                                       lambda message: print(f"[ERROR] StructuresPage: gents failed: {message}"))
        except Exception as e:
            print(f"[ERROR] StructuresPage: Refresh failed: {e}")

    def _on_structures_read(self, reply):
        try:
            self.structures = [row for row in ((reply or {}).get("entities") or []) if isinstance(row, dict)]
            self.show_structures()
        except Exception as e:
            print(f"[ERROR] StructuresPage: Could not read structures: {e}")

    def show_structures(self):
        try:
            picked = self.selected_structure()
            self.shown_structures = [row for row in self.structures
                                     if self.active_filter == "ALL" or str(row.get("type", "")).upper() == self.active_filter]
            self.tbl_structures.blockSignals(True)
            self.tbl_structures.setRowCount(0)
            for row in self.shown_structures:
                row_index = self.tbl_structures.rowCount()
                self.tbl_structures.insertRow(row_index)
                powered = row.get("powered")
                status = "--" if powered is None else ("POWERED" if powered else "OFF")

                ## The game reports the owning faction only, so OWNER and FACTION show the same name.
                values = (row.get("type", "--"), row.get("name", "--"), row.get("faction") or "--", row.get("faction") or "--",
                          "--" if row.get("blocks") is None else f"{int(row['blocks']):,}", row.get("playfield", "--"), status)
                for column_index, value in enumerate(values):
                    self.tbl_structures.setItem(row_index, column_index, QTableWidgetItem(str(value)))
                if picked is not None and row.get("id") == picked.get("id"):
                    self.tbl_structures.selectRow(row_index)
            self.tbl_structures.blockSignals(False)
            self.lbl_structure_count.setText(f"{len(self.structures):,} STRUCTURES")
            self.lbl_structures_empty.setVisible(not self.shown_structures)
            if not self.shown_structures:
                self.lbl_structures_empty.setText("No structures on the loaded playfields." if self.structures == [] else "No structures of this type.")
            self.show_detail()
        except Exception as e:
            print(f"[ERROR] StructuresPage: Could not show structures: {e}")

    def selected_structure(self):
        row_index = self.tbl_structures.currentRow()
        if 0 <= row_index < len(self.shown_structures) and self.tbl_structures.selectedItems():
            return self.shown_structures[row_index]
        return None

    def show_detail(self):
        try:
            structure = self.selected_structure()
            if structure is None:
                self.lbl_preview_empty.setText("No structure selected.")
                for lbl_info, title in ((self.lbl_structure_id, "ID"), (self.lbl_structure_owner, "OWNER"),
                                        (self.lbl_structure_blocks, "BLOCKS"), (self.lbl_structure_devices, "DEVICES")):
                    lbl_info.setText(f"{title}:  --")
            else:
                self.lbl_preview_empty.setText(f"{structure.get('name', '?')}\n{structure.get('type', '')} on {structure.get('playfield', '?')}\n{structure.get('pos', '')}")
                self.lbl_structure_id.setText(f"ID:  {structure.get('id', '--')}")
                self.lbl_structure_owner.setText(f"OWNER:  {structure.get('faction') or '--'}")
                self.lbl_structure_blocks.setText(f"BLOCKS:  {structure.get('blocks') if structure.get('blocks') is not None else '--'}")
                self.lbl_structure_devices.setText(f"DEVICES:  {structure.get('devices') if structure.get('devices') is not None else '--'}")
            for action_key, action_text in (("structure_teleport", "TELEPORT TO"), ("structure_destroy", "DESTROY")):
                reason = server_actions.block_reason(self, action_key) or ("" if structure is not None else "Pick a structure first.")
                if not reason and action_text == "TELEPORT TO" and parse_position(structure.get("pos")) is None:  # pyright: ignore[reportOptionalMemberAccess]
                    reason = "The bridge did not send this structure's position."
                self.action_buttons[action_text].setEnabled(reason == "")
                self.action_buttons[action_text].setToolTip(reason or ("Moves a player next to it (Safety Flow)." if action_text == "TELEPORT TO" else "Destroys it for good (Safety Flow)."))
            self.action_buttons["SET FACTION"].setEnabled(False)
        except Exception as e:
            print(f"[ERROR] StructuresPage: Could not show detail: {e}")

    # endregion

    # region Actions

    def _on_teleport_clicked(self):
        """Reads the online players, asks which one, then sends the move through the Safety Flow."""
        try:
            structure = self.selected_structure()
            if structure is None:
                return
            server_actions.read_bridge("plys", "PLAYER_CACHE", lambda reply: self._ask_teleport(structure, reply),
                                       lambda message: print(f"[ERROR] StructuresPage: plys failed: {message}"))
        except Exception as e:
            print(f"[ERROR] StructuresPage: Teleport failed: {e}")

    def _ask_teleport(self, structure, reply):
        try:
            online = [row for row in ((reply or {}).get("player_list") or [])
                      if isinstance(row, dict) and row.get("status") == "Online" and str(row.get("entityId", "")).isdigit()]
            if not online:
                print("[WARN] StructuresPage: Nobody is online to teleport.")
                return
            labels = [f"{row.get('name', '?')}  ({row.get('playfield', '?')})" for row in online]
            label, accepted = QInputDialog.getItem(self, "Teleport to structure", "Player:", labels, 0, False)
            if not accepted or label not in labels:
                return
            player = online[labels.index(label)]
            x, y, z = parse_position(structure.get("pos"))  # pyright: ignore[reportGeneralTypeIssues]
            position = f'"pos":{{"x":{x},"y":{y + TELEPORT_LIFT},"z":{z}}},"rot":{{"x":0,"y":0,"z":0}}'
            playfield = str(structure.get("playfield", "")).replace('"', "")
            if str(player.get("playfield", "")) == playfield:
                command = f'api:Request_Entity_Teleport {{"id":{int(player["entityId"])},{position}}}'
            else:
                command = f'api:Request_Entity_ChangePlayfield {{"id":{int(player["entityId"])},"playfield":"{playfield}",{position}}}'
            server_actions.run_server_action(self, "structure_teleport", "Teleport a player to a structure", command,
                                             lambda ok, answer: print(f"[INFO] StructuresPage: Teleport ok={ok}"),
                                             explanation=f"Moves {player.get('name', '?')} to {structure.get('name', '?')} on {playfield}.")
        except Exception as e:
            print(f"[ERROR] StructuresPage: Teleport failed: {e}")

    def _on_destroy_clicked(self):
        try:
            structure = self.selected_structure()
            if structure is None:
                return
            command = server_actions.api_command("Request_Entity_Destroy", {"id": int(structure["id"])})

            def done(ok, reply):
                print(f"[{'SUCCESS' if ok else 'ERROR'}] StructuresPage: Destroy: {server_actions.reply_text(reply)}")
                if ok:
                    self.refresh_live()
            server_actions.run_server_action(self, "structure_destroy", "Destroy a structure", command, done,
                                             explanation=f"Destroys {structure.get('name', '?')} (id {structure.get('id')}) on "
                                                         f"{structure.get('playfield', '?')}. This cannot be undone. The playfield must be loaded.")
        except Exception as e:
            print(f"[ERROR] StructuresPage: Destroy failed: {e}")

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return StructuresPage()

# endregion
