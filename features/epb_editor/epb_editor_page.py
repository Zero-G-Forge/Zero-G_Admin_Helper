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

import hashlib
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QFileDialog, QInputDialog, QMessageBox, QWidget, QFrame, QLabel, QHBoxLayout, QGridLayout, QLineEdit,
                             QPushButton, QComboBox, QSizePolicy, QListWidget, QListWidgetItem,
                             QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)
from PyQt6.QtWidgets import QStyledItemDelegate
from PyQt6.QtGui import QColor, QPen

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card

## Read-only device list from a .epb file.
from features.epb_editor.epb_core import (list_device_records, format_fields)

## Writes one field, always with a backup first.
from features.epb_editor.epb_core import (set_field_value, TYPE_STRING, TYPE_FLOAT, TYPE_COLOR)

## The downloaded server files on this PC
## (never the local base game).
from features.server_files.local_files import (NO_FILES_TEXT, current_scenario_folder, list_files)

## Edited-copy bookkeeping and the three upload questions,
## shared with the ECF and PDA Editors.
from features.server_files import edit_store, upload_flow

## The thread and the step that send a file to the server.
from features.server_files.write_worker import (ServerWriteWorker, put_file, start_write_worker)

## The Wipe playfields button: which playfields use the
## uploaded prefabs, and the steps that wipe their POIs.
from features.epb_editor import wipe_flow, wipe_lookup

## The role check, Safety Flow and audit log the wipe uses.
from features.shared import server_actions

# endregion


# region Constants

## Tooltip for every button that isn't wired up yet.
LATER_TIP = "Coming in a later step."

## Builds the upload thread. A test can swap in a fake one.
CREATE_WRITE_WORKER = ServerWriteWorker

## The folder UPLOAD opens first, inside the downloaded
## files (where the patched prefabs are kept).
PATCHED_FOLDER = "patched_prefabs"

## Bottom line text after an upload that did not go through.
FAILED_TEXT = "Upload failed     |     server unchanged"

## Marks a device row whose fields no longer
## match the file as it was first opened (or
## the oldest .bak_ copy next to it).
EDITED_ROLE = int(Qt.ItemDataRole.UserRole) + 1
EDITED_OUTLINE = QColor(51, 214, 255, 120)

# endregion


# region Edited Rows

def _oldest_epb_backup(path):
    ## The first backup made before an edit,
    ## e.g. name.epb.bak_20261127_143000.
    folder = os.path.dirname(path)
    prefix = os.path.basename(path) + ".bak_"
    matches = []
    try:
        for name in os.listdir(folder or "."):
            if name.startswith(prefix):
                matches.append(
                    os.path.join(folder, name))
    except OSError:
        return None
    if not matches:
        return None
    return min(matches)


