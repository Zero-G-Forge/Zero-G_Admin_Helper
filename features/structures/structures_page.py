## ==========================================
## ZERO-G ADMIN HELPER - STRUCTURES PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Structures.jpg:
## STRUCTURES table with ALL / BA / CV / SV / HV filters on the left, a structure count bar under it,
## STRUCTURE DETAIL with TELEPORT TO, SET FACTION and DESTROY on the right.
## Layout only for now: there is no structure data source yet, so everything shows "--" or "nothing yet".
## All three detail buttons stay greyed out; each one changes the server and gets its own step with Ray's OK.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
                             QButtonGroup, QTableWidget, QHeaderView, QAbstractItemView)

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

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
        self.setup_widgets()

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
        self.tbl_structures.verticalHeader().setVisible(False)
        self.tbl_structures.setShowGrid(False)
        self.tbl_structures.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_structures.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_structures.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_structures.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
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
            btn_action.setToolTip("Coming in a later step.")
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

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return StructuresPage()

# endregion
