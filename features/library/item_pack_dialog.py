## ==========================================
## ZERO-G ADMIN HELPER - BUILD ITEM TEMPLATE WINDOW
## Opened by BUILD ITEM TEMPLATE on the Library page. Names a pack, then adds
## giveable items from the same tile grid the Library uses (search, category
## buttons, FILTER, and the Choose a Category empty state). Quantity and ADD
## put the picked tile into the pack table. SAVE writes data/loadout_templates.json
## on this PC only. Nothing is sent to a server.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QComboBox, QSpinBox, QPushButton, QTableWidget, QTableWidgetItem,
                             QHeaderView, QAbstractItemView, QWidget, QSizePolicy)

from features.dashboard.dashboard_page import make_card, spread_letters
from features.library.item_browser import ItemBrowser
from features.library.item_library import FILTER_ORDER
from features.shared import loadouts

## Qt calls that may return None, wrapped once.
from features.shared.qt_types import horizontal_header, vertical_header

# endregion


# region ItemPackDialog Class

class ItemPackDialog(QDialog):

    def __init__(self, items, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the window.
        self.setObjectName("ItemPackDialog")
        self.setWindowTitle("Build Item Template")
        self.resize(1280, 820)
        self.picked_item = None
        self._loading_pack = False
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        pack_card, pack_layout = make_card("BUILD ITEM TEMPLATE")
        self._setup_name_row(pack_layout)
        body = QHBoxLayout()
        body.setSpacing(14)
        self._setup_item_browser(body, items or [])
        self._setup_pack_table(body)
        pack_layout.addLayout(body, stretch=1)
        self._setup_buttons(pack_layout)
        outer_layout.addWidget(pack_card)
        self._fill_existing_packs()

    def _setup_name_row(self, pack_layout):
        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        lbl_existing = QLabel("EXISTING PACK")
        lbl_existing.setObjectName("PlayerInfoLabel")
        name_row.addWidget(lbl_existing)
        self.cmb_existing = QComboBox()
        self.cmb_existing.setObjectName("EcfFileCombo")
        self.cmb_existing.setMinimumWidth(180)
        self.cmb_existing.currentIndexChanged.connect(self._on_existing_picked)
        name_row.addWidget(self.cmb_existing, stretch=1)
        lbl_name = QLabel("PACK NAME")
        lbl_name.setObjectName("PlayerInfoLabel")
        name_row.addWidget(lbl_name)
        self.txt_name = QLineEdit()
        self.txt_name.setObjectName("EcfSearchBox")
        self.txt_name.setPlaceholderText("Name this pack")
        self.txt_name.setMaxLength(loadouts.MAX_PACK_NAME_LEN)
        name_row.addWidget(self.txt_name, stretch=2)
        pack_layout.addLayout(name_row)

    def _setup_item_browser(self, body, items):
        browser_box = QWidget()
        browser_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        browser_layout = QVBoxLayout(browser_box)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.setSpacing(8)

        ## Same search, category buttons, FILTER menu, and picture tile grid as the Library.
        self.item_browser = ItemBrowser(log_name="ItemPackDialog", parent=self)
        self.item_browser.set_empty_texts(
            "No items loaded yet.",
            "Choose a Category",
            "No items match.",
        )
        self.item_browser.rebuild_filters(FILTER_ORDER)
        self.item_browser.tile_picked.connect(self._on_tile_picked)
        self.item_browser.set_items(items)
        browser_layout.addWidget(self.item_browser, stretch=1)
        add_row = QHBoxLayout()
        add_row.setSpacing(10)
        lbl_quantity = QLabel("QUANTITY")
        lbl_quantity.setObjectName("PlayerInfoLabel")
        add_row.addWidget(lbl_quantity)
        self.spn_quantity = QSpinBox()
        self.spn_quantity.setObjectName("LibraryQuantityBox")
        self.spn_quantity.setRange(1, 9999)
        self.spn_quantity.setValue(1)
        add_row.addWidget(self.spn_quantity)
        self.btn_add = QPushButton("ADD")
        self.btn_add.setObjectName("DashActionButton")
        self.btn_add.setFixedHeight(34)
        self.btn_add.setEnabled(False)
        self.btn_add.setToolTip("Pick an item first.")
        self.btn_add.clicked.connect(self._on_add_clicked)
        add_row.addWidget(self.btn_add)
        add_row.addStretch()
        self.lbl_picked = QLabel("Nothing picked")
        self.lbl_picked.setObjectName("PlayerInfoLabel")
        add_row.addWidget(self.lbl_picked)
        browser_layout.addLayout(add_row)
        body.addWidget(browser_box, stretch=3)

    def _setup_pack_table(self, body):
        table_box = QWidget()
        table_layout = QVBoxLayout(table_box)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(8)
        lbl_rows = QLabel("PACK ITEMS")
        lbl_rows.setObjectName("PlayerInfoLabel")
        spread_letters(lbl_rows, 1.5)
        table_layout.addWidget(lbl_rows)
        self.tbl_rows = QTableWidget(0, 3)
        self.tbl_rows.setObjectName("DashTable")
        self.tbl_rows.setHorizontalHeaderLabels(["NAME", "ID", "COUNT"])
        self.tbl_rows.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_rows.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_rows.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        vertical_header(self.tbl_rows).setVisible(False)
        horizontal_header(self.tbl_rows).setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        horizontal_header(self.tbl_rows).setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        horizontal_header(self.tbl_rows).setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table_layout.addWidget(self.tbl_rows, stretch=1)
        self.btn_remove = QPushButton("REMOVE")
        self.btn_remove.setObjectName("DashActionButton")
        self.btn_remove.setFixedHeight(34)
        self.btn_remove.setToolTip("Removes the selected row from this pack.")
        self.btn_remove.clicked.connect(self._on_remove_clicked)
        table_layout.addWidget(self.btn_remove)
        body.addWidget(table_box, stretch=2)

    def _setup_buttons(self, pack_layout):
        button_row = QHBoxLayout()
        button_row.addStretch()
        self.btn_save = QPushButton("SAVE")
        self.btn_cancel = QPushButton("CANCEL")
        for btn in (self.btn_save, self.btn_cancel):
            btn.setObjectName("DashActionButton")
            btn.setFixedHeight(38)
            btn.setMinimumWidth(120)
        self.btn_save.setToolTip("Saves this pack on this PC.")
        self.btn_cancel.setToolTip("Closes without saving.")
        self.btn_save.clicked.connect(self._on_save_clicked)
        self.btn_cancel.clicked.connect(self.reject)
        button_row.addWidget(self.btn_save)
        button_row.addWidget(self.btn_cancel)
        pack_layout.addLayout(button_row)

    def _fill_existing_packs(self):
        self._loading_pack = True
        try:
            self.cmb_existing.blockSignals(True)
            self.cmb_existing.clear()
            self.cmb_existing.addItem("New pack", "")
            templates = loadouts.load_templates()
            for name in loadouts.list_template_names(templates):
                rows = templates.get(name) or []
                self.cmb_existing.addItem(f"{name}   ({len(rows)} item(s))", name)
            self.cmb_existing.setCurrentIndex(0)
            self.cmb_existing.blockSignals(False)
        finally:
            self._loading_pack = False

    def _on_existing_picked(self, index):
        if self._loading_pack:
            return
        name = self.cmb_existing.currentData()
        if not name:
            return
        self.txt_name.setText(name)
        self.set_pack_rows(loadouts.load_templates().get(name) or [])

    def _on_tile_picked(self, item):
        self.picked_item = item
        self.lbl_picked.setText(f"{item.get('display_name') or item.get('name')}  (ID {item.get('id')})")
        self.btn_add.setEnabled(True)
        self.btn_add.setToolTip("Adds this item and quantity to the pack.")

    def _on_add_clicked(self):
        try:
            if self.picked_item is None or not self.btn_add.isEnabled():
                return
            item_id = int(self.picked_item["id"])
            item_name = self.picked_item.get("display_name") or self.picked_item.get("name") or str(item_id)
            count = int(self.spn_quantity.value())
            for row_number in range(self.tbl_rows.rowCount()):
                if int(self.tbl_rows.item(row_number, 1).text()) == item_id:
                    current = int(self.tbl_rows.item(row_number, 2).text())
                    self.tbl_rows.item(row_number, 2).setText(str(current + count))
                    self.tbl_rows.selectRow(row_number)
                    return
            self._append_row({"id": item_id, "name": item_name, "count": count})
            self.tbl_rows.selectRow(self.tbl_rows.rowCount() - 1)
        except Exception as e:
            print(f"[ERROR] ItemPackDialog: Could not add item: {e}")

    def _on_remove_clicked(self):
        row_number = self.tbl_rows.currentRow()
        if row_number >= 0:
            self.tbl_rows.removeRow(row_number)

    def _append_row(self, row):
        row_number = self.tbl_rows.rowCount()
        self.tbl_rows.insertRow(row_number)
        values = [str(row.get("name", "")), str(row["id"]), str(row["count"])]
        for column, value in enumerate(values):
            cell = QTableWidgetItem(value)
            cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tbl_rows.setItem(row_number, column, cell)

    def set_pack_rows(self, rows):
        self.tbl_rows.setRowCount(0)
        for row in rows or []:
            self._append_row(row)

    def pack_rows(self):
        rows = []
        for row_number in range(self.tbl_rows.rowCount()):
            rows.append({
                "id": int(self.tbl_rows.item(row_number, 1).text()),
                "name": self.tbl_rows.item(row_number, 0).text(),
                "count": int(self.tbl_rows.item(row_number, 2).text()),
            })
        return rows

    def _on_save_clicked(self):
        try:
            loadouts.save_pack(self.txt_name.text(), self.pack_rows())
            self.accept()
        except ValueError as e:
            print(f"[WARN] ItemPackDialog: Could not save pack: {e}")
            self.txt_name.setFocus()
        except Exception as e:
            print(f"[ERROR] ItemPackDialog: Could not save pack: {e}")

# endregion
