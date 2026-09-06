# =====================================================================
# MODULE: features/dashboard/popups/player_registry_popup.py
# DESCRIPTION: Master Player Registry Modal (Full-Schema Stats & Roles)
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
    Modal dialog rendering the complete server player database with full schema details
    including Role, Playtime, Bases, and Ships statistics from player_registry_cache.json.
    """

    def __init__(self, telemetry_worker=None, player_manager=None, parent=None):
        super().__init__(parent)
        self.telemetry_worker = telemetry_worker
        self.player_manager = player_manager

        # -----------------------------------------------------------------
        # 1. Dialog Canvas Configuration & Geometry Locking
        # -----------------------------------------------------------------
        self.setObjectName("PlayerRegistryPopupCanvas")
        self.setWindowTitle("Zero-G Admin Helper - Master Player Registry")
        self.setFixedSize(1040, 580)
        self.setModal(True)

        # -----------------------------------------------------------------
        # 2. Structural Layout Initialization
        # -----------------------------------------------------------------
        print("[DEBUG] PlayerRegistryPopup: Constructing UI Layout...")
        self._init_ui()

        # -----------------------------------------------------------------
        # 3. Apply Centralized Stylesheet Theme
        # -----------------------------------------------------------------
        print("[DEBUG] PlayerRegistryPopup: Loading QSS Theme...")
        self._apply_theme()

        # -----------------------------------------------------------------
        # 4. Wire Telemetry Worker Signal Slots
        # -----------------------------------------------------------------
        self._wire_signals()

        # -----------------------------------------------------------------
        # 5. Populate Initial Roster from Local Cache
        # -----------------------------------------------------------------
        if self.player_manager:
            players = self.player_manager.get_all_players()
            print(f"[PlayerRegistryPopup] -INFO- Populating modal with {len(players)} player records.")
            self.populate_players(players)

        # -----------------------------------------------------------------
        # 6. Request Live Server Cache Refresh
        # -----------------------------------------------------------------
        self._request_player_refresh()

    def _init_ui(self):
        """
        Constructs table, search bar, control headers, and footer status strips.
        """
        self.master_layout = QVBoxLayout(self)
        self.master_layout.setContentsMargins(15, 15, 15, 15)
        self.master_layout.setSpacing(10)

        # --- Top Header Section Layout ---
        self.header_layout = QHBoxLayout()
        self.lbl_title = QLabel("Server Player Registry (Loading...)", self)
        self.lbl_title.setObjectName("PopupHeaderLabel")
        self.header_layout.addWidget(self.lbl_title)
        self.header_layout.addStretch()

        # Manual Refresh Action Button
        self.btn_refresh = QPushButton("Refresh Roster", self)
        self.btn_refresh.setObjectName("ExecuteButton")
        self.btn_refresh.setFixedWidth(130)
        self.btn_refresh.clicked.connect(self._request_player_refresh)
        self.header_layout.addWidget(self.btn_refresh)

        self.master_layout.addLayout(self.header_layout)

        # --- Search / Filter Input Bar ---
        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("CommandInput")
        self.search_input.setPlaceholderText("Filter by Player Name, Steam ID, Entity ID, Faction, Role, or Playfield...")
        self.search_input.textChanged.connect(self._filter_players)
        self.master_layout.addWidget(self.search_input)

        # --- Master Player Table Widget (9 Rich Columns) ---
        # Column Index Mapping:
        # [0: Status, 1: Player Name, 2: Steam ID, 3: Entity ID, 4: Faction, 5: Role, 6: Playtime, 7: Structures, 8: Last Seen (UTC)]
        self.player_table = QTableWidget(0, 9, self)
        self.player_table.setObjectName("PlayerRegistryTable")
        self.player_table.setHorizontalHeaderLabels([
            "Status", "Player Name", "Steam ID", "Entity ID", "Faction", "Role", "Playtime", "Structures", "Last Seen (UTC)"
        ])
        
        # Configure Header Stretch Modes and Sizing Constraints
        self.player_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.player_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.player_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.player_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.player_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self.player_table.verticalHeader().setVisible(False)
        
        self.master_layout.addWidget(self.player_table)

        # --- Bottom Status Summary Strip ---
        self.lbl_summary = QLabel("Total Registered: 0 | Online: 0 | Offline: 0", self)
        self.lbl_summary.setObjectName("PopupFooterLabel")
        self.lbl_summary.setStyleSheet("color: #00ffff; font-family: monospace; font-size: 11px;")
        self.master_layout.addWidget(self.lbl_summary)

    def _apply_theme(self):
        """
        Loads external CSS stylesheet styling from assets/ZAH.css.
        """
        try:
            css_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'assets', 'ZAH.css')
            if os.path.exists(css_path):
                with open(css_path, "r", encoding="utf-8") as f:
                    self.setStyleSheet(f.read())
                print(f"[SUCCESS] PlayerRegistryPopup: Applied theme stylesheet from {css_path}")
            else:
                print(f"[WARN] PlayerRegistryPopup: Stylesheet not found at {css_path}")
        except Exception as e:
            print(f"[ERROR] PlayerRegistryPopup: Failed to load stylesheet: {e}")

    def _wire_signals(self):
        """
        Wires background TelemetryWorker signals to synchronize data updates.
        """
        if self.telemetry_worker:
            if hasattr(self.telemetry_worker, 'players_updated'):
                self.telemetry_worker.players_updated.connect(self._on_live_stream_tick)
            if hasattr(self.telemetry_worker, 'player_cache_received'):
                self.telemetry_worker.player_cache_received.connect(self._on_player_cache_received)

    def _request_player_refresh(self):
        """
        Dispatches 'plys' command to ZeroGBridge across Port 30500.
        """
        print("[PlayerRegistryPopup] -ACTION- Requesting player registry via 'plys'...")
        if self.telemetry_worker:
            self.telemetry_worker.send_command("plys")

    def _on_live_stream_tick(self, online_list: list):
        """
        Slot receiver handling periodic 2-second telemetry live stream packets.
        """
        if self.player_manager:
            self.populate_players(self.player_manager.get_all_players())

    def _on_player_cache_received(self, cache_pkg: dict):
        """
        Slot receiver handling full player roster responses from the server.
        """
        if self.player_manager:
            if isinstance(cache_pkg, dict):
                # Update persistent local storage with newly returned server records
                self.player_manager.update_from_roster_cache(cache_pkg.get("player_list", []))
            # Repopulate table from master database
            self.populate_players(self.player_manager.get_all_players())

    def populate_players(self, player_list: list):
        """
        Populates the 9-column registry table with rich stats and updates summary counters.
        """
        if player_list is None or not isinstance(player_list, list):
            return

        # Disable sorting and widget updates during bulk row insertion
        self.player_table.setSortingEnabled(False)
        self.player_table.setRowCount(len(player_list))

        online_count = 0
        offline_count = 0

        # Iterate over records and build table items
        for row_idx, p in enumerate(player_list):
            if isinstance(p, dict):
                p_name = str(p.get("name", "Unknown"))
                status = str(p.get("status", "Offline"))
                steam_id = str(p.get("steamId", "--"))
                entity_id = str(p.get("entityId", "--"))
                faction = str(p.get("faction", "--"))
                role = str(p.get("role", "Member"))
                
                # Extract embedded Stats dictionary safely
                stats_dict = p.get("stats", {})
                playtime = str(stats_dict.get("playtime", "0h")) if isinstance(stats_dict, dict) else "0h"
                bases = stats_dict.get("bases", 0) if isinstance(stats_dict, dict) else 0
                ships = stats_dict.get("ships", 0) if isinstance(stats_dict, dict) else 0
                structures_str = f"BA: {bases} | Ships: {ships}"

                # Format UTC timestamp string
                last_seen = str(p.get("last_seen", "--")).replace("T", " ")
                if "." in last_seen:
                    last_seen = last_seen.split(".")[0]
            else:
                p_name = str(p)
                status = "Offline"
                steam_id = "--"
                entity_id = "--"
                faction = "--"
                role = "Member"
                playtime = "0h"
                structures_str = "BA: 0 | Ships: 0"
                last_seen = "--"

            # Tally active vs inactive counts
            if status == "Online":
                online_count += 1
            else:
                offline_count += 1

            # 9-Column Array Mapping:
            # [0: Status, 1: Name, 2: SteamID, 3: EntityID, 4: Faction, 5: Role, 6: Playtime, 7: Structures, 8: LastSeen]
            cols = [status, p_name, steam_id, entity_id, faction, role, playtime, structures_str, last_seen]

            for col_idx, val in enumerate(cols):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                # Keep table items strictly read-only and selectable
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

                # Apply visual status accenting to column 0
                if col_idx == 0:
                    if status == "Online":
                        item.setForeground(Qt.GlobalColor.green)
                    else:
                        item.setForeground(Qt.GlobalColor.red)

                self.player_table.setItem(row_idx, col_idx, item)

        # Re-enable sorting once batch insertion is finalized
        self.player_table.setSortingEnabled(True)

        # Update Header and Footer counters
        total_players = len(player_list)
        self.lbl_title.setText(f"Server Player Registry ({total_players} Total Players)")
        self.lbl_summary.setText(f"Total Registered: {total_players} | Online: {online_count} | Offline: {offline_count}")

    def _filter_players(self, text: str):
        """
        Filters table rows dynamically in real-time as search text changes.
        """
        search_query = text.strip().lower()
        for row in range(self.player_table.rowCount()):
            match_found = False
            for col in range(self.player_table.columnCount()):
                item = self.player_table.item(row, col)
                if item and search_query in item.text().lower():
                    match_found = True
                    break
            self.player_table.setRowHidden(row, not match_found)