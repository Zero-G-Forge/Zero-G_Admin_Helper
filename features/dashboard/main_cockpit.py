# =====================================================================
# MODULE: features/dashboard/main_cockpit.py
# DESCRIPTION: Core Main Cockpit Window Shell (Pure Layout & CSS Core)
# =====================================================================

import os
import sys
import json
import socket 
from PyQt6 import QtCore
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QGridLayout, QFrame, QLabel, QVBoxLayout, 
    QTextEdit, QHBoxLayout, QComboBox, QLineEdit, QPushButton, 
    QTableWidget, QTableWidgetItem, QHeaderView, QStackedWidget
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QPixmap

from features.dashboard.telemetry_worker import TelemetryWorker
## from features.dashboard.resource_worker import ResourcePollingWorker
## from features.dashboard.command_pipe import CommandPipe
## from features.dashboard.log_tee import LogTee
## from features.network.connection import is_network_ready
## from data.player_registry import PlayerRegistryPopup
## from data.playfield_registry import ActivePlayfieldsPopup

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
        self.background = QPixmap("assets/backgrounds/background.png")

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
        print("[SUCCESS] Main Cockpit Dashboard structure initialized.")

        # 6. Initialize Network Background Services and UI Bindings
        self._init_network_services()

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

        self.faction_chat_box = QTextEdit()
        self.faction_chat_box.setObjectName("FactionChatBox")
        self.faction_chat_box.setReadOnly(True)

        self.console = QTextEdit()
        self.console.setObjectName("ConsoleDisplay")
        self.console.setReadOnly(True)

        self.system_logs_box = QTextEdit()
        self.system_logs_box.setObjectName("SystemLogsBox")
        self.system_logs_box.setReadOnly(True)

        self.feed_stack.addWidget(self.global_chat_box)
        self.feed_stack.addWidget(self.faction_chat_box)
        self.feed_stack.addWidget(self.console)
        self.feed_stack.addWidget(self.system_logs_box)

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
    # Initating Network Connection
    # -------------------------------------------------------------------------

    def _init_network_services(self):
        """
        Instantiates background telemetry streaming worker and wires UI control triggers.
        Dynamically extracts host IP and Port from server_config.json.
        """
        target_ip = None
        target_port = 30500

        # Step 1: Attempt lookup from passed configuration dictionary
        if self.config and isinstance(self.config, dict):
            target_ip = self.config.get("input_ip")
            raw_port = self.config.get("input_port")
            if raw_port:
                target_port = int(raw_port)

        # Step 2: Fallback direct read from data/server_config.json on disk
        if not target_ip:
            config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'server_config.json')
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                        target_ip = cfg.get("input_ip")
                        raw_port = cfg.get("input_port")
                        if raw_port:
                            target_port = int(raw_port)
                except Exception as e:
                    print(f"[ERROR] MainCockpit: Failed to parse server_config.json: {e}")

        # Step 3: Guard check to abort cleanly if no valid target IP was found
        if not target_ip:
            print("[ERROR] MainCockpit: No valid server IP found in config or on disk.")
            self.telemetry_widget.lbl_target_ip.setText("Target IP: Not Configured")
            return

        # Step 4: Update HUD Header Label dynamically with resolved IP and Port
        self.telemetry_widget.lbl_target_ip.setText(f"Target IP: {target_ip}:{target_port}")

        # Step 5: Ingest background telemetry stream over Port 30500
        print(f"[DEBUG] MainCockpit: Initializing TelemetryWorker target: {target_ip}:{target_port}")
        self.telemetry_worker = TelemetryWorker(host=target_ip, port=target_port)
        self.telemetry_worker.metrics_updated.connect(self._on_metrics_received)
        self.telemetry_worker.players_updated.connect(self._on_players_received)
        self.telemetry_worker.connection_status.connect(self._on_connection_status)
        self.telemetry_worker.start()

        # Step 6: Wire UI input triggers and feed selector stack
        self.execute_btn.clicked.connect(self._handle_command_execution)
        self.cmd_input.returnPressed.connect(self._handle_command_execution)
        self.feed_selector.currentIndexChanged.connect(self.feed_stack.setCurrentIndex)

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
    # Populates Active Player Table
    # -------------------------------------------------------------------------

    def _on_players_received(self, player_list: list):
        """
        Slot receiver handling active player roster packets from TelemetryWorker.
        Re-renders the 5-column QTableWidget with current server player states.
        """
        if player_list is None or not isinstance(player_list, list):
            return

        # Step 1: Temporarily disable sorting/updates during batch population
        self.player_table.setSortingEnabled(False)
        self.player_table.setRowCount(len(player_list))

        # Step 2: Update HUD Header text with active roster count
        self.lbl_players_header.setText(f"Players on Server: ({len(player_list)} Active)")

        # Step 3: Iterate and populate the 5-column table structure
        for row_idx, player in enumerate(player_list):
            # Normalize dictionary or raw object lookups safely
            if isinstance(player, dict):
                p_name = player.get("name") or player.get("steamId", "Unknown Player")
                p_status = player.get("status", "Active")
                p_faction = player.get("faction", "--")
                p_system = player.get("system", "SolarSystem")
                p_playfield = player.get("playfield", "--")
            else:
                p_name = str(player)
                p_status = "Active"
                p_faction = "--"
                p_system = "SolarSystem"
                p_playfield = "--"

            # Column mapping: [Player, Status, Faction, System, Playfield]
            col_values = [p_name, p_status, p_faction, p_system, p_playfield]

            for col_idx, text_val in enumerate(col_values):
                item = QTableWidgetItem(str(text_val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                # Keep table items read-only
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.player_table.setItem(row_idx, col_idx, item)

        # Step 4: Re-enable sorting and trigger table redraw
        self.player_table.setSortingEnabled(True)
        print(f"[ROSTER INGEST] Populated {len(player_list)} active player record(s) into table.")

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
        echo_line = f"[ADMIN >>] {raw_command}"
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
        Queries the current connected player cache from ZeroGBridge.
        """
        print("[MainCockpit] -ACTION- 'Player Registry' invoked. Requesting player roster...")
        if hasattr(self, "telemetry_worker") and self.telemetry_worker:
            self.telemetry_worker.send_command("plys")

    def _on_active_playfield_clicked(self):
        """
        Placeholder slot for the Active Playfields matrix action.
        """
        print("[MainCockpit] -ACTION- 'Active Playfields' clicked.")
        if hasattr(self, "telemetry_worker") and self.telemetry_worker:
            self.telemetry_worker.send_command("gents")

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
        if hasattr(self, 'telemetry_worker') and self.telemetry_worker:
            self.telemetry_worker.stop()
        
        event.accept()

    # -------------------------------------------------------------------------
    # 
    # -------------------------------------------------------------------------

