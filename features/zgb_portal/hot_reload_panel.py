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

from PyQt6 import sip
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
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
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from features.paths import asset_path

from .bridge_panel import BridgePanel
from .data_source import (
    HistoryEntry,
    LiveDataSource,
    LoaderState,
    PortalDataSource,
    SampleDataSource,
    offline_state,
)
from .live_client import run_async

LIVE_UPLOAD_TIP = (
    "Not available on live data: the bridge has no upload command. "
    "Drop the new ZeroGBridge.Core.dll into the server's Mods/ZeroGBridge/Updates/ "
    "folder with the host panel, then use Reload now."
)
LIVE_REFRESH_MS = 30_000

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
COLOR_DIM = "#a8c2cf"      # help text / dim log lines (brightened for readability)
COLOR_LABEL = "#c3d6e0"    # field labels (Server, Loader version, ...)

# Portal-only border palette: muted teal-grey instead of neon cyan.
BORDER = "#335a66"
BORDER_SOFT = "#26424c"
BORDER_HOVER = "#5d8f9c"

# Sans for labels/body, monospace for logs, paths, versions and code.
UI_FONT = '"Noto Sans", "DejaVu Sans", "Segoe UI", sans-serif'
MONO_FONT = FONT_FAMILY

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
    border: 1px solid {BORDER};
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
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 4px 8px;
    font-family: {FONT_FAMILY};
    font-size: 12px;
    selection-background-color: #005577;
}}

QTextEdit#ConsoleDisplay {{
    background-color: rgba(10, 15, 25, 230);
    color: {COLOR_TEXT};
    border: 1px solid {BORDER_SOFT};
    border-radius: 3px;
    font-family: {FONT_FAMILY};
    font-size: 11px;
    padding: 6px;
}}

QTableWidget#PlayerRegistryTable {{
    background-color: rgba(10, 15, 25, 230);
    color: {COLOR_TEXT};
    border: 1px solid {BORDER_SOFT};
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
    border: 1px solid {BORDER_SOFT};
    font-weight: bold;
    font-family: {FONT_FAMILY};
    padding: 5px 6px;
}}

QTableCornerButton::section {{
    background-color: #141e2d;
    border: 1px solid {BORDER_SOFT};
}}

QPushButton#ExecuteButton, QPushButton#MatrixButton, QPushButton#DangerButton {{
    background-color: rgba(0, 85, 119, 180);
    color: #ffffff;
    border: 1px solid {BORDER};
    border-radius: 3px;
    font-family: {FONT_FAMILY};
    font-weight: bold;
    font-size: 11px;
    padding: 6px 12px;
    min-height: 28px;
}}

QPushButton#ExecuteButton:hover, QPushButton#MatrixButton:hover {{
    background-color: rgba(0, 150, 200, 190);
    border: 1px solid {BORDER_HOVER};
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
    border: 1px solid {BORDER_HOVER};
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
    border: 1px solid {BORDER};
    border-radius: 2px;
    background-color: rgba(15, 25, 35, 220);
}}

QCheckBox::indicator:checked {{
    background-color: #00d4ff;
}}

QProgressBar#ReloadProgress {{
    background-color: rgba(10, 15, 25, 230);
    border: 1px solid {BORDER_SOFT};
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
    border: 1px solid {BORDER};
    border-radius: 5px;
    background-color: #0c1020;
    top: -1px;
}}

QTabBar::tab {{
    background-color: rgba(15, 25, 35, 220);
    color: #00d4ff;
    border: 1px solid {BORDER_SOFT};
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
    border: 1px solid {BORDER};
    border-bottom: 1px solid #0c1020;
}}

QTabBar::tab:hover {{
    background-color: rgba(0, 150, 200, 140);
    color: #00ffff;
}}

