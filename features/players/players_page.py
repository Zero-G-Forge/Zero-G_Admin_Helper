## ==========================================
## ZERO-G ADMIN HELPER - PLAYERS PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Players.jpg:
## PLAYER LIST on the left, PLAYER DETAIL and INVENTORY in the middle,
## ACTIONS and LOADOUT TEMPLATES on the right.
## Layout only for now: there is no player data source on this page yet, so everything shows "--" or "nothing yet".
## Every action button stays greyed out; each one changes something on the server and gets its own step with Ray's OK.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
                             QTableWidget, QHeaderView, QAbstractItemView, QProgressBar)

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

# endregion


# region Constants

## Columns of the PLAYER LIST table, as in the mockup.
PLAYER_COLUMNS = ["PLAYER", "STATUS", "FACTION", "PLAYFIELD", "PING"]

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

# endregion


# region PlayersPage Class

class PlayersPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("PlayersPage")

        ## Bars and action buttons by name, so later steps can fill or turn them on.
        self.stat_bars = {}
        self.action_buttons = {}
        self.setup_widgets()

    def setup_widgets(self):

        ## 3 columns: player list, detail + inventory, actions + loadouts.
        page_grid = QGridLayout(self)
        page_grid.setContentsMargins(4, 4, 4, 4)
        page_grid.setHorizontalSpacing(14)
        page_grid.setVerticalSpacing(14)

        # region Player List

        ## Rows get filled once the bridge sends the player list. Clicking a row will fill PLAYER DETAIL.
        list_card, list_layout = make_card("PLAYER LIST")
        self.tbl_players = QTableWidget(0, len(PLAYER_COLUMNS))
        self.tbl_players.setObjectName("DashTable")
        self.tbl_players.setHorizontalHeaderLabels(PLAYER_COLUMNS)
        self.tbl_players.verticalHeader().setVisible(False)
        self.tbl_players.setShowGrid(False)
        self.tbl_players.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_players.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_players.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_players.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
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
        page_grid.addWidget(actions_card, 0, 2)

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
        page_grid.addWidget(loadout_card, 1, 2)

        # endregion

        ## Column widths roughly match the mockup: 5 : 5 : 3.
        page_grid.setColumnStretch(0, 5)
        page_grid.setColumnStretch(1, 5)
        page_grid.setColumnStretch(2, 3)

        ## Detail and actions on top take a bit more height than inventory and loadouts.
        page_grid.setRowStretch(0, 3)
        page_grid.setRowStretch(1, 2)

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

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return PlayersPage()

# endregion
