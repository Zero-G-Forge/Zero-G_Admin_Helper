## ==========================================
## ZERO-G ADMIN HELPER - ALERTS & ANTI-CHEAT PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Alerts_Anti-cheat.jpg:
## ALERT QUEUE on the left, the picked alert's details and EVIDENCE TIMELINE in the middle,
## COMMAND PREVIEW with the PREVIEW BAN button on the right.
## Layout only for now: there is no alert data source yet, so every panel shows "nothing yet".
## PREVIEW BAN stays greyed out; a ban is a real server action and gets its own step with Ray's OK.
## ==========================================

# region Imports

from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QGridLayout, QPushButton,
                             QTableWidget, QHeaderView, QAbstractItemView, QPlainTextEdit)

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

# endregion


# region Constants

## Columns of the alert detail table, as in the mockup.
DETAIL_COLUMNS = ["ITEM", "BEFORE", "AFTER", "DELTA"]

# endregion


# region AlertsPage Class

class AlertsPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("AlertsPage")
        self.setup_widgets()

    def setup_widgets(self):

        ## 3 columns: queue (narrow), details + timeline (wide), command preview (medium).
        ## The queue and command preview cards span both rows.
        page_grid = QGridLayout(self)
        page_grid.setContentsMargins(4, 4, 4, 4)
        page_grid.setHorizontalSpacing(14)
        page_grid.setVerticalSpacing(14)

        # region Alert Queue

        ## Each alert will be a row with a CRITICAL or WARNING badge and an ACK button.
        queue_card, queue_layout = make_card("ALERT QUEUE")
        self.lbl_queue_empty = QLabel("No alerts yet.")
        self.lbl_queue_empty.setObjectName("DashEmptyLabel")
        queue_layout.addWidget(self.lbl_queue_empty)
        queue_layout.addStretch()
        page_grid.addWidget(queue_card, 0, 0, 2, 1)

        # endregion

        # region Alert Details

        ## The title becomes the alert's name (e.g. INVENTORY JUMP DETECTED) once one is picked.
        detail_card, detail_layout = make_card("NO ALERT SELECTED")
        self.lbl_detail_title = detail_card.findChild(QLabel, "DashCardTitle")
        self.lbl_detail_player = QLabel("PLAYER:  --")
        self.lbl_detail_player.setObjectName("AlertPlayerLabel")
        detail_layout.addWidget(self.lbl_detail_player)

        self.tbl_detail = QTableWidget(0, len(DETAIL_COLUMNS))
        self.tbl_detail.setObjectName("DashTable")
        self.tbl_detail.setHorizontalHeaderLabels(DETAIL_COLUMNS)
        self.tbl_detail.verticalHeader().setVisible(False)
        self.tbl_detail.setShowGrid(False)
        self.tbl_detail.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_detail.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tbl_detail.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        detail_layout.addWidget(self.tbl_detail)
        self.lbl_detail_empty = QLabel("Pick an alert to see its details.")
        self.lbl_detail_empty.setObjectName("DashEmptyLabel")
        detail_layout.addWidget(self.lbl_detail_empty)
        page_grid.addWidget(detail_card, 0, 1)

        # endregion

        # region Evidence Timeline

        ## The dots-on-a-line timeline is drawn here once an alert has evidence times.
        timeline_card, timeline_layout = make_card("EVIDENCE TIMELINE")
        self.lbl_timeline_empty = QLabel("No evidence yet.")
        self.lbl_timeline_empty.setObjectName("DashEmptyLabel")
        timeline_layout.addWidget(self.lbl_timeline_empty)
        timeline_layout.addStretch()
        page_grid.addWidget(timeline_card, 1, 1)

        # endregion

        # region Command Preview

        ## Read-only box: shows the exact command before anything is sent, so nothing is a surprise.
        preview_card, preview_layout = make_card("COMMAND PREVIEW")
        self.txt_command_preview = QPlainTextEdit()
        self.txt_command_preview.setObjectName("AlertPreviewBox")
        self.txt_command_preview.setReadOnly(True)
        self.txt_command_preview.setPlaceholderText("No command yet.")
        preview_layout.addWidget(self.txt_command_preview, stretch=1)

        ## Amber outlined button from the mockup, greyed out until bans get their own step.
        self.btn_preview_ban = QPushButton("PREVIEW BAN")
        self.btn_preview_ban.setObjectName("AlertBanButton")
        self.btn_preview_ban.setMinimumHeight(52)
        self.btn_preview_ban.setEnabled(False)
        self.btn_preview_ban.setToolTip("Coming in a later step.")
        spread_letters(self.btn_preview_ban, 2.0)
        preview_layout.addWidget(self.btn_preview_ban)
        page_grid.addWidget(preview_card, 0, 2, 2, 1)

        # endregion

        ## Column widths roughly match the mockup: 3 : 5 : 4.
        page_grid.setColumnStretch(0, 3)
        page_grid.setColumnStretch(1, 5)
        page_grid.setColumnStretch(2, 4)

        ## The details card is a bit shorter than the timeline below it.
        page_grid.setRowStretch(0, 2)
        page_grid.setRowStretch(1, 3)

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return AlertsPage()

# endregion
