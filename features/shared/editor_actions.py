## ==========================================
## ZERO-G ADMIN HELPER - EDITOR ACTIONS
## The VALIDATE, CHANGES PREVIEW and SAVE buttons, shared by the ECF Editor and the PDA Editor.
## EditorActions is a mixin: a small class whose methods are added to a page class next to QWidget,
## e.g. class EcfEditorPage(EditorActions, QWidget). It expects the page to have btn_validate, btn_save,
## code_editor, txt_changes, lbl_backup, cmb_file, current_entry, original_text and server_folder.
## SAVE only writes the edited copy on this PC (data/server_files/<scenario>/_edits/), with a timestamped
## backup of the previous edited copy. The downloaded copy and the server are not changed by SAVE.
## ==========================================

# region Imports

import os

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QMessageBox

from features.server_files import edit_store
from features.shared.edit_tools import validate_text, has_errors, format_problems, make_diff, diff_counts

# endregion


# region Constants

## Text on the line along the bottom of both editors.
LOCAL_ONLY_TEXT = "Local copy only - server unchanged"

## Most problem lines shown in the VALIDATE window (the rest are counted).
MAX_SHOWN_PROBLEMS = 30

# endregion


# region EditorActions Class

class EditorActions:

    # region Setup

    def _setup_edit_buttons(self):
        """Connects VALIDATE and SAVE, and keeps their on/off state in step with the open file."""
        try:
            self.btn_validate.clicked.connect(self._on_validate_clicked)
            self.btn_save.clicked.connect(self._on_save_clicked)
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
        except Exception as e:
            print(f"[ERROR] EditorActions: Save failed: {e}")
            QMessageBox.warning(self, "Save failed", "The local copy could not be saved. Details are in the terminal.")

    # endregion

# endregion