QTreeWidget#ApiTree, QListWidget#ScriptList {{
    background-color: rgba(10, 15, 25, 230);
    color: {COLOR_TEXT};
    border: 1px solid {BORDER_SOFT};
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
    border: 1px solid {BORDER_SOFT};
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
    border: 1px solid {BORDER};
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
    border: 1px solid {BORDER};
}}

QSplitter::handle {{
    background-color: {BORDER_SOFT};
}}

QSplitter::handle:horizontal {{
    width: 3px;
}}

QSplitter::handle:vertical {{
    height: 3px;
}}

/* ---- Readability pass (portal only) ---------------------------------- */

QWidget#HotReloadCanvas {{
    font-family: {UI_FONT};
    font-size: 14px;
}}

QScrollArea#PortalScroll, QScrollArea#PortalScroll > QWidget > QWidget {{
    background-color: #0c1020;
    border: none;
}}

QLabel {{
    font-family: {UI_FONT};
    font-size: 14px;
}}

QLabel#PopupHeaderLabel {{
    font-size: 20px;
}}

QLabel#SectionHeader {{
    color: #4fe0ff;
    font-size: 15px;
    letter-spacing: 1px;
    padding-bottom: 2px;
}}

QLabel#FieldLabel {{
    color: {COLOR_LABEL};
    font-size: 14px;
}}

QLabel#FieldValue {{
    color: #7ff4ff;
    font-family: {MONO_FONT};
    font-size: 15px;
}}

QLabel#SubtitleLabel {{
    color: {COLOR_DIM};
    font-size: 13px;
}}

QLabel#PopupFooterLabel {{
    color: #bfefff;
    font-size: 13px;
}}

QLineEdit#CommandInput {{
    font-family: {MONO_FONT};
    font-size: 13px;
    padding: 6px 10px;
    min-height: 24px;
}}

QTextEdit#ConsoleDisplay {{
    color: #e8f1f5;
    font-family: {MONO_FONT};
    font-size: 14px;
    padding: 8px;
}}

QPlainTextEdit#ScriptEditor {{
    font-family: {MONO_FONT};
    font-size: 14px;
    padding: 8px;
}}

QTableWidget#PlayerRegistryTable {{
    color: #dfeaf0;
    font-family: {UI_FONT};
    font-size: 14px;
    gridline-color: #1f3540;
    background-color: #0d1622;
    alternate-background-color: #142230;
}}

QTableWidget#PlayerRegistryTable::item {{
    padding: 6px 8px;
}}

QHeaderView::section, QTableWidget#PlayerRegistryTable QHeaderView::section {{
    background-color: #17283a;
    color: #7fe6ff;
    border: 1px solid {BORDER_SOFT};
    font-family: {UI_FONT};
    font-size: 14px;
    font-weight: bold;
    padding: 8px 8px;
}}

QTreeWidget#ApiTree {{
    color: #dfeaf0;
    font-family: {UI_FONT};
    font-size: 14px;
}}

QTreeWidget#ApiTree::item {{
    padding: 5px 4px;
}}

QPushButton#ExecuteButton, QPushButton#MatrixButton, QPushButton#DangerButton {{
    font-family: {UI_FONT};
    font-size: 14px;
    padding: 8px 16px;
    min-height: 32px;
}}

QPushButton#ExecuteButton:disabled, QPushButton#MatrixButton:disabled, QPushButton#DangerButton:disabled {{
    background-color: rgba(30, 42, 54, 200);
    color: #8a9aa6;
    border: 1px dashed #4a5c66;
}}

QCheckBox {{
    color: #cfeef8;
    font-family: {UI_FONT};
    font-size: 14px;
}}

QCheckBox:disabled {{
    color: #7d8d98;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
}}

QComboBox, QSpinBox {{
    font-family: {MONO_FONT};
    font-size: 14px;
    min-height: 28px;
}}

QProgressBar#ReloadProgress {{
    font-size: 12px;
    min-height: 20px;
}}

QTabBar::tab {{
    font-family: {UI_FONT};
    font-size: 14px;
    padding: 8px 32px;
}}

