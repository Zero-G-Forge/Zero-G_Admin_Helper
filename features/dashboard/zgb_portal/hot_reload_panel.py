#!/usr/bin/env python3
"""ZeroGBridge Portal: Loader + Bridge viewer for Zero-G Admin Helper.

Opened from the main window via View > ZeroGBridge Portal.

Viewer only. It uses fake loader/core/API/script data and QTimer-driven
reload steps. It never opens a socket and never sends commands (no
hot:reload / hot:rollback) to any live game server.

Tabs:
  LOADER  - core versions, reload, rollback, history, log (simulated)
  BRIDGE  - Empyrion/ModAPI catalog + IronPython (.py) script editor (simulated)

Data comes from a PortalDataSource (data_source.py). For now that is
SampleDataSource, which reads <ZAH>/Examples/ZGB_Portal/.
"""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from features.paths import asset_path

from .bridge_panel import BridgePanel
from .data_source import HistoryEntry, LoaderState, PortalDataSource, SampleDataSource

# ---------------------------------------------------------------------------
# Paths & theme
# ---------------------------------------------------------------------------

# All portal files live inside the ZAH package, next to this module.
HERE = Path(__file__).resolve().parent
ZAH_CSS = Path(asset_path("ZAH.css"))
TZ = ZoneInfo("America/Chicago")
FONT_FAMILY = '"Courier Prime", "Courier New", "DejaVu Sans Mono", monospace'

# Result / status colors used across the cockpit (online = #00ff88, offline = #ff3355)
COLOR_OK = "#00ff88"
COLOR_FAIL = "#ff3355"
COLOR_WARN = "#ffaa33"
COLOR_CYAN = "#00d4ff"
COLOR_TEXT = "#e0e0e0"
COLOR_DIM = "#7aa0b0"

