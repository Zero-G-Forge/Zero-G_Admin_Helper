# =====================================================================
# MODULE: features/dashboard/popups/player_registry_popup.py
# DESCRIPTION: Full Master Player Registry Popup Dialog
# =====================================================================

import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QTableWidget, QTableWidgetItem, QHeaderView, 
    QPushButton, QLineEdit, QFrame
)
from PyQt6.QtCore import Qt

class PlayerRegistryPopup(QDialog):
    """
    Modal dialog rendering the entire historical server player database.
    Integrates directly with PlayerManager to read player_registry_cache.json.
    """

    def __init__(self, telemetry_worker=None, player_manager=None, parent=None):
        super().__init__(parent)
        self.telemetry_worker = telemetry_worker
        self.player_manager = player_manager

        # 1. Dialog Canvas Configuration
        self.setObjectName("PlayerRegistryPopupCanvas")
        self.setWindowTitle("Zero-G Admin Helper - Master Player Registry")
        self.setFixedSize(920, 560)
        self.setModal(True)

        # 2. Build UI Layout
        self._init_ui()

        # 3. Apply CSS Theme
        self._apply_theme()

        # 4. Wire Telemetry Worker Signals
        self._wire_signals()

        # 5. Populate immediately from local cache
        if self.player_manager:
            players = self.player_manager.get_all_players()
            print(f"[PlayerRegistryPopup] -INFO- Populating modal with {len(players)} player records.")
            self.populate_players(players)

        # 6. Request server refresh
        self._request_player_refresh()

    def _init_ui(self):
        """Constructs table, search bar, and control headers."""
        self.master_layout = QVBoxLayout(self)
        self.master_layout.setContentsMargins(15, 15, 15, 15)
        self.master_layout.setSpacing(10)

        # --- Top Header Section ---
        self.header_layout = QHBoxLayout()
        self.lbl_title = QLabel("Server Player Registry (Loading...)", self)
        self.lbl_title.setObjectName("PopupHeaderLabel")
        self.header_layout.addWidget(self.lbl_title)
        self.header_layout.addStretch()

        self.btn_refresh = QPushButton("Refresh Roster", self)
        self.btn_refresh.setObjectName("ExecuteButton")
        self.btn_refresh.setFixedWidth(130)
        self.btn_refresh.clicked.connect(self._request_player_refresh)
        self.header_layout.addWidget(self.btn_refresh)

        self.master_layout.addLayout(self.header_layout)

        # --- Search / Filter Input Bar ---
        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("CommandInput")
        self.search_input.setPlaceholderText("Filter by Player Name, Steam ID, Entity ID, Faction, or Playfield...")
        self.search_input.textChanged.connect(self._filter_players)
        self.master_layout.addWidget(self.search_input)

        # --- Master Player Table Widget ---
        self.player_table = QTableWidget(0, 7, self)
        self.player_table.setObjectName("PlayerRegistryTable")
        self.player_table.setHorizontalHeaderLabels([
            "Status", "Player Name", "Steam ID", "Entity ID", "Faction", "Playfield", "Last Seen (UTC)"
        ])
        self.player_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.player_table.verticalHeader().setVisible(False)
        self.master_layout.addWidget(self.player_table)

        # --- Bottom Status Summary Strip ---
        self.lbl_summary = QLabel("Total Registered: 0 | Online: 0 | Offline: 0", self)
        self.lbl_summary.setObjectName("PopupFooterLabel")
        self.lbl_summary.setStyleSheet("color: #00ffff; font-family: monospace; font-size: 11px;")
        self.master_layout.addWidget(self.lbl_summary)

    def _apply_theme(self):
        """Loads external CSS styling from assets/ZAH.css."""
        try:
            css_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'assets', 'ZAH.css')
            if os.path.exists(css_path):
                with open(css_path, "r", encoding="utf-8") as f:
                    self.setStyleSheet(f.read())
        except Exception as e:
            print(f"[ERROR] PlayerRegistryPopup: Failed to load stylesheet: {e}")

    def _wire_signals(self):
        """Wires live stream signals to auto-update the table."""
        if self.telemetry_worker:
            if hasattr(self.telemetry_worker, 'players_updated'):
                self.telemetry_worker.players_updated.connect(self._on_live_stream_tick)
            if hasattr(self.telemetry_worker, 'player_cache_received'):
                self.telemetry_worker.player_cache_received.connect(self._on_player_cache_received)

    def _request_player_refresh(self):
        """Dispatches 'plys' command to ZeroGBridge."""
        print("[PlayerRegistryPopup] -ACTION- Requesting player registry via 'plys'...")
        if self.telemetry_worker:
            self.telemetry_worker.send_command("plys")

    def _on_live_stream_tick(self, online_list: list):
        if self.player_manager:
            self.populate_players(self.player_manager.get_all_players())

    def _on_player_cache_received(self, cache_pkg: dict):
        if self.player_manager:
            self.populate_players(self.player_manager.get_all_players())

    def populate_players(self, player_list: list):
        """Populates the 7-column registry table and updates summary counters."""
        if player_list is None or not isinstance(player_list, list):
            return

        self.player_table.setSortingEnabled(False)
        self.player_table.setRowCount(len(player_list))

        online_count = 0
        offline_count = 0

        for row_idx, p in enumerate(player_list):
            if isinstance(p, dict):
                p_name = str(p.get("name") or p.get("player_name", "Unknown"))
                status = str(p.get("status") or p.get("active", "Offline"))
                steam_id = str(p.get("steamId", "--"))
                entity_id = str(p.get("entityId") or p.get("private_id", "--"))
                faction = str(p.get("faction") or "--")
                playfield = str(p.get("playfield") or "--")
                last_seen = str(p.get("last_seen") or p.get("lastSeen", "--")).replace("T", " ")
            else:
                p_name = str(p)
                status = "Offline"
                steam_id = "--"
                entity_id = "--"
                faction = "--"
                playfield = "--"
                last_seen = "--"

            if status == "Online":
                online_count += 1
            else:
                offline_count += 1

            cols = [status, p_name, steam_id, entity_id, faction, playfield, last_seen]
            for col_idx, val in enumerate(cols):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

                # Status coloring
                if col_idx == 0:
                    if status == "Online":
                        item.setForeground(Qt.GlobalColor.green)
                    else:
                        item.setForeground(Qt.GlobalColor.red)

                self.player_table.setItem(row_idx, col_idx, item)

        self.player_table.setSortingEnabled(True)

        total_players = len(player_list)
        self.lbl_title.setText(f"Server Player Registry ({total_players} Total Players)")
        self.lbl_summary.setText(f"Total Registered: {total_players} | Online: {online_count} | Offline: {offline_count}")

    def _filter_players(self, text: str):
        """Filters table rows in real-time as the user types into the search box."""
        search_query = text.strip().lower()
        for row in range(self.player_table.rowCount()):
            match_found = False
            for col in range(self.player_table.columnCount()):
                item = self.player_table.item(row, col)
                if item and search_query in item.text().lower():
                    match_found = True
                    break
            self.player_table.setRowHidden(row, not match_found)