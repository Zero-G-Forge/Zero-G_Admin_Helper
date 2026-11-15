# server_switch.py

import os

from PyQt6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from PyQt6.QtCore import Qt

from features.network.server_config import profile_label
from features.paths import asset_path


class ServerSwitchDialog(QDialog):
    """Lets the operator pick a saved ZeroGBridge server profile."""

    def __init__(self, servers, active_index=0, parent=None):
        super().__init__(parent)
        self._servers = list(servers or [])
        self.selected_profile = None

        self.setObjectName("ServerSwitchDialog")
        self.setWindowTitle("Zero-G Admin Helper - Switch Servers")
        self.setFixedSize(420, 220)
        self.setModal(True)

        print("[DEBUG] ServerSwitchDialog: Constructing server picker...")
        self._build_form(active_index)
        self._apply_theme()

    def _build_form(self, active_index):
        """Builds the saved-server combo and the Switch / Cancel buttons."""
        self.master_layout = QVBoxLayout(self)
        self.master_layout.setContentsMargins(18, 18, 18, 18)
        self.master_layout.setSpacing(12)

        self.lbl_title = QLabel("SELECT SAVED SERVER", self)
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setStyleSheet(
            "QLabel { color: #00ffff; font-family: 'Courier New'; font-weight: bold; font-size: 14px; }"
        )
        self.master_layout.addWidget(self.lbl_title)

        self.server_picker = QComboBox(self)
        self.server_picker.setObjectName("ServerPicker")
        for index, server in enumerate(self._servers):
            label = profile_label(server)
            if index == active_index:
                label = f"{label} (active)"
            self.server_picker.addItem(label)

        if self._servers:
            safe_index = active_index if 0 <= active_index < len(self._servers) else 0
            self.server_picker.setCurrentIndex(safe_index)
        self.master_layout.addWidget(self.server_picker)

        self.error_label = QLabel("", self)
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.setStyleSheet(
            "QLabel { color: #ff3333; font-family: 'Courier New'; font-size: 11px; font-weight: bold; }"
        )
        self.master_layout.addWidget(self.error_label)

        self.button_row = QHBoxLayout()
        self.btn_switch = QPushButton("Switch", self)
        self.btn_switch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_switch.clicked.connect(self._accept_selection)

        self.btn_cancel = QPushButton("Cancel", self)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)

        self.button_row.addWidget(self.btn_switch)
        self.button_row.addWidget(self.btn_cancel)
        self.master_layout.addLayout(self.button_row)

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

    def _apply_theme(self):
        """Loads assets/ZAH.css when it is present."""
        try:
            css_path = asset_path("ZAH.css")
            if os.path.exists(css_path):
                with open(css_path, "r", encoding="utf-8") as handle:
                    self.setStyleSheet(handle.read())
                print(f"[SUCCESS] ServerSwitchDialog: Applied theme stylesheet from {css_path}")
            else:
                print(f"[WARNING] ServerSwitchDialog: Stylesheet not found at {css_path}")
        except Exception as err:
            print(f"[ERROR] ServerSwitchDialog: Failed to load stylesheet: {err}")
