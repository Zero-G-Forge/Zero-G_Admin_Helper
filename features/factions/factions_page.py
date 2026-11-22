## ==========================================
## ZERO-G ADMIN HELPER - FACTIONS PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Factions.jpg:
## FACTION LIST on the left, FACTION DETAIL with its member table in the middle,
## RELATIONS with SET RELATION and RENAME on the right.
## Layout only for now: there is no faction data source yet, so everything shows "--" or "nothing yet".
## SET RELATION and RENAME stay greyed out; both change the server and get their own step with Ray's OK.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QGridLayout, QPushButton,
                             QTableWidget, QHeaderView, QAbstractItemView)

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

# endregion


# region Constants

## Columns of the member table in FACTION DETAIL, as in the mockup.
MEMBER_COLUMNS = ["NAME", "ROLE", "STATUS"]

## Buttons under RELATIONS, in mockup order.
FACTION_ACTIONS = ["SET RELATION", "RENAME"]

# endregion


# region FactionsPage Class

class FactionsPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("FactionsPage")
        self.setup_widgets()

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
        self.relations_box_layout.addStretch()
        relations_layout.addWidget(self.relations_box, stretch=1)

        ## Wide outlined cyan buttons at the bottom, greyed out for now.
        self.action_buttons = []
        for action_text in FACTION_ACTIONS:
            btn_action = QPushButton(action_text)
            btn_action.setObjectName("DashActionButton")
            btn_action.setMinimumHeight(44)
            btn_action.setEnabled(False)
            btn_action.setToolTip("Coming in a later step.")
            spread_letters(btn_action, 1.5)
            relations_layout.addWidget(btn_action)
            self.action_buttons.append(btn_action)
        page_grid.addWidget(relations_card, 0, 2)

        # endregion

        ## Equal column widths, like the mockup.
        for column_index in range(3):
            page_grid.setColumnStretch(column_index, 1)

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return FactionsPage()

# endregion