PANEL_QSS = f"""
/* Supplemental theme for the ZeroGBridge Portal. ZAH.css assumes the cockpit
   background image and makes bare QPushButtons invisible, so we restate
   the visible Execute/Matrix button look and give the dialog a dark canvas. */

QWidget#HotReloadCanvas {{
    background-color: #0c1020;
    color: {COLOR_CYAN};
    font-family: {FONT_FAMILY};
}}

QFrame#TelemetryPanel, QFrame#ControlPanel, QFrame#PlayerRegistry, QFrame#ConsoleFrame {{
    background-color: rgba(15, 25, 35, 220);
    border: 1px solid #00d4ff;
    border-radius: 5px;
}}

QLabel {{
    background-color: transparent;
    border: none;
    color: {COLOR_CYAN};
    font-family: {FONT_FAMILY};
}}

QLabel#PopupHeaderLabel {{
    color: {COLOR_CYAN};
    font-size: 16px;
    font-weight: bold;
}}

QLabel#SectionHeader {{
    color: {COLOR_CYAN};
    font-size: 12px;
    font-weight: bold;
    letter-spacing: 1px;
}}

QLabel#FieldLabel {{
    color: {COLOR_DIM};
    font-size: 11px;
}}

QLabel#FieldValue {{
    color: #00ffff;
    font-size: 12px;
    font-weight: bold;
}}

QLabel#StatusBadge {{
    font-size: 11px;
    font-weight: bold;
    padding: 3px 10px;
    border-radius: 3px;
    border: 1px solid {COLOR_OK};
    color: {COLOR_OK};
    background-color: rgba(0, 255, 136, 30);
}}

QLabel#SubtitleLabel {{
    color: {COLOR_DIM};
    font-size: 11px;
}}

QLabel#PopupFooterLabel {{
    color: #00ffff;
    font-family: {FONT_FAMILY};
    font-size: 11px;
}}

QLineEdit#CommandInput {{
    background-color: rgba(15, 25, 35, 220);
    color: #00ffff;
    border: 1px solid #00d4ff;
    border-radius: 3px;
    padding: 4px 8px;
    font-family: {FONT_FAMILY};
    font-size: 12px;
    selection-background-color: #005577;
}}

QTextEdit#ConsoleDisplay {{
    background-color: rgba(10, 15, 25, 230);
    color: {COLOR_TEXT};
    border: 1px solid #005577;
    border-radius: 3px;
    font-family: {FONT_FAMILY};
    font-size: 11px;
    padding: 6px;
}}

QTableWidget#PlayerRegistryTable {{
    background-color: rgba(10, 15, 25, 230);
    color: {COLOR_TEXT};
    border: 1px solid #005577;
    border-radius: 3px;
    gridline-color: #1a3344;
    font-family: {FONT_FAMILY};
    font-size: 11px;
    selection-background-color: rgba(0, 85, 119, 180);
    selection-color: #00ffff;
}}

QTableWidget#PlayerRegistryTable::item {{
    padding: 4px;
}}

QHeaderView::section, QTableWidget#PlayerRegistryTable QHeaderView::section {{
    background-color: #141e2d;
    color: #00d4ff;
    border: 1px solid #005577;
    font-weight: bold;
    font-family: {FONT_FAMILY};
    padding: 5px 6px;
}}

QTableCornerButton::section {{
    background-color: #141e2d;
    border: 1px solid #005577;
}}

QPushButton#ExecuteButton, QPushButton#MatrixButton, QPushButton#DangerButton {{
    background-color: rgba(0, 85, 119, 180);
    color: #ffffff;
    border: 1px solid #00d4ff;
    border-radius: 3px;
    font-family: {FONT_FAMILY};
    font-weight: bold;
    font-size: 11px;
    padding: 6px 12px;
    min-height: 28px;
}}

QPushButton#ExecuteButton:hover, QPushButton#MatrixButton:hover {{
    background-color: rgba(0, 150, 200, 190);
    border: 1px solid #ffffff;
    color: #00ffff;
}}

QPushButton#ExecuteButton:disabled, QPushButton#MatrixButton:disabled, QPushButton#DangerButton:disabled {{
    background-color: rgba(20, 30, 40, 180);
    color: #556677;
    border: 1px solid #334455;
}}

QPushButton#DangerButton {{
    background-color: rgba(119, 60, 0, 160);
    border: 1px solid {COLOR_WARN};
    color: #ffffff;
}}

QPushButton#DangerButton:hover {{
    background-color: rgba(180, 90, 0, 200);
    border: 1px solid #ffffff;
    color: {COLOR_WARN};
}}

QCheckBox {{
    color: #00ffff;
    font-family: {FONT_FAMILY};
    font-size: 11px;
    spacing: 8px;
}}

QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid #00d4ff;
    border-radius: 2px;
    background-color: rgba(15, 25, 35, 220);
}}

QCheckBox::indicator:checked {{
    background-color: #00d4ff;
}}

QProgressBar#ReloadProgress {{
    background-color: rgba(10, 15, 25, 230);
    border: 1px solid #005577;
    border-radius: 3px;
    color: #00ffff;
    font-family: {FONT_FAMILY};
    font-size: 10px;
    text-align: center;
    min-height: 16px;
}}

QProgressBar#ReloadProgress::chunk {{
    background-color: #00d4ff;
    border-radius: 2px;
}}

QScrollBar:vertical {{
    background: rgba(10, 15, 25, 200);
    width: 10px;
    border: none;
}}

QScrollBar::handle:vertical {{
    background: #005577;
    min-height: 24px;
    border-radius: 4px;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QTabWidget::pane {{
    border: 1px solid #00d4ff;
    border-radius: 5px;
    background-color: #0c1020;
    top: -1px;
}}

QTabBar::tab {{
    background-color: rgba(15, 25, 35, 220);
    color: #00d4ff;
    border: 1px solid #005577;
    border-bottom: none;
    border-top-left-radius: 3px;
    border-top-right-radius: 3px;
    padding: 8px 28px;
    font-family: {FONT_FAMILY};
    font-weight: bold;
    font-size: 12px;
    min-width: 110px;
}}

QTabBar::tab:selected {{
    background-color: rgba(0, 85, 119, 200);
    color: #00ffff;
    border: 1px solid #00d4ff;
    border-bottom: 1px solid #0c1020;
}}

QTabBar::tab:hover {{
    background-color: rgba(0, 150, 200, 140);
    color: #00ffff;
}}

QTreeWidget#ApiTree, QListWidget#ScriptList {{
    background-color: rgba(10, 15, 25, 230);
    color: {COLOR_TEXT};
    border: 1px solid #005577;
    border-radius: 3px;
    font-family: {FONT_FAMILY};
    font-size: 11px;
    outline: none;
}}

QTreeWidget#ApiTree::item, QListWidget#ScriptList::item {{
    padding: 3px 4px;
}}

QTreeWidget#ApiTree::item:selected, QListWidget#ScriptList::item:selected {{
    background-color: rgba(0, 85, 119, 180);
    color: #00ffff;
}}

QPlainTextEdit#ScriptEditor {{
    background-color: rgba(10, 15, 25, 240);
    color: {COLOR_TEXT};
    border: 1px solid #005577;
    border-radius: 3px;
    font-family: {FONT_FAMILY};
    font-size: 11px;
    padding: 6px;
    selection-background-color: #005577;
    selection-color: #00ffff;
}}

QComboBox, QSpinBox {{
    background-color: rgba(15, 25, 35, 220);
    color: #00ffff;
    border: 1px solid #00d4ff;
    border-radius: 3px;
    padding: 3px 6px;
    font-family: {FONT_FAMILY};
    font-size: 11px;
    min-height: 24px;
}}

QComboBox::drop-down {{
    border: none;
    width: 18px;
}}

QComboBox QAbstractItemView {{
    background-color: #0c1020;
    color: #00ffff;
    selection-background-color: #005577;
    border: 1px solid #00d4ff;
}}

QSplitter::handle {{
    background-color: #005577;
}}

QSplitter::handle:horizontal {{
    width: 3px;
}}

QSplitter::handle:vertical {{
    height: 3px;
}}
"""


