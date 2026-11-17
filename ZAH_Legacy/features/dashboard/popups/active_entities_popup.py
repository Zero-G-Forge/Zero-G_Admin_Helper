# =====================================================================
# MODULE: features/dashboard/popups/active_entities_popup.py
# DESCRIPTION: Modal HUD Sub-Panel displaying Active Server Entities & Structures
# =====================================================================

import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QLineEdit, QFrame
)
from PyQt6.QtCore import Qt


class ActiveEntitiesPopup(QDialog):
    """
    Modal HUD Sub-Panel displaying the live entity and structure list.
    Queries the server via ZeroGBridge 'gents' command and binds response packets.
    """

    def __init__(self, telemetry_worker=None, parent=None):
        super().__init__(parent)
        self.telemetry_worker = telemetry_worker

        # 1. Dialog Canvas Configuration
        self.setObjectName("ActiveEntitiesPopupCanvas")
        self.setWindowTitle("Zero-G Admin Helper - Active Entities Registry")
        self.setFixedSize(880, 540)
        self.setModal(True)

        # 2. Construct Visual Layout
        self._init_ui()

        # 3. Apply External Stylesheet
        self._apply_theme()

        # 4. Wire Telemetry Worker Signals (if connected)
        self._wire_signals()

        # 5. Request initial entity roster over Port 30500
        self._request_entity_refresh()

    def _init_ui(self):
        """Constructs the internal table, filter bar, and action buttons."""
        self.master_layout = QVBoxLayout(self)
        self.master_layout.setContentsMargins(15, 15, 15, 15)
        self.master_layout.setSpacing(10)

        # --- Header Section ---
        self.header_layout = QHBoxLayout()
        self.lbl_title = QLabel("Active Playfield Entities & Structures", self)
        self.lbl_title.setObjectName("PopupHeaderLabel")
        self.header_layout.addWidget(self.lbl_title)
        self.header_layout.addStretch()

        self.btn_refresh = QPushButton("Refresh Roster", self)
        self.btn_refresh.setObjectName("ExecuteButton")
        self.btn_refresh.setFixedWidth(130)
        self.btn_refresh.clicked.connect(self._request_entity_refresh)
        self.header_layout.addWidget(self.btn_refresh)

        self.master_layout.addLayout(self.header_layout)

        # --- Search / Filter Bar ---
        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("CommandInput")
        self.search_input.setPlaceholderText("Filter by Name, Entity ID, Type, Faction, or Playfield...")
        self.search_input.textChanged.connect(self._filter_entities)
        self.master_layout.addWidget(self.search_input)

        # --- Entity Table Widget (6 Columns) ---
        self.entity_table = QTableWidget(0, 6, self)
        self.entity_table.setObjectName("PlayerRegistryTable")
        self.entity_table.setHorizontalHeaderLabels([
            "Entity ID", "Structure Name", "Type", "Faction", "Playfield", "Position (X, Y, Z)"
        ])
        self.entity_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.entity_table.verticalHeader().setVisible(False)
        self.master_layout.addWidget(self.entity_table)

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
            print(f"[ERROR] ActiveEntitiesPopup: Failed to load stylesheet: {e}")

    def _wire_signals(self):
        """Connects the telemetry worker's command_response signal to populate table."""
        if self.telemetry_worker and hasattr(self.telemetry_worker, 'command_response'):
            self.telemetry_worker.command_response.connect(self._on_command_response)

    def _request_entity_refresh(self):
        """Dispatches the 'gents' command across the active telemetry connection."""
        print("[ActiveEntitiesPopup] -ACTION- Requesting active entity registry via 'gents'...")
        self.lbl_status.setText("Querying server for active entities...")
        if self.telemetry_worker:
            self.telemetry_worker.send_command("gents")
        else:
            print("[WARN] ActiveEntitiesPopup: Telemetry worker unavailable.")
            self.lbl_status.setText("Telemetry worker offline.")

    def _on_command_response(self, response_pkg: dict):
        """Slot receiver for incoming command response packets."""
        if not response_pkg or not isinstance(response_pkg, dict):
            return

        pkg_type = response_pkg.get("type", "")
        if pkg_type == "ENTITY_LIST":
            entities = response_pkg.get("entities", [])
            self.populate_entities(entities)

    def populate_entities(self, entity_list: list):
        """
        Populates the 6-column QTableWidget from an incoming ENTITY_LIST package.
        """
        if entity_list is None or not isinstance(entity_list, list):
            return

        self.entity_table.setSortingEnabled(False)
        self.entity_table.setRowCount(len(entity_list))

        for row_idx, ent in enumerate(entity_list):
            if isinstance(ent, dict):
                e_id = str(ent.get("id", ent.get("entityId", "--")))
                e_name = str(ent.get("name", "Unknown Structure"))
                e_type = str(ent.get("type", "BA"))
                e_fac = str(ent.get("faction", "--"))
                e_pf = str(ent.get("playfield", "--"))
                e_pos = str(ent.get("pos", ent.get("position", "--")))
            else:
                e_id = str(ent)
                e_name = "Structure"
                e_type = "--"
                e_fac = "--"
                e_pf = "--"
                e_pos = "--"

            cols = [e_id, e_name, e_type, e_fac, e_pf, e_pos]
            for col_idx, val in enumerate(cols):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.entity_table.setItem(row_idx, col_idx, item)

        self.entity_table.setSortingEnabled(True)
        self.lbl_status.setText(f"Displaying {len(entity_list)} active entities.")
        print(f"[ActiveEntitiesPopup] -SYNC- Populated {len(entity_list)} entity records.")

    def _filter_entities(self, text: str):
        """Filters table rows based on user input in the search field."""
        search_query = text.strip().lower()
        for row in range(self.entity_table.rowCount()):
            match_found = False
            for col in range(self.entity_table.columnCount()):
                item = self.entity_table.item(row, col)
                if item and search_query in item.text().lower():
                    match_found = True
                    break
            self.entity_table.setRowHidden(row, not match_found)

    def closeEvent(self, event):
        """Disconnect signal listener on close to prevent dangling callbacks."""
        if self.telemetry_worker and hasattr(self.telemetry_worker, 'command_response'):
            try:
                self.telemetry_worker.command_response.disconnect(self._on_command_response)
            except (TypeError, RuntimeError):
                pass
        event.accept()