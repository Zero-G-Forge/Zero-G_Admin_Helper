## ==========================================
## ZERO-G ADMIN HELPER - ECF EDITOR PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/ECF_Editor.jpg:
## a toolbar (file picker, DOWNLOAD, VALIDATE, SAVE, UPLOAD) across the top,
## TRADERS on the left, ITEMS in the middle, VALIDATION and CHANGES PREVIEW on the right,
## and a backup line along the bottom.
## Layout only for now: no ECF file is loaded yet, so every panel shows "nothing yet".
## UPLOAD TO SERVER changes the live server, so it stays locked until Ray OKs that step.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QPushButton, QComboBox, QLineEdit, QListWidget, QTableWidget,
                             QAbstractItemView, QHeaderView, QPlainTextEdit, QSizePolicy)

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

# endregion


# region Constants

## Columns of the ITEMS table, left to right.
ITEM_COLUMNS = ["ITEM NAME", "ID", "BUY PRICE", "SELL PRICE", "STOCK MIN-MAX"]

## Tooltip for every button that isn't wired up yet.
LATER_TIP = "Coming in a later step."

# endregion


# region EcfEditorPage Class

class EcfEditorPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("EcfEditorPage")
        self.setup_widgets()

    def setup_widgets(self):

        ## Toolbar on row 0 across all 3 columns, the 3 columns of cards on rows 1-2, the backup line on row 3.
        page_grid = QGridLayout(self)
        page_grid.setContentsMargins(4, 4, 4, 4)
        page_grid.setHorizontalSpacing(14)
        page_grid.setVerticalSpacing(14)

        # region Toolbar

        ## A card with no title: just the file picker and the 4 buttons in a row.
        toolbar_card = QFrame()
        toolbar_card.setObjectName("DashCard")
        toolbar_layout = QHBoxLayout(toolbar_card)
        toolbar_layout.setContentsMargins(14, 10, 14, 10)
        toolbar_layout.setSpacing(12)

        ## Which ECF file to edit, e.g. TraderNPCConfig.ecf. Empty until the files are read from the server.
        self.cmb_file = QComboBox()
        self.cmb_file.setObjectName("EcfFileCombo")
        self.cmb_file.setPlaceholderText("No file loaded")
        self.cmb_file.setMinimumWidth(200)
        self.cmb_file.setEnabled(False)
        self.cmb_file.setToolTip(LATER_TIP)
        toolbar_layout.addWidget(self.cmb_file)
        toolbar_layout.addStretch(1)

        ## DOWNLOAD only reads from the server; VALIDATE and SAVE work on the local copy.
        self.btn_download = self._make_tool_button("DOWNLOAD FROM SERVER (READ-ONLY)", "DashActionButton")
        self.btn_validate = self._make_tool_button("VALIDATE", "DashActionButton")
        self.btn_save = self._make_tool_button("SAVE (BACKUP FIRST)", "DashActionButton")

        ## UPLOAD changes the live server, so it's amber with a lock, like the other server-changing buttons.
        self.btn_upload = self._make_tool_button("🔒  UPLOAD TO SERVER", "AlertBanButton")
        for tool_button in (self.btn_download, self.btn_validate, self.btn_save, self.btn_upload):
            toolbar_layout.addWidget(tool_button)
        page_grid.addWidget(toolbar_card, 0, 0, 1, 3)

        # endregion

        # region Traders

        ## Search box over the list of traders found in the file.
        traders_card, traders_layout = make_card("TRADERS")
        self.txt_trader_search = QLineEdit()
        self.txt_trader_search.setObjectName("EcfSearchBox")
        self.txt_trader_search.setPlaceholderText("Search traders")
        self.txt_trader_search.setClearButtonEnabled(True)
        traders_layout.addWidget(self.txt_trader_search)
        self.lst_traders = QListWidget()
        self.lst_traders.setObjectName("EcfTraderList")
        traders_layout.addWidget(self.lst_traders, stretch=1)
        self.lbl_traders_empty = QLabel("No traders yet.")
        self.lbl_traders_empty.setObjectName("DashEmptyLabel")
        traders_layout.addWidget(self.lbl_traders_empty)
        page_grid.addWidget(traders_card, 1, 0, 2, 1)

        # endregion

        # region Items

        ## The picked trader's items. A warning icon will mark rows that fail validation.
        items_card, items_layout = make_card("ITEMS")
        self.tbl_items = QTableWidget(0, len(ITEM_COLUMNS))
        self.tbl_items.setObjectName("DashTable")
        self.tbl_items.setHorizontalHeaderLabels(ITEM_COLUMNS)
        self.tbl_items.verticalHeader().setVisible(False)
        self.tbl_items.setShowGrid(False)
        self.tbl_items.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_items.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_items.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_items.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        ## ITEM NAME takes the spare width; the number columns fit their header text (so STOCK MIN-MAX isn't cut off).
        self.tbl_items.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        items_layout.addWidget(self.tbl_items, stretch=1)
        self.lbl_items_empty = QLabel("Pick a trader to see its items.")
        self.lbl_items_empty.setObjectName("DashEmptyLabel")
        items_layout.addWidget(self.lbl_items_empty)
        page_grid.addWidget(items_card, 1, 1, 2, 1)

        # endregion

        # region Validation

        ## Each check will be a line with a green tick or a red warning, e.g. "Brackets OK".
        validation_card, validation_layout = make_card("VALIDATION")
        self.validation_box = QFrame()
        self.validation_box.setObjectName("DashInnerBox")
        self.validation_box_layout = QVBoxLayout(self.validation_box)
        self.validation_box_layout.setContentsMargins(12, 10, 12, 10)
        self.validation_box_layout.setSpacing(8)
        self.lbl_validation_empty = QLabel("Not validated yet.")
        self.lbl_validation_empty.setObjectName("DashEmptyLabel")
        self.validation_box_layout.addWidget(self.lbl_validation_empty)
        validation_layout.addWidget(self.validation_box)
        validation_layout.addStretch()
        page_grid.addWidget(validation_card, 1, 2)

        # endregion

        # region Changes Preview

        ## Lines added (+, green) and removed (-, red) compared to the downloaded file. Read-only.
        changes_card, changes_layout = make_card("CHANGES PREVIEW")
        self.txt_changes = QPlainTextEdit()
        self.txt_changes.setObjectName("EcfChangesBox")
        self.txt_changes.setReadOnly(True)
        self.txt_changes.setPlaceholderText("No changes yet.")
        changes_layout.addWidget(self.txt_changes, stretch=1)
        page_grid.addWidget(changes_card, 2, 2)

        # endregion

        # region Backup Line

        ## Which backup SAVE made, and a reminder that only the local copy changes until UPLOAD.
        backup_card = QFrame()
        backup_card.setObjectName("DashCard")
        backup_layout = QHBoxLayout(backup_card)
        backup_layout.setContentsMargins(18, 10, 18, 10)
        self.lbl_backup = QLabel("Backup:  --     |     Local copy only - server unchanged")
        self.lbl_backup.setObjectName("EcfBackupLabel")
        backup_layout.addWidget(self.lbl_backup)
        backup_layout.addStretch()
        page_grid.addWidget(backup_card, 3, 0, 1, 3)

        # endregion

        ## Column widths roughly match the mockup: 3 : 6 : 4. The cards share the height between rows 1 and 2.
        page_grid.setColumnStretch(0, 3)
        page_grid.setColumnStretch(1, 6)
        page_grid.setColumnStretch(2, 4)
        page_grid.setRowStretch(1, 1)
        page_grid.setRowStretch(2, 1)

    # endregion

    # region Helpers

    def _make_tool_button(self, button_text, object_name):
        """Builds one toolbar button, greyed out until its step is wired up."""
        btn = QPushButton(button_text)
        btn.setObjectName(object_name)
        btn.setFixedHeight(36)
        btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        btn.setEnabled(False)
        btn.setToolTip(LATER_TIP)
        return btn

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return EcfEditorPage()

# endregion
