# =====================================================================
# MODULE: features/dashboard/main_cockpit.py
# DESCRIPTION: Core Main Cockpit Window Shell (Pure Layout & CSS Core)
# =====================================================================

import os
import sys
import json
import socket 
from datetime import datetime, timedelta
from PyQt6 import QtCore
from PyQt6.QtWidgets import (
    QMainWindow, QMenuBar, QMenu, QWidget, QGridLayout, QFrame, QLabel, QVBoxLayout, 
    QTextEdit, QHBoxLayout, QComboBox, QLineEdit, QPushButton, 
    QTableWidget, QTableWidgetItem, QHeaderView, QStackedWidget
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QPixmap, QAction, QKeySequence

from features.dashboard.telemetry_worker import TelemetryWorker
from features.dashboard.popups.active_entities_popup import ActiveEntitiesPopup
from features.dashboard.popups.player_registry_popup import PlayerRegistryPopup

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
        # Master in-memory dictionary keyed by Steam ID for synchronized state management
        self._master_roster = {}
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

        logout_action = QAction("&Log Out of ZAH", self)
        logout_action.setShortcut("Ctrl+Shift+L")
        logout_action.setStatusTip("Logs you out and back to main login screen")

        exit_action = QAction("&Exit ZAH", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)

        # 4. Pack items cleanly into the layout
        file_menu.addAction(refresh_action)
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
                ## ===============
                ## Row 4 (Index 3)
                ## ===============
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
        self.telemetry_worker.players_updated.connect(self._on_live_stream_received)
        self.telemetry_worker.player_cache_received.connect(self._on_full_cache_received)
        self.telemetry_worker.connection_status.connect(self._on_connection_status)
        self.telemetry_worker.start()

        # Step 6: Dispatch immediate query on app launch to populate initial roster database
        self.telemetry_worker.send_command("plys")

        # Step 7: Wire UI input triggers and feed selector stack
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
    # Ingests Master Server Roster (From 'plys')
    # -------------------------------------------------------------------------

    def _on_full_cache_received(self, cache_pkg: dict):
        """
        Slot receiver handling the full server roster package returned from 'plys'.
        Synchronizes historical records into the master in-memory cache.
        """
        if not cache_pkg or not isinstance(cache_pkg, dict):
            return

        roster_list = cache_pkg.get("player_list", [])
        for p in roster_list:
            if isinstance(p, dict):
                sid = str(p.get("steamId", p.get("id", "")))
                if sid:
                    self._master_roster[sid] = p

        print(f"[ROSTER SYNC] Master roster updated: {len(self._master_roster)} total player record(s) loaded.")
        self._refresh_dashboard_table()

    # -------------------------------------------------------------------------
    # Ingests 2-Second Live Telemetry Stream
    # -------------------------------------------------------------------------

    def _on_live_stream_received(self, online_list: list):
        """
        Receives the 2-second live active player stream from METRIC broadcasts.
        Updates active player states to Online and sets absent players to Offline.
        """
        if not isinstance(online_list, list):
            return

        active_sids = set()
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        # Step 1: Update or insert actively connected players
        for p in online_list:
            if isinstance(p, dict):
                sid = str(p.get("steamId", p.get("id", "")))
                if sid:
                    active_sids.add(sid)
                    p["status"] = "Online"
                    p["lastSeen"] = p.get("lastSeen", now_str)
                    self._master_roster[sid] = p

        # Step 2: Mark cached players absent from the live stream as Offline
        for sid, p in self._master_roster.items():
            if sid not in active_sids:
                p["status"] = "Offline"

        # Step 3: Refresh the dashboard table with 14-day cutoff filter
        self._refresh_dashboard_table()

    # -------------------------------------------------------------------------
    # Renders 14-Day Dashboard Table
    # -------------------------------------------------------------------------

    def _refresh_dashboard_table(self):
        """
        Filters the master player roster for records active within the past 14 days
        and repopulates the 5-column QTableWidget on the main cockpit.
        """
        cutoff_date = datetime.utcnow() - timedelta(days=14)
        filtered_players = []

        # Step 1: Filter entries by lastSeen timestamp
        for p in self._master_roster.values():
            if not isinstance(p, dict):
                continue

            last_seen_str = p.get("lastSeen", "")
            try:
                last_seen_dt = datetime.strptime(last_seen_str, "%Y-%m-%d %H:%M:%S")
                if last_seen_dt >= cutoff_date:
                    filtered_players.append(p)
            except Exception:
                # Include record if timestamp parsing is unformatted or unavailable
                filtered_players.append(p)

        # Step 2: Populate the dashboard QTableWidget
        self.player_table.setSortingEnabled(False)
        self.player_table.setRowCount(len(filtered_players))

        for row_pos, p in enumerate(filtered_players):
            name = str(p.get("name", "Unknown"))
            status = str(p.get("status", "Offline"))
            faction = str(p.get("faction", "--"))
            system = str(p.get("playfield", "--"))
            playfield = str(p.get("playfield", "--"))

            col_values = [name, status, faction, system, playfield]
            for col_idx, text_val in enumerate(col_values):
                item = QTableWidgetItem(str(text_val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.player_table.setItem(row_pos, col_idx, item)

        self.player_table.setSortingEnabled(True)

        # Step 3: Update Header Label with 14-day player count
        self.lbl_players_header.setText(f"Players on Server (Past 2 Weeks: {len(filtered_players)})")

    # -------------------------------------------------------------------------
    # Legacy Signal Pass-Through
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
        Spawns the PlayerRegistryPopup modal and requests the complete player roster.
        """
        print("[MainCockpit] -ACTION- 'Player Registry' invoked.")
        if hasattr(self, 'telemetry_worker') and self.telemetry_worker:
            self.telemetry_worker.send_command("plys")

        try:
            from features.dashboard.popups.player_registry_popup import PlayerRegistryPopup
            popup = PlayerRegistryPopup(telemetry_worker=getattr(self, 'telemetry_worker', None), parent=self)
            popup.exec()
        except Exception as e:
            print(f"[ERROR] MainCockpit: Could not launch PlayerRegistryPopup: {e}")

    def _on_active_playfield_clicked(self):
        """
        Spawns the ActiveEntitiesPopup modal dialog and issues the 'gents' query.
        """
        print("[MainCockpit] -ACTION- 'Active Entities / Playfields' invoked.")
        try:
            from features.dashboard.popups.active_entities_popup import ActiveEntitiesPopup
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
        if hasattr(self, 'telemetry_worker') and self.telemetry_worker:
            self.telemetry_worker.stop()
        
        event.accept()

    # -------------------------------------------------------------------------
    # 
    # -------------------------------------------------------------------------