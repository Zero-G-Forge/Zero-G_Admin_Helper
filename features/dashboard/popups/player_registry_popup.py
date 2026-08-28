# =====================================================================
# MODULE: features/dashboard/popups/player_registry_popup.py
# DESCRIPTION: Modal HUD Sub-Panel displaying the Comprehensive Player Registry
# =====================================================================

import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QLineEdit
)
from PyQt6.QtCore import Qt


class PlayerRegistryPopup(QDialog):
    """
    Modal HUD Sub-Panel displaying detailed player registry information.
    Connects to TelemetryWorker to ingest 'plys' queries and live player arrays.
    """

    def __init__(self, telemetry_worker=None, parent=None):
        super().__init__(parent)
        self.telemetry_worker = telemetry_worker

        # 1. Dialog Canvas Configuration
        self.setObjectName("PlayerRegistryPopupCanvas")
        self.setWindowTitle("Zero-G Admin Helper - Player Registry")
        self.setFixedSize(880, 540)
        self.setModal(True)

        # 2. Construct Visual Layout
        self._init_ui()

        # 3. Apply External Stylesheet
        self._apply_theme()

        # 4. Wire Telemetry Worker Signals (if connected)
        self._wire_signals()

        # 5. Request initial player roster over Port 30500
        self._request_player_refresh()

    def _init_ui(self):
        """Constructs the internal table, filter bar, and action buttons."""
        self.master_layout = QVBoxLayout(self)
        self.master_layout.setContentsMargins(15, 15, 15, 15)
        self.master_layout.setSpacing(10)

        # --- Header Section ---
        self.header_layout = QHBoxLayout()
        self.lbl_title = QLabel("Server Player Registry", self)
        self.lbl_title.setObjectName("PopupHeaderLabel")
        self.header_layout.addWidget(self.lbl_title)
        self.header_layout.addStretch()

        self.btn_refresh = QPushButton("Refresh Roster", self)
        self.btn_refresh.setObjectName("ExecuteButton")
        self.btn_refresh.setFixedWidth(130)
        self.btn_refresh.clicked.connect(self._request_player_refresh)
        self.header_layout.addWidget(self.btn_refresh)

        self.master_layout.addLayout(self.header_layout)

        # --- Search / Filter Bar ---
        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("CommandInput")
        self.search_input.setPlaceholderText("Filter by Player Name, Steam ID, Entity ID, Faction, or Playfield...")
        self.search_input.textChanged.connect(self._filter_players)
        self.master_layout.addWidget(self.search_input)

        # --- Player Table Widget (6 Columns) ---
        self.player_table = QTableWidget(0, 6, self)
        self.player_table.setObjectName("PlayerRegistryTable")
        self.player_table.setHorizontalHeaderLabels([
            "Entity ID", "Player Name", "Steam ID", "Faction", "Playfield", "Ping"
        ])
        self.player_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.player_table.verticalHeader().setVisible(False)
        self.master_layout.addWidget(self.player_table)

        # --- Footer Status Bar ---
        self.lbl_status = QLabel("Ready.", self)
        self.lbl_status.setObjectName("TelemetryLabel")
        self.master_layout.addWidget(self.lbl_status)

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
        """Connects TelemetryWorker signals to populate table."""
        if self.telemetry_worker:
            if hasattr(self.telemetry_worker, 'players_updated'):
                self.telemetry_worker.players_updated.connect(self.populate_players)
            if hasattr(self.telemetry_worker, 'player_cache_received'):
                self.telemetry_worker.player_cache_received.connect(self._on_player_cache_received)

    def _request_player_refresh(self):
        """Dispatches the 'plys' command across the active telemetry connection."""
        print("[PlayerRegistryPopup] -ACTION- Requesting player registry via 'plys'...")
        self.lbl_status.setText("Querying server for player roster...")
        if self.telemetry_worker:
            self.telemetry_worker.send_command("plys")
        else:
            print("[WARN] PlayerRegistryPopup: Telemetry worker unavailable.")
            self.lbl_status.setText("Telemetry worker offline.")

    def _on_player_cache_received(self, cache_pkg: dict):
        """Slot receiver for PLAYER_CACHE response packets."""
        if not cache_pkg or not isinstance(cache_pkg, dict):
            return

        players = cache_pkg.get("player_list", [])
        self.populate_players(players)

    def populate_players(self, player_list: list):
        """
        Populates the 6-column QTableWidget from an incoming player roster array.
        """
        if player_list is None or not isinstance(player_list, list):
            return

        self.player_table.setSortingEnabled(False)
        self.player_table.setRowCount(len(player_list))

        for row_idx, p in enumerate(player_list):
            if isinstance(p, dict):
                p_id = str(p.get("entityId", p.get("id", "--")))
                p_name = str(p.get("name", "Unknown Player"))
                p_steam = str(p.get("steamId", "--"))
                p_fac = str(p.get("faction", "--"))
                p_pf = str(p.get("playfield", "--"))
                p_ping = f"{p.get('ping', 0)}ms" if "ping" in p else "--"
            else:
                p_id = "--"
                p_name = str(p)
                p_steam = "--"
                p_fac = "--"
                p_pf = "--"
                p_ping = "--"

            cols = [p_id, p_name, p_steam, p_fac, p_pf, p_ping]
            for col_idx, val in enumerate(cols):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.player_table.setItem(row_idx, col_idx, item)

        self.player_table.setSortingEnabled(True)
        self.lbl_status.setText(f"Displaying {len(player_list)} active player record(s).")
        print(f"[PlayerRegistryPopup] -SYNC- Populated {len(player_list)} player records.")

    def _filter_players(self, text: str):
        """Filters table rows based on user input in the search field."""
        search_query = text.strip().lower()
        for row in range(self.player_table.rowCount()):
            match_found = False
            for col in range(self.player_table.columnCount()):
                item = self.player_table.item(row, col)
                if item and search_query in item.text().lower():
                    match_found = True
                    break
            self.player_table.setRowHidden(row, not match_found)

    def closeEvent(self, event):
        """Disconnect signal listeners on close to prevent dangling callbacks."""
        if self.telemetry_worker:
            if hasattr(self.telemetry_worker, 'players_updated'):
                try:
                    self.telemetry_worker.players_updated.disconnect(self.populate_players)
                except (TypeError, RuntimeError):
                    pass
            if hasattr(self.telemetry_worker, 'player_cache_received'):
                try:
                    self.telemetry_worker.player_cache_received.disconnect(self._on_player_cache_received)
                except (TypeError, RuntimeError):
                    pass
        event.accept()