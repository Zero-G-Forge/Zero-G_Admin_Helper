## ==========================================
## ZERO-G ADMIN HELPER - EDITOR ACTIONS
## The VALIDATE, CHANGES PREVIEW and SAVE buttons, shared by the ECF Editor and the PDA Editor.
## EditorActions is a mixin: a small class whose methods are added to a page class next to QWidget,
## e.g. class EcfEditorPage(EditorActions, QWidget). It expects the page to have btn_validate, btn_save,
## code_editor, txt_changes, lbl_backup, cmb_file, current_entry, original_text and server_folder.
## SAVE only writes the edited copy on this PC (data/server_files/<scenario>/_edits/), with a timestamped
## backup of the previous edited copy. The downloaded copy and the server are not changed by SAVE.
## UPLOAD TO SERVER (and SAVE while LIVE MODE is on) sends the edited text with files:put after three
## confirmations (upload_flow.py). Only users the role gate allows get the button; the bridge backs up the
## server's old file first, and refuses when the server copy changed since it was downloaded.
## ==========================================

# region Imports

import os

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QMessageBox

from features.server_files import edit_store, upload_flow
from features.server_files.write_worker import ServerWriteWorker, fetch_file, put_file, start_write_worker
from features.shared.edit_tools import validate_text, has_errors, format_problems, make_diff, diff_counts

# endregion


# region Constants

## Text on the line along the bottom of both editors.
LOCAL_ONLY_TEXT = "Local copy only - server unchanged"

## Most problem lines shown in the VALIDATE window (the rest are counted).
MAX_SHOWN_PROBLEMS = 30

## Text on the bottom line while LIVE MODE is on.
LIVE_TEXT = "LIVE MODE - SAVE also uploads to the server"

## Builds the write thread. A test can swap this for one that talks to the local harness.
CREATE_WRITE_WORKER = ServerWriteWorker

# endregion


# region EditorActions Class