def now_cst() -> datetime:
    return datetime.now(TZ)


def fmt_time(dt: datetime) -> str:
    """Format a timestamp in the user's America/Chicago zone."""
    local = dt.astimezone(TZ)
    return local.strftime("%b %d, %Y, %I:%M %p CST").replace(" 0", " ")


def load_stylesheet() -> str:
    chunks = []
    if ZAH_CSS.exists():
        chunks.append(ZAH_CSS.read_text(encoding="utf-8"))
    chunks.append(PANEL_QSS)
    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# Fake loader state
# ---------------------------------------------------------------------------

def infer_version(path: str) -> str:
    name = Path(path).stem  # ZeroGBridge.Core.1.4.3
    parts = name.split(".")
    # Expect trailing N.N.N
    nums = []
    for part in reversed(parts):
        if part.isdigit():
            nums.append(part)
        else:
            break
    if len(nums) >= 2:
        return ".".join(reversed(nums))
    return name or "unknown"


def should_fail(path: str) -> bool:
    lower = Path(path).name.lower()
    if any(tag in lower for tag in ("fail", "bad", "broken", "1.4.3")):
        return True
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
        return "FAIL" in text.upper()
    except OSError:
        return False


def short_hash(path: str) -> str:
    try:
        data = Path(path).read_bytes()
    except OSError:
        data = path.encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Themed confirm dialog
# ---------------------------------------------------------------------------

