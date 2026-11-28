## ==========================================
## ZERO-G ADMIN HELPER - PLAYERS PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Players.jpg:
## PLAYER LIST on the left, PLAYER DETAIL and INVENTORY in the middle,
## LOADOUT TEMPLATES and ACTIONS on the right (LOADOUT TEMPLATES lines up with
## PLAYER DETAIL, ACTIONS with INVENTORY). Nov 23, 2026: PLAYER DETAIL is sized
## to its content so INVENTORY can be taller.
## Layout only for now: there is no player data source on this page yet, so everything shows "--" or "nothing yet".
## Every action button stays greyed out; each one changes something on the server and gets its own step with Ray's OK.
## Wired (Nov 22, 2026): the list comes from plys, the detail from api:Request_Player_Info, the inventory from
## api:Request_Player_GetInventory (all read-only, refreshed every 15 s while the page is open).
## Ping for ONLINE players is filled from Request_Player_Info (PlayerInfo.ping), in ms; OFFLINE players show "--".
## The list defaults to online players only. SHOW ALL PLAYERS lists everyone in the plys cache
## (all players registered on the server); SHOW ONLINE ONLY returns to the default. Offline ping is "--".
## Clicking a PLAYER LIST column header sorts that column A-Z, then Z-A; in-game GameMaster/Admin
## (PlayerInfo.permission >= 3) stay at the top in both views. The sort, the filter, and the selection
## are kept across refreshes.
## FACTION tags are taken from Request_Get_Factions by factionId, so a leftover plys tag is not shown.
## MESSAGE (api:Request_InGameMessage_SinglePlayer), WARP (api:Request_Entity_Teleport / Request_Entity_ChangePlayfield), KICK (con:kick),
## BAN (con:ban), SAVE & APPLY (api:Request_Player_SetInventory) and the loadouts (api:Request_Player_AddItem)
## go through the ZAH Safety Flow in features/shared/server_actions.py. GOD MODE stays off (see GOD_MODE_TIP).
## GIVE PACK (Nov 23, 2026) hands a custom item pack, built with BUILD ITEM TEMPLATE, to the picked player
## through the same player_loadout path as STARTER, EXPLORER and BUILDER.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
                             QTableWidget, QHeaderView, QAbstractItemView, QProgressBar, QTableWidgetItem,
                             QInputDialog, QDialog, QFormLayout, QLineEdit, QDoubleSpinBox, QDialogButtonBox,
                             QComboBox)

## Read-only bridge reads and the Safety Flow for every server-changing button.
from features.shared import server_actions
from features.shared.faction_display import faction_tag, format_faction_role
from features.shared.loadouts import load_templates, list_template_names, TEMPLATE_NAMES

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

## Qt calls that may return None, wrapped once.
from features.shared.qt_types import horizontal_header, vertical_header

# endregion


# region Constants

## Columns of the PLAYER LIST table, as in the mockup.
PLAYER_COLUMNS = ["PLAYER", "STATUS", "FACTION", "PLAYFIELD", "PING"]

## PlayerInfo.permission: 0 is a regular player, 3 is GameMaster, 9 is Admin. Staff at 3 or above stay at the top.
STAFF_PERMISSION = 3

## Table columns whose cells are numbers (missing values, shown as "--", sort last).
NUMERIC_COLUMNS = {"PING"}

## Stat bars in PLAYER DETAIL: (label text, CSS object name that sets the bar colour).
STAT_BARS = [
    ("HEALTH", "PlayerHealthBar"),
    ("OXYGEN", "PlayerOxygenBar"),
    ("FOOD", "PlayerFoodBar"),
]

## ACTIONS buttons in mockup order: (title, small line under it, CSS object name for the colour).
## Cyan for everyday actions, amber for KICK, red for BAN.
PLAYER_ACTIONS = [
    ("MESSAGE", "Send a private message", "PlayerActionButton"),
    ("WARP", "Teleport to location", "PlayerActionButton"),
    ("GOD MODE", "Toggle invulnerability", "PlayerActionButton"),
    ("KICK", "Remove from the server", "PlayerKickButton"),
    ("BAN", "Restrict access", "PlayerBanButton"),
]

## LOADOUT TEMPLATES buttons, in mockup order.
LOADOUT_TEMPLATES = ["STARTER", "EXPLORER", "BUILDER"]

## Which Safety Flow action key each ACTIONS button uses (see server_actions.ACTION_ROLES).
ACTION_KEYS = {"MESSAGE": "player_message", "WARP": "player_warp", "KICK": "player_kick", "BAN": "player_ban"}

## The game's godmode console command only works for the player typing it, not from the server console.
GOD_MODE_TIP = "Not possible from the server: the game's godmode command only works in a player's own console."

## Seconds between read-only refreshes while the page is open.
REFRESH_SEC = 15

## Columns of the inventory table.
INVENTORY_COLUMNS = ["WHERE", "SLOT", "ITEM", "COUNT"]

## Ban lengths offered by BAN (the game's ban command takes these forms).
BAN_LENGTHS = ["1h", "1d", "7d", "30d", "1y"]