class EditedRowDelegate(QStyledItemDelegate):
    """Draws a dim cyan box around an edited row."""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.column() != 0:
            return
        if not index.data(EDITED_ROLE):
            return
        table = self.parent()
        rect = option.rect
        if table is not None:
            rect.setLeft(0)
            rect.setWidth(
                table.viewport().width())
        painter.save()
        painter.setPen(QPen(EDITED_OUTLINE, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(
            rect.adjusted(0, 0, -1, -1))
        painter.restore()

# endregion


# region EpbEditorPage Class

class EpbEditorPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("EpbEditorPage")
        self.setup_widgets()

        ## Fill the blueprint list from the downloaded files, if any.
        self.load_server_files()

        ## When a file is picked, fill the device table.
        self.cmb_file.currentIndexChanged.connect(self._on_file_picked)

        ## UPLOAD picks the edited files and sends them.
        self.btn_upload.clicked.connect(self._on_upload_clicked)

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

        ## Sends edited prefabs to the server
        ## (see the Upload region).
        self.btn_upload = self._make_tool_button("🔒  UPLOAD TO SERVER", "AlertBanButton")
        toolbar_layout.addWidget(self.btn_upload)
        page_grid.addWidget(toolbar_card, 0, 0, 1, 2)

        # endregion

        # region Blueprints

        ## Each blueprint will be a row with its name and type (BA, CV, SV, HV, POI).
        blueprints_card, blueprints_layout = make_card("BLUEPRINTS")

        ## Type part of a name to narrow the list.
        self.txt_blueprint_search = QLineEdit()
        self.txt_blueprint_search.setObjectName("EcfSearchBox")
        self.txt_blueprint_search.setPlaceholderText("Search blueprints")
        self.txt_blueprint_search.setClearButtonEnabled(True)
        self.txt_blueprint_search.textChanged.connect(self._filter_blueprints)
        blueprints_layout.addWidget(self.txt_blueprint_search)

        ## Click a name to show its device records.
        self.lst_blueprints = QListWidget()
        self.lst_blueprints.setObjectName("EcfTraderList")
        self.lst_blueprints.itemClicked.connect(self._on_blueprint_clicked)
        blueprints_layout.addWidget(self.lst_blueprints, stretch=1)

        self.lbl_blueprints_empty = QLabel("No blueprints loaded yet.")
        self.lbl_blueprints_empty.setObjectName("DashEmptyLabel")
        blueprints_layout.addWidget(self.lbl_blueprints_empty)
        page_grid.addWidget(blueprints_card, 1, 0)

        # endregion

        # region Blueprint Details

        ## The picked blueprint's details will show here.
        details_card, details_layout = make_card("BLUEPRINT DETAILS")

        ## Read-only list of device records in the file.
        self.tbl_devices = QTableWidget(0, 3)
        self.tbl_devices.setObjectName("DashTable")
        self.tbl_devices.setHorizontalHeaderLabels(["OFFSET", "TYPE", "FIELDS"])

        ## Hide the row numbers (the check keeps VS Code happy).
        row_header = self.tbl_devices.verticalHeader()
        if row_header is not None:
            row_header.setVisible(False)
        self.tbl_devices.setShowGrid(False)
        self.tbl_devices.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_devices.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_devices.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_devices.setItemDelegate(
            EditedRowDelegate(self.tbl_devices))

        ## Double-click a row to pick a field and type a new value.
        self.tbl_devices.cellDoubleClicked.connect(self._on_device_double_clicked)

        ## Columns fit their text; FIELDS takes the spare width.
        header = self.tbl_devices.horizontalHeader()
        if header is not None:
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

        ## Remember what is open, for editing.
        self.current_path = path
        self.records = []
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
        self.records = records
        self.tbl_devices.setRowCount(len(records))
        for row, rec in enumerate(records):
            offset_item = QTableWidgetItem(str(rec["offset"]))
            kind_item = QTableWidgetItem(rec["kind"])
            fields_text = format_fields(rec["fields"])
            fields_item = QTableWidgetItem(fields_text)
            self.tbl_devices.setItem(row, 0, offset_item)
            self.tbl_devices.setItem(row, 1, kind_item)
            self.tbl_devices.setItem(row, 2, fields_item)
            if self._row_is_edited(
                path, row, records, fields_text):
                offset_item.setData(
                    EDITED_ROLE, True)

    def _original_field_rows(self, path, records):
        ## One fields string per row, from the first
        ## look at this file, or from its oldest
        ## backup if the file was already edited.
        stored = getattr(
            self, "_original_fields", None)
        if stored is None:
            stored = {}
            self._original_fields = stored
        if path not in stored:
            source = _oldest_epb_backup(path)
            if source:
                try:
                    records = list_device_records(
                        source)
                except Exception:
                    pass
            stored[path] = [
                format_fields(rec["fields"])
                for rec in records]
        return stored[path]

    def _row_is_edited(self, path, row,
                      records, fields_text):
        original = self._original_field_rows(
            path, records)
        if row >= len(original):
            return True
        return fields_text != original[row]

    def _on_blueprint_clicked(self, item):
        ## Open the clicked blueprint in the table.
        path = item.data(Qt.ItemDataRole.UserRole)
        self._fill_device_table(path or "")

    def _filter_blueprints(self, text):
        ## Hide rows whose name doesn't match.
        needle = text.strip().lower()
        for row in range(self.lst_blueprints.count()):
            item = self.lst_blueprints.item(row)
            if item is None:
                continue

            ## An empty box shows every row.
            match = needle in item.text().lower()
            item.setHidden(not match)

    # endregion

    # region Server Files

    def load_server_files(self, folder=None):
        ## Lists .epb files under Prefabs in the local copy.
        try:
            if folder is None:
                folder = current_scenario_folder()
            self.server_folder = folder
            entries = list_files(folder, (".epb",), under=("Prefabs",))
            self.lst_blueprints.clear()
            prefix = "Prefabs/"
            for entry in entries:
                rel = entry["path"]

                ## Hide the Prefabs/ part of the name.
                if rel.lower().startswith(prefix.lower()):
                    rel = rel[len(prefix):]
                item = QListWidgetItem(rel)

                ## The full path rides along, hidden.
                item.setData(Qt.ItemDataRole.UserRole, entry["full"])
                item.setToolTip(entry["root"] + "/" + entry["path"])
                self.lst_blueprints.addItem(item)
            if entries:
                self.lbl_blueprints_empty.hide()
            else:
                if folder is None:
                    text = NO_FILES_TEXT
                else:
                    text = "No blueprints in the downloaded files."
                self.lbl_blueprints_empty.setText(text)
                self.lbl_blueprints_empty.show()
        except Exception as exc:
            print("[ERROR] EpbEditorPage: Could not list the downloaded blueprints: " + str(exc))
            self.lbl_blueprints_empty.setText(NO_FILES_TEXT)
            self.lbl_blueprints_empty.show()

    # endregion

    # region Editing

    def _can_edit(self, path):
        ## Only files inside the downloaded server
        ## folder, never the local base game.
        folder = getattr(self, "server_folder", None)
        if not path or not folder:
            return False
        root = os.path.realpath(folder) + os.sep
        return os.path.realpath(path).startswith(root)

    def _entry_for(self, path):
        ## Where a downloaded scenario file lives on the
        ## server, e.g. root scenario, path Prefabs/Name.epb.
        ## None if the file is outside the scenario folder.
        folder = getattr(self, "server_folder", None)
        if not path or not folder:
            return None
        base = os.path.join(folder, "scenario")
        try:
            rel = os.path.relpath(path, base)
            rel = rel.replace(os.sep, "/")
        except ValueError:
            return None
        if rel.split("/")[0] == "..":
            return None
        return {"root": "scenario", "path": rel, "full": path}

    def _on_device_double_clicked(self, row, column):
        ## Pick a field, type a value, confirm, save.
        records = getattr(self, "records", [])
        if row < 0 or row >= len(records):
            return
        path = self.current_path
        if not self._can_edit(path):
            QMessageBox.warning(self, "EPB Editor", "Only the downloaded server files can be edited.")
            return
        rec = records[row]

        ## Colors can't be typed, so they are skipped.
        by_key = {}
        for field in rec["fields"]:
            if field["type"] != TYPE_COLOR:
                by_key[field["key"]] = field
        if not by_key:
            return
        key, ok = QInputDialog.getItem(self, "Edit field", "Field:", list(by_key), 0, False)
        if not ok:
            return
        field = by_key[key]

        ## Show floats short, e.g. 0.3 not 0.30000001.
        if field["type"] == TYPE_FLOAT:
            old_text = f"{field['value']:.6g}"
        else:
            old_text = str(field["value"])

        ## Text can have several lines (LCD screens).
        if field["type"] == TYPE_STRING:
            new_text, ok = QInputDialog.getMultiLineText(self, "Edit field", key + " =", old_text)
        else:
            new_text, ok = QInputDialog.getText(self, "Edit field", key + " =", text=old_text)
        if not ok or new_text == old_text:
            return

        ## Before/after check before anything is written.
        message = "File: " + os.path.basename(path) + "\n" + "Field: " + key + "\n\n" + "Before: " + old_text + "\n" + "After:  " + new_text + "\n\n" + "A backup is made first. Only the local copy changes."
        buttons = QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel
        answer = QMessageBox.question(self, "Save change?", message, buttons)
        if answer != QMessageBox.StandardButton.Save:
            return
        try:
            ## Remember the server's version of the file, once, before the first edit changes it (for upload).
            entry = self._entry_for(path)
            if entry is not None:
                folder = self.server_folder
                edit_store.remember_original(folder, entry)

            ## Write the new value, always with a backup first. The backup name is returned.
            ## The table is reloaded to show the new value, and the backup name is shown.
            result = set_field_value(path, rec["offset"], key, new_text)
        except Exception as exc:
            QMessageBox.warning(self, "EPB Editor", "Could not save: " + str(exc))
            return

        ## Show the backup name, then reload the table.
        self.lbl_backup.setText("Backup:  " + os.path.basename(result["backup"]) + "     |     Local copy only - server unchanged")
        self._fill_device_table(path)
        self.tbl_devices.selectRow(row)

    # endregion

    # region Upload

    ## The sending thread, and the files it will send.
    upload_worker = None
    pending_jobs = None

    ## The playfields ticked for a wipe, until it is sent.
    pending_wipe = None

    def showEvent(self, event):
        ## Each time the page appears, UPLOAD follows the
        ## latest bridge state and role.
        super().showEvent(event)
        self._refresh_upload_button()

    def _upload_block_reason(self):
        ## Why UPLOAD is off right now,
        ## or "" when it may be used.
        if not getattr(self, "server_folder", None):
            return "Download the server files first."
        if not upload_flow.user_can_write_server_files(self):
            return ("Uploads are for developer and owner, or Live file editing.")
        if not upload_flow.bridge_is_connected(self):
            return "Connect to the server first."
        if self.upload_worker is not None:
            return "An upload is running."
        return ""

    def _refresh_upload_button(self):
        reason = self._upload_block_reason()
        self.btn_upload.setEnabled(reason == "")
        if reason == "":
            reason = ("Replace server prefabs with edited copies (backed up first).")
        self.btn_upload.setToolTip(reason)

    def _check_upload_file(self, path):
        ## Returns (job, "") for a file worth sending,
        ## or (None, the reason it was skipped).
        name = os.path.basename(path)

        ## The page only gets here with a server folder ("" keeps Pylance happy).
        folder = self.server_folder or ""
        downloaded = os.path.join(folder, "scenario", "Prefabs", name)
        entry = self._entry_for(downloaded)
        if entry is None or not os.path.isfile(downloaded):
            return None, name + ": not in the downloaded Prefabs."
        try:
            ## An unreadable blueprint never goes up.
            list_device_records(path)
            with open(path, "rb") as file_handle:
                data = file_handle.read()
        except Exception:
            return None, name + ": not a readable blueprint."

        ## Same as the server's version: nothing to send.
        base = edit_store.base_sha256(folder, entry)
        if hashlib.sha256(data).hexdigest() == base:
            return None, name + ": same as the server copy."
        return {"entry": entry, "data": data, "base": base}, ""

    def _on_upload_clicked(self):
        try:
            self._pick_and_confirm()
        except Exception as exc:
            print("[ERROR] EpbEditor: Upload did not start: " + str(exc))
            self._refresh_upload_button()

    def _pick_and_confirm(self):
        ## Gates, pick files, confirmation 1, then a
        ## read-only player count for confirmation 2.
        reason = self._upload_block_reason()
        if reason:
            QMessageBox.information(self, "Upload", reason)
            return
        folder = self.server_folder or ""
        start = os.path.join(folder, PATCHED_FOLDER)
        if not os.path.isdir(start):
            start = folder
        paths, _ = QFileDialog.getOpenFileNames(self, "Pick the edited blueprints", start, "Blueprints (*.epb)")
        if not paths:
            return
        jobs = []
        skipped = []
        for path in paths:
            job, why = self._check_upload_file(path)
            if job is None:
                skipped.append(why)
            else:
                jobs.append(job)
        if not jobs:
            QMessageBox.information(self, "Upload", "Nothing to upload:\n" + "\n".join(skipped))
            return
        names = [job["entry"]["path"] for job in jobs]
        if not upload_flow.ask_files(self, names, skipped):
            print("[INFO] EpbEditor: Cancelled at step 1.")
            return
        self.pending_jobs = jobs
        self.btn_upload.setEnabled(False)
        self.btn_upload.setToolTip("Reading the online players.")
        from features.zgb_portal.live_client import run_async
        run_async(upload_flow.fetch_players_for_upload, self._continue_upload, lambda kind, message: self._continue_upload(None))

    
    def _continue_upload(self, players_payload):
        try:
            self._confirm_and_send(players_payload)
        except Exception as exc:
            print("[ERROR] EpbEditor: Upload failed: " + str(exc))
            self.upload_worker = None
            self._refresh_upload_button()

    def _confirm_and_send(self, players_payload):
        ## Confirmation 2 (players), 3 (type the name),
        ## then send.
        self._refresh_upload_button()
        jobs = self.pending_jobs
        if not jobs:
            return
        found = upload_flow.count_online(players_payload)
        if not upload_flow.ask_players(self, found[0], found[1]):
            print("[INFO] EpbEditor: Cancelled at step 2.")
            return

        ## One file: type its name.
        ## Several: type UPLOAD 3 FILES (the number).
        if len(jobs) == 1:
            label = jobs[0]["entry"]["path"].split("/")[-1]
        else:
            label = "UPLOAD " + str(len(jobs)) + " FILES"
        if not upload_flow.ask_type_name(self, label):
            print("[INFO] EpbEditor: Cancelled at step 3.")
            return

        ## Last line of defense: the gates are asked
        ## again right before sending.
        if self._upload_block_reason():
            return
        worker = CREATE_WRITE_WORKER(lambda s, report: self._send_jobs(s, jobs, report))
        worker.finished_ok.connect(self._on_upload_done)
        worker.failed.connect(self._on_upload_failed)
        self.upload_worker = worker
        self._refresh_upload_button()
        self.lbl_backup.setText("Uploading " + str(len(jobs)) + " file(s)     |     do not close ZAH")
        start_write_worker(worker)

    def _send_jobs(self, session, jobs, report):
        ## Runs on the worker thread: one file at a time,
        ## stops at the first problem.
        done = []
        error = None
        for job in jobs:
            entry = job["entry"]
            try:
                reply = put_file(session, entry["root"], entry["path"], job["data"], job["base"], report)
            except Exception as exc:
                code = getattr(exc, "code", "") or ""
                error = (entry["path"], code, str(exc))
                break
            backup = str(reply.get("backup") or "")
            done.append((job, backup))
        return {"done": done, "error": error}

    def _on_upload_done(self, result):
        ## The server has the files: each downloaded copy
        ## and its base follow it (the old copy is
        ## backed up first).
        try:
            self.upload_worker = None
            names = []
            backup = "--"
            for job, backup_path in result["done"]:
                entry = job["entry"]
                edit_store.record_upload(self.server_folder, entry, job["data"])
                names.append(entry["path"].split("/")[-1])
                backup = os.path.basename(backup_path) or "--"
            self._refresh_upload_button()
            bar = "     |     "
            if len(names) == 1:
                self.lbl_backup.setText("Server backup:  " + backup + bar + "Uploaded " + names[0])
            elif names:
                self.lbl_backup.setText("Server backups made" + bar + "Uploaded " + str(len(names)) + " files")
            print("[SUCCESS] EpbEditor: Uploaded " + ", ".join(names))

            ## Show every picked file and how it went.
            wipe_asked = self._show_upload_results(result)
            error = result["error"]
            if error:
                if not names:
                    self.lbl_backup.setText(FAILED_TEXT)
                self._show_upload_error(error[1], error[2], error[0])

            ## The Wipe playfields button was clicked: start
            ## it now, after any error popup is closed.
            if wipe_asked:
                self._start_wipe(names)

        except Exception as exc:
            print("[ERROR] EpbEditor: Uploaded, but the local copy was not updated: " + str(exc))

    def _on_upload_failed(self, kind, code, message):
        ## The thread itself stopped: nothing was replaced.
        self.upload_worker = None
        self._refresh_upload_button()
        self.lbl_backup.setText(FAILED_TEXT)
        self._show_upload_error(code, message)

    def _show_upload_results(self, result):
        ## One line per picked file: its status and the
        ## server backup made for it.
        lines = []
        sent = []
        for job, backup_path in result["done"]:
            path = job["entry"]["path"]
            sent.append(path)
            backup = os.path.basename(backup_path) or "--"
            lines.append("SUCCESS File uploaded   " + path + "   (server backup: " + backup + ")")

        ## Files that were picked but did not go up.
        error = result["error"]
        for job in self.pending_jobs or []:
            path = job["entry"]["path"]
            if path in sent:
                continue
            if error and path == error[0]:
                lines.append("UPLOAD FAILED     " + path)
            else:
                lines.append("UPLOAD NOT SENT   " + path)

        ## The popup has a Wipe playfields button when at
        ## least one file went up. True = it was clicked.
        text = "\n".join(lines)
        return wipe_flow.ask_results(self, text, bool(sent))
    
    def _show_upload_error(self, code, message, name=""):
        if code == "changed_on_server":
            prefix = ""
            if name:
                prefix = name + ": "
            message = (prefix + "the server's copy changed since it was downloaded, so nothing was replaced. Download the file again, then redo the edit.")
        QMessageBox.warning(self, "Upload failed", message)

    # endregion

    # region Wipe Playfields

    def _start_wipe(self, names):
        ## names: the uploaded prefab file names. Finds the
        ## playfields that use them, then shows their list.
        action = wipe_flow.WIPE_ACTION
        reason = server_actions.block_reason(self, action)
        if reason:
            title = "Wipe playfields"
            QMessageBox.information(self, title, reason)
            return
        folder = self.server_folder or ""
        scenario = os.path.join(folder, "scenario")
        lookup = wipe_lookup.playfields_for_prefabs
        rows, missing = lookup(scenario, names)
        ask = wipe_flow.ask_playfields
        picked = ask(self, rows, missing)
        if not picked:
            return
        self.pending_wipe = picked

        ## A fresh, read-only player list for step 2.
        from features.zgb_portal import live_client
        read = upload_flow.fetch_players_for_upload

        def no_players(kind, message):
            self._continue_wipe(None)

        live_client.run_async(read, self._continue_wipe, no_players)

    def _continue_wipe(self, players_payload):
        ## Step 2 (players on those playfields), then the
        ## Safety Flow and the send.
        try:
            picked = self.pending_wipe or []
            self.pending_wipe = None
            if not picked:
                return
            flow = wipe_flow
            online = flow.online_on_playfields
            found = online(players_payload, picked)
            if not flow.ask_wipe_players(self, found):
                print("[INFO] EpbEditor: Wipe stopped (2).")
                return
            done = self._on_wipe_done
            flow.start_wipes(self, picked, done)
        except Exception as exc:
            text = str(exc)
            print("[ERROR] EpbEditor: Wipe failed: " + text)

    def _on_wipe_done(self, results):
        ## Every playfield and how it went.
        try:
            wipe_flow.show_results(self, results)
            count = str(len(results))
            note = "[INFO] EpbEditor: Wiped " + count
            print(note + " playfield(s).")
        except Exception as exc:
            text = str(exc)
            print("[ERROR] EpbEditor: Wipe: " + text)

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return EpbEditorPage()

# endregion