class EditorActions:

    # region Setup

    ## Qt calls showEvent each time the page appears, so UPLOAD follows the latest bridge state and LIVE MODE.
    def showEvent(self, event):
        super().showEvent(event)
        try:
            self._refresh_edit_buttons()
        except Exception as e:
            print(f"[ERROR] EditorActions: Could not refresh on show: {e}")

    def _setup_edit_buttons(self):
        """Connects VALIDATE and SAVE, and keeps their on/off state in step with the open file."""
        try:
            self.btn_validate.clicked.connect(self._on_validate_clicked)
            self.btn_save.clicked.connect(self._on_save_clicked)

            ## UPLOAD is only usable for users the role gate allows (checked again before anything is sent).
            self.upload_worker = None
            self.btn_upload.clicked.connect(self._on_upload_clicked)
            self.code_editor.textChanged.connect(self._refresh_edit_buttons)
            self._refresh_edit_buttons()
        except Exception as e:
            print(f"[ERROR] EditorActions: Could not connect the edit buttons: {e}")

    def _refresh_edit_buttons(self):
        """VALIDATE needs an open file. SAVE needs an open downloaded server file (it has a place to save to)."""
        try:
            has_file = self.current_entry is not None
            can_save = has_file and bool(self.server_folder) and bool(self.current_entry.get("root"))
            self.btn_validate.setEnabled(has_file)
            self.btn_validate.setToolTip("Check the open file for mistakes, with line numbers." if has_file else "Open a file first.")
            self.btn_save.setEnabled(can_save)
            self.btn_save.setToolTip("Save the edited copy on this PC. The last saved copy is backed up first." if can_save
                                     else "Open a downloaded server file first.")
            self._refresh_upload_button(can_save)
        except Exception as e:
            print(f"[ERROR] EditorActions: Could not refresh the edit buttons: {e}")

    def _after_file_opened(self):
        """Called by the page right after it loaded the downloaded copy. Shows the edited copy instead when
        there is one. Returns the text now in the editor."""
        try:
            entry = self.current_entry
            if entry and self.server_folder and entry.get("root") and edit_store.has_edit(self.server_folder, entry):
                edited_text, came_from_edit = edit_store.load_editor_text(self.server_folder, entry)
                self.code_editor.load_text(edited_text)
                self.lbl_backup.setText("Backup:  --     |     Showing your saved edit     |     " + LOCAL_ONLY_TEXT)
            else:
                self.lbl_backup.setText("Backup:  --     |     " + LOCAL_ONLY_TEXT)
            self._refresh_edit_buttons()

            ## LIVE MODE: fetch the server's current copy once per opened file (read-only files:get).
            if upload_flow.live_mode_on(self) and entry and entry.get("root") and self.server_folder:
                self._live_refresh_open_file()
            return self.code_editor.toPlainText()
        except Exception as e:
            print(f"[ERROR] EditorActions: Could not load the saved edit: {e}")
            return self.code_editor.toPlainText()

    # endregion

    # region Validate

    def _on_validate_clicked(self):
        """Checks the editor text and lists every problem with its line number. Jumps to the first one."""
        try:
            if self.current_entry is None:
                return
            file_name = self.current_entry["path"].split("/")[-1]
            problems = validate_text(file_name, self.code_editor.toPlainText())
            if not problems:
                QMessageBox.information(self, "Validate", file_name + ": no problems found.")
                return
            shown = format_problems(problems[:MAX_SHOWN_PROBLEMS])
            if len(problems) > MAX_SHOWN_PROBLEMS:
                shown.append(f"and {len(problems) - MAX_SHOWN_PROBLEMS} more.")
            errors = sum(1 for problem in problems if problem["level"] == "error")
            title = f"{file_name}: {errors} error(s), {len(problems) - errors} warning(s)"
            box = QMessageBox(QMessageBox.Icon.Warning if errors else QMessageBox.Icon.Information, "Validate", title, parent=self)
            box.setDetailedText("\n".join(shown))
            box.setInformativeText("\n".join(shown[:8]))
            box.exec()
            self._jump_to_line(problems[0]["line"])
        except Exception as e:
            print(f"[ERROR] EditorActions: Validate failed: {e}")

    def _jump_to_line(self, line_number):
        """Moves the editor's cursor to a line (1 = first line)."""
        block = self.code_editor.document().findBlockByNumber(max(0, line_number - 1))
        if block.isValid():
            cursor = self.code_editor.textCursor()
            cursor.setPosition(block.position())
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            self.code_editor.setTextCursor(cursor)
            self.code_editor.centerCursor()

    # endregion

    # region Changes Preview

    def _refresh_changes(self):
        """Fills the Changes Preview with a real diff: the downloaded copy against the editor text."""
        try:
            if self.current_entry is None:
                self.txt_changes.setPlainText("")
                return []
            file_name = self.current_entry["path"].split("/")[-1]
            diff_lines = make_diff(self.original_text, self.code_editor.toPlainText(), file_name)
            if not diff_lines:
                self.txt_changes.setPlainText("")
                self.txt_changes.setPlaceholderText("No changes yet: the text matches the downloaded file.")
                return []
            added, removed = diff_counts(diff_lines)
            self.txt_changes.setPlainText(f"{added} line(s) added, {removed} line(s) removed\n\n" + "\n".join(diff_lines))
            return diff_lines
        except Exception as e:
            print(f"[ERROR] EditorActions: Could not build the changes preview: {e}")
            return []

    # endregion

    # region Save

    def _on_save_clicked(self):
        """Saves the edited copy on this PC, after VALIDATE. Errors ask first; No is the default."""
        try:
            entry = self.current_entry
            if entry is None or not self.server_folder or not entry.get("root"):
                return
            file_name = entry["path"].split("/")[-1]
            text = self.code_editor.toPlainText()
            problems = validate_text(file_name, text)
            if has_errors(problems):
                answer = QMessageBox.question(
                    self, "Save with errors?",
                    f"VALIDATE found {sum(1 for p in problems if p['level'] == 'error')} error(s) in {file_name}.\n"
                    f"First: {format_problems(problems[:1])[0]}\n\nSave the local copy anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
            result = edit_store.save_edit(self.server_folder, entry, text)
            backup_name = os.path.basename(result["backup"]) if result["backup"] else "-- (first save)"
            self.lbl_backup.setText("Backup:  " + backup_name + "     |     Saved " + file_name + "     |     " + LOCAL_ONLY_TEXT)
            print(f"[SUCCESS] EditorActions: Saved edit of {entry['root']}/{entry['path']}, backup {backup_name}")

            ## LIVE MODE: the local save is followed by the same three-step upload.
            if upload_flow.live_mode_on(self):
                self._on_upload_clicked()
        except Exception as e:
            print(f"[ERROR] EditorActions: Save failed: {e}")
            QMessageBox.warning(self, "Save failed", "The local copy could not be saved. Details are in the terminal.")

    # endregion

    # region Upload

    def _upload_block_reason(self):
        """Why UPLOAD is off right now, or "" when it may be used."""
        entry = self.current_entry
        if entry is None or not self.server_folder or not entry.get("root"):
            return "Open a downloaded server file first."
        if not upload_flow.user_can_write_server_files(self):
            return "Server uploads are for developer and owner, or an admin/moderator given Live file editing."
        if not upload_flow.bridge_is_connected(self):
            return "Connect to the server first."
        if self.upload_worker is not None:
            return "An upload is running."
        return ""

    def _refresh_upload_button(self, can_save=True):
        """Turns UPLOAD on only when the role gate, the bridge and the open file all allow it."""
        try:
            reason = self._upload_block_reason() if can_save else "Open a downloaded server file first."
            self.btn_upload.setEnabled(reason == "")
            self.btn_upload.setToolTip("Upload the edited text to the server after three confirmations. "
                                       "The bridge backs up the server's old file first." if reason == "" else reason)
            if upload_flow.live_mode_on(self) and LIVE_TEXT not in self.lbl_backup.text():
                self.lbl_backup.setText(self.lbl_backup.text() + "     |     " + LIVE_TEXT)
        except Exception as e:
            print(f"[ERROR] EditorActions: Could not refresh the upload button: {e}")

    def _on_upload_clicked(self):
        """Step 0 checks, then confirmation 1 (changes), then a read-only player count for confirmation 2."""
        try:
            reason = self._upload_block_reason()
            if reason:
                QMessageBox.information(self, "Upload", reason)
                return
            entry = self.current_entry
            file_name = entry["path"].split("/")[-1]
            text = self.code_editor.toPlainText()
            diff_lines = make_diff(self.original_text, text, file_name)
            if not diff_lines:
                QMessageBox.information(self, "Upload", "Nothing to upload: the text matches the server copy.")
                return

            ## Errors must be fixed before anything goes to the server (SAVE may still keep them locally).
            problems = validate_text(file_name, text)
            if has_errors(problems):
                QMessageBox.warning(self, "Upload stopped", f"VALIDATE found errors in {file_name}. Fix them first.\n"
                                    f"First: {format_problems(problems[:1])[0]}")
                return
            if not upload_flow.ask_changes(self, file_name, diff_lines):
                print("[INFO] EditorActions: Upload cancelled at step 1. Nothing was sent.")
                return
            self.btn_upload.setEnabled(False)
            self.btn_upload.setToolTip("Reading the online players.")
            from features.zgb_portal.live_client import run_async
            run_async(upload_flow.fetch_players_for_upload, self._continue_upload,
                      lambda kind, message: self._continue_upload(None))
        except Exception as e:
            print(f"[ERROR] EditorActions: Upload failed to start: {e}")
            self._refresh_edit_buttons()

    def _continue_upload(self, players_payload):
        """Confirmation 2 (players) and 3 (type the name), then the upload thread."""
        try:
            self._refresh_edit_buttons()
            entry = self.current_entry
            if entry is None:
                return
            file_name = entry["path"].split("/")[-1]
            online_count, names = upload_flow.count_online(players_payload)
            if not upload_flow.ask_players(self, online_count, names):
                print("[INFO] EditorActions: Upload cancelled at step 2. Nothing was sent.")
                return
            if not upload_flow.ask_type_name(self, file_name):
                print("[INFO] EditorActions: Upload cancelled at step 3 (name not typed). Nothing was sent.")
                return

            ## Last line of defense: the role gate is asked again right before the send.
            if self._upload_block_reason():
                return
            text = self.code_editor.toPlainText()
            edit_store.save_edit(self.server_folder, entry, text)
            data = edit_store.text_to_bytes(text, edit_store.detect_newline(entry["full"]))
            base = edit_store.base_sha256(self.server_folder, entry)
            root, path = entry["root"], entry["path"]
            worker = CREATE_WRITE_WORKER(lambda session, report: put_file(session, root, path, data, base, report))
            worker.finished_ok.connect(lambda reply, e=entry, d=data, t=text: self._on_upload_done(e, d, t, reply))
            worker.failed.connect(self._on_upload_failed)
            self.upload_worker = worker
            self._refresh_edit_buttons()
            self.lbl_backup.setText("Uploading " + file_name + "     |     do not close ZAH")
            start_write_worker(worker)
        except Exception as e:
            print(f"[ERROR] EditorActions: Upload failed: {e}")
            self.upload_worker = None
            self._refresh_edit_buttons()

    def _on_upload_done(self, entry, data, text, reply):
        """The server has the new file: the downloaded copy and its base follow it."""
        try:
            self.upload_worker = None
            edit_store.record_upload(self.server_folder, entry, data)
            if entry is self.current_entry:
                self.original_text = text
                self._refresh_changes()
            backup = os.path.basename(str(reply.get("backup") or "")) or "--"
            self.lbl_backup.setText("Server backup:  " + backup + "     |     Uploaded " + entry["path"].split("/")[-1])
            print(f"[SUCCESS] EditorActions: Uploaded {entry['root']}/{entry['path']}, server backup {backup}")
            self._refresh_edit_buttons()
        except Exception as e:
            print(f"[ERROR] EditorActions: Upload finished but the local copy was not updated: {e}")

    def _on_upload_failed(self, kind, code, message):
        """Explains a refused or broken upload. The server file is unchanged in every case here."""
        try:
            self.upload_worker = None
            self._refresh_edit_buttons()
            if code == "changed_on_server":
                message = ("The server's copy changed since it was downloaded, so nothing was replaced. "
                           "Download the file again, then redo the edit.")
            self.lbl_backup.setText("Upload failed     |     server unchanged")
            QMessageBox.warning(self, "Upload failed", message)
        except Exception as e:
            print(f"[ERROR] EditorActions: Could not show the upload error: {e}")

    def _live_refresh_open_file(self):
        """LIVE MODE: reads the open file from the server; when it differs, the local copy follows it."""
        try:
            entry = self.current_entry
            if getattr(self, "_live_fetching", None) is not None:
                return
            root, path = entry["root"], entry["path"]
            worker = CREATE_WRITE_WORKER(lambda session, report: {"data": fetch_file(session, root, path)})
            worker.finished_ok.connect(lambda result, e=entry: self._on_live_fetched(e, result.get("data")))
            worker.failed.connect(lambda kind, code, message: self._on_live_fetch_failed(message))
            self._live_fetching = worker
            start_write_worker(worker)
        except Exception as e:
            print(f"[ERROR] EditorActions: Live read failed to start: {e}")

    def _on_live_fetched(self, entry, data):
        try:
            self._live_fetching = None
            if not isinstance(data, bytes) or entry is not self.current_entry:
                return
            with open(entry["full"], "rb") as file_handle:
                same = file_handle.read() == data
            if same:
                return

            ## The server copy is newer: back up the old download, take the server's copy, open it again.
            edit_store.record_upload(self.server_folder, entry, data)
            self.original_text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
            if not edit_store.has_edit(self.server_folder, entry):
                self.code_editor.load_text(self.original_text)
            self._refresh_changes()
            self.lbl_backup.setText(self.lbl_backup.text() + "     |     Server copy was newer: loaded")
        except Exception as e:
            print(f"[ERROR] EditorActions: Live read could not be applied: {e}")

    def _on_live_fetch_failed(self, message):
        self._live_fetching = None
        print(f"[ERROR] EditorActions: Live read failed: {message}")

    # endregion

# endregion