class ConfirmDialog(QDialog):
    """ZAH-styled confirm prompt used before reload or rollback."""

    def __init__(self, title: str, body: str, action_label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("HotReloadCanvas")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedSize(520, 240)
        self.setStyleSheet(load_stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        hdr = QLabel(title)
        hdr.setObjectName("PopupHeaderLabel")
        layout.addWidget(hdr)

        msg = QLabel(body)
        msg.setWordWrap(True)
        msg.setStyleSheet(f"color: {COLOR_TEXT}; font-size: 12px;")
        layout.addWidget(msg, stretch=1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("MatrixButton")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton(action_label)
        btn_ok.setObjectName("DangerButton")
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.clicked.connect(self.accept)
        buttons.addWidget(btn_cancel)
        buttons.addWidget(btn_ok)
        layout.addLayout(buttons)


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class HotReloadPanel(QWidget):
    """Interactive Hot Reload panel mock for the planned ZeroGBridge loader."""

    capture_finished = pyqtSignal()

    def __init__(self, capture_mode: bool = False, parent=None, embedded: bool = False,
                 source: PortalDataSource | None = None):
        super().__init__(parent)
        self.source = source or SampleDataSource()
        self.state = self.source.loader_state()
        self.capture_mode = capture_mode
        self.embedded = embedded
        self._timers: list[QTimer] = []
        self._mid_captured = False
        self._capture_dir = HERE
        self._pending_finish = None
        self._shot_target = None  # set by the parent window so tab chrome is included


        self.setObjectName("HotReloadCanvas")
        if not embedded:
            self.setWindowTitle("Zero-G Admin Helper - ZeroGBridge Hot Reload")
            self.setFixedSize(1080, 820)
            self.setStyleSheet(load_stylesheet())

        self._init_ui()
        self._refresh_status()
        self._refresh_history()
        self._set_busy(False)

        st = self.state
        self._log(f"Loader {st.loader_version} holding port {st.port}. ZAH session attached.", "info")
        self._log(f"Core {st.core_version} loaded since {fmt_time(st.loaded_since)} — {st.last_result}.",
                  "ok" if st.last_ok else "warn")
        self._log(f"Data source: {self.source.label}. No live server. Reloads and rollbacks are simulated.", "dim")

    # ----- layout ----------------------------------------------------------

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        if self.embedded:
            root.setContentsMargins(12, 10, 12, 10)
        else:
            root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        root.addLayout(self._build_header())
        root.addWidget(self._build_status_frame())
        root.addWidget(self._build_actions_frame())
        root.addWidget(self._build_history_frame(), stretch=3)
        root.addWidget(self._build_log_frame(), stretch=2)

        self.progress = QProgressBar()
        self.progress.setObjectName("ReloadProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Idle")
        self.progress.setVisible(True)
        root.addWidget(self.progress)

        self.footer = QLabel("Ready. Port 30500 is held by the loader.")
        self.footer.setObjectName("PopupFooterLabel")
        root.addWidget(self.footer)

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("ZeroGBridge Hot Reload")
        title.setObjectName("PopupHeaderLabel")
        subtitle = QLabel(
            "Loader stays loaded and keeps the bridge port open. "
            "The core DLL (commands, factions, alerts) can be swapped while the server runs."
        )
        subtitle.setObjectName("SubtitleLabel")
        subtitle.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        row.addLayout(titles, stretch=1)

        self.badge = QLabel("LOADER ACTIVE")
        self.badge.setObjectName("StatusBadge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setFixedHeight(28)
        row.addWidget(self.badge, alignment=Qt.AlignmentFlag.AlignTop)
        return row

    def _kv(self, label: str) -> tuple[QLabel, QLabel]:
        k = QLabel(label)
        k.setObjectName("FieldLabel")
        v = QLabel("—")
        v.setObjectName("FieldValue")
        v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return k, v

    def _build_status_frame(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("TelemetryPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(6)

        hdr = QLabel("CONNECTION / STATUS")
        hdr.setObjectName("SectionHeader")
        layout.addWidget(hdr)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self.lbl_server_k, self.lbl_server = self._kv("Server")
        self.lbl_loader_k, self.lbl_loader = self._kv("Loader version")
        self.lbl_core_k, self.lbl_core = self._kv("Current core")
        self.lbl_since_k, self.lbl_since = self._kv("Loaded since")
        self.lbl_result_k, self.lbl_result = self._kv("Last reload result")
        self.lbl_players_k, self.lbl_players = self._kv("Players online")
        self.lbl_port_k, self.lbl_port = self._kv("Bridge port")
        self.lbl_hold_k, self.lbl_hold = self._kv("Session")

        pairs = [
            (0, 0, self.lbl_server_k, self.lbl_server),
            (1, 0, self.lbl_loader_k, self.lbl_loader),
            (2, 0, self.lbl_core_k, self.lbl_core),
            (3, 0, self.lbl_since_k, self.lbl_since),
            (0, 2, self.lbl_result_k, self.lbl_result),
            (1, 2, self.lbl_players_k, self.lbl_players),
            (2, 2, self.lbl_port_k, self.lbl_port),
            (3, 2, self.lbl_hold_k, self.lbl_hold),
        ]
        for r, c, k, v in pairs:
            grid.addWidget(k, r, c)
            grid.addWidget(v, r, c + 1)

        layout.addLayout(grid)
        return frame

    def _build_actions_frame(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("ControlPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(8)

        hdr = QLabel("ACTIONS")
        hdr.setObjectName("SectionHeader")
        layout.addWidget(hdr)

        file_row = QHBoxLayout()
        file_lbl = QLabel("New core DLL")
        file_lbl.setObjectName("FieldLabel")
        file_lbl.setFixedWidth(100)
        self.dll_path = QLineEdit()
        self.dll_path.setObjectName("CommandInput")
        self.dll_path.setPlaceholderText("Pick a ZeroGBridge.Core.*.dll to upload…")
        self.dll_path.setText(self.state.pending_dll)
        self.btn_browse = QPushButton("Browse…")
        self.btn_browse.setObjectName("ExecuteButton")
        self.btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse.setFixedWidth(110)
        self.btn_browse.clicked.connect(self._on_browse)
        file_row.addWidget(file_lbl)
        file_row.addWidget(self.dll_path, stretch=1)
        file_row.addWidget(self.btn_browse)
        layout.addLayout(file_row)

        btn_row = QHBoxLayout()
        self.btn_reload = QPushButton("Reload now")
        self.btn_reload.setObjectName("ExecuteButton")
        self.btn_reload.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reload.clicked.connect(self._on_reload_clicked)

        self.btn_rollback_prev = QPushButton("Roll back to previous")
        self.btn_rollback_prev.setObjectName("DangerButton")
        self.btn_rollback_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_rollback_prev.clicked.connect(self._on_rollback_previous)

        self.chk_auto = QCheckBox("Auto-reload when a new core is dropped")
        self.chk_auto.setChecked(False)
        self.chk_auto.toggled.connect(self._on_auto_toggled)

        self.btn_sim_drop = QPushButton("Simulate drop")
        self.btn_sim_drop.setObjectName("MatrixButton")
        self.btn_sim_drop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sim_drop.setFixedWidth(140)
        self.btn_sim_drop.setEnabled(False)
        self.btn_sim_drop.setToolTip("Mock only: pretend a new core DLL was copied into the incoming folder.")
        self.btn_sim_drop.clicked.connect(self._on_simulate_drop)

        btn_row.addWidget(self.btn_reload)
        btn_row.addWidget(self.btn_rollback_prev)
        btn_row.addSpacing(12)
        btn_row.addWidget(self.chk_auto)
        btn_row.addWidget(self.btn_sim_drop)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return frame

    def _build_history_frame(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("PlayerRegistry")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        hdr = QLabel("VERSION HISTORY")
        hdr.setObjectName("SectionHeader")
        header.addWidget(hdr)
        header.addStretch()
        self.btn_rollback_sel = QPushButton("Roll back to selected")
        self.btn_rollback_sel.setObjectName("DangerButton")
        self.btn_rollback_sel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_rollback_sel.setEnabled(False)
        self.btn_rollback_sel.clicked.connect(self._on_rollback_selected)
        header.addWidget(self.btn_rollback_sel)
        layout.addLayout(header)

        self.history = QTableWidget(0, 4)
        self.history.setObjectName("PlayerRegistryTable")
        self.history.setHorizontalHeaderLabels(["Version", "Time (CST)", "Result", "Notes"])
        self.history.verticalHeader().setVisible(False)
        self.history.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.history.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history.setAlternatingRowColors(False)
        hdr_view = self.history.horizontalHeader()
        hdr_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.history.itemSelectionChanged.connect(self._on_history_selection)
        self.history.setMinimumHeight(200)
        self.history.verticalHeader().setDefaultSectionSize(26)
        self.history.setCornerButtonEnabled(False)
        self.history.setShowGrid(True)
        layout.addWidget(self.history)
        return frame

    def _build_log_frame(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("ConsoleFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(6)

        hdr = QLabel("LOADER LOG")
        hdr.setObjectName("SectionHeader")
        layout.addWidget(hdr)

        self.log = QTextEdit()
        self.log.setObjectName("ConsoleDisplay")
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Loader events will appear here…")
        layout.addWidget(self.log)
        return frame

    # ----- status / history painting --------------------------------------

    def _set_badge(self, text: str, color: str) -> None:
        self.badge.setText(text)
        self.badge.setStyleSheet(
            f"QLabel#StatusBadge {{"
            f"  font-size: 11px; font-weight: bold; padding: 3px 10px;"
            f"  border-radius: 3px; border: 1px solid {color}; color: {color};"
            f"  background-color: rgba(0, 0, 0, 80);"
            f"}}"
        )

    def _refresh_status(self) -> None:
        s = self.state
        self.lbl_server.setText(s.server_name)
        self.lbl_loader.setText(s.loader_version)
        self.lbl_core.setText(s.core_version)
        self.lbl_since.setText(fmt_time(s.loaded_since))
        self.lbl_result.setText(s.last_result)
        self.lbl_result.setStyleSheet(
            f"color: {COLOR_OK if s.last_ok else COLOR_FAIL}; font-size: 12px; font-weight: bold;"
        )
        self.lbl_players.setText(str(s.players_online))
        self.lbl_port.setText(f"{s.port}  (held by loader)")
        self.lbl_hold.setText("ZAH connection retained")
        if s.busy:
            self._set_badge("RELOADING", COLOR_WARN)
        elif s.last_ok:
            self._set_badge("LOADER ACTIVE", COLOR_OK)
        else:
            self._set_badge("ROLLED BACK", COLOR_WARN)

    def _refresh_history(self) -> None:
        self.history.setRowCount(0)
        for entry in self.state.history:
            row = self.history.rowCount()
            self.history.insertRow(row)
            current = entry.version == self.state.core_version and entry.result == "OK"
            note = entry.note
            if current and "Current" not in note:
                note = (note + "  " if note else "") + "Current core"

            values = [entry.version, fmt_time(entry.when), entry.result, note]
            color = {
                "OK": COLOR_OK,
                "Failed": COLOR_FAIL,
                "Rolled back": COLOR_WARN,
            }.get(entry.result, COLOR_TEXT)

            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter if col < 3 else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if col == 2:
                    item.setForeground(QColor(color))
                elif current:
                    item.setForeground(QColor("#00ffff"))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.history.setItem(row, col, item)
        self._on_history_selection()

    def _log(self, message: str, kind: str = "info") -> None:
        stamp = now_cst().strftime("%H:%M:%S")
        color = {
            "info": COLOR_TEXT,
            "ok": COLOR_OK,
            "fail": COLOR_FAIL,
            "warn": COLOR_WARN,
            "dim": COLOR_DIM,
            "cyan": COLOR_CYAN,
        }.get(kind, COLOR_TEXT)
        html = (
            f'<span style="color:{COLOR_CYAN};">[{stamp}]</span> '
            f'<span style="color:{color};">{_escape(message)}</span>'
        )
        self.log.append(html)
        self.log.moveCursor(QTextCursor.MoveOperation.End)

    # ----- actions ---------------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        self.state.busy = busy
        enabled = not busy
        self.btn_browse.setEnabled(enabled)
        self.btn_reload.setEnabled(enabled)
        self.btn_rollback_prev.setEnabled(enabled)
        self.chk_auto.setEnabled(enabled)
        self.btn_sim_drop.setEnabled(enabled and self.chk_auto.isChecked())
        self.dll_path.setEnabled(enabled)
        if not busy:
            self._on_history_selection()
        else:
            self.btn_rollback_sel.setEnabled(False)
        self._refresh_status()

    def _on_history_selection(self) -> None:
        if self.state.busy:
            self.btn_rollback_sel.setEnabled(False)
            return
        row = self.history.currentRow()
        if row < 0 or row >= len(self.state.history):
            self.btn_rollback_sel.setEnabled(False)
            return
        entry = self.state.history[row]
        can = entry.version != self.state.core_version and entry.result == "OK"
        self.btn_rollback_sel.setEnabled(can)

    def _on_browse(self) -> None:
        cores = self.source.cores_dir()
        start = str(cores if cores.exists() else HERE)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Pick a ZeroGBridge core DLL",
            start,
            "Core libraries (*.dll);;All files (*)",
        )
        if path:
            self.dll_path.setText(path)
            self._log(f"Selected {Path(path).name} for upload.", "cyan")

    def _on_auto_toggled(self, checked: bool) -> None:
        self.state.auto_reload = checked
        self.btn_sim_drop.setEnabled(checked and not self.state.busy)
        if checked:
            self._log("Auto-reload armed. Watching Mods/ZeroGBridge/incoming for a new core DLL.", "cyan")
        else:
            self._log("Auto-reload off. New cores will wait for Reload now.", "dim")

    def _on_simulate_drop(self) -> None:
        # Prefer a successful sample if present, otherwise the selected path.
        candidate = self.source.drop_core()
        path = str(candidate) if candidate else (self.dll_path.text().strip() or self.state.pending_dll)
        if not path:
            self._log("Simulate drop: no core DLL is selected.", "warn")
            return
        self.dll_path.setText(path)
        self._log(f"Auto-reload: new core dropped ({Path(path).name}).", "cyan")
        self._start_reload(path, confirm=True, source="auto-drop")

    def _on_reload_clicked(self) -> None:
        path = self.dll_path.text().strip()
        if not path:
            self._log("Choose a core DLL before reloading.", "warn")
            return
        self._start_reload(path, confirm=True, source="manual")

    def _previous_ok_version(self) -> HistoryEntry | None:
        current = self.state.core_version
        for entry in self.state.history:
            if entry.version != current and entry.result == "OK":
                return entry
        return None

    def _on_rollback_previous(self) -> None:
        entry = self._previous_ok_version()
        if not entry:
            self._log("No previous OK core is stashed in the loader.", "warn")
            return
        self._start_rollback(entry.version, confirm=True)

    def _on_rollback_selected(self) -> None:
        row = self.history.currentRow()
        if row < 0 or row >= len(self.state.history):
            return
        entry = self.state.history[row]
        self._start_rollback(entry.version, confirm=True)

    def _confirm(self, title: str, body: str, action: str) -> bool:
        if self.capture_mode:
            return True
        dlg = ConfirmDialog(title, body, action, parent=self)
        return dlg.exec() == QDialog.DialogCode.Accepted

    def _player_warning(self) -> str:
        n = self.state.players_online
        server = self.state.server_name
        if n == 0:
            return f"No players are currently online on {server}."
        noun = "player" if n == 1 else "players"
        return f"{n} {noun} are currently online on {server}."

    # ----- simulated reload / rollback ------------------------------------

    def _clear_timers(self) -> None:
        for t in self._timers:
            t.stop()
            t.deleteLater()
        self._timers.clear()

    def _schedule(self, delay_ms: int, fn) -> None:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(fn)
        timer.start(delay_ms)
        self._timers.append(timer)

    def _start_reload(self, path: str, confirm: bool, source: str) -> None:
        if self.state.busy:
            return
        version = infer_version(path)
        fail = should_fail(path)
        if confirm:
            body = (
                f"{self._player_warning()}\n\n"
                f"Reload the bridge core from {self.state.core_version} to {version}?\n\n"
                "The loader will keep port 30500 open, so Zero-G Admin Helper stays connected. "
                "Commands will pause for a few seconds during the swap. "
                "If the new core fails its self-test, the loader will roll back automatically."
            )
            if not self._confirm("Confirm core reload", body, "Reload now"):
                self._log("Reload cancelled.", "dim")
                return

        self._run_sequence(
            kind="reload",
            target=version,
            path=path,
            fail=fail,
            source=source,
        )

    def _start_rollback(self, version: str, confirm: bool) -> None:
        if self.state.busy:
            return
        if version == self.state.core_version:
            self._log(f"{version} is already the running core.", "dim")
            return
        if confirm:
            body = (
                f"{self._player_warning()}\n\n"
                f"Roll back the bridge core from {self.state.core_version} to {version}?\n\n"
                "The loader will keep port 30500 open. If the stashed core fails to load, "
                "the current one will be restored."
            )
            if not self._confirm("Confirm rollback", body, "Roll back"):
                self._log("Rollback cancelled.", "dim")
                return
        self._run_sequence(
            kind="rollback",
            target=version,
            path="",
            fail=False,
            source="rollback",
        )

    def _run_sequence(self, kind: str, target: str, path: str, fail: bool, source: str) -> None:
        self._clear_timers()
        self._set_busy(True)
        current = self.state.core_version
        dll_name = Path(path).name if path else f"ZeroGBridge.Core.{target}.dll"
        digest = short_hash(path) if path else "stashed-core"
        size_label = "186 KB" if kind == "reload" else "stashed"

        steps: list[tuple[int, int, str, str]] = []
        # delay_ms, progress_pct, message, kind
        if kind == "reload":
            steps = [
                (0, 8, f"Uploading {dll_name} ({size_label}) to the loader…", "cyan"),
                (700, 22, f"Upload complete. SHA256 {digest}…", "info"),
                (1400, 38, f"Loader holding port {self.state.port} open. Unloading core {current}…", "info"),
                (2100, 52, f"Core {current} unloaded. ZAH session retained.", "ok"),
                (2800, 68, f"Loading core {target} into an isolated context…", "cyan"),
                (3600, 82, f"Core {target} mapped. Running self-test…", "warn"),
            ]
            if fail:
                steps += [
                    (4500, 88, f"SELF-TEST FAILED: FactionCache.Init threw NullReferenceException in {target}.", "fail"),
                    (5200, 92, f"Reload aborted. Rolling back to {current}…", "warn"),
                    (6000, 96, f"Previous core {current} reloaded from loader stash.", "info"),
                    (6600, 100, f"Self-test passed on {current}.", "ok"),
                    (7200, 100, f"Rollback complete. Port {self.state.port} still open. ZAH connection held.", "ok"),
                ]
            else:
                steps += [
                    (4500, 92, f"Self-test passed on {target} (commands, faction cache, auth handshake).", "ok"),
                    (5300, 100, f"Swapped. Now running core {target}. Port {self.state.port} still open.", "ok"),
                ]
        else:
            steps = [
                (0, 15, f"Preparing rollback from {current} to {target}…", "cyan"),
                (700, 35, f"Loader holding port {self.state.port} open. Unloading core {current}…", "info"),
                (1500, 55, f"Core {current} unloaded. ZAH session retained.", "ok"),
                (2300, 75, f"Restoring stashed core {target}…", "cyan"),
                (3200, 88, f"Core {target} mapped. Running self-test…", "warn"),
                (4000, 100, f"Self-test passed on {target}. Rollback complete. Port {self.state.port} still open.", "ok"),
            ]

        mid_token = "Running self-test"
        total_ms = steps[-1][0] + 200

        def fire(pct: int, message: str, log_kind: str, is_mid: bool) -> None:
            self.progress.setValue(pct)
            self.progress.setFormat(message[:80])
            self.footer.setText(message)
            self._log(message, log_kind)
            if (
                self.capture_mode
                and not self._mid_captured
                and is_mid
            ):
                self._mid_captured = True
                QTimer.singleShot(80, self._capture_mid)

        for delay, pct, message, log_kind in steps:
            is_mid = mid_token in message
            self._schedule(delay, lambda p=pct, m=message, k=log_kind, mid=is_mid: fire(p, m, k, mid))

        def finish() -> None:
            stamp = now_cst()
            if kind == "reload" and fail:
                self.state.history.insert(
                    0,
                    HistoryEntry(target, stamp, "Failed", f"Rolled back to {current}"),
                )
                self.state.last_result = f"Failed — rolled back to {current}"
                self.state.last_ok = False
                # core_version stays on current
                self.footer.setText(
                    f"Reload of {target} failed. Running {current} again. Port {self.state.port} still open."
                )
            elif kind == "reload":
                self.state.history.insert(0, HistoryEntry(target, stamp, "OK", "Current core"))
                self.state.core_version = target
                self.state.loaded_since = stamp
                self.state.last_result = f"OK — {target} self-test passed"
                self.state.last_ok = True
                self.footer.setText(f"Now running core {target}. Port {self.state.port} held by the loader.")
            else:
                self.state.history.insert(
                    0,
                    HistoryEntry(target, stamp, "Rolled back", f"Restored from {current}"),
                )
                self.state.core_version = target
                self.state.loaded_since = stamp
                self.state.last_result = f"Rolled back — now running {target}"
                self.state.last_ok = True
                self.footer.setText(f"Rolled back to {target}. Port {self.state.port} held by the loader.")

            self.progress.setValue(0)
            self.progress.setFormat("Idle")
            self._set_busy(False)
            self._refresh_history()
            if self.capture_mode and kind == "reload" and fail:
                QTimer.singleShot(120, self._capture_after)

        self._schedule(total_ms, finish)

    # ----- screenshot helpers ---------------------------------------------

    def save_shot(self, path: Path) -> None:
        target = self._shot_target or self
        target.repaint()
        QApplication.processEvents()
        pix = target.grab()
        path.parent.mkdir(parents=True, exist_ok=True)
        ok = pix.save(str(path), "PNG")
        print(f"[CAPTURE] {'wrote' if ok else 'FAILED'} {path} ({pix.width()}x{pix.height()})")

    def _capture_mid(self) -> None:
        self.save_shot(self._capture_dir / "mid_reload.png")

    def _capture_after(self) -> None:
        self.save_shot(self._capture_dir / "after_failed_reload.png")
        self.capture_finished.emit()


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class HotReloadWindow(QWidget):
    """Top-level mock window with LOADER and BRIDGE tabs."""

    capture_finished = pyqtSignal()

    def __init__(self, capture_mode: bool = False, parent=None, source: PortalDataSource | None = None):
        super().__init__(parent)
        self.capture_mode = capture_mode
        self.source = source or SampleDataSource()
        self._capture_dir = HERE

        self.setObjectName("HotReloadCanvas")
        self.setWindowTitle("Zero-G Admin Helper - ZeroGBridge")
        self.setFixedSize(1280, 900)
        self.setStyleSheet(load_stylesheet())

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(8)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("ZeroGBridge")
        title.setObjectName("PopupHeaderLabel")
        subtitle = QLabel(
            "Loader and Bridge tools for Zero-G Admin Helper. "
            "Viewer only — simulated data, no live server connection."
        )
        subtitle.setObjectName("SubtitleLabel")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        head.addLayout(titles, stretch=1)
        root.addLayout(head)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("MainTabs")
        self.tabs.setDocumentMode(False)

        self.loader = HotReloadPanel(capture_mode=capture_mode, parent=self, embedded=True, source=self.source)
        self.loader._shot_target = self
        self.loader._capture_dir = self._capture_dir

        self.bridge = BridgePanel(parent=self, capture_mode=capture_mode, source=self.source)

        self.tabs.addTab(self.loader, "  LOADER  ")
        self.tabs.addTab(self.bridge, "  BRIDGE  ")
        root.addWidget(self.tabs, stretch=1)

    def save_shot(self, path: Path) -> None:
        self.repaint()
        QApplication.processEvents()
        pix = self.grab()
        path.parent.mkdir(parents=True, exist_ok=True)
        ok = pix.save(str(path), "PNG")
        print(f"[CAPTURE] {'wrote' if ok else 'FAILED'} {path} ({pix.width()}x{pix.height()})")
