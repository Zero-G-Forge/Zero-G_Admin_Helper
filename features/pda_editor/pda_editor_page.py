## ==========================================
## ZERO-G ADMIN HELPER - PDA EDITOR PAGE
## Same layout as the ECF Editor (Ray, Nov 22, 2026):
## a toolbar (file picker, DOWNLOAD FOLDER, VALIDATE, CHANGES PREVIEW, SAVE, UPLOAD) across the top,
## CHAPTERS on the left, the CODE editor filling the rest, and a backup line along the bottom.
## PDA files live on the server in Content/Scenarios/<scenario>/Extras/PDA (PDA.yaml plus its PDA.csv text).
## Download, edit, upload: edits only change the local copy until UPLOAD, which stays locked until Ray OKs that step.
## ==========================================

# region Imports

import csv
import os
import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QPushButton, QComboBox, QLineEdit, QListWidget, QListWidgetItem,
                             QPlainTextEdit, QSizePolicy, QDialog)

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

## The same code editor as the ECF Editor (line numbers, current line, brace matching), with YAML colours.
from features.ecf_editor.ecf_code_editor import EcfCodeEditor
from features.pda_editor.pda_yaml_highlighter import PdaYamlHighlighter

# endregion


# region Constants

## Tooltip for every button that isn't wired up yet.
LATER_TIP = "Coming in a later step."

## File types the dropdown lists from the downloaded PDA folder.
PDA_FILE_TYPES = (".yaml", ".csv")

## Finds chapter lines like '  - ChapterTitle: pda_uW0W4W4' and keeps the title.
CHAPTER_PATTERN = re.compile(r"^\s*-\s*ChapterTitle:\s*(.+?)\s*$")

## The text file next to PDA.yaml: one row per text id (KEY) with a column per language.
PDA_TEXT_FILE = "PDA.csv"

## Game colour and style tags inside PDA text, e.g. [c][ff0000][b]READ FIRST[/b][-][/c] -> READ FIRST
STYLE_TAG_PATTERN = re.compile(r"\[/?[a-z]\]|\[[0-9a-fA-F]{6}\]|\[-\]")

# endregion


# region PdaEditorPage Class

class PdaEditorPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("PdaEditorPage")
        self.setup_widgets()

    def setup_widgets(self):

        ## Toolbar on row 0 across both columns, the list and editor on row 1, the backup line on row 2.
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

        ## Which PDA file to edit (PDA.yaml or PDA.csv). Empty until the folder is downloaded.
        self.cmb_file = QComboBox()
        self.cmb_file.setObjectName("EcfFileCombo")
        self.cmb_file.setPlaceholderText("No files downloaded")
        self.cmb_file.setMinimumWidth(200)
        self.cmb_file.setEnabled(False)
        self.cmb_file.setToolTip(LATER_TIP)
        toolbar_layout.addWidget(self.cmb_file)

        ## Picking a file in the dropdown opens it in the editor.
        self.cmb_file.currentIndexChanged.connect(self._on_file_picked)

        ## Folder on this computer that holds the downloaded copies. None until a download has happened.
        self.local_folder = None
        toolbar_layout.addStretch(1)

        ## DOWNLOAD only reads from the server; VALIDATE and SAVE work on the local copy.
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

        # region Chapters

        ## Every chapter found in PDA.yaml. Clicking one jumps the editor to it.
        chapters_card, chapters_layout = make_card("CHAPTERS")
        self.txt_chapter_search = QLineEdit()
        self.txt_chapter_search.setObjectName("EcfSearchBox")
        self.txt_chapter_search.setPlaceholderText("Search chapters")
        self.txt_chapter_search.setClearButtonEnabled(True)
        self.txt_chapter_search.textChanged.connect(self._filter_chapters)
        chapters_layout.addWidget(self.txt_chapter_search)
        self.lst_chapters = QListWidget()
        self.lst_chapters.setObjectName("EcfTraderList")
        self.lst_chapters.itemClicked.connect(self._on_chapter_clicked)
        chapters_layout.addWidget(self.lst_chapters, stretch=1)
        self.lbl_chapters_empty = QLabel("No chapters yet.")
        self.lbl_chapters_empty.setObjectName("DashEmptyLabel")
        chapters_layout.addWidget(self.lbl_chapters_empty)
        page_grid.addWidget(chapters_card, 1, 0)

        # endregion

        # region Code

        ## The whole PDA file, editable, coloured like code. It stays a local copy until SAVE.
        code_card, code_layout = make_card("CODE")
        self.code_editor = EcfCodeEditor(highlighter_class=PdaYamlHighlighter)
        code_layout.addWidget(self.code_editor, stretch=1)
        page_grid.addWidget(code_card, 1, 1)

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
        page_grid.addWidget(backup_card, 2, 0, 1, 2)

        # endregion

        ## Two columns: the list (narrow) and the editor (wide), 3 : 10. The editor row takes the spare height.
        page_grid.setColumnStretch(0, 3)
        page_grid.setColumnStretch(1, 10)
        page_grid.setRowStretch(1, 1)

    # endregion

    # region Local Files

    def load_local_folder(self, folder_path):
        """Fills the file dropdown with the PDA files in a downloaded folder. Only reads this computer."""
        self.local_folder = folder_path
        try:
            file_names = sorted(name for name in os.listdir(folder_path) if name.lower().endswith(PDA_FILE_TYPES))

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
        """Opens the picked file from the local folder in the editor and lists its chapters."""
        if index < 0 or self.local_folder is None:
            return
        file_path = os.path.join(self.local_folder, self.cmb_file.itemText(index))
        try:

            ## errors="replace" keeps odd characters from stopping the file opening.
            with open(file_path, encoding="utf-8", errors="replace") as pda_file:
                file_text = pda_file.read()
        except OSError:
            self.code_editor.load_text("")
            self.code_editor.setPlaceholderText("Could not open " + self.cmb_file.itemText(index) + ".")
            file_text = ""
        else:
            self.code_editor.load_text(file_text)
        self._fill_chapters(file_text)

    # endregion

    # region Chapters

    def _fill_chapters(self, file_text):
        """Lists every '- ChapterTitle:' line. Each list row remembers its line number for jumping."""
        self.lst_chapters.clear()

        ## English names from PDA.csv, so the list says "SEND US YOUR FEEDBACK!" instead of pda_m88uV8C.
        chapter_names = self._read_pda_names()
        for line_number, line_text in enumerate(file_text.splitlines()):
            chapter_match = CHAPTER_PATTERN.match(line_text)
            if chapter_match:
                chapter_id = chapter_match.group(1)

                ## No name found: fall back to the id. Hovering a row always shows its id.
                chapter_item = QListWidgetItem(chapter_names.get(chapter_id) or chapter_id)
                chapter_item.setToolTip(chapter_id)

                ## UserRole is a hidden slot on the row, used here to store the line number.
                chapter_item.setData(Qt.ItemDataRole.UserRole, line_number)
                self.lst_chapters.addItem(chapter_item)
        self.lbl_chapters_empty.setVisible(self.lst_chapters.count() == 0)
        self._filter_chapters(self.txt_chapter_search.text())

    def _filter_chapters(self, search_text):
        """Hides chapters that don't contain the search text (upper/lower case doesn't matter)."""
        search_text = search_text.strip().lower()
        for row in range(self.lst_chapters.count()):
            chapter_item = self.lst_chapters.item(row)

            ## Search finds a chapter by its name or by its pda_ id.
            searchable_text = (chapter_item.text() + " " + chapter_item.toolTip()).lower()
            chapter_item.setHidden(bool(search_text) and search_text not in searchable_text)

    def _read_pda_names(self):
        """Reads PDA.csv from the local folder into {text id: English name}. Empty if it's missing."""
        chapter_names = {}
        if self.local_folder is None:
            return chapter_names
        try:

            ## newline="" lets the csv module handle line breaks inside quoted text.
            with open(os.path.join(self.local_folder, PDA_TEXT_FILE), encoding="utf-8", errors="replace", newline="") as text_file:
                for row in csv.DictReader(text_file):
                    english_text = STYLE_TAG_PATTERN.sub("", row.get("English") or "").strip()
                    if row.get("KEY") and english_text:
                        chapter_names[row["KEY"]] = english_text

        ## No PDA.csv (or unreadable): the list just shows the ids.
        except (OSError, csv.Error):
            pass
        return chapter_names

    def _on_chapter_clicked(self, chapter_item):
        """Moves the editor's cursor to the chapter's line and scrolls it near the top."""
        line_number = chapter_item.data(Qt.ItemDataRole.UserRole)
        block = self.code_editor.document().findBlockByNumber(line_number)
        if not block.isValid():
            return
        cursor = self.code_editor.textCursor()
        cursor.setPosition(block.position())
        self.code_editor.setTextCursor(cursor)
        self.code_editor.verticalScrollBar().setValue(max(0, line_number - 2))
        self.code_editor.setFocus()

    # endregion

    # region Helpers

    def _show_changes_preview(self):
        """Opens the Changes Preview window (or brings it to the front if it's already open)."""
        self.changes_dialog.show()
        self.changes_dialog.raise_()
        self.changes_dialog.activateWindow()

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
    return PdaEditorPage()

# endregion