# endregion


# region PlayersPage Class


# region List Helpers

def format_ping(player):
    """Live ping in milliseconds for an online player, or '--' when there is none."""
    if str((player or {}).get("status") or "") != "Online":
        return "--"
    try:
        ping = int(player.get("ping"))
    except (TypeError, ValueError):
        return "--"
    if ping <= 0:
        return "--"
    return str(ping) + " ms"


def is_staff(player):
    """True when PlayerInfo.permission is GameMaster (3) or Admin (9). Faction 'Admin' role is ignored."""
    try:
        return int((player or {}).get("permission")) >= STAFF_PERMISSION
    except (TypeError, ValueError):
        return False


def ping_sort_value(player):
    """(0, ping) for a real online ping, or (1, 0) so '--' sorts last in both directions."""
    if format_ping(player) == "--":
        return (1, 0)
    return (0, int(player.get("ping")))


def column_sort_key(player, column, descending):
    """Sort key for one column. PING is numeric, with '--' last even when the order is Z-A."""
    heading = PLAYER_COLUMNS[column]
    if heading == "PING":
        missing, value = ping_sort_value(player)
        return (missing, -value if descending else value)
    field_names = {"PLAYER": "name", "STATUS": "status", "FACTION": "faction", "PLAYFIELD": "playfield"}
    text = str((player or {}).get(field_names[heading], "") or "").lower()
    if descending:
        return tuple(255 - ord(char) for char in text[:80])
    return text


def is_online(player):
    """True when plys marks this row as Online."""
    return str((player or {}).get("status") or "") == "Online"


def visible_player_rows(rows, show_all):
    """Online players only, or the full registered list when show_all is True."""
    players = [row for row in rows if isinstance(row, dict)]
    if show_all:
        return players
    return [row for row in players if is_online(row)]


def sort_player_rows(rows, column, descending):
    """Staff first, then everyone else, each group sorted by the same column and direction."""
    players = [row for row in rows if isinstance(row, dict)]
    staff = [row for row in players if is_staff(row)]
    others = [row for row in players if not is_staff(row)]
    if column is None:
        staff.sort(key=lambda row: (str(row.get("status")) != "Online", str(row.get("name", "")).lower()))
        others.sort(key=lambda row: (str(row.get("status")) != "Online", str(row.get("name", "")).lower()))
        return staff + others
    staff.sort(key=lambda row: column_sort_key(row, column, descending))
    others.sort(key=lambda row: column_sort_key(row, column, descending))
    return staff + others

# endregion


class PlayersPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("PlayersPage")

        ## Bars and action buttons by name, so later steps can fill or turn them on.
        self.stat_bars = {}
        self.action_buttons = {}

        ## Live data: the plys rows, the picked player, and the inventory as read (for RESET).
        self.players = []
        self.selected_player = None
        self.inventory_original = None
        self._sort_column = None
        self._sort_descending = False
        self._show_all_players = False
        self._shown_players = []
        self._info_by_id = {}
        self.factions = []
        self.setup_widgets()
        self._wire_live_data()

    def setup_widgets(self):

        ## 3 columns: player list, detail + inventory, loadouts + actions.
        page_grid = QGridLayout(self)
        page_grid.setContentsMargins(4, 4, 4, 4)
        page_grid.setHorizontalSpacing(14)
        page_grid.setVerticalSpacing(14)

        # region Player List

        ## Rows get filled once the bridge sends the player list. Clicking a row will fill PLAYER DETAIL.
        ## SHOW ALL PLAYERS sits in the title row; the list itself starts as online only.
        list_card, list_layout = make_card("")
        list_header = QHBoxLayout()
        lbl_list_title = QLabel("PLAYER LIST")
        lbl_list_title.setObjectName("DashCardTitle")
        spread_letters(lbl_list_title, 1.5)
        list_header.addWidget(lbl_list_title)
        list_header.addStretch()
        self.btn_list_filter = QPushButton("SHOW ALL PLAYERS")
        self.btn_list_filter.setObjectName("StructFilterButton")
        self.btn_list_filter.setMinimumHeight(28)
        self.btn_list_filter.setToolTip("Show every player registered on the server.")
        list_header.addWidget(self.btn_list_filter)
        list_layout.addLayout(list_header)
        self.tbl_players = QTableWidget(0, len(PLAYER_COLUMNS))
        self.tbl_players.setObjectName("DashTable")
        self.tbl_players.setHorizontalHeaderLabels(PLAYER_COLUMNS)
        vertical_header(self.tbl_players).setVisible(False)
        self.tbl_players.setShowGrid(False)
        self.tbl_players.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_players.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_players.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        horizontal_header(self.tbl_players).setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        horizontal_header(self.tbl_players).setSortIndicatorShown(True)
        horizontal_header(self.tbl_players).setSectionsClickable(True)
        list_layout.addWidget(self.tbl_players, stretch=1)
        self.lbl_players_empty = QLabel("No player data yet.")
        self.lbl_players_empty.setObjectName("DashEmptyLabel")
        list_layout.addWidget(self.lbl_players_empty)
        page_grid.addWidget(list_card, 0, 0, 2, 1)

        # endregion

        # region Player Detail

        ## Big cyan name with ONLINE/OFFLINE beside it, then Steam ID, faction, playfield and the stat bars.
        detail_card, detail_layout = make_card("PLAYER DETAIL")
        name_row = QHBoxLayout()
        self.lbl_player_name = QLabel("NO PLAYER SELECTED")
        self.lbl_player_name.setObjectName("PlayerNameLabel")
        spread_letters(self.lbl_player_name, 1.5)
        name_row.addWidget(self.lbl_player_name)
        name_row.addStretch()
        self.lbl_player_status = QLabel("--")
        self.lbl_player_status.setObjectName("PlayerStatusLabel")
        name_row.addWidget(self.lbl_player_status)
        detail_layout.addLayout(name_row)

        self.lbl_steam_id = QLabel("STEAM ID:  --")
        self.lbl_faction = QLabel("FACTION:  --")
        self.lbl_playfield = QLabel("PLAYFIELD:  --")
        for lbl_info in (self.lbl_steam_id, self.lbl_faction, self.lbl_playfield):
            lbl_info.setObjectName("PlayerInfoLabel")
            detail_layout.addWidget(lbl_info)

        ## Each stat bar: label on the left, thin coloured bar on the right. Empty (0) until there is data.
        for bar_text, bar_name in STAT_BARS:
            bar_row = QHBoxLayout()
            lbl_bar = QLabel(bar_text)
            lbl_bar.setObjectName("PlayerInfoLabel")
            lbl_bar.setFixedWidth(80)
            bar_row.addWidget(lbl_bar)
            bar_stat = QProgressBar()
            bar_stat.setObjectName(bar_name)
            bar_stat.setRange(0, 100)
            bar_stat.setValue(0)
            bar_stat.setTextVisible(False)
            bar_stat.setFixedHeight(6)
            bar_row.addWidget(bar_stat, stretch=1)
            detail_layout.addLayout(bar_row)
            self.stat_bars[bar_text] = bar_stat
        detail_layout.addStretch()
        page_grid.addWidget(detail_card, 0, 1)

        # endregion

        # region Inventory

        ## Item slots go in the dark box. RESET and SAVE & APPLY stay off until inventory edits are built.
        inventory_card, inventory_layout = make_card("INVENTORY")
        self.inventory_box = QFrame()
        self.inventory_box.setObjectName("DashInnerBox")
        self.inventory_box_layout = QVBoxLayout(self.inventory_box)
        self.inventory_box_layout.setContentsMargins(12, 8, 12, 8)
        self.lbl_inventory_empty = QLabel("Pick a player to see their inventory.")
        self.lbl_inventory_empty.setObjectName("DashEmptyLabel")
        self.inventory_box_layout.addWidget(self.lbl_inventory_empty)

        ## The inventory as a table. Only COUNT can be edited; SAVE & APPLY sends the whole inventory back.
        self.tbl_inventory = QTableWidget(0, len(INVENTORY_COLUMNS))
        self.tbl_inventory.setObjectName("DashTable")
        self.tbl_inventory.setHorizontalHeaderLabels(INVENTORY_COLUMNS)
        vertical_header(self.tbl_inventory).setVisible(False)
        self.tbl_inventory.setShowGrid(False)
        horizontal_header(self.tbl_inventory).setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_inventory.setVisible(False)
        self.inventory_box_layout.addWidget(self.tbl_inventory, stretch=1)
        self.inventory_box_layout.addStretch()
        inventory_layout.addWidget(self.inventory_box, stretch=1)

        inventory_buttons = QHBoxLayout()
        inventory_buttons.setSpacing(12)
        self.btn_inventory_reset = QPushButton("RESET")
        self.btn_inventory_reset.setObjectName("PlayerMuteButton")

        ## "&&" shows one "&". A single "&" is Qt's keyboard-shortcut marker and would vanish.
        self.btn_inventory_save = QPushButton("SAVE && APPLY")
        self.btn_inventory_save.setObjectName("DashActionButton")
        for btn_inventory in (self.btn_inventory_reset, self.btn_inventory_save):
            btn_inventory.setMinimumHeight(40)
            btn_inventory.setEnabled(False)
            btn_inventory.setToolTip("Coming in a later step.")
            spread_letters(btn_inventory, 1.5)
        inventory_buttons.addWidget(self.btn_inventory_reset, stretch=2)
        inventory_buttons.addWidget(self.btn_inventory_save, stretch=3)
        inventory_layout.addLayout(inventory_buttons)
        page_grid.addWidget(inventory_card, 1, 1)

        # endregion

        # region Actions

        ## Tall two-line buttons: big title, small grey line under it.
        actions_card, actions_layout = make_card("ACTIONS")
        for action_title, action_hint, action_style in PLAYER_ACTIONS:
            btn_action = self._make_action_button(action_title, action_hint, action_style)
            actions_layout.addWidget(btn_action)
            self.action_buttons[action_title] = btn_action
        actions_layout.addStretch()
        page_grid.addWidget(actions_card, 1, 2)

        # endregion

        # region Loadout Templates

        ## One square button per template. Giving a loadout changes a player's inventory, so they stay off.
        loadout_card, loadout_layout = make_card("LOADOUT TEMPLATES")
        loadout_row = QHBoxLayout()
        loadout_row.setSpacing(8)
        self.loadout_buttons = []
        for template_text in LOADOUT_TEMPLATES:
            btn_template = QPushButton(template_text)
            btn_template.setObjectName("DashActionButton")
            btn_template.setMinimumHeight(56)
            btn_template.setEnabled(False)
            btn_template.setToolTip("Coming in a later step.")
            btn_template.setStyleSheet("font-size: 12px;")
            loadout_row.addWidget(btn_template)
            self.loadout_buttons.append(btn_template)

        ## The stretch keeps the title at the top and the buttons at the bottom of the card.
        loadout_layout.addStretch()
        loadout_layout.addLayout(loadout_row)
        pack_row = QHBoxLayout()
        pack_row.setSpacing(8)
        self.cmb_custom_pack = QComboBox()
        self.cmb_custom_pack.setObjectName("EcfFileCombo")
        self.cmb_custom_pack.setPlaceholderText("No custom packs")
        self.cmb_custom_pack.setEnabled(False)
        self.btn_give_pack = QPushButton("GIVE PACK")
        self.btn_give_pack.setObjectName("DashActionButton")
        self.btn_give_pack.setMinimumHeight(40)
        self.btn_give_pack.setEnabled(False)
        self.btn_give_pack.setToolTip("Coming in a later step.")
        pack_row.addWidget(self.cmb_custom_pack, stretch=3)
        pack_row.addWidget(self.btn_give_pack, stretch=2)
        loadout_layout.addLayout(pack_row)
        page_grid.addWidget(loadout_card, 0, 2)

        # endregion

        ## Column widths roughly match the mockup: 5 : 5 : 3.
        page_grid.setColumnStretch(0, 5)
        page_grid.setColumnStretch(1, 5)
        page_grid.setColumnStretch(2, 3)

        ## PLAYER DETAIL and LOADOUT TEMPLATES on top fit their content.
        ## INVENTORY and ACTIONS below take the leftover height, so the two rows
        ## line up across the middle and right columns.
        page_grid.setRowStretch(0, 0)
        page_grid.setRowStretch(1, 1)

    ## Builds one ACTIONS button with a title and a hint line inside it.
    ## The labels are children of the button, so they grey out with it when it is disabled.
    def _make_action_button(self, title_text, hint_text, style_name):
        btn_action = QPushButton()
        btn_action.setObjectName(style_name)
        btn_action.setMinimumHeight(54)
        btn_action.setEnabled(False)
        btn_action.setToolTip("Coming in a later step.")
        button_layout = QVBoxLayout(btn_action)
        button_layout.setContentsMargins(14, 6, 14, 6)
        button_layout.setSpacing(0)
        lbl_title = QLabel(title_text)
        lbl_title.setObjectName("PlayerActionTitle")
        spread_letters(lbl_title, 1.5)
        lbl_hint = QLabel(hint_text)
        lbl_hint.setObjectName("PlayerActionHint")

        ## Clicks pass through the labels to the button underneath.
        for lbl_inside in (lbl_title, lbl_hint):
            lbl_inside.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            button_layout.addWidget(lbl_inside)
        return btn_action

    # endregion

    # region Live Data

    def _wire_live_data(self):
        """Connects the table and buttons, and starts the read-only refresh timer."""
        try:
            self.tbl_players.itemSelectionChanged.connect(self._on_player_picked)
            horizontal_header(self.tbl_players).sectionClicked.connect(self._on_header_clicked)
            self.action_buttons["MESSAGE"].clicked.connect(self._on_message_clicked)
            self.action_buttons["WARP"].clicked.connect(self._on_warp_clicked)
            self.action_buttons["KICK"].clicked.connect(self._on_kick_clicked)
            self.action_buttons["BAN"].clicked.connect(self._on_ban_clicked)
            self.action_buttons["GOD MODE"].setToolTip(GOD_MODE_TIP)
            self.btn_inventory_reset.clicked.connect(self._on_inventory_reset)
            self.btn_inventory_save.clicked.connect(self._on_inventory_save)
            for btn_template, template_name in zip(self.loadout_buttons, LOADOUT_TEMPLATES):
                btn_template.clicked.connect(lambda checked=False, name=template_name: self._on_loadout_clicked(name))
            self.btn_give_pack.clicked.connect(self._on_give_pack_clicked)
            self.cmb_custom_pack.currentIndexChanged.connect(lambda index: self._refresh_buttons())
            self.btn_list_filter.clicked.connect(self._on_list_filter_clicked)
            self.refresh_timer = QTimer(self)
            self.refresh_timer.setInterval(REFRESH_SEC * 1000)
            self.refresh_timer.timeout.connect(self.refresh_players)
            self._refresh_buttons()
        except Exception as e:
            print(f"[ERROR] PlayersPage: Could not wire live data: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        try:
            self.refresh_players()
            self.refresh_timer.start()
        except Exception as e:
            print(f"[ERROR] PlayersPage: Refresh on show failed: {e}")

    def hideEvent(self, event):
        super().hideEvent(event)
        try:
            self.refresh_timer.stop()
        except Exception:
            pass

    def refresh_players(self):
        """Reads plys (read-only) when the bridge is connected."""
        try:
            self._refresh_buttons()
            if not server_actions.bridge_is_connected(self):
                self.lbl_players_empty.setText("Connect to the server to see players.")
                return
            server_actions.read_bridge_many([
                ("plys", "PLAYER_CACHE", self._on_players_read,
                 lambda message: print(f"[ERROR] PlayersPage: plys failed: {message}")),
                ('api:Request_Get_Factions {"id":1}', ("API_RESULT", "ERROR"),
                 self._on_factions_read,
                 lambda message: print(f"[ERROR] PlayersPage: Factions read failed: {message}"))])
        except Exception as e:
            print(f"[ERROR] PlayersPage: Refresh failed: {e}")

    def _on_factions_read(self, reply):
        try:
            data = reply.get("data") if isinstance(reply, dict) else None
            rows = data.get("factions") if isinstance(data, dict) else None
            self.factions = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
            if self.players:
                self.fill_players(self.players)
        except Exception as e:
            print(f"[ERROR] PlayersPage: Could not read factions: {e}")

    def _on_players_read(self, reply):
        try:
            rows = reply.get("player_list") if isinstance(reply, dict) else None
            self.fill_players(rows if isinstance(rows, list) else [])
            self._log_player_counts()
            self._request_online_info()
        except Exception as e:
            print(f"[ERROR] PlayersPage: Could not show players: {e}")

    def _apply_faction_fields(self, player):
        """Fills the faction tag from the live faction list, and the club rank for display."""
        player = dict(player or {})
        player["faction"] = faction_tag(self.factions, player.get("factionId"), fallback=player.get("faction") or "--")
        player["role"] = format_faction_role(player.get("role"))
        return player

    def _merge_live_info(self, player):
        """Applies the last Request_Player_Info ping and permission for this entity, if any."""
        entity_id = str((player or {}).get("entityId") or "")
        extra = self._info_by_id.get(entity_id)
        if extra:
            player = dict(player)
            player.update(extra)
        return player

    def _request_online_info(self):
        """Reads Request_Player_Info (read-only) for each online player, once per list refresh."""
        if not server_actions.bridge_is_connected(self):
            return
        for player in self.players:
            if str(player.get("status") or "") != "Online":
                continue
            try:
                entity_id = int(player.get("entityId"))
            except (TypeError, ValueError):
                continue
            server_actions.read_bridge(
                'api:Request_Player_Info {"id":' + str(entity_id) + "}",
                ("API_RESULT", "ERROR"),
                lambda reply, eid=str(entity_id): self._on_online_info_read(eid, reply),
                lambda message: None,
            )

    def _on_online_info_read(self, entity_id, reply):
        try:
            info = reply.get("data") if isinstance(reply, dict) and reply.get("status") == "ok" else None
            if not isinstance(info, dict):
                return
            extra = dict(self._info_by_id.get(entity_id) or {})
            if "ping" in info:
                extra["ping"] = info.get("ping")
            if "permission" in info:
                extra["permission"] = info.get("permission")
            if extra == (self._info_by_id.get(entity_id) or {}):
                return
            self._info_by_id[entity_id] = extra
            self.fill_players(self.players)
        except Exception as e:
            print(f"[ERROR] PlayersPage: Could not apply player ping: {e}")

    def _log_player_counts(self):
        """Writes the online count, and the registered total when the list is showing everyone."""
        online = sum(1 for player in self.players if is_online(player))
        if self._show_all_players:
            print(f"[INFO] PlayersPage: {online} online player(s), {len(self.players)} registered")
        else:
            print(f"[INFO] PlayersPage: {online} online player(s)")

    def _sync_list_filter_button(self):
        """Keeps the title-row button in step with the current list filter."""
        if self._show_all_players:
            self.btn_list_filter.setText("SHOW ONLINE ONLY")
            self.btn_list_filter.setToolTip("Show only players who are online.")
        else:
            self.btn_list_filter.setText("SHOW ALL PLAYERS")
            self.btn_list_filter.setToolTip("Show every player registered on the server.")

    def _on_list_filter_clicked(self):
        try:
            self._show_all_players = not self._show_all_players
            self._sync_list_filter_button()
            self.fill_players(self.players)
            self._log_player_counts()
        except Exception as e:
            print(f"[ERROR] PlayersPage: Could not switch the player list: {e}")

    def _on_header_clicked(self, column):
        try:
            if column < 0 or column >= len(PLAYER_COLUMNS):
                return
            if self._sort_column == column:
                self._sort_descending = not self._sort_descending
            else:
                self._sort_column = column
                self._sort_descending = False
            self.fill_players(self.players)
        except Exception as e:
            print(f"[ERROR] PlayersPage: Could not sort the player list: {e}")

    def fill_players(self, rows):
        """Fills PLAYER LIST, keeping the picked player picked and the current column sort."""
        picked_id = (self.selected_player or {}).get("entityId")
        merged = [self._apply_faction_fields(self._merge_live_info(row)) for row in rows if isinstance(row, dict)]
        self.players = merged
        shown = sort_player_rows(visible_player_rows(merged, self._show_all_players),
                                 self._sort_column, self._sort_descending)
        self._shown_players = shown
        self.tbl_players.blockSignals(True)
        self.tbl_players.setRowCount(len(shown))
        picked_row = -1
        for row_number, player in enumerate(shown):
            cells = [player.get("name", "--"), player.get("status", "--"), player.get("faction", "--"),
                     player.get("playfield", "--"), format_ping(player)]
            for column, cell in enumerate(cells):
                self.tbl_players.setItem(row_number, column, QTableWidgetItem(str(cell)))
            if picked_id is not None and str(player.get("entityId")) == str(picked_id):
                picked_row = row_number
        header = horizontal_header(self.tbl_players)
        if self._sort_column is not None:
            order = Qt.SortOrder.DescendingOrder if self._sort_descending else Qt.SortOrder.AscendingOrder
            header.setSortIndicator(self._sort_column, order)
        if picked_row >= 0:
            self.tbl_players.selectRow(picked_row)
        self.tbl_players.blockSignals(False)
        if not merged:
            empty_text = "No players known yet."
        elif not shown:
            empty_text = "No players are online."
        else:
            empty_text = ""
        self.lbl_players_empty.setText(empty_text)
        self.lbl_players_empty.setVisible(not shown)

    def _on_player_picked(self):
        """Shows the picked row, then reads its detail and inventory (read-only)."""
        try:
            row = self.tbl_players.currentRow()
            if row < 0 or row >= len(self._shown_players):
                self.selected_player = None
                self._refresh_buttons()
                return
            self.selected_player = self._shown_players[row]
            player = self.selected_player
            self.lbl_player_name.setText(str(player.get("name", "--")).upper())
            self.lbl_player_status.setText(str(player.get("status", "--")).upper())
            self.lbl_steam_id.setText(f"STEAM ID:  {player.get('steamId', '--')}")
            self.lbl_faction.setText(f"FACTION:  {player.get('faction', '--')}")
            self.lbl_playfield.setText(f"PLAYFIELD:  {player.get('playfield', '--')}")
            self._refresh_buttons()
            entity_id = self._entity_id()
            if entity_id is None or not server_actions.bridge_is_connected(self):
                return
            server_actions.read_bridge_many([
                (f'api:Request_Player_Info {{"id":{entity_id}}}', ("API_RESULT", "ERROR"),
                 self._on_info_read, lambda message: None),
                (f'api:Request_Player_GetInventory {{"id":{entity_id}}}', ("API_RESULT", "ERROR"),
                 self._on_inventory_read, lambda message: None)])
        except Exception as e:
            print(f"[ERROR] PlayersPage: Could not show the player: {e}")

    def _entity_id(self):
        try:
            return int((self.selected_player or {}).get("entityId"))
        except (TypeError, ValueError):
            return None

    def _on_info_read(self, reply):
        """Fills the HEALTH / OXYGEN / FOOD bars from Request_Player_Info."""
        try:
            info = reply.get("data") if isinstance(reply, dict) and reply.get("status") == "ok" else None
            if not isinstance(info, dict):
                return
            for bar_text, value_key, max_key in (("HEALTH", "health", "healthMax"), ("OXYGEN", "oxygen", "oxygenMax"),
                                                 ("FOOD", "food", "foodMax")):
                value, most = float(info.get(value_key) or 0), float(info.get(max_key) or 0)
                self.stat_bars[bar_text].setValue(int(100 * value / most) if most > 0 else 0)
                self.stat_bars[bar_text].setToolTip(f"{value:g} / {most:g}")
        except Exception as e:
            print(f"[ERROR] PlayersPage: Could not show player info: {e}")

    def _on_inventory_read(self, reply):
        try:
            inventory = reply.get("data") if isinstance(reply, dict) and reply.get("status") == "ok" else None
            if not isinstance(inventory, dict):
                return
            self.inventory_original = inventory
            self.fill_inventory(inventory)
        except Exception as e:
            print(f"[ERROR] PlayersPage: Could not show inventory: {e}")

    def fill_inventory(self, inventory):
        """Shows toolbelt and bag stacks. COUNT is the only cell that can be changed."""
        stacks = [("TOOLBELT", stack) for stack in inventory.get("toolbelt") or []] + \
                 [("BAG", stack) for stack in inventory.get("bag") or []]
        self.tbl_inventory.setRowCount(len(stacks))
        for row_number, (where, stack) in enumerate(stacks):
            cells = [where, stack.get("slotIdx", "--"), stack.get("id", "--"), stack.get("count", 0)]
            for column, cell in enumerate(cells):
                item = QTableWidgetItem(str(cell))
                if column != 3:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.tbl_inventory.setItem(row_number, column, item)
        self.tbl_inventory.setVisible(True)
        self.lbl_inventory_empty.setVisible(not stacks)
        self.lbl_inventory_empty.setText("The inventory is empty." if not stacks else "")
        self._refresh_buttons()

    def edited_inventory(self):
        """The inventory as read, with the COUNT column from the table. A bad number gives None."""
        if not isinstance(self.inventory_original, dict):
            return None
        stacks = list(self.inventory_original.get("toolbelt") or []) + list(self.inventory_original.get("bag") or [])
        toolbelt_count = len(self.inventory_original.get("toolbelt") or [])
        result = {"playerId": self._entity_id(), "toolbelt": [], "bag": []}
        for row_number, stack in enumerate(stacks):
            cell = self.tbl_inventory.item(row_number, 3)
            try:
                count = int(cell.text()) if cell else int(stack.get("count", 0))
            except ValueError:
                return None
            if count < 0:
                return None
            new_stack = dict(stack)
            new_stack["count"] = count
            if count > 0:
                result["toolbelt" if row_number < toolbelt_count else "bag"].append(new_stack)
        return result

    # endregion

    # region Actions

    def _refresh_buttons(self):
        """Each button is on only for the right role, a connected bridge and a picked player."""
        try:
            has_player = self._entity_id() is not None
            for title, key in ACTION_KEYS.items():
                reason = "Pick a player first." if not has_player else server_actions.block_reason(self, key)
                self.action_buttons[title].setEnabled(reason == "")
                self.action_buttons[title].setToolTip(reason or "Asks for CONFIRM and waits 15 s before sending.")
            self.action_buttons["GOD MODE"].setEnabled(False)
            has_inventory = has_player and isinstance(self.inventory_original, dict)
            inventory_reason = "Pick a player first." if not has_inventory else server_actions.block_reason(self, "player_inventory")
            self.btn_inventory_save.setEnabled(inventory_reason == "")
            self.btn_inventory_save.setToolTip(inventory_reason or "Sends the changed counts (Safety Flow).")
            self.btn_inventory_reset.setEnabled(has_inventory)
            self.btn_inventory_reset.setToolTip("Puts the counts back as they were read." if has_inventory else "Pick a player first.")
            templates = load_templates()
            for btn_template, template_name in zip(self.loadout_buttons, LOADOUT_TEMPLATES):
                reason = "Pick a player first." if not has_player else server_actions.block_reason(self, "player_loadout")
                if not reason and not templates.get(template_name):
                    reason = "This template is empty. Add items on the Library page (ADD TO TEMPLATE)."
                btn_template.setEnabled(reason == "")
                btn_template.setToolTip(reason or ", ".join(f"{row['count']}x {row.get('name', row['id'])}"
                                                            for row in templates[template_name]))
            custom_names = [name for name in list_template_names(templates) if name not in TEMPLATE_NAMES]
            picked_pack = self.cmb_custom_pack.currentData()
            self.cmb_custom_pack.blockSignals(True)
            self.cmb_custom_pack.clear()
            for name in custom_names:
                self.cmb_custom_pack.addItem(name, name)
                if name == picked_pack:
                    self.cmb_custom_pack.setCurrentIndex(self.cmb_custom_pack.count() - 1)
            if self.cmb_custom_pack.currentIndex() < 0 and self.cmb_custom_pack.count() > 0:
                self.cmb_custom_pack.setCurrentIndex(0)
            self.cmb_custom_pack.blockSignals(False)
            self.cmb_custom_pack.setEnabled(self.cmb_custom_pack.count() > 0)
            pack_name = self.cmb_custom_pack.currentData()
            pack_reason = "No custom packs yet. Build one on the Library page (BUILD ITEM TEMPLATE)."
            if pack_name:
                pack_reason = "Pick a player first." if not has_player else server_actions.block_reason(self, "player_loadout")
                if not pack_reason and not templates.get(pack_name):
                    pack_reason = "This pack is empty. Add items on the Library page (BUILD ITEM TEMPLATE)."
            self.btn_give_pack.setEnabled(pack_reason == "")
            if pack_name and not pack_reason:
                self.btn_give_pack.setToolTip(", ".join(f"{row['count']}x {row.get('name', row['id'])}"
                                                         for row in templates[pack_name]))
            else:
                self.btn_give_pack.setToolTip(pack_reason)
        except Exception as e:
            print(f"[ERROR] PlayersPage: Could not refresh buttons: {e}")

    def _after_action(self, label):
        """Shared result handler: one line in the terminal, and a fresh read."""
        def done(ok, reply):
            print(f"[{'SUCCESS' if ok else 'ERROR'}] PlayersPage: {label}: {server_actions.reply_text(reply)}")
            self.lbl_players_empty.setVisible(True)
            self.lbl_players_empty.setText(f"{label}: {'done' if ok else 'failed'} ({server_actions.reply_text(reply)})")
            self.refresh_players()
        return done

    def _player_label(self):
        return f"{(self.selected_player or {}).get('name', '?')} (id {self._entity_id()})"

    def _on_message_clicked(self):
        try:
            text, accepted = QInputDialog.getText(self, "Message", f"Private message to {self._player_label()}:")
            text = text.strip().replace("|", "/")
            if not accepted or not text:
                return
            server_actions.run_server_action(self, "player_message", "Send a private message",
                                             server_actions.message_player_command(self._entity_id(), text), self._after_action("Message"))
        except Exception as e:
            print(f"[ERROR] PlayersPage: Message failed: {e}")

    def _on_kick_clicked(self):
        try:
            reason, accepted = QInputDialog.getText(self, "Kick", f"Reason shown to {self._player_label()}:")
            reason = reason.strip().replace("'", "")
            if not accepted or not reason:
                return
            server_actions.run_server_action(self, "player_kick", "Kick a player",
                                             f"con:kick {self._entity_id()} '{reason}'", self._after_action("Kick"),
                                             explanation=f"Removes {self._player_label()} from the server.")
        except Exception as e:
            print(f"[ERROR] PlayersPage: Kick failed: {e}")

    def _on_ban_clicked(self):
        try:
            length, accepted = QInputDialog.getItem(self, "Ban", f"Ban length for {self._player_label()}:", BAN_LENGTHS, 1, False)
            if not accepted or length not in BAN_LENGTHS:
                return
            server_actions.run_server_action(self, "player_ban", "Ban a player",
                                             f"con:ban {self._entity_id()} {length}", self._after_action("Ban"),
                                             explanation=f"Bans {self._player_label()} for {length}.")
        except Exception as e:
            print(f"[ERROR] PlayersPage: Ban failed: {e}")

    def _on_warp_clicked(self):
        try:
            target = ask_warp_target(self, str((self.selected_player or {}).get("playfield", "")))
            if target is None:
                return
            playfield, x, y, z = target
            entity_id = self._entity_id()
            position = f'"pos":{{"x":{x},"y":{y},"z":{z}}},"rot":{{"x":0,"y":0,"z":0}}'
            if playfield == str((self.selected_player or {}).get("playfield", "")):
                command = f'api:Request_Entity_Teleport {{"id":{entity_id},{position}}}'
            else:
                command = f'api:Request_Entity_ChangePlayfield {{"id":{entity_id},"playfield":"{playfield}",{position}}}'
            server_actions.run_server_action(self, "player_warp", "Warp a player", command, self._after_action("Warp"),
                                             explanation=f"Moves {self._player_label()} to {playfield} ({x}, {y}, {z}).")
        except Exception as e:
            print(f"[ERROR] PlayersPage: Warp failed: {e}")

    def _on_inventory_reset(self):
        if isinstance(self.inventory_original, dict):
            self.fill_inventory(self.inventory_original)

    def _on_inventory_save(self):
        try:
            import json
            inventory = self.edited_inventory()
            if inventory is None:
                print("[WARN] PlayersPage: A COUNT cell is not a whole number of 0 or more. Nothing was sent.")
                return
            command = "api:Request_Player_SetInventory " + json.dumps(inventory, separators=(",", ":"))
            server_actions.run_server_action(self, "player_inventory", "Replace a player's inventory", command,
                                             self._after_action("Inventory"),
                                             explanation=f"Replaces the toolbelt and bag of {self._player_label()}.")
        except Exception as e:
            print(f"[ERROR] PlayersPage: Inventory save failed: {e}")

    def _on_give_pack_clicked(self):
        pack_name = self.cmb_custom_pack.currentData()
        if pack_name:
            self._on_loadout_clicked(pack_name)

    def _on_loadout_clicked(self, template_name):
        try:
            rows = load_templates().get(template_name) or []
            if not rows:
                return
            entity_id = self._entity_id()
            commands = [f'api:Request_Player_AddItem {{"id":{entity_id},"item":{{"id":{row["id"]},"count":{row["count"]}}}}}'
                        for row in rows]
            server_actions.run_server_action(self, "player_loadout", f"Give the {template_name} loadout", commands,
                                             self._after_action(f"Loadout {template_name}"),
                                             explanation=f"Adds {len(rows)} item stack(s) to {self._player_label()}.")
        except Exception as e:
            print(f"[ERROR] PlayersPage: Loadout failed: {e}")

    # endregion

# endregion


# region Warp Dialog

## Asks for a playfield and a position. Returns (playfield, x, y, z) or None when cancelled.
def ask_warp_target(parent, current_playfield):
    dialog = QDialog(parent)
    dialog.setWindowTitle("Warp")
    form = QFormLayout(dialog)
    txt_playfield = QLineEdit(current_playfield)
    form.addRow("PLAYFIELD", txt_playfield)
    spins = []
    for axis in ("X", "Y", "Z"):
        spin = QDoubleSpinBox()
        spin.setRange(-1000000.0, 1000000.0)
        spin.setDecimals(1)
        form.addRow(axis, spin)
        spins.append(spin)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted or not txt_playfield.text().strip():
        return None
    playfield = txt_playfield.text().strip().replace('"', "")
    return playfield, spins[0].value(), spins[1].value(), spins[2].value()

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return PlayersPage()

# endregion