QScrollBar:vertical {{
    width: 12px;
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
        self.setFixedSize(620, 300)
        self.setStyleSheet(load_stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        hdr = QLabel(title)
        hdr.setObjectName("PopupHeaderLabel")
        layout.addWidget(hdr)

        msg = QLabel(body)
        msg.setWordWrap(True)
        msg.setStyleSheet(f"color: {COLOR_TEXT}; font-size: 14px;")
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
        self._live_inflight = False   # a status read is running
        self._live_action = False     # a confirmed reload/rollback is running
        self._last_conn = None        # last live connection state written to the log
        self._last_core_id = None
        self._last_refresh = None


        self.setObjectName("HotReloadCanvas")
        if not embedded:
            self.setWindowTitle("Zero-G Admin Helper - ZeroGBridge Hot Reload")
            self.setFixedSize(1080, 820)
            self.setStyleSheet(load_stylesheet())

        self._init_ui()
        self._apply_mode()
        self._refresh_status()
        self._refresh_history()
        self._set_busy(False)
        self._log_source_intro()
        if self.source.is_live:
            self.refresh_live()

    # ----- data source -----------------------------------------------------

    def _alive(self) -> bool:
        return not sip.isdeleted(self)

    def set_source(self, source: PortalDataSource) -> None:
        """Switch between Live and Examples. Pending simulated steps are dropped."""
        self._clear_timers()
        self.source = source
        self.state = source.loader_state()
        self._last_conn = None
        self._last_core_id = None
        self._live_action = False
        self._live_inflight = False
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Idle")
        self._apply_mode()
        self._refresh_history()
        self._set_busy(False)
        self._log_source_intro()
        if source.is_live:
            self.refresh_live()

    def _log_source_intro(self) -> None:
        st = self.state
        if self.source.is_live:
            self._log(
                f"Data source: Live — {st.server_name} (bridge {st.port}). Reading hot:status… "
                "Reload and rollback always ask before anything is sent.",
                "cyan",
            )
            self.footer.setText(f"Live: {st.server_name}, bridge {st.port}.")
        else:
            self._log(f"Data source: Examples (Examples/ZGB_Portal). Loader {st.loader_version}, "
                      f"core {st.core_version}.", "info")
            self._log("Examples only: reloads and rollbacks are simulated, nothing is sent to a server.", "dim")
            self.footer.setText(f"Examples. Port {st.port} is held by the loader (simulated).")

    def _apply_mode(self) -> None:
        live = self.source.is_live
        self.file_lbl.setText("Pending drop" if live else "New core DLL")
        self.dll_path.setReadOnly(live)
        if live:
            self.dll_path.setPlaceholderText("No new core is waiting in Updates/")
            self.dll_path.setText(self.state.pending_drop)
        else:
            self.dll_path.setPlaceholderText("Pick a ZeroGBridge.Core.*.dll to upload…")
            self.dll_path.setText(self.state.pending_dll)
        self.btn_browse.setToolTip(LIVE_UPLOAD_TIP if live else "Pick an example core DLL.")
        self.btn_sim_drop.setToolTip(
            LIVE_UPLOAD_TIP if live else "Examples only: pretend a new core DLL was copied into the incoming folder."
        )
        self.chk_auto.setToolTip(
            "Shows the server's AutoReloadOnDrop setting (read-only on live data)." if live else ""
        )
        self.chk_auto.blockSignals(True)
        self.chk_auto.setChecked(bool(self.state.server_auto_reload) if live else False)
        self.chk_auto.blockSignals(False)
        self.chk_force.setVisible(live)
        self.btn_rollback_sel.setToolTip(
            "Live data: use Roll back to previous (the bridge restores its last good core)." if live else ""
        )
        self.btn_reload.setText("Reload now")
        self.lbl_hold_k.setText("Core domain" if live else "Session")

    # ----- live reads ------------------------------------------------------

    def refresh_live(self) -> None:
        """Reads hot:status in a worker thread. Read-only; safe to call any time."""
        if not self.source.is_live or self._live_inflight or self._live_action:
            return
        self._live_inflight = True
        src = self.source
        if self.state.connection != "Online":
            self.state.connection = "Connecting"
            self._refresh_status()
        run_async(
            src.fetch_state,
            lambda st, src=src: self._on_live_state(src, st),
            lambda kind, msg, src=src: self._on_live_error(src, kind, msg),
        )

    def _on_live_state(self, src, state: LoaderState) -> None:
        if not self._alive() or src is not self.source:
            return
        self._live_inflight = False
        self._last_refresh = now_cst()
        self.state = state
        if self._last_conn != "Online" or self._last_core_id != state.core_id:
            self._log(
                f"Live: {state.server_name} — loader {state.loader_version}, core "
                f"{state.core_release or '?'} ({state.core_version}) in {state.core_domain or '—'}, "
                f"{state.players_online} online.",
                "ok",
            )
        self._last_conn = "Online"
        self._last_core_id = state.core_id
        self._apply_mode()
        self._refresh_history()
        self._set_busy(False)
        self.footer.setText(
            f"Live: {state.server_name}, bridge {state.port}. Updated {self._last_refresh.strftime('%I:%M:%S %p CST').lstrip('0')}."
        )

    def _on_live_error(self, src, kind: str, message: str) -> None:
        if not self._alive() or src is not self.source:
            return
        self._live_inflight = False
        conn = "Auth failed" if kind == "auth" else "Offline"
        self.state = offline_state(src.profile(), conn, message)
        if self._last_conn != conn:
            self._log(f"Live: {message}", "fail")
        self._last_conn = conn
        self._last_core_id = None
        self._apply_mode()
        self._refresh_history()
        self._set_busy(False)
        self.footer.setText(f"Live: {conn.lower()} — {message}")

    # ----- live reload / rollback (always confirmed) -----------------------

    def _refresh_age(self) -> str:
        if not self._last_refresh:
            return ""
        return f" (as of {self._last_refresh.strftime('%I:%M %p CST').lstrip('0')})"

    def _live_reload(self) -> None:
        if self._live_action or self.state.connection != "Online":
            return
        s = self.state
        force = self.chk_force.isChecked()
        if force:
            what = (f"Force reload: the running core {s.core_release or ''} ({s.core_version}) is "
                    "unloaded and loaded again, even if nothing new is in Updates/.")
        elif s.pending_drop:
            what = f"Load the core waiting in Updates/: {s.pending_drop}."
        else:
            what = ("No new core is waiting in Updates/. The bridge will answer 'unchanged' "
                    "unless you tick Force reload same core.")
        body = (
            f"{self._player_warning()}{self._refresh_age()}\n\n"
            f"Send a hot reload to {s.server_name} (bridge port {s.port})?\n\n{what}\n\n"
            "The loader keeps the bridge port open and the server does not restart. "
            "If the new core fails, the loader rolls back on its own."
        )
        if not self._confirm(f"Confirm live reload on {s.server_name}", body, "Reload on server"):
            self._log("Live reload cancelled. Nothing was sent.", "dim")
            return
        self._start_live_action("reload", lambda src=self.source: src.reload(force=force),
                                f"hot reload{' (force)' if force else ''}")

    def _live_rollback(self) -> None:
        if self._live_action or self.state.connection != "Online":
            return
        s = self.state
        body = (
            f"{self._player_warning()}{self._refresh_age()}\n\n"
            f"Roll back the bridge core on {s.server_name} (bridge port {s.port})?\n\n"
            f"Running now: {s.core_release or ''} ({s.core_version}). The loader restores its "
            "previous good core. The server does not restart."
        )
        if not self._confirm(f"Confirm live rollback on {s.server_name}", body, "Roll back on server"):
            self._log("Live rollback cancelled. Nothing was sent.", "dim")
            return
        self._start_live_action("rollback", lambda src=self.source: src.rollback(), "hot rollback")

    def _start_live_action(self, kind: str, fn, label: str) -> None:
        ## Last line of defense: nothing live is sent unless the developer is signed in.
        if not self._is_developer():
            self._log(f"Live {kind} is developer only. Nothing was sent.", "warn")
            return
        src = self.source
        self._live_action = True
        self._set_busy(True)
        self.progress.setRange(0, 0)
        self.progress.setFormat(f"{kind.title()} running on server…")
        self._log(f"Sent {label} to {self.state.server_name}.", "cyan")
        run_async(
            fn,
            lambda res, src=src: self._on_live_action_done(src, kind, res),
            lambda k, msg, src=src: self._on_live_action_failed(src, kind, msg),
        )

    def _end_live_action(self) -> None:
        self._live_action = False
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Idle")
        self._set_busy(False)

    def _on_live_action_done(self, src, kind: str, res: dict) -> None:
        if not self._alive() or src is not self.source:
            return
        self._end_live_action()
        res = res if isinstance(res, dict) else {}
        ok = bool(res.get("ok"))
        result = str(res.get("result") or ("ok" if ok else "failed"))
        parts = [f"{kind.title()} result: {result}"]
        if res.get("from") or res.get("to"):
            parts.append(f"{res.get('from') or '—'} → {res.get('to') or res.get('current') or '—'}")
        if res.get("durationMs") is not None:
            parts.append(f"{res.get('durationMs')} ms")
        if res.get("rolledBackTo"):
            parts.append(f"rolled back to {res.get('rolledBackTo')}")
        detail = res.get("error") or res.get("message")
        if detail:
            parts.append(str(detail))
        text = " — ".join(parts)
        level = "ok" if ok and result.lower() not in ("unchanged", "failed", "error") else ("warn" if ok else "fail")
        self._log(text, level)
        self.footer.setText(text)
        self._last_core_id = None  # log the fresh state after the action
        self.refresh_live()

    def _on_live_action_failed(self, src, kind: str, message: str) -> None:
        if not self._alive() or src is not self.source:
            return
        self._end_live_action()
        self._log(f"{kind.title()} request failed: {message}", "fail")
        self.footer.setText(f"{kind.title()} request failed: {message}")
        self.refresh_live()

    # ----- layout ----------------------------------------------------------

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        if self.embedded:
            root.setContentsMargins(12, 8, 12, 8)
        else:
            root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(8)

        root.addLayout(self._build_header())
        root.addWidget(self._build_status_frame())
        root.addWidget(self._build_actions_frame())
        root.addWidget(self._build_history_frame(), stretch=3)
        root.addWidget(self._build_log_frame(), stretch=0)

        self.progress = QProgressBar()
        self.progress.setObjectName("ReloadProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Idle")
        self.progress.setVisible(True)
        self.progress.setFixedWidth(360)

        self.footer = QLabel("Ready. Port 30500 is held by the loader.")
        self.footer.setObjectName("PopupFooterLabel")

        bottom = QHBoxLayout()
        bottom.addWidget(self.footer, stretch=1)
        bottom.addWidget(self.progress)
        root.addLayout(bottom)

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        titles = QHBoxLayout()
        titles.setSpacing(16)
        title = QLabel("ZeroGBridge Hot Reload")
        title.setObjectName("PopupHeaderLabel")
        subtitle = QLabel(
            "The loader keeps the bridge port open while the core DLL is swapped. No restart."
        )
        subtitle.setObjectName("SubtitleLabel")
        subtitle.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(subtitle, stretch=1)
        row.addLayout(titles, stretch=1)

        self.badge = QLabel("LOADER ACTIVE")
        self.badge.setObjectName("StatusBadge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setFixedHeight(34)
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
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)

        hdr = QLabel("CONNECTION / STATUS")
        hdr.setObjectName("SectionHeader")
        layout.addWidget(hdr)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(3)
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
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)

        hdr = QLabel("ACTIONS")
        hdr.setObjectName("SectionHeader")
        layout.addWidget(hdr)

        file_row = QHBoxLayout()
        self.file_lbl = file_lbl = QLabel("New core DLL")
        file_lbl.setObjectName("FieldLabel")
        file_lbl.setFixedWidth(110)
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

        self.chk_force = QCheckBox("Force reload same core")
        self.chk_force.setToolTip("Live only: send reload with force, so the running core is reloaded "
                                  "even when nothing new is waiting in Updates/.")
        self.chk_force.setVisible(False)

        btn_row.addWidget(self.btn_reload)
        btn_row.addWidget(self.chk_force)
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
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)

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
        self.history.setAlternatingRowColors(True)
        hdr_view = self.history.horizontalHeader()
        hdr_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.history.itemSelectionChanged.connect(self._on_history_selection)
        self.history.setMinimumHeight(154)
        self.history.verticalHeader().setDefaultSectionSize(27)
        self.history.setCornerButtonEnabled(False)
        self.history.setShowGrid(True)
        layout.addWidget(self.history)
        return frame

    def _build_log_frame(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("ConsoleFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)

        hdr = QLabel("LOADER LOG")
        hdr.setObjectName("SectionHeader")
        layout.addWidget(hdr)

        self.log = QTextEdit()
        self.log.setObjectName("ConsoleDisplay")
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Loader events will appear here…")
        self.log.setMinimumHeight(82)
        self.log.setMaximumHeight(84)
        layout.addWidget(self.log)
        return frame

    # ----- status / history painting --------------------------------------

    def _set_badge(self, text: str, color: str) -> None:
        self.badge.setText(text)
        self.badge.setStyleSheet(
            f"QLabel#StatusBadge {{"
            f"  font-size: 13px; font-weight: bold; padding: 4px 12px;"
            f"  border-radius: 3px; border: 1px solid {color}; color: {color};"
            f"  background-color: rgba(0, 0, 0, 80);"
            f"}}"
        )

    def _refresh_status(self) -> None:
        s = self.state
        live = self.source.is_live
        online = s.connection == "Online"
        self.lbl_server.setText(s.server_name)
        self.lbl_loader.setText(s.loader_version)
        if live and s.core_release:
            self.lbl_core.setText(f"{s.core_release}  ({s.core_version})")
        else:
            self.lbl_core.setText(s.core_version)
        self.lbl_since.setText(fmt_time(s.loaded_since) if (online or not live) else "—")
        self.lbl_result.setText(s.last_result)
        if live and s.connection == "Connecting":
            color = COLOR_WARN
        else:
            color = COLOR_OK if s.last_ok else COLOR_FAIL
        self.lbl_result.setStyleSheet(f"color: {color}; font-size: 15px; font-weight: bold;")
        self.lbl_players.setText(str(s.players_online) if (online or not live) else "—")
        if live:
            self.lbl_port.setText(str(s.port))
            self.lbl_hold.setText(s.core_domain or "—")
            if s.busy or s.reload_in_progress:
                self._set_badge("RELOADING", COLOR_WARN)
            elif s.connection == "Connecting":
                self._set_badge("CONNECTING…", COLOR_WARN)
            elif s.connection == "Auth failed":
                self._set_badge("AUTH FAILED", COLOR_FAIL)
            elif s.connection == "Offline":
                self._set_badge("OFFLINE", COLOR_FAIL)
            elif s.last_ok:
                self._set_badge("LIVE · LOADER ACTIVE", COLOR_OK)
            else:
                self._set_badge("LIVE · LAST RELOAD FAILED", COLOR_WARN)
            return
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
        marked = False
        for entry in self.state.history:
            row = self.history.rowCount()
            self.history.insertRow(row)
            current = (not marked) and entry.version == self.state.core_version and entry.result == "OK"
            marked = marked or current
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
                elif not current:
                    item.setForeground(QColor("#d6e4ec"))
                else:
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

    ## Walks up the parents (panel -> portal -> cockpit) until it finds the cockpit's user_has_role.
    ## If no cockpit is found (e.g. the portal run on its own), the answer is no (fail closed).
    def _is_developer(self) -> bool:
        widget = self.parent()
        while widget is not None:
            user_has_role = getattr(widget, "user_has_role", None)
            if user_has_role is not None:
                return bool(user_has_role("developer"))
            widget = widget.parent()
        return False

    def _set_busy(self, busy: bool) -> None:
        self.state.busy = busy
        enabled = not busy
        live = self.source.is_live
        can_send = enabled and (not live or self.state.connection == "Online")
        ## Live Reload/Rollback change the server, so only the developer gets them.
        if live and not self._is_developer():
            can_send = False
        self.btn_browse.setEnabled(enabled and not live)
        self.btn_reload.setEnabled(can_send)
        self.btn_rollback_prev.setEnabled(can_send)
        self.chk_force.setEnabled(can_send and live)
        self.chk_auto.setEnabled(enabled and not live)
        self.btn_sim_drop.setEnabled(enabled and not live and self.chk_auto.isChecked())
        self.dll_path.setEnabled(enabled)
        if not busy:
            self._on_history_selection()
        else:
            self.btn_rollback_sel.setEnabled(False)
        self._refresh_status()

    def _on_history_selection(self) -> None:
        if self.state.busy or self.source.is_live:
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
        if self.source.is_live:
            return
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
        if self.source.is_live:
            return
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
        if self.source.is_live:
            self._live_reload()
            return
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
        if self.source.is_live:
            self._live_rollback()
            return
        entry = self._previous_ok_version()
        if not entry:
            self._log("No previous OK core is stashed in the loader.", "warn")
            return
        self._start_rollback(entry.version, confirm=True)

    def _on_rollback_selected(self) -> None:
        if self.source.is_live:
            return
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
        if n == 1:
            return f"1 player is currently online on {server}."
        return f"{n} players are currently online on {server}."

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


class _FitScrollArea(QScrollArea):
    """Fills the viewport, and only scrolls when the window is smaller than
    the panel's minimum size (plain widgetResizable grows to sizeHint, which
    adds a scrollbar even when everything would fit)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def _fit(self) -> None:
        w = self.widget()
        if w is None:
            return
        need = w.minimumSizeHint()
        vp = self.maximumViewportSize()
        width, height = vp.width(), vp.height()
        sb = self.style().pixelMetric(self.style().PixelMetric.PM_ScrollBarExtent)
        if need.height() > height:
            width -= sb
        if need.width() > width:
            height -= sb
        w.resize(max(width, need.width()), max(height, need.height()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit()


class HotReloadWindow(QWidget):
    """Top-level window with LOADER and BRIDGE tabs and a Live | Examples data source switch."""

    capture_finished = pyqtSignal()

    def __init__(self, capture_mode: bool = False, parent=None, source: PortalDataSource | None = None,
                 profile_provider=None):
        super().__init__(parent)
        self.capture_mode = capture_mode
        self.source = source or SampleDataSource()
        if self.source.is_live:
            self._live_source = self.source
        else:
            self._live_source = LiveDataSource(profile_provider)
        self._sample_source = self.source if not self.source.is_live else SampleDataSource()
        self._capture_dir = HERE
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(LIVE_REFRESH_MS)
        self._refresh_timer.timeout.connect(self.refresh)

        self.setObjectName("HotReloadCanvas")
        self.setWindowTitle("Zero-G Admin Helper - ZeroGBridge")
        self.resize(1280, 900)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(load_stylesheet())

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 12, 18, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        titles = QHBoxLayout()
        titles.setSpacing(16)
        title = QLabel("ZeroGBridge")
        title.setObjectName("PopupHeaderLabel")
        self.subtitle = subtitle = QLabel("")
        subtitle.setObjectName("SubtitleLabel")
        titles.addWidget(title)
        titles.addWidget(subtitle, stretch=1, alignment=Qt.AlignmentFlag.AlignBottom)
        head.addLayout(titles, stretch=1)

        src_lbl = QLabel("Data source")
        src_lbl.setObjectName("FieldLabel")
        self.source_picker = QComboBox()
        self.source_picker.setObjectName("SourcePicker")
        self.source_picker.addItems(["Live", "Examples"])
        self.source_picker.setToolTip("Live: the server ZAH is connected to. Examples: sample files in Examples/ZGB_Portal.")
        self.source_picker.setCurrentIndex(0 if self.source.is_live else 1)
        self.source_picker.currentIndexChanged.connect(self._on_source_picked)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setObjectName("ExecuteButton")
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.setToolTip("Read hot:status again now (read-only). Live data also refreshes every 30 s.")
        self.btn_refresh.clicked.connect(self.refresh)
        # Compact so the header stays one short row.
        self.btn_refresh.setStyleSheet("QPushButton#ExecuteButton { min-height: 22px; padding: 3px 14px; }")
        self.source_picker.setStyleSheet("QComboBox#SourcePicker { min-height: 22px; padding: 2px 8px; }")
        head.addWidget(src_lbl)
        head.addWidget(self.source_picker)
        head.addWidget(self.btn_refresh)
        root.addLayout(head)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("MainTabs")
        self.tabs.setDocumentMode(False)

        self.loader = HotReloadPanel(capture_mode=capture_mode, parent=self, embedded=True, source=self.source)
        self.loader._shot_target = self
        self.loader._capture_dir = self._capture_dir

        self.bridge = BridgePanel(parent=self, capture_mode=capture_mode, source=self.source)

        # Each tab scrolls if the window is smaller than the content.
        self.tabs.addTab(self._scrollable(self.loader), "  LOADER  ")
        self.tabs.addTab(self._scrollable(self.bridge), "  BRIDGE  ")
        root.addWidget(self.tabs, stretch=1)
        self._update_source_chrome()

    # ----- data source / refresh ------------------------------------------

    def _on_source_picked(self, index: int) -> None:
        src = self._live_source if index == 0 else self._sample_source
        if src is self.source:
            return
        self.source = src
        self.loader.set_source(src)
        self.bridge.set_source(src)
        self._update_source_chrome()

    def _update_source_chrome(self) -> None:
        live = self.source.is_live
        self.btn_refresh.setEnabled(live)
        if live:
            st = self.loader.state
            self.subtitle.setText(
                f"LIVE — {self._live_source.server_label()} · bridge {st.port} · auto refresh 30 s"
            )
            if self.isVisible():
                self._refresh_timer.start()
        else:
            self.subtitle.setText("EXAMPLES — sample data from Examples/ZGB_Portal, nothing is sent")
            self._refresh_timer.stop()

    def refresh(self) -> None:
        """Live: re-read hot:status (read-only). Examples: nothing to do."""
        if self.source.is_live:
            self.loader.refresh_live()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.source.is_live:
            self._refresh_timer.start()

    def hideEvent(self, event) -> None:
        self._refresh_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._refresh_timer.stop()
        super().closeEvent(event)

    @staticmethod
    def _scrollable(panel: QWidget) -> QScrollArea:
        area = _FitScrollArea()
        area.setObjectName("PortalScroll")
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(panel)
        return area

    def save_shot(self, path: Path) -> None:
        self.repaint()
        QApplication.processEvents()
        pix = self.grab()
        path.parent.mkdir(parents=True, exist_ok=True)
        ok = pix.save(str(path), "PNG")
        print(f"[CAPTURE] {'wrote' if ok else 'FAILED'} {path} ({pix.width()}x{pix.height()})")
