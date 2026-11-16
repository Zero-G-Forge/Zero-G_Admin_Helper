# server_switch.py

import os

from PyQt6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout
from PyQt6.QtCore import Qt

from features.network.server_config import profile_label, set_server_name, switch_list_label
from features.paths import asset_path


def _apply_zah_theme(widget, label):
    """Loads assets/ZAH.css onto one dialog."""
    try:
        css_path = asset_path("ZAH.css")
        if os.path.exists(css_path):
            with open(css_path, "r", encoding="utf-8") as handle:
                widget.setStyleSheet(handle.read())
            print(f"[SUCCESS] {label}: Applied theme stylesheet from {css_path}")
        else:
            print(f"[WARNING] {label}: Stylesheet not found at {css_path}")
    except Exception as err:
        print(f"[ERROR] {label}: Failed to load stylesheet: {err}")


class ServerLoginDialog(QDialog):
    """
    Result of File > Log into another server.
    ask_to_save adds the "Save this server anyway?" question.
    """

    def __init__(self, message, ask_to_save=False, parent=None):
        super().__init__(parent)
        self.ask_to_save = ask_to_save
        self.setObjectName("ServerLoginDialog")
        self.setWindowTitle("Zero-G Admin Helper - Server Login")
        self.setFixedSize(520, 260)
        self.setModal(True)

        print("[DEBUG] ServerLoginDialog: Showing server login result...")
        self._build_form(message, ask_to_save)
        self._apply_theme()

    def _build_form(self, message, ask_to_save):
        """Builds the result text and Save / Cancel or OK."""
        self.master_layout = QVBoxLayout(self)
        self.master_layout.setContentsMargins(18, 18, 18, 18)
        self.master_layout.setSpacing(12)

        self.lbl_title = QLabel("SERVER LOGIN", self)
        self.lbl_title.setObjectName("ServerLoginTitle")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.master_layout.addWidget(self.lbl_title)

        self.lbl_message = QLabel(message, self)
        self.lbl_message.setObjectName("LoginResultMessage")
        self.lbl_message.setWordWrap(True)
        self.lbl_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.master_layout.addWidget(self.lbl_message)

        self.lbl_question = None
        self.btn_save = None
        self.btn_ok = None
        self.btn_cancel = None
        self.button_row = QHBoxLayout()

        if ask_to_save:
            self.lbl_question = QLabel("Save this server anyway?", self)
            self.lbl_question.setObjectName("SaveAnywayQuestion")
            self.lbl_question.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.master_layout.addWidget(self.lbl_question)

            self.btn_save = QPushButton("Save", self)
            self.btn_save.setObjectName("SaveLoginButton")
            self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_save.clicked.connect(self.accept)
            self.btn_cancel = QPushButton("Cancel", self)
            self.btn_cancel.setObjectName("CancelLoginButton")
            self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_cancel.clicked.connect(self.reject)
            self.button_row.addWidget(self.btn_save)
            self.button_row.addWidget(self.btn_cancel)
        else:
            self.btn_ok = QPushButton("OK", self)
            self.btn_ok.setObjectName("OkLoginButton")
            self.btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_ok.clicked.connect(self.accept)
            self.button_row.addWidget(self.btn_ok)

        self.master_layout.addLayout(self.button_row)

    def _apply_theme(self):
        """Loads assets/ZAH.css when it is present."""
        _apply_zah_theme(self, "ServerLoginDialog")


class ServerNameDialog(QDialog):
    """Asks for a display name. A blank name is allowed."""

    def __init__(self, initial="", parent=None):
        super().__init__(parent)
        self.entered_name = ""
        self.setObjectName("ServerNameDialog")
        self.setWindowTitle("Zero-G Admin Helper - Server Name")
        self.setFixedSize(460, 220)
        self.setModal(True)

        print("[DEBUG] ServerNameDialog: Asking for a server display name...")
        self._build_form(initial)
        self._apply_theme()

    def _build_form(self, initial):
        """Builds the name field and Save / Cancel."""
        self.master_layout = QVBoxLayout(self)
        self.master_layout.setContentsMargins(18, 18, 18, 18)
        self.master_layout.setSpacing(12)

        self.lbl_title = QLabel("NAME THIS SERVER", self)
        self.lbl_title.setObjectName("ServerNameTitle")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.master_layout.addWidget(self.lbl_title)

        self.name_input = QLineEdit(self)
        self.name_input.setObjectName("ServerNameInput")
        self.name_input.setPlaceholderText("Server name (optional)")
        self.name_input.setText(str(initial or ""))
        self.master_layout.addWidget(self.name_input)

        self.button_row = QHBoxLayout()
        self.btn_save = QPushButton("Save", self)
        self.btn_save.setObjectName("SaveNameButton")
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.clicked.connect(self._accept_name)
        self.btn_cancel = QPushButton("Cancel", self)
        self.btn_cancel.setObjectName("CancelNameButton")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        self.button_row.addWidget(self.btn_save)
        self.button_row.addWidget(self.btn_cancel)
        self.master_layout.addLayout(self.button_row)

    def _accept_name(self):
        """Stores the typed name, which may be blank, and closes."""
        self.entered_name = self.name_input.text().strip()
        print(f"[STATUS] Server display name entered: {self.entered_name or '(blank)'}")
        self.accept()

    def _apply_theme(self):
        """Loads assets/ZAH.css when it is present."""
        _apply_zah_theme(self, "ServerNameDialog")


