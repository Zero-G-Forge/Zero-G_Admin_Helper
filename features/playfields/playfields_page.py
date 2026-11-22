## ==========================================
## ZERO-G ADMIN HELPER - PLAYFIELDS PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Playfields.jpg:
## the playfield map on top left, BULK ACTIONS (UNLOAD / RESTART PLAYFIELD / WIPE) on top right,
## and a row of playfield cards (name, players, structures) along the bottom.
## Layout only for now: there is no playfield data source yet, so the map and cards show "nothing yet".
## All bulk actions stay greyed out; each one changes the server and gets its own step with Ray's OK.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton)

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
        self.setup_widgets()

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
            btn_bulk.setToolTip("Coming in a later step.")
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

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return PlayfieldsPage()

# endregion
