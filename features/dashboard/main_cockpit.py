# =====================================================================
# MODULE: features/dashboard/main_cockpit.py
# DESCRIPTION: Core Main Cockpit Window Shell (Pure Layout & CSS Core)
# =====================================================================

import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QGridLayout, QFrame, QLabel, QVBoxLayout, 
    QTextEdit, QHBoxLayout, QComboBox, QLineEdit, QPushButton, 
    QTableWidget, QHeaderView, QStackedWidget
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QPixmap


class TelemetryWidget(QFrame):
    """
    Standalone high-density sub-panel managing server health metrics layout structure.
    Styled exclusively via assets/ZAH.css using object names.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TelemetryPanel")
        self.setFixedSize(330, 70)

        self.telemetry_layout = QGridLayout(self)
        self.telemetry_layout.setObjectName("TelemetryPanelLayout")
        self.telemetry_layout.setContentsMargins(6, 4, 6, 4)
        self.telemetry_layout.setSpacing(4)

        # Telemetry Labels
        self.lbl_target_ip = QLabel("Target IP: Loading...", self)
        self.lbl_target_ip.setObjectName("TelemetryLabel")
        self.lbl_server_status = QLabel("Server Status: STANDBY", self)
        self.lbl_server_status.setObjectName("TelemetryLabel")
        
        self.lbl_server_cpu = QLabel("CPU: --%", self)
        self.lbl_server_cpu.setObjectName("TelemetryLabel")
        self.lbl_server_ram = QLabel("RAM: --%", self)
        self.lbl_server_ram.setObjectName("TelemetryLabel")

        self.telemetry_layout.addWidget(self.lbl_target_ip, 0, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.telemetry_layout.addWidget(self.lbl_server_status, 0, 1, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.telemetry_layout.addWidget(self.lbl_server_cpu, 1, 0)
        self.telemetry_layout.addWidget(self.lbl_server_ram, 1, 1)


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
        self.master_layout.setContentsMargins(90, 205, 90, 95) 
        self.master_layout.setSpacing(15)
        self.central_widget.setLayout(self.master_layout)

        # 4. Construct Layout Zones
        self.setup_zones()

        # 5. Apply External QSS Theme
        print("[DEBUG] MainCockpit: Applying CSS Styles...")
        self.apply_theme()
        print("[SUCCESS] Main Cockpit Dashboard structure initialized.")

    def setup_zones(self):
        """Constructs layout zones across the central dashboard canvas."""
        
        # Top Header Strip Layout
        self.top_header_layout = QHBoxLayout()
        self.top_header_layout.setObjectName("TopHeaderLayout")
        self.top_header_layout.setContentsMargins(10, 0, 10, 10)
        self.top_header_layout.addStretch()

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
                if row == 0 and col == 0:
                    btn_text = "Player\nRegistry"
                else:
                    btn_text = f"[{row+1},{col+1}]"

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