class ServerSwitchDialog(QDialog):
    """Lets the operator pick a saved ZeroGBridge server profile."""

    def __init__(self, servers, active_index=0, parent=None):
        super().__init__(parent)
        self._servers = list(servers or [])
        self.selected_profile = None
        self._active_index = self._safe_index(active_index)

        self.setObjectName("ServerSwitchDialog")
        self.setWindowTitle("Zero-G Admin Helper - Switch Servers")
        self.setFixedSize(520, 280)
        self.setModal(True)

        print("[DEBUG] ServerSwitchDialog: Constructing server picker...")
        self._build_form()
        self._apply_theme()

    def _safe_index(self, active_index):
        """Clamps the active row so the combo and the (active) tag use the same index."""
        count = len(self._servers)
        if count <= 0:
            return 0
        try:
            if isinstance(active_index, bool):
                raise ValueError
            index = int(active_index)
        except (TypeError, ValueError):
            print(f"[WARNING] Switch dialog active_index {active_index!r} is not a number. Using the first profile.")
            return 0
        if index < 0 or index >= count:
            print(f"[WARNING] Switch dialog active_index {index} is outside the list. Using the first profile.")
            return 0
        return index

    def _row_label(self, index):
        """Name and IP only. The active row keeps the (active) marker."""
        label = switch_list_label(self._servers[index])
        if index == self._active_index:
            label = f"{label} (active)"
        return label

    def _build_form(self):
        """Builds the saved-server combo and the Switch / Rename / Cancel buttons."""
        self.master_layout = QVBoxLayout(self)
        self.master_layout.setContentsMargins(18, 18, 18, 18)
        self.master_layout.setSpacing(12)

        self.lbl_title = QLabel("SELECT SAVED SERVER", self)
        self.lbl_title.setObjectName("ServerSwitchTitle")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.master_layout.addWidget(self.lbl_title)

        self.server_picker = QComboBox(self)
        self.server_picker.setObjectName("ServerPicker")
        for index in range(len(self._servers)):
            self.server_picker.addItem(self._row_label(index))
        self.master_layout.addWidget(self.server_picker)

        self.error_label = QLabel("", self)
        self.error_label.setObjectName("ServerSwitchError")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.master_layout.addWidget(self.error_label)

        self.button_row = QHBoxLayout()
        self.btn_switch = QPushButton("Switch", self)
        self.btn_switch.setObjectName("SwitchServerButton")
        self.btn_switch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_switch.clicked.connect(self._accept_selection)

        self.btn_rename = QPushButton("Rename", self)
        self.btn_rename.setObjectName("RenameServerButton")
        self.btn_rename.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_rename.clicked.connect(self._rename_selected)

        self.btn_cancel = QPushButton("Cancel", self)
        self.btn_cancel.setObjectName("CancelSwitchButton")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)

        self.button_row.addWidget(self.btn_switch)
        self.button_row.addWidget(self.btn_rename)
        self.button_row.addWidget(self.btn_cancel)
        self.master_layout.addLayout(self.button_row)

    def _select_active_row(self):
        """Selects the active profile after the stylesheet, which can reset a combo."""
        if not self._servers:
            return
        self.server_picker.setCurrentIndex(self._active_index)
        print(f"[STATUS] Switch servers highlighting profile {self._active_index} as active.")

    def showEvent(self, event):
        """Re-applies the active row once the themed combo is on screen."""
        super().showEvent(event)
        self._select_active_row()

    def _accept_selection(self):
        """Stores the chosen profile and accepts the dialog."""
        if not self._servers:
            self.error_label.setText("NO SAVED SERVERS")
            return

        index = self.server_picker.currentIndex()
        if index < 0 or index >= len(self._servers):
            self.error_label.setText("SELECT A SERVER")
            return

        self.selected_profile = dict(self._servers[index])
        print(f"[UI EVENT] Switch servers selection: {profile_label(self.selected_profile)}")
        self.accept()

    def _rename_selected(self):
        """Edits the selected profile's display name and saves it."""
        if not self._servers:
            self.error_label.setText("NO SAVED SERVERS")
            return
        index = self.server_picker.currentIndex()
        if index < 0 or index >= len(self._servers):
            self.error_label.setText("SELECT A SERVER")
            return

        current = self._servers[index]
        ip = str(current.get("input_ip", "")).strip()
        print(f"[UI EVENT] Rename requested for {ip}.")
        dialog = ServerNameDialog(initial=current.get("server_name", ""), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            print("[STATUS] Server rename canceled.")
            return

        updated = set_server_name(ip, current.get("input_port", ""), dialog.entered_name)
        if not updated:
            self.error_label.setText("RENAME FAILED")
            print(f"[ERROR] Could not rename {ip}.")
            return

        self._servers[index] = updated
        self.server_picker.setItemText(index, self._row_label(index))
        self.error_label.setText("")
        print(f"[STATUS] Switch list now shows {switch_list_label(updated)}.")

    def _apply_theme(self):
        """Loads assets/ZAH.css, then selects the active row."""
        _apply_zah_theme(self, "ServerSwitchDialog")
        self._select_active_row()
