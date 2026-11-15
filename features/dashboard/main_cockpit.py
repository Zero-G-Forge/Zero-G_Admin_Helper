# =====================================================================
# MODULE: features/dashboard/main_cockpit.py
# DESCRIPTION: Core Main Cockpit Window Shell (Pure Layout & CSS Core)
# =====================================================================

import os
from features.paths import asset_path
import sys
import json
import socket
from datetime import datetime, timezone
from PyQt6 import QtCore
from PyQt6.QtWidgets import (
    QMainWindow, QMenuBar, QMenu, QWidget, QGridLayout, QFrame, QLabel, QVBoxLayout, 
    QTextEdit, QHBoxLayout, QComboBox, QLineEdit, QPushButton, 
    QTableWidget, QTableWidgetItem, QHeaderView, QStackedWidget, QDialog
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QPixmap, QAction, QKeySequence

# Core background workers, database manager, and popup modal imports
from features.auth.persistence import clear_login_session
from features.dashboard.player_manager import PlayerManager
from features.dashboard.telemetry_worker import TelemetryWorker
from features.dashboard.popups.active_entities_popup import ActiveEntitiesPopup
from features.dashboard.popups.player_registry_popup import PlayerRegistryPopup
from features.network.bridge_session import open_authenticated_socket, close_bridge_socket, switch_authenticated_socket
from features.network.connection import NetworkWizardOverlay
from features.network.server_config import (
    add_server_profile,
    get_active_profile,
    list_server_profiles,
    profile_label,
    registry_cache_for,
    set_active_server,
)
from features.network.server_switch import ServerSwitchDialog

class TelemetryWidget(QFrame):
    """
    Standalone high-density sub-panel managing server health metrics.
    Abstracted component for precision placement inside header controls.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("TelemetryPanel")
        self.setFixedSize(330, 70)  # Strict dimensional boundary control
        self.setStyleSheet("""
            QFrame#TelemetryPanel {
                background-color: rgba(10, 15, 25, 140);
                border: 1px solid #005577;
                border-radius: 4px;
            }
            QLabel {
                font-size: 11px;  /* Highly compressed font footprint */
                color: #e0e0e0;
                background: transparent;
                border: none;
            }
        """)

        # Micro sub-grid coordinates mapped inside the shrunk layout structure
        self.telemetry_layout = QGridLayout(self)
        self.telemetry_layout.setContentsMargins(6, 4, 6, 4)
        self.telemetry_layout.setSpacing(4)

        # --- Upper Telemetry Matrix Elements ---
        self.lbl_target_ip = QLabel("Target IP: Loading...", self)
        self.lbl_server_status = QLabel("Server Status: DETECTING....", self)
        self.telemetry_layout.addWidget(self.lbl_target_ip, 0, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.telemetry_layout.addWidget(self.lbl_server_status, 0, 1, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        # --- Lower Telemetry Matrix Elements ---
        self.lbl_server_cpu = QLabel("CPU: --%", self)
        self.lbl_server_ram = QLabel("RAM: --%", self)
        
        self.telemetry_layout.addWidget(self.lbl_server_cpu, 1, 0)
        self.telemetry_layout.addWidget(self.lbl_server_ram, 1, 1)

        # --- Dynamic Log Metrics Ingestion Elements ---
        self.lbl_fps = QLabel("FPS: --", self)
        self.lbl_heap = QLabel("Heap: --", self)
        self.lbl_players = QLabel("Players: --", self)
        self.lbl_uptime = QLabel("Uptime: --", self)
        
        self.telemetry_layout.addWidget(self.lbl_fps, 2, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.telemetry_layout.addWidget(self.lbl_heap, 2, 1, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.telemetry_layout.addWidget(self.lbl_players, 3, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.telemetry_layout.addWidget(self.lbl_uptime, 3, 1, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

class MainCockpit(QMainWindow):
    """ 
    Core Main Administration Cockpit Dashboard Shell.
    Maintains clean layout scaffolding and centralized CSS lookups.
    """
    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        
        # Instantiate local database manager backed by data/player_registry_cache.json
        self.player_manager = PlayerManager()
        self.config = config

        # 1. Base UI Setup
        print("[DEBUG] MainCockpit: Initializing Structural Window...")
        self.setObjectName("MainCockpitCanvas")
        self.setWindowTitle("Zero-G Admin Helper - Dashboard")
        self.setFixedSize(1280, 900)

        # 2. Central UI Canvas
        self.central_widget = QWidget()
        self.central_widget.setObjectName("CentralWidgetCanvas")
        self.setCentralWidget(self.central_widget)
        self.background = QPixmap(asset_path("backgrounds", "background.png"))

        # 3. Master Layout & Scaffolding
        self.master_layout = QHBoxLayout()
        self.master_layout.setObjectName("MasterLayout")
        self.master_layout.setContentsMargins(90, 200, 90, 95) 
        self.master_layout.setSpacing(15)
        self.central_widget.setLayout(self.master_layout)

        # 4. Construct Layout Zones
        print("[DEBUG] MainCockpit: Constructing Layout Zones...")
        self.setup_zones()

        # 5. Apply External QSS Theme
        print("[DEBUG] MainCockpit: Applying CSS Styles...")
        self.apply_theme()

        # --- Initialize the File Menu ---
        print("[DEBUG] MainCockpit: Initializing File Menu...")
        self.setup_menu_bar()

        print("[SUCCESS] Main Cockpit Dashboard structure initialized.")

        # 6. Initialize Network Background Services and UI Bindings
        self._init_network_services()

    def setup_menu_bar(self):
        """Constructs the native File Menu at the top of the QMainWindow."""
        # 1. Access the window's top-level menu bar container
        menu_bar = self.menuBar()

        # 2. Create the primary drop-down menu header
        file_menu = menu_bar.addMenu("&File")

        # 3. Define actionable drop-down line items
        refresh_action = QAction("&Refresh Tables", self)
        refresh_action.setShortcut("Ctrl+R")
        refresh_action.setStatusTip("Force a database sync refresh with the server mod bridge")
        refresh_action.triggered.connect(lambda: self.telemetry_worker.send_command("plys") if hasattr(self, 'telemetry_worker') and self.telemetry_worker else None)

        login_server_action = QAction("&Log into another server", self)
        login_server_action.setStatusTip("Authenticate to another ZeroGBridge server and save the profile")
        login_server_action.triggered.connect(self._on_log_into_another_server)

        switch_server_action = QAction("&Switch servers", self)
        switch_server_action.setStatusTip("Close this session and reconnect to a saved server profile")
        switch_server_action.triggered.connect(self._on_switch_servers)

        logout_action = QAction("&Log Out of ZAH", self)
        logout_action.setShortcut("Ctrl+Shift+L")
        logout_action.setStatusTip("Logs you out and back to main login screen")
        logout_action.triggered.connect(self._on_log_out)

        exit_action = QAction("&Exit ZAH", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)

        # 4. Pack items cleanly into the layout
        file_menu.addAction(refresh_action)
        file_menu.addSeparator()  # Native visual divider line
        file_menu.addAction(login_server_action)
        file_menu.addAction(switch_server_action)
        file_menu.addSeparator()  # Native visual divider line
        file_menu.addAction(logout_action)
        file_menu.addSeparator()  # Native visual divider line
        file_menu.addAction(exit_action)

    def setup_zones(self):
        """Constructs layout zones across the central dashboard canvas."""
        
        # Top Header Strip Layout
        self.top_header_layout = QHBoxLayout()
        self.top_header_layout.setObjectName("TopHeaderLayout")
        self.top_header_layout.setContentsMargins(10, 10, 10, 10)
        self.top_header_layout.addStretch()

        # Telemetry panel integrated into the top header strip
        self.telemetry_widget = TelemetryWidget(self)
        self.telemetry_widget.move(850, 110)

        # Left Column: Stacked Communications Engine Layout
        self.left_column = QVBoxLayout()
        self.left_column.setObjectName("LeftColumnLayout")

        self.feed_selector = QComboBox()
        self.feed_selector.setObjectName("FeedSelector")
        self.feed_selector.addItems([
            "Global Live Feed Chat", 
            "Faction Live Feed Chat", 
            "Admin Command Console", 
            "Active System DEBUG Logs"
        ])
        self.left_column.addWidget(self.feed_selector)

        self.feed_stack = QStackedWidget()
        self.feed_stack.setObjectName("FeedStack")

        self.global_chat_box = QTextEdit()
        self.global_chat_box.setObjectName("GlobalChatBox")
        self.global_chat_box.setReadOnly(True)
        self.global_chat_box.setPlaceholderText("Global communication feeds stand by...")

        self.faction_chat_box = QTextEdit()
        self.faction_chat_box.setObjectName("FactionChatBox")
        self.faction_chat_box.setReadOnly(True)
        self.faction_chat_box.setPlaceholderText("Faction communication feeds stand by...")

        self.console = QTextEdit()
        self.console.setObjectName("ConsoleDisplay")
        self.console.setReadOnly(True)
        self.console.setPlaceholderText("Data stream initialized, now listening...")

        self.system_logs_box = QTextEdit()
        self.system_logs_box.setObjectName("SystemLogsBox")
        self.system_logs_box.setReadOnly(True)
        self.system_logs_box.setPlaceholderText("System diagnostic records stand by...")

        self.feed_stack.addWidget(self.global_chat_box)  # Index 0
        self.feed_stack.addWidget(self.faction_chat_box) # Index 1
        self.feed_stack.addWidget(self.console)          # Index 2
        self.feed_stack.addWidget(self.system_logs_box)  # Index 3

        self.left_column.addWidget(self.feed_stack, stretch=1)

        # Input Submission Field Panel Layout
        self.input_layout = QHBoxLayout()
        self.input_layout.setObjectName("InputLayout")
        
        self.cmd_input = QLineEdit()
        self.cmd_input.setObjectName("CommandInput")
        self.cmd_input.setPlaceholderText("Enter Chat Message or Admin Command...")
        
        self.execute_btn = QPushButton("Execute")
        self.execute_btn.setObjectName("ExecuteButton")
        
        self.input_layout.addWidget(self.cmd_input, stretch=4)
        self.input_layout.addWidget(self.execute_btn, stretch=1)
        self.left_column.addLayout(self.input_layout)

        # Right Column: Metrics & Button Matrices Layout
        self.right_column = QVBoxLayout()
        self.right_column.setObjectName("RightColumnLayout")
        self.right_column.setSpacing(15)

        self.mid_row_layout = QHBoxLayout()
        self.mid_row_layout.setObjectName("MidRowLayout")

        # Player Registry Table Container Frame
        self.player_registry = QFrame()
        self.player_registry.setObjectName("PlayerRegistry")
        self.players_layout = QVBoxLayout(self.player_registry)
        self.players_layout.setObjectName("PlayersLayout")
        
        self.lbl_players_header = QLabel("Players on Server Within the Past 2 Weeks")
        self.lbl_players_header.setObjectName("HeaderLabel")

        self.player_table = QTableWidget(0, 5)
        self.player_table.setObjectName("PlayerRegistryTable")
        self.player_table.setHorizontalHeaderLabels(["Player", "Status", "Faction", "System", "Playfield"])
        self.player_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.player_table.verticalHeader().setVisible(False)
        
        self.players_layout.addWidget(self.lbl_players_header)
        self.players_layout.addWidget(self.player_table)

        # Button Matrix Control Panel Frame
        self.control_panel = QFrame()
        self.control_panel.setObjectName("ControlPanel")
        self.button_grid = QGridLayout(self.control_panel)
        self.button_grid.setObjectName("ButtonGrid")
        self.button_grid.setContentsMargins(5, 5, 5, 5)
        
        for row in range(4):
            for col in range(4):
                ## ===============
                ## Row 1 (Index 0)
                ## ===============
                if row == 0 and col == 0:
                    btn_text = "Player\nRegistry"
                    btn = QPushButton(btn_text)
                    btn.setObjectName("MatrixButton")
                    self.btn_player_registry = btn
                    self.btn_player_registry.clicked.connect(self._on_player_registry_clicked)
                elif row == 0 and col == 1:
                    btn_text = "Active\nPlayfields"
                    btn = QPushButton(btn_text)
                    btn.setObjectName("MatrixButton")
                    self.btn_active_playfields = btn
                    self.btn_active_playfields.clicked.connect(self._on_active_playfield_clicked)
                # elif row == 0 and col == 2:
                    # btn_text = f"[{row},{col}]"
                # elif row == 0 and col == 3:
                    # btn_text = f"[{row},{col}]"
                ## ===============
                ## Row 2 (Index 1)
                ## ===============
                # elif row == 1 and col == 0:
                    # btn_text = f"[{row},{col}]"
                # elif row == 1 and col == 1:
                    # btn_text = f"[{row},{col}]"
                # elif row == 1 and col == 2:
                    # btn_text = f"[{row},{col}]"
                # elif row == 1 and col == 3:
                    # btn_text = f"[{row},{col}]"
                ## ===============
                ## Row 3 (Index 2)
                ## ===============
                # elif row == 2 and col == 0:
                    # btn_text = f"[{row},{col}]"
                # elif row == 2 and col == 1:
                    # btn_text = f"[{row},{col}]"
                # elif row == 2 and col == 2:
                    # btn_text = f"[{row},{col}]"
                # elif row == 2 and col == 3:
                    # btn_text = f"[{row},{col}]"
                ## ===============
                ## Row 4 (Index 3)
                ## ===============
                # elif row == 3 and col == 0:
                    # btn_text = f"[{row},{col}]"
                # elif row == 3 and col == 1:
                    # btn_text = f"[{row},{col}]"
                elif row == 3 and col == 2:
                    btn_text = "Backup\nServer"
                    btn = QPushButton(btn_text)
                    btn.setObjectName("MatrixButton")
                    self.btn_backup_server = btn
                    self.btn_backup_server.clicked.connect(self._on_backup_clicked)
                elif row == 3 and col == 3:
                    btn_text = "Restart\nServer"
                    btn = QPushButton(btn_text)
                    btn.setObjectName("MatrixButton")
                    self.btn_restart_server = btn
                    self.btn_restart_server.clicked.connect(self._on_restart_clicked)
                else:
                    btn_text = f"[{row},{col}]"
                    btn = QPushButton(btn_text)
                    btn.setObjectName("MatrixButton")

                btn.setSizePolicy(btn.sizePolicy().Policy.Expanding, btn.sizePolicy().Policy.Expanding)
                self.button_grid.addWidget(btn, row, col)
      
        self.mid_row_layout.addWidget(self.player_registry, stretch=2)
        self.mid_row_layout.addWidget(self.control_panel, stretch=1)
        self.right_column.addLayout(self.mid_row_layout, stretch=2)

        # Lower Right Dynamic Sub-Panel Frame
        self.bottom_row_layout = QHBoxLayout()
        self.bottom_row_layout.setObjectName("BottomRowLayout")

        self.display_fbp = QFrame()
        self.display_fbp.setObjectName("DynamicDisplayA")
        self.layout_fbp = QVBoxLayout(self.display_fbp)
        self.layout_fbp.setObjectName("DynamicDisplayLayout")
        
        self.dynamic_display_fbp = QStackedWidget()
        self.dynamic_display_fbp.setObjectName("DynamicDisplayStack")
        
        fbp1 = QLabel("Functional Button Display")
        fbp1.setObjectName("DynamicDisplayLabel")
        fbp1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.dynamic_display_fbp.addWidget(fbp1)
        self.layout_fbp.addWidget(self.dynamic_display_fbp)
        
        self.bottom_row_layout.addWidget(self.display_fbp, stretch=1)
        self.right_column.addLayout(self.bottom_row_layout, stretch=3)

        # Canvas Consolidation Assembly
        self.content_columns_layout = QHBoxLayout()
        self.content_columns_layout.setObjectName("ContentColumnsLayout")
        self.content_columns_layout.addLayout(self.left_column, stretch=35)
        self.content_columns_layout.addLayout(self.right_column, stretch=65)

        self.master_vertical_layout = QVBoxLayout()
        self.master_vertical_layout.setObjectName("MasterVerticalLayout")
        self.master_vertical_layout.addLayout(self.top_header_layout)
        self.master_vertical_layout.addLayout(self.content_columns_layout)

        self.master_layout.addLayout(self.master_vertical_layout)

    # -------------------------------------------------------------------------
    # Loads Visualization Programming
    # -------------------------------------------------------------------------

    def paintEvent(self, event):
        """Force background canvas visualization mapping."""
        painter = QPainter(self)
        if not self.background.isNull():
            scaled_bg = self.background.scaled(self.size(), Qt.AspectRatioMode.IgnoreAspectRatio)
            painter.drawPixmap(0, 0, scaled_bg)
        painter.end()

    def apply_theme(self):
        """Loads external CSS stylesheet from assets/ZAH.css."""
        try:
            css_path = os.path.join(os.path.dirname(__file__), '..', '..', 'assets', 'ZAH.css')
            with open(css_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
            print(f"[SUCCESS] Main Cockpit applied stylesheet: {css_path}")
        except Exception as e:
            print(f"[ERROR] Could not load stylesheet: {e}")

    # -------------------------------------------------------------------------
    # Initiating Network Connection
    # -------------------------------------------------------------------------

    def _init_network_services(self):
        """
        Instantiates background telemetry streaming worker and wires UI control triggers.
        Dynamically extracts host IP and Port from the active server profile.
        """
        self._wire_command_inputs()

        target_ip, target_port, token = self._resolve_server_target()

        # Guard check to abort cleanly if no valid target IP was found
        if not target_ip:
            print("[ERROR] MainCockpit: No valid server IP found in config or on disk.")
            self.setWindowTitle("Zero-G Admin Helper - Dashboard")
            self.telemetry_widget.lbl_target_ip.setText("Target IP: Not Configured")
            return

        self._show_active_server({"input_ip": target_ip, "input_port": target_port, "input_pass": token})
        self._load_registry_for_profile(self.config)
        self._spawn_telemetry_worker(target_ip, target_port, token)

        # Render immediately from the local database on startup
        self._refresh_dashboard_table()

    def _wire_command_inputs(self):
        """Connects the console controls once. Later server switches must not stack handlers."""
        if getattr(self, "_inputs_wired", False):
            return
        self._inputs_wired = True
        self.execute_btn.clicked.connect(self._handle_command_execution)
        self.cmd_input.returnPressed.connect(self._handle_command_execution)
        self.feed_selector.currentIndexChanged.connect(self.feed_stack.setCurrentIndex)

    def _resolve_server_target(self):
        """
        Returns (ip, port, token) for the active profile.
        The in-memory config wins. Otherwise the saved active profile is loaded.
        """
        source = {}
        if self.config and isinstance(self.config, dict) and self.config.get("input_ip"):
            source = self.config
        else:
            try:
                source = get_active_profile()
            except Exception as err:
                print(f"[ERROR] MainCockpit: Failed to parse server_config.json: {err}")
                source = {}
            if source:
                self.config = source

        target_ip = source.get("input_ip") if isinstance(source, dict) else None
        target_port = 30500
        raw_port = source.get("input_port") if isinstance(source, dict) else None
        if raw_port:
            try:
                target_port = int(raw_port)
            except (TypeError, ValueError):
                print(f"[ERROR] MainCockpit: Invalid port value in server profile: {raw_port}")
                target_port = 30500
        token = source.get("input_pass") if isinstance(source, dict) and source.get("input_pass") else ""
        return target_ip, target_port, token

    def _show_active_server(self, profile):
        """Puts the active host:port in the window title and the telemetry target label."""
        label = profile_label(profile)
        self.setWindowTitle(f"Zero-G Admin Helper - Dashboard ({label})")
        self.telemetry_widget.lbl_target_ip.setText(f"Target IP: {label}")
        print(f"[STATUS] Active server: {label}")

    def _reset_metric_readouts(self):
        """Clears the last server's telemetry while a new session is opening."""
        self.telemetry_widget.lbl_server_status.setText("Server Status: DETECTING....")
        self.telemetry_widget.lbl_server_status.setStyleSheet("")
        self.telemetry_widget.lbl_server_cpu.setText("CPU: --%")
        self.telemetry_widget.lbl_server_ram.setText("RAM: --%")
        self.telemetry_widget.lbl_fps.setText("FPS: --")
        self.telemetry_widget.lbl_heap.setText("Heap: --")
        self.telemetry_widget.lbl_players.setText("Players: --")
        self.telemetry_widget.lbl_uptime.setText("Uptime: --")

    def _load_registry_for_profile(self, profile):
        """Reloads the player table cache that belongs to this server."""
        if not profile or not profile.get("input_ip"):
            return
        cache_path = registry_cache_for(profile)
        current = os.path.abspath(self.player_manager.storage_path)
        if os.path.abspath(cache_path) == current:
            return
        self.player_manager.reload_storage(cache_path)

    def _stop_telemetry_worker(self):
        """Closes the current ZeroGBridge session and drops the worker."""
        worker = getattr(self, "telemetry_worker", None)
        if worker is not None:
            worker.stop()
            self.telemetry_worker = None

    def _spawn_telemetry_worker(self, host, port, token, connected_socket=None):
        """Starts a telemetry worker for host:port. An already-authenticated socket is reused."""
        print(f"[DEBUG] MainCockpit: Initializing TelemetryWorker target: {host}:{port}")
        worker = TelemetryWorker(
            host=host,
            port=port,
            password=token,
            connected_socket=connected_socket,
        )
        worker.metrics_updated.connect(self._on_metrics_received)
        worker.players_updated.connect(self._on_live_stream_received)
        worker.player_cache_received.connect(self._on_full_cache_received)
        worker.command_response_received.connect(self._on_command_response_received)
        worker.connection_status.connect(self._on_connection_status)
        worker.start()
        self.telemetry_worker = worker

    def _refresh_after_server_switch(self, profile):
        """Shows the new server and repaints the roster from that server's cache."""
        self._show_active_server(profile)
        self._load_registry_for_profile(profile)
        self._refresh_dashboard_table()
        label = profile_label(profile)
        timestamp = datetime.now(timezone.utc).strftime("%H:%M")
        self.console.append(f"[{timestamp}] [ADMIN >>] Switched server to {label}")
        self.system_logs_box.append(f"[NETWORK] Active server: {label}")

    def _switch_to_saved_profile(self, profile, allow_restore=True):
        """
        Closes the current ZeroGBridge session, authenticates to the chosen
        profile, then refreshes the dashboard. A failed auth tries the previous
        server once so the cockpit is not left with no session.
        """
        previous = dict(self.config) if isinstance(self.config, dict) else {}
        ip = str(profile.get("input_ip", "")).strip()
        port_text = str(profile.get("input_port", "")).strip()
        token = str(profile.get("input_pass", "") or "")
        if not ip or not port_text:
            self.system_logs_box.append("[NETWORK WARNING] Cannot switch: server profile is missing a host or port.")
            return False
        try:
            port = int(port_text)
        except (TypeError, ValueError):
            self.system_logs_box.append(f"[NETWORK WARNING] Cannot switch: invalid port for {ip}.")
            return False

        print(f"[STATUS] Closing current ZeroGBridge session before switching to {ip}:{port}")
        self.system_logs_box.append(f"[NETWORK] Closing current session. Switching to {ip}:{port}...")
        self._reset_metric_readouts()
        self._stop_telemetry_worker()

        try:
            new_sock = switch_authenticated_socket(None, ip, port, token)
        except Exception as err:
            print(f"[WARNING] Server switch failed for {ip}:{port}: {err}")
            self.system_logs_box.append(f"[NETWORK WARNING] Switch failed for {ip}:{port}: {err}")
            self.telemetry_widget.lbl_server_status.setText("Server Status: OFFLINE")
            self.telemetry_widget.lbl_server_status.setStyleSheet("color: #ff3355; font-weight: bold;")
            if allow_restore and previous.get("input_ip") and profile_label(previous) != profile_label(profile):
                print("[STATUS] Restoring the previous ZeroGBridge session.")
                self.system_logs_box.append("[NETWORK] Restoring the previous server session.")
                self._switch_to_saved_profile(previous, allow_restore=False)
            return False

        set_active_server(ip, port_text)
        self.config = {
            "input_ip": ip,
            "input_port": port_text,
            "input_pass": token,
        }
        self._spawn_telemetry_worker(ip, port, token, connected_socket=new_sock)
        self._refresh_after_server_switch(self.config)
        return True

    def _on_log_into_another_server(self):
        """
        Opens the network wizard for another host, port, and auth token.
        The profile is saved only after that bridge accepts the handshake,
        and the other saved servers are left in place.
        """
        print("[UI EVENT] Log into another server requested.")
        wizard = NetworkWizardOverlay(self, persist_profile=False)
        if wizard.exec() != QDialog.DialogCode.Accepted:
            print("[STATUS] Additional server login canceled.")
            return

        profile = dict(getattr(wizard, "entered_profile", None) or {})
        ip = str(profile.get("input_ip", "")).strip()
        port_text = str(profile.get("input_port", "")).strip()
        token = str(profile.get("input_pass", "") or "")
        if not ip or not port_text:
            self.system_logs_box.append("[NETWORK WARNING] Server host and port are required.")
            return
        try:
            port = int(port_text)
        except (TypeError, ValueError):
            self.system_logs_box.append("[NETWORK WARNING] Server port is not a number.")
            return

        print(f"[STATUS] Checking auth for additional server {ip}:{port}...")
        try:
            probe = open_authenticated_socket(ip, port, token)
            close_bridge_socket(probe)
        except Exception as err:
            print(f"[WARNING] Additional server login failed: {err}")
            self.system_logs_box.append(
                f"[NETWORK WARNING] Login failed for {ip}:{port}. Current session was left open. {err}"
            )
            return

        add_server_profile(ip, port_text, token, make_active=False)
        self._switch_to_saved_profile({
            "input_ip": ip,
            "input_port": port_text,
            "input_pass": token,
        })

    def _on_switch_servers(self):
        """Opens the saved-server list and reconnects to the operator's choice."""
        print("[UI EVENT] Switch servers requested.")
        servers, active_index = list_server_profiles()
        if not servers:
            self.system_logs_box.append("[NETWORK WARNING] No saved servers yet. Use Log into another server first.")
            print("[WARNING] Switch servers opened with an empty profile list.")
            return

        dialog = ServerSwitchDialog(servers, active_index=active_index, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.selected_profile:
            print("[STATUS] Server switch canceled.")
            return
        self._switch_to_saved_profile(dialog.selected_profile)

    def _on_log_out(self):
        """
        Closes the ZeroGBridge session and returns to the startup login flow.
        Saved server profiles and auth tokens stay on disk.
        """
        print("[UI EVENT] Log Out of ZAH requested.")
        self._stop_telemetry_worker()
        self._clear_dashboard_session()
        clear_login_session()
        self._return_to_start_screen()

    def _clear_dashboard_session(self):
        """Clears the live dashboard. Saved server profiles are left on disk."""
        self._reset_metric_readouts()
        self.telemetry_widget.lbl_server_status.setText("Server Status: OFFLINE")
        self.telemetry_widget.lbl_server_status.setStyleSheet("color: #ff3355; font-weight: bold;")
        self.telemetry_widget.lbl_target_ip.setText("Target IP: Not Configured")
        self.setWindowTitle("Zero-G Admin Helper - Dashboard")
        self.console.clear()
        self.global_chat_box.clear()
        self.faction_chat_box.clear()
        self.system_logs_box.clear()
        self.cmd_input.clear()
        self.player_table.setRowCount(0)
        self.lbl_players_header.setText("Players on Server Within the Past 2 Weeks")
        print("[STATUS] Dashboard session cleared.")

    def _return_to_start_screen(self):
        """
        Hides the dashboard and runs the startup loader.
        The loader opens the login window, then the network check.
        """
        print("[STATUS] Returning to the login screen.")
        self.hide()
        loader = None
        result = QDialog.DialogCode.Rejected
        try:
            from features.loading.loading_screen import ApplicationLoader
            loader = ApplicationLoader()
            loader.start_boot_sequence()
            result = loader.exec()
        except Exception as err:
            print(f"[ERROR] Login flow failed after logout: {err}")
            self.close()
            return
        finally:
            if loader is not None:
                loader.deleteLater()

        if result == QDialog.DialogCode.Accepted:
            print("[SUCCESS] Login verified after logout. Restoring the dashboard.")
            try:
                self.config = get_active_profile()
            except Exception as err:
                print(f"[WARNING] Could not reload the active server profile: {err}")
            self._init_network_services()
            self.show()
            return

        print("[STATUS] Login canceled after logout. Shutting down.")
        self.close()

    # -------------------------------------------------------------------------
    # Determines if Server is ONLINE/OFFLINE
    # -------------------------------------------------------------------------

    def _on_connection_status(self, is_connected: bool, message: str):
        """
        Slot receiver handling connection state changes from TelemetryWorker.
        Updates HUD status labels and logs network link events.
        """
        if is_connected:
            # Update HUD status label to ONLINE with neon cyan/green accent
            self.telemetry_widget.lbl_server_status.setText("Server Status: ONLINE")
            self.telemetry_widget.lbl_server_status.setStyleSheet("color: #00ff88; font-weight: bold;")
            print(f"[STATUS] MainCockpit: Link established over Port 30500 - Connected")
            self.system_logs_box.append(f"[NETWORK] Link established: {message}")
        else:
            # Update HUD status label to OFFLINE with red accent
            self.telemetry_widget.lbl_server_status.setText("Server Status: OFFLINE")
            self.telemetry_widget.lbl_server_status.setStyleSheet("color: #ff3355; font-weight: bold;")
            print(f"[WARN] MainCockpit: Link closed over Port 30500 - Disconnected")
            self.system_logs_box.append(f"[NETWORK WARNING] Link closed: {message}")

    # -------------------------------------------------------------------------
    # Receiving Telemetry UI Metrics
    # -------------------------------------------------------------------------

    def _on_metrics_received(self, metric: dict):
        """
        Slot receiver handling live engine telemetry updates emitted by TelemetryWorker.
        Extracts performance metrics and updates the upper HUD telemetry panel.
        """
        if not metric or not isinstance(metric, dict):
            return

        # Step 1: Safely extract telemetry fields with fallbacks
        cpu = metric.get("cpu", 0.0)
        ram = metric.get("ram", "--")
        fps = metric.get("fps", 0.0)
        heap = metric.get("heap", "--")
        players = metric.get("players", 0)
        uptime = metric.get("uptime", "--")

        # Step 2: Dynamically update host hardware labels (CPU & RAM)
        try:
            self.telemetry_widget.lbl_server_cpu.setText(f"CPU: {float(cpu):.1f}%")
        except (ValueError, TypeError):
            self.telemetry_widget.lbl_server_cpu.setText(f"CPU: {cpu}%")

        # Format RAM display string cleanly
        if isinstance(ram, str) and (ram.endswith("MB") or ram.endswith("GB") or ram.endswith("%") or ram == "--"):
            self.telemetry_widget.lbl_server_ram.setText(f"RAM: {ram}")
        else:
            self.telemetry_widget.lbl_server_ram.setText(f"RAM: {ram}%")

        # Step 3: Dynamically update HUD Telemetry labels
        try:
            self.telemetry_widget.lbl_fps.setText(f"FPS: {float(fps):.1f}")
        except (ValueError, TypeError):
            self.telemetry_widget.lbl_fps.setText(f"FPS: {fps}")

        self.telemetry_widget.lbl_heap.setText(f"Heap: {heap}")
        self.telemetry_widget.lbl_players.setText(f"Players: {players}")
        self.telemetry_widget.lbl_uptime.setText(f"Uptime: {uptime}")

        # Step 4: Diagnostic terminal trace for ingestion verification
        print(f"[METRIC INGEST] CPU: {cpu} | RAM: {ram} | FPS: {fps} | Heap: {heap} | Players: {players} | Uptime: {uptime}")

    # -------------------------------------------------------------------------
    # Ingests Master Server Roster (From 'plys')
    # -------------------------------------------------------------------------

    def _on_full_cache_received(self, cache_pkg: dict):
        """Ingests server player cache, merges it with local disk JSON, and refreshes table."""

        if not cache_pkg or not isinstance(cache_pkg, dict):
            return

        roster = cache_pkg.get("player_list", [])

        self.player_manager.update_from_roster_cache(roster)
        self._refresh_dashboard_table()

    # -------------------------------------------------------------------------
    # Ingests 2-Second Live Telemetry Stream
    # -------------------------------------------------------------------------

    def _on_live_stream_received(self, online_list: list):
        """Ingests 2-second METRIC player stream into PlayerManager and refreshes table."""

        if not isinstance(online_list, list):
            return

        self.player_manager.update_from_live_stream(online_list)
        self._refresh_dashboard_table()

    # -------------------------------------------------------------------------
    # Renders 14-Day Dashboard Table
    # -------------------------------------------------------------------------

    def _refresh_dashboard_table(self):
        """
        Filters the local database for players active within the past 14 days
        and repopulates the 5-column QTableWidget on the main cockpit.
        """
        recent_players = self.player_manager.get_recent_players(days=14)

        # Step 1: Temporarily disable sorting during batch population
        self.player_table.setSortingEnabled(False)
        self.player_table.setRowCount(len(recent_players))

        # Step 2: Populate the 5-column table structure using modern keys
        for row_pos, p in enumerate(recent_players):
            name = str(p.get("name", "Unknown"))
            status = str(p.get("status", "Offline"))
            faction = str(p.get("faction", "--"))
            system = str(p.get("solar_system", "--"))
            playfield = str(p.get("playfield", "--"))

            col_values = [name, status, faction, system, playfield]
            for col_idx, text_val in enumerate(col_values):
                item = QTableWidgetItem(str(text_val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.player_table.setItem(row_pos, col_idx, item)

        # Step 3: Re-enable sorting and update header counter
        self.player_table.setSortingEnabled(True)
        self.lbl_players_header.setText(f"Players on Server (Past 2 Weeks: {len(recent_players)})")

    # -------------------------------------------------------------------------
    # Command Response Handler
    # -------------------------------------------------------------------------
    
    def _on_command_response_received(self, response_data: dict):
        """
        Slot receiver displaying raw JSON and structured feedback in the Admin Command Console.
        """
        if not response_data or not isinstance(response_data, dict):
            return

        timestamp = datetime.now(timezone.utc).strftime("%H:%M")
        res_type = response_data.get("type", "RESPONSE")
        status = response_data.get("status", "")
        message = response_data.get("message", "")

        # Format output for the console text display
        if res_type == "ERROR":
            display_line = f"[{timestamp}] [SERVER ERROR] {message}"
        elif res_type == "PLAYER_CACHE":
            total = response_data.get("players", 0)
            display_line = f"[{timestamp}] [SERVER <<] PLAYER_CACHE: {total} player(s) returned."
        elif res_type == "ENTITY_LIST":
            ents = len(response_data.get("entities", []))
            display_line = f"[{timestamp}] [SERVER <<] ENTITY_LIST: {ents} structure(s) returned."
        else:
            display_line = f"[{timestamp}] [SERVER <<] ({status}) {message if message else json.dumps(response_data)}"

        self.console.append(display_line)

    # -------------------------------------------------------------------------
    # Legacy Signal Pass-Through Slots
    # -------------------------------------------------------------------------

    def _on_players_received(self, player_list: list):
        """Direct pass-through slot routing to live stream handler."""
        self._on_live_stream_received(player_list)

    def _on_player_cache_received(self, cache_pkg: dict):
        """Direct pass-through slot routing to full cache handler."""
        self._on_full_cache_received(cache_pkg)

    # -------------------------------------------------------------------------
    # Feed Stack Execute Action Controller
    # -------------------------------------------------------------------------

    def _handle_command_execution(self):
        """
        Slot handler triggered by Return key or the Execute button.
        Routes outbound admin console commands and broadcasts to TelemetryWorker.
        """
        raw_command = self.cmd_input.text().strip()
        if not raw_command:
            return

        # Step 1: Echo outbound command to the console/chat feed
        timestamp = datetime.now(timezone.utc).strftime("%H:%M")
        echo_line = f"[{timestamp}] [ADMIN >>] {raw_command}"
        self.console.append(echo_line)

        # Mirror to global chat box if chat feed is active
        if self.feed_selector.currentIndex() == 0:
            self.global_chat_box.append(echo_line)

        # Step 2: Transmit outbound command over Port 30500 via TelemetryWorker
        if hasattr(self, 'telemetry_worker') and self.telemetry_worker:
            self.telemetry_worker.send_command(raw_command)
            print(f"[DISPATCH] MainCockpit: Transmitted console command: '{raw_command}'")
        else:
            print("[WARN] MainCockpit: Cannot dispatch command - TelemetryWorker offline.")

        # Step 3: Reset input field and maintain active keyboard focus
        self.cmd_input.clear()
        self.cmd_input.setFocus()

    # -------------------------------------------------------------------------
    # Button Matrix Action Controllers
    # -------------------------------------------------------------------------

    def _on_player_registry_clicked(self):
        """
        Spawns the PlayerRegistryPopup modal passing the persistent PlayerManager.
        """
        print("[MainCockpit] -ACTION- 'Player Registry' invoked.")
        if hasattr(self, 'telemetry_worker') and self.telemetry_worker:
            self.telemetry_worker.send_command("plys")

        try:
            popup = PlayerRegistryPopup(
                telemetry_worker=getattr(self, 'telemetry_worker', None),
                player_manager=self.player_manager,
                parent=self
            )
            popup.exec()
        except Exception as e:
            print(f"[ERROR] MainCockpit: Could not launch PlayerRegistryPopup: {e}")

    def _on_active_playfield_clicked(self):
        """
        Spawns the ActiveEntitiesPopup modal dialog.
        """
        print("[MainCockpit] -ACTION- 'Active Entities / Playfields' invoked.")
        try:
            popup = ActiveEntitiesPopup(telemetry_worker=getattr(self, 'telemetry_worker', None), parent=self)
            popup.exec()
        except Exception as ex:
            print(f"[ERROR] MainCockpit: Failed to launch ActiveEntitiesPopup: {ex}")

    def _on_backup_clicked(self):
        """
        Issues dedicated world backup and save directives to the server.
        """
        print("[MainCockpit] -ACTION- 'Backup Server' triggered. Dispatching backup token...")
        if hasattr(self, "telemetry_worker") and self.telemetry_worker:
            self.telemetry_worker.send_command("save")

    def _on_restart_clicked(self):
        """
        Issues a server restart instruction sequence across Port 30500.
        """
        print("[MainCockpit] -ACTION- 'Restart Server' triggered. Dispatching restart token...")
        if hasattr(self, "telemetry_worker") and self.telemetry_worker:
            self.telemetry_worker.send_command("restart")

    # -------------------------------------------------------------------------
    # Program Close Action Handler
    # -------------------------------------------------------------------------

    def closeEvent(self, event):
        """
        Ensures background worker threads and socket listeners are terminated
        before the window is destroyed.
        """
        print("[INFO] MainCockpit: Shutting down background network threads...")
        self._stop_telemetry_worker()
        event.accept()

    # -------------------------------------------------------------------------
    # 
    # -------------------------------------------------------------------------