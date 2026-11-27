## ==========================================
## ZERO-G ADMIN HELPER - EPB EDITOR PAGE
## Editor for Empyrion blueprint files (.epb), opened from the EDITORS group in the nav column.
## Same layout idea as the ECF and PDA Editors (Ray, Nov 27, 2026):
## a toolbar (file picker and buttons) across the top, BLUEPRINTS on the left,
## BLUEPRINT DETAILS filling the rest, and a backup line along the bottom.
## Starter page only for now: no .epb file is read yet, so every panel shows "nothing yet"
## and every button stays off until its step is built.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QHBoxLayout, QGridLayout,
                             QPushButton, QComboBox, QSizePolicy,
                             QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card

## Read-only device list from a .epb file.
from features.epb_editor.epb_core import (list_device_records, format_fields)

# endregion


# region Constants

## Tooltip for every button that isn't wired up yet.
LATER_TIP = "Coming in a later step."

# endregion


# region EpbEditorPage Class

class EpbEditorPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("EpbEditorPage")
        self.setup_widgets()

        ## When a file is picked, fill the device table.
        self.cmb_file.currentIndexChanged.connect(self._on_file_picked)

    def setup_widgets(self):

        ## Toolbar on row 0 across both columns, the 2 cards on row 1, the backup line on row 2.
        page_grid = QGridLayout(self)
        page_grid.setContentsMargins(4, 4, 4, 4)
        page_grid.setHorizontalSpacing(14)
        page_grid.setVerticalSpacing(14)

        # region Toolbar

        ## A card with no title: just the file picker and the buttons in a row.
        toolbar_card = QFrame()
        toolbar_card.setObjectName("DashCard")
        toolbar_layout = QHBoxLayout(toolbar_card)
        toolbar_layout.setContentsMargins(14, 10, 14, 10)
        toolbar_layout.setSpacing(12)

        ## Which blueprint to open, e.g. a base or ship .epb. Empty until blueprint reading is built.
        self.cmb_file = QComboBox()
        ## Same combo style as the ECF and PDA Editors (EcfFileCombo in ZAH_main.css).
        self.cmb_file.setObjectName("EcfFileCombo")
        self.cmb_file.setPlaceholderText("No blueprints loaded")
        self.cmb_file.setMinimumWidth(200)
        self.cmb_file.setEnabled(False)
        self.cmb_file.setToolTip(LATER_TIP)
        toolbar_layout.addWidget(self.cmb_file)
        toolbar_layout.addStretch(1)

        ## Buttons are off for now; each one gets wired up in its own step.
        self.btn_validate = self._make_tool_button("VALIDATE", "DashActionButton")
        self.btn_save = self._make_tool_button("SAVE", "DashActionButton")
        toolbar_layout.addWidget(self.btn_validate)
        toolbar_layout.addWidget(self.btn_save)
        page_grid.addWidget(toolbar_card, 0, 0, 1, 2)

        # endregion

        # region Blueprints

        ## Each blueprint will be a row with its name and type (BA, CV, SV, HV, POI).
        blueprints_card, blueprints_layout = make_card("BLUEPRINTS")
        self.lbl_blueprints_empty = QLabel("No blueprints loaded yet.")
        self.lbl_blueprints_empty.setObjectName("DashEmptyLabel")
        blueprints_layout.addWidget(self.lbl_blueprints_empty)
        blueprints_layout.addStretch()
        page_grid.addWidget(blueprints_card, 1, 0)

        # endregion

        # region Blueprint Details

        ## The picked blueprint's details will show here.
        details_card, details_layout = make_card("BLUEPRINT DETAILS")

        ## Read-only list of device records in the file.
        self.tbl_devices = QTableWidget(0, 3)
        self.tbl_devices.setObjectName("DashTable")
        self.tbl_devices.setHorizontalHeaderLabels(["OFFSET", "TYPE", "FIELDS"])
        self.tbl_devices.verticalHeader().setVisible(False)
        self.tbl_devices.setShowGrid(False)
        self.tbl_devices.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_devices.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_devices.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.tbl_devices.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        details_layout.addWidget(self.tbl_devices, stretch=1)
        self.lbl_details_empty = QLabel("Pick a blueprint to see its details.")
        self.lbl_details_empty.setObjectName("DashEmptyLabel")
        self.lbl_details_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        details_layout.addWidget(self.lbl_details_empty)
        page_grid.addWidget(details_card, 1, 1)

        # endregion

        # region Backup Line

        ## Which backup SAVE made, and a reminder that only the local copy changes, like the other editors.
        backup_card = QFrame()
        backup_card.setObjectName("DashCard")
        backup_layout = QHBoxLayout(backup_card)
        backup_layout.setContentsMargins(18, 10, 18, 10)
        self.lbl_backup = QLabel("Backup:  --     |     Local copy only - server unchanged")
        self.lbl_backup.setObjectName("EcfBackupLabel")
        backup_layout.addWidget(self.lbl_backup)
        backup_layout.addStretch()
        page_grid.addWidget(backup_card, 2, 0, 1, 2)

        # endregion

        ## Column widths: blueprint list narrow, details wide (3 : 7). The cards row takes the spare height.
        page_grid.setColumnStretch(0, 3)
        page_grid.setColumnStretch(1, 7)
        page_grid.setRowStretch(1, 1)

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

    def _on_file_picked(self, index):
        ## An empty pick clears the table.
        if index < 0:
            self._fill_device_table("")
            return
        path = self.cmb_file.itemData(index)
        if not path:
            path = self.cmb_file.itemText(index)
        self._fill_device_table(path)

    def _fill_device_table(self, path):
        ## Read-only: lists records, never writes.
        self.tbl_devices.setRowCount(0)
        if not path:
            self.lbl_details_empty.show()
            return
        try:
            records = list_device_records(path)
        except Exception:
            self.lbl_details_empty.setText("Could not read that blueprint.")
            self.lbl_details_empty.show()
            return
        if not records:
            self.lbl_details_empty.setText("No device records in that file.")
            self.lbl_details_empty.show()
            return
        self.lbl_details_empty.hide()
        self.tbl_devices.setRowCount(len(records))
        for row, rec in enumerate(records):
            offset_item = QTableWidgetItem(str(rec["offset"]))
            kind_item = QTableWidgetItem(rec["kind"])
            fields_item = QTableWidgetItem(format_fields(rec["fields"]))
            self.tbl_devices.setItem(row, 0, offset_item)
            self.tbl_devices.setItem(row, 1, kind_item)
            self.tbl_devices.setItem(row, 2, fields_item)

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return EpbEditorPage()

# endregion
