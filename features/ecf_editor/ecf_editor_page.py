## ==========================================
## ZERO-G ADMIN HELPER - ECF EDITOR PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/ECF_Editor.jpg:
## a toolbar (file picker, DOWNLOAD, VALIDATE, CHANGES PREVIEW, SAVE, UPLOAD) across the top,
## TRADERS on the left, the ITEMS table / CODE editor filling the rest, and a backup line along the bottom.
## (Ray, Nov 22, 2026: the VALIDATION plate was removed since VALIDATE is a button, and
## CHANGES PREVIEW moved to a toolbar button that opens it in its own window.)
## Layout only for now: no ECF file is loaded yet, so every panel shows "nothing yet".
## (Nov 22, 2026: the file dropdown now lists every .ecf in the downloaded server files, scenario and save,
## through load_server_files. With nothing downloaded it says how to download them.)
## UPLOAD TO SERVER changes the live server, so it stays locked until Ray OKs that step.
## ==========================================

# region Imports

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QPushButton, QComboBox, QLineEdit, QListWidget, QTableWidget,
                             QAbstractItemView, QHeaderView, QPlainTextEdit, QSizePolicy,
                             QStackedWidget, QButtonGroup, QDialog)

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

## The downloaded server files on this PC (never the local base game).
from features.server_files.local_files import NO_FILES_TEXT, current_scenario_folder, list_files

## The code-style editor (line numbers, colours, brace matching) for the CODE view.
from features.ecf_editor.ecf_code_editor import EcfCodeEditor

# endregion


# region Constants

## Columns of the ITEMS table, left to right.
ITEM_COLUMNS = ["ITEM NAME", "ID", "BUY PRICE", "SELL PRICE", "STOCK MIN-MAX"]

## Tooltip for every button that isn't wired up yet.
LATER_TIP = "Coming in a later step."

## The two ways to look at the file in the middle card: (key, tab text, card title).
VIEW_TABS = [("table", "TABLE", "ITEMS"), ("code", "CODE", "CODE")]

# endregion


# region EcfEditorPage Class

class EcfEditorPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("EcfEditorPage")
        self.setup_widgets()

        ## The picked file: its server entry ({"root", "path", "full", "label"}) and the text it had when opened.
        self.current_entry = None
        self.original_text = ""

        ## Fill the file dropdown from the downloaded server files (or say how to download them).
        self.load_server_files()

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
        ## After DOWNLOAD FOLDER, it lists every .ecf file in the downloaded folder.
        self.cmb_file = QComboBox()
        self.cmb_file.setObjectName("EcfFileCombo")
        self.cmb_file.setPlaceholderText("No files downloaded")
        self.cmb_file.setMinimumWidth(200)
        self.cmb_file.setEnabled(False)
        self.cmb_file.setToolTip(LATER_TIP)
        toolbar_layout.addWidget(self.cmb_file)

        ## Picking a file in the dropdown opens it in the CODE view.
        self.cmb_file.currentIndexChanged.connect(self._on_file_picked)

        ## Folder on this computer that holds the downloaded copies. None until a download has happened.
        self.local_folder = None

        ## The downloaded scenario folder (data/server_files/<scenario>), set by load_server_files.
        self.server_folder = None
        toolbar_layout.addStretch(1)

        ## DOWNLOAD only reads from the server; VALIDATE and SAVE work on the local copy.
        ## It copies the whole folder of .ecf files down, so any of them can be picked and edited here.
        self.btn_download = self._make_tool_button("DOWNLOAD FOLDER FROM SERVER (READ-ONLY)", "DashActionButton")
        self.btn_validate = self._make_tool_button("VALIDATE", "DashActionButton")

        ## CHANGES PREVIEW only shows the local edits, so it works now (it opens its own window).
        self.btn_changes = self._make_tool_button("CHANGES PREVIEW", "DashActionButton")
        self.btn_changes.setEnabled(True)
        self.btn_changes.setToolTip("See what you changed compared to the downloaded file.")
        self.btn_changes.clicked.connect(self._show_changes_preview)
        self.btn_save = self._make_tool_button("SAVE (BACKUP FIRST)", "DashActionButton")

        ## UPLOAD changes the live server, so it's amber with a lock, like the other server-changing buttons.
        self.btn_upload = self._make_tool_button("🔒  UPLOAD TO SERVER", "AlertBanButton")
        for tool_button in (self.btn_download, self.btn_validate, self.btn_changes, self.btn_save, self.btn_upload):
            toolbar_layout.addWidget(tool_button)
        page_grid.addWidget(toolbar_card, 0, 0, 1, 2)

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

        ## Keep the card's title label so it can say ITEMS or CODE to match the view.
        self.lbl_items_title = items_card.findChild(QLabel, "DashCardTitle")

        ## TABLE / CODE tabs: the same file shown as a tidy table or as the raw .ecf code.
        view_row = QHBoxLayout()
        view_row.setSpacing(4)
        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self.view_buttons = {}
        for view_key, view_text, view_title in VIEW_TABS:
            btn_view = QPushButton(view_text)
            btn_view.setObjectName("ChatTabButton")
            btn_view.setCheckable(True)
            btn_view.setMinimumHeight(30)
            spread_letters(btn_view, 1.5)

            ## The lambda passes this tab's key to _on_view_clicked.
            btn_view.clicked.connect(lambda checked, key=view_key: self._on_view_clicked(key))
            self.view_group.addButton(btn_view)
            self.view_buttons[view_key] = btn_view
            view_row.addWidget(btn_view)
        view_row.addStretch()
        items_layout.addLayout(view_row)

        ## The stack shows one view at a time: page 0 is the table, page 1 is the code editor.
        self.items_stack = QStackedWidget()
        table_view = QWidget()
        table_layout = QVBoxLayout(table_view)
        table_layout.setContentsMargins(0, 0, 0, 0)
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
        table_layout.addWidget(self.tbl_items, stretch=1)
        self.lbl_items_empty = QLabel("Pick a trader to see its items.")
        self.lbl_items_empty.setObjectName("DashEmptyLabel")
        table_layout.addWidget(self.lbl_items_empty)
        self.items_stack.addWidget(table_view)

        ## CODE view: the whole .ecf file, editable, coloured like code. It stays a local copy until SAVE.
        self.code_editor = EcfCodeEditor()
        self.items_stack.addWidget(self.code_editor)
        items_layout.addWidget(self.items_stack, stretch=1)
        self._on_view_clicked("table")
        page_grid.addWidget(items_card, 1, 1, 2, 1)

        # endregion

        # region Changes Preview

        ## Lines added (+, green) and removed (-, red) compared to the downloaded file. Read-only.
        ## It lives in its own window (opened by the CHANGES PREVIEW button) instead of on the page.
        self.changes_dialog = QDialog(self)
        self.changes_dialog.setObjectName("EcfChangesDialog")
        self.changes_dialog.setWindowTitle("Changes Preview")
        self.changes_dialog.resize(700, 480)
        changes_dialog_layout = QVBoxLayout(self.changes_dialog)
        changes_dialog_layout.setContentsMargins(0, 0, 0, 0)
        changes_card, changes_layout = make_card("CHANGES PREVIEW")
        self.txt_changes = QPlainTextEdit()
        self.txt_changes.setObjectName("EcfChangesBox")
        self.txt_changes.setReadOnly(True)
        self.txt_changes.setPlaceholderText("No changes yet.")
        changes_layout.addWidget(self.txt_changes, stretch=1)
        changes_dialog_layout.addWidget(changes_card)

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
        page_grid.addWidget(backup_card, 3, 0, 1, 2)

        # endregion

        ## Two columns now: the list (narrow) and the editor (wide), 3 : 10. The cards share the height between rows 1 and 2.
        page_grid.setColumnStretch(0, 3)
        page_grid.setColumnStretch(1, 10)
        page_grid.setRowStretch(1, 1)
        page_grid.setRowStretch(2, 1)

    # endregion

    # region Server Files

    def load_server_files(self, folder=None):
        """Fills the file dropdown from the downloaded server files. folder=None uses the last download."""
        try:
            if folder is None:
                folder = current_scenario_folder()
            self.server_folder = folder
            entries = list_files(folder, (".ecf",))

            ## blockSignals stops _on_file_picked firing for every name while the list is being filled.
            self.cmb_file.blockSignals(True)
            self.cmb_file.clear()
            for entry in entries:

                ## The whole entry rides along with each row, so picking it knows the exact local file.
                self.cmb_file.addItem(entry["label"], entry)
                self.cmb_file.setItemData(self.cmb_file.count() - 1, entry["root"] + "/" + entry["path"], Qt.ItemDataRole.ToolTipRole)
            self.cmb_file.setCurrentIndex(-1)
            self.cmb_file.blockSignals(False)
            self.cmb_file.setEnabled(bool(entries))
            if entries:
                self.cmb_file.setPlaceholderText("Pick a file")
                self.cmb_file.setToolTip("Pick a downloaded server file to edit.")
                self.code_editor.setPlaceholderText("Pick a file to edit.")
            else:
                self.cmb_file.setPlaceholderText("No files downloaded")
                self.cmb_file.setToolTip(NO_FILES_TEXT)
                self.code_editor.setPlaceholderText(NO_FILES_TEXT if folder is None else "The downloaded server files have no .ecf files.")
            return entries
        except Exception as e:
            print(f"[ERROR] EcfEditorPage: Could not list the downloaded server files: {e}")
            return []

    # endregion

    # region Local Files

    def load_local_folder(self, folder_path):
        """Fills the file dropdown with every .ecf file in a downloaded folder. Only reads this computer."""
        self.local_folder = folder_path
        try:
            file_names = sorted(name for name in os.listdir(folder_path) if name.lower().endswith(".ecf"))

        ## Folder missing or unreadable: show an empty, greyed dropdown instead of crashing.
        except OSError:
            file_names = []

        ## blockSignals stops _on_file_picked firing for every name while the list is being filled.
        self.cmb_file.blockSignals(True)
        self.cmb_file.clear()
        self.cmb_file.addItems(file_names)
        self.cmb_file.setCurrentIndex(-1)
        self.cmb_file.blockSignals(False)
        self.cmb_file.setEnabled(bool(file_names))
        self.cmb_file.setToolTip("Pick a file to edit." if file_names else LATER_TIP)
        return file_names

    def _on_file_picked(self, index):
        """Opens the picked file from the local folder in the CODE view."""
        if index < 0:
            return

        ## A row from load_server_files carries its full local path; a row from load_local_folder is a plain name.
        entry = self.cmb_file.itemData(index)
        if isinstance(entry, dict):
            file_path = entry["full"]
        elif self.local_folder is None:
            return
        else:
            file_path = os.path.join(self.local_folder, self.cmb_file.itemText(index))
        self.current_entry = entry if isinstance(entry, dict) else {"root": "", "path": self.cmb_file.itemText(index), "full": file_path, "label": self.cmb_file.itemText(index)}
        try:

            ## errors="replace" keeps odd characters from stopping the file opening.
            with open(file_path, encoding="utf-8", errors="replace") as ecf_file:
                file_text = ecf_file.read()
        except OSError:
            self.code_editor.load_text("")
            self.code_editor.setPlaceholderText("Could not open " + self.cmb_file.itemText(index) + ".")
            return
        self.original_text = file_text
        self.code_editor.load_text(file_text)
        self._on_view_clicked("code")

    # endregion

    # region Helpers

    def _show_changes_preview(self):
        """Opens the Changes Preview window (or brings it to the front if it's already open)."""
        self.changes_dialog.show()
        self.changes_dialog.raise_()
        self.changes_dialog.activateWindow()

    def _on_view_clicked(self, view_key):
        """Switches the middle card between the TABLE and CODE views and updates its title."""
        for index, (tab_key, tab_text, tab_title) in enumerate(VIEW_TABS):
            if tab_key == view_key:
                self.view_buttons[tab_key].setChecked(True)
                self.items_stack.setCurrentIndex(index)
                if self.lbl_items_title is not None:
                    self.lbl_items_title.setText(tab_title)

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
