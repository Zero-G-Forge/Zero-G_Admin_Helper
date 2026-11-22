## ==========================================
## ZERO-G ADMIN HELPER - ITEM & BLUEPRINT LIBRARY PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Item_BP_Library.jpg:
## ITEMS / BLUEPRINTS tabs with a search box, filter buttons and a grid of tiles on the left;
## the picked tile's details, GIVE ITEM and LOADOUT TEMPLATES on the right.
## The ITEMS and BP EDITOR nav entries both open this page, each starting on its own tab.
## ITEMS reads a game Content folder (ItemsConfig.ecf + Localization.csv) through load_items_from; read-only.
## (Nov 22, 2026: on opening, ITEMS reads the downloaded server files through load_server_files, never the
## local base game. Pictures come from the downloaded SharedData/Content/Images/<ItemName>.jpg or .png.)
## BLUEPRINTS has no data yet, so it shows "nothing yet".
## GIVE ITEM changes a live player, so its button stays off until Ray OKs that step.
## Wired (Nov 22, 2026): GIVE ITEM sends api:Request_Player_AddItem through the Safety Flow (admin and up), to
## an online player from plys. ADD TO TEMPLATE saves the picked item and quantity on this PC (loadouts.py).
## The old ADD TO PENDING EDITS button is now labelled GIVE ITEM (there is no separate pending-edit queue).
## ==========================================

# region Imports

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QPushButton, QButtonGroup, QLineEdit, QSpinBox, QComboBox, QInputDialog)

## Read-only bridge reads, the Safety Flow, and loadout templates saved on this PC.
from features.shared import server_actions, loadouts

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

## Item data, the hex tile grid and the full stats window.
from features.library.item_library import load_items
from features.library.item_tiles import TileFlowArea, make_hex_pixmap
from features.library.item_stats_dialog import ItemStatsDialog

## Where the downloaded server files are, and the item pictures inside them.
from features.server_files.local_files import (NO_FILES_TEXT, ITEMS_FILE, NAMES_FILE, current_scenario_folder,
                                               find_file, build_image_index)

# endregion


# region Constants

## Tabs across the top: (key, text).
LIBRARY_TABS = [("items", "ITEMS"), ("blueprints", "BLUEPRINTS")]

## Filter buttons under the search box, different for each tab.
TAB_FILTERS = {
    "items": ["WEAPONS", "ARMOR", "MEDICAL", "AMMO", "COMPONENTS", "ORES", "DEVICES", "FOOD"],
    "blueprints": ["BA", "CV", "SV", "HV"],
}

## What the empty grid says on each tab.
TAB_EMPTY_TEXT = {
    "items": "No items loaded yet.",
    "blueprints": "No blueprints loaded yet.",
}

## Tooltip for every button that isn't wired up yet.
LATER_TIP = "Coming in a later step."

# endregion


# region LibraryPage Class

class LibraryPage(QWidget):

    # region Setup

    def __init__(self, start_tab="items", parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("LibraryPage")
        self.active_tab = start_tab if start_tab in TAB_FILTERS else "items"
        self.tab_buttons = {}
        self.filter_buttons = []

        ## Loaded items, and the one picked in the grid (None until a tile is clicked).
        self.items = []
        self.picked_item = None
        self.stats_dialog = None

        ## The downloaded scenario folder the items came from (None = nothing downloaded).
        self.server_folder = None
        self.setup_widgets()

        ## Fill ITEMS from the downloaded server files (or show how to download them) before the first tab shows.
        self.load_server_files()
        self._on_tab_clicked(self.active_tab)
        self._wire_give_and_templates()

    def setup_widgets(self):

        ## 2 columns: the library (wide, both rows) and the detail cards (narrow) stacked on the right.
        page_grid = QGridLayout(self)
        page_grid.setContentsMargins(4, 4, 4, 4)
        page_grid.setHorizontalSpacing(14)
        page_grid.setVerticalSpacing(14)

        # region Library Card

        library_card, library_layout = make_card()

        ## Tab row: checkable buttons in an exclusive group, so only one tab is lit at a time (same look as chat).
        tab_row = QHBoxLayout()
        tab_row.setSpacing(4)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        for tab_key, tab_text in LIBRARY_TABS:
            btn_tab = QPushButton(tab_text)
            btn_tab.setObjectName("ChatTabButton")
            btn_tab.setCheckable(True)
            btn_tab.setMinimumHeight(34)
            spread_letters(btn_tab, 1.5)

            ## The lambda passes this tab's key to _on_tab_clicked.
            btn_tab.clicked.connect(lambda checked, key=tab_key: self._on_tab_clicked(key))
            self.tab_group.addButton(btn_tab)
            self.tab_buttons[tab_key] = btn_tab
            tab_row.addWidget(btn_tab)
        library_layout.addLayout(tab_row)

        ## Search box, same look as the ECF Editor's trader search.
        self.txt_search = QLineEdit()
        self.txt_search.setObjectName("EcfSearchBox")
        self.txt_search.setPlaceholderText("Search")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.setMaximumWidth(300)
        library_layout.addWidget(self.txt_search)

        ## Typing in the search box narrows the grid straight away.
        self.txt_search.textChanged.connect(self._apply_filters)

        ## Filter buttons. They are rebuilt by _on_tab_clicked, since each tab has its own set.
        self.filter_row = QHBoxLayout()
        self.filter_row.setSpacing(8)
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(False)
        library_layout.addLayout(self.filter_row)

        ## Tile grid: each item or blueprint will be a hex tile with its picture, name and ID.
        self.grid_box = QFrame()
        self.grid_box.setObjectName("DashInnerBox")
        grid_box_layout = QVBoxLayout(self.grid_box)
        grid_box_layout.setContentsMargins(12, 12, 12, 12)

        ## TileFlowArea scrolls and fits as many tile columns as the width allows.
        self.tile_area = TileFlowArea()
        self.tile_area.tile_picked.connect(self._on_tile_picked)
        grid_box_layout.addWidget(self.tile_area, stretch=1)
        self.lbl_grid_empty = QLabel("")
        self.lbl_grid_empty.setObjectName("DashEmptyLabel")
        self.lbl_grid_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid_box_layout.addWidget(self.lbl_grid_empty, stretch=1)
        library_layout.addWidget(self.grid_box, stretch=1)
        page_grid.addWidget(library_card, 0, 0, 3, 1)

        # endregion

        # region Detail Card

        ## The picked tile: a big picture on the left, NAME / ID / STACK SIZE / CATEGORY on the right.
        detail_card, detail_layout = make_card()
        detail_row = QHBoxLayout()
        detail_row.setSpacing(14)
        self.lbl_detail_picture = QLabel("")
        self.lbl_detail_picture.setObjectName("LibraryPictureBox")
        self.lbl_detail_picture.setFixedSize(84, 84)
        self.lbl_detail_picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail_row.addWidget(self.lbl_detail_picture, alignment=Qt.AlignmentFlag.AlignTop)
        detail_text = QVBoxLayout()
        detail_text.setSpacing(4)
        self.lbl_detail_name = QLabel("Nothing picked")
        self.lbl_detail_name.setObjectName("PlayerNameLabel")
        detail_text.addWidget(self.lbl_detail_name)
        self.lbl_detail_id = QLabel("ID:  --")
        self.lbl_detail_stack = QLabel("STACK SIZE:  --")
        self.lbl_detail_category = QLabel("CATEGORY:  --")
        for lbl_detail in (self.lbl_detail_id, self.lbl_detail_stack, self.lbl_detail_category):
            lbl_detail.setObjectName("PlayerInfoLabel")
            detail_text.addWidget(lbl_detail)
        detail_text.addStretch()
        detail_row.addLayout(detail_text, stretch=1)
        detail_layout.addLayout(detail_row)

        ## Opens every stat for the picked item in its own window. Off until a tile is picked.
        self.btn_view_stats = QPushButton("VIEW ALL STATS")
        self.btn_view_stats.setObjectName("DashActionButton")
        self.btn_view_stats.setFixedHeight(34)
        self.btn_view_stats.setEnabled(False)
        self.btn_view_stats.setToolTip("Pick an item first.")
        self.btn_view_stats.clicked.connect(self._show_item_stats)
        detail_layout.addWidget(self.btn_view_stats)
        page_grid.addWidget(detail_card, 0, 1)

        # endregion

        # region Give Item

        ## How many, to which online player, then ADD TO PENDING EDITS (nothing is sent until the edits are applied).
        give_card, give_layout = make_card("GIVE ITEM")
        give_labels = QHBoxLayout()
        lbl_quantity = QLabel("QUANTITY")
        lbl_quantity.setObjectName("PlayerInfoLabel")
        lbl_player = QLabel("PLAYER:")
        lbl_player.setObjectName("PlayerInfoLabel")
        give_labels.addWidget(lbl_quantity, stretch=1)
        give_labels.addWidget(lbl_player, stretch=3)
        give_layout.addLayout(give_labels)
        give_inputs = QHBoxLayout()
        give_inputs.setSpacing(10)
        self.spn_quantity = QSpinBox()
        self.spn_quantity.setObjectName("LibraryQuantityBox")
        self.spn_quantity.setRange(1, 9999)
        self.spn_quantity.setValue(1)
        self.cmb_player = QComboBox()
        self.cmb_player.setObjectName("EcfFileCombo")
        self.cmb_player.setPlaceholderText("No players online")
        self.cmb_player.setEnabled(False)
        give_inputs.addWidget(self.spn_quantity, stretch=1)
        give_inputs.addWidget(self.cmb_player, stretch=3)
        give_layout.addLayout(give_inputs)
        self.btn_add_pending = QPushButton("GIVE ITEM")
        self.btn_add_pending.setObjectName("DashActionButton")
        self.btn_add_pending.setFixedHeight(38)
        self.btn_add_pending.setEnabled(False)
        self.btn_add_pending.setToolTip(LATER_TIP)
        give_layout.addWidget(self.btn_add_pending)
        page_grid.addWidget(give_card, 1, 1)

        # endregion

        # region Loadout Templates

        ## Saved kits like Starter or Explorer. ADD TO TEMPLATE puts the picked item into one.
        templates_card, templates_layout = make_card("LOADOUT TEMPLATES")
        self.lbl_templates_empty = QLabel("No templates yet.")
        self.lbl_templates_empty.setObjectName("DashEmptyLabel")
        templates_layout.addWidget(self.lbl_templates_empty)
        templates_layout.addStretch()
        self.btn_add_template = QPushButton("ADD TO TEMPLATE")
        self.btn_add_template.setObjectName("DashActionButton")
        self.btn_add_template.setFixedHeight(38)
        self.btn_add_template.setEnabled(False)
        self.btn_add_template.setToolTip(LATER_TIP)
        templates_layout.addWidget(self.btn_add_template)
        page_grid.addWidget(templates_card, 2, 1)

        # endregion

        ## Column widths roughly match the mockup: 3 : 1.3. The templates card takes the spare height.
        page_grid.setColumnStretch(0, 30)
        page_grid.setColumnStretch(1, 13)
        page_grid.setRowStretch(2, 1)

    # endregion

    # region Tabs

    def _on_tab_clicked(self, tab_key):
        """Lights the picked tab, swaps in its filter buttons and its empty-grid text."""
        try:
            self.active_tab = tab_key
            if tab_key in self.tab_buttons:
                self.tab_buttons[tab_key].setChecked(True)

            ## Take the old filter buttons out, then add the ones for this tab.
            for btn_old in self.filter_buttons:
                self.filter_group.removeButton(btn_old)
                self.filter_row.removeWidget(btn_old)
                btn_old.deleteLater()
            self.filter_buttons = []
            while self.filter_row.count() > 0:
                self.filter_row.takeAt(0)
            for filter_text in TAB_FILTERS.get(tab_key, []):
                btn_filter = QPushButton(filter_text)
                btn_filter.setObjectName("StructFilterButton")
                btn_filter.setCheckable(True)
                btn_filter.setFixedHeight(30)
                btn_filter.setCursor(Qt.CursorShape.PointingHandCursor)

                ## Turning a filter on or off narrows the grid straight away.
                btn_filter.toggled.connect(self._apply_filters)
                self.filter_group.addButton(btn_filter)
                self.filter_buttons.append(btn_filter)
                self.filter_row.addWidget(btn_filter)
            self.filter_row.addStretch()
            self.lbl_grid_empty.setText(TAB_EMPTY_TEXT.get(tab_key, ""))
            self._apply_filters()
        except Exception as e:
            print(f"[ERROR] LibraryPage: Failed to switch tab to {tab_key}: {e}")

    # endregion

    # region Items

    def load_server_files(self, folder=None):
        """Loads ITEMS from the downloaded server files. folder=None uses the last download. Returns how many loaded."""
        try:
            if folder is None:
                folder = current_scenario_folder()
            self.server_folder = folder
            items_root, items_path = find_file(folder, ITEMS_FILE)
            if items_path is None:

                ## Nothing downloaded (or no ItemsConfig.ecf in it): the grid says how to get the files.
                TAB_EMPTY_TEXT["items"] = NO_FILES_TEXT if folder is None else "The downloaded server files have no ItemsConfig.ecf."
                self.items = []
                self.tile_area.set_items(self.items)
                self._apply_filters()
                return 0
            TAB_EMPTY_TEXT["items"] = "No items loaded yet."

            ## Localization.csv may be missing (the scenario then shows internal names).
            names_root, names_path = find_file(folder, NAMES_FILE)
            self.items = load_items(None, items_path=items_path, names_path=names_path or "")
            image_index = build_image_index(folder)
            for item in self.items:
                item["image_path"] = image_index.get(item["name"].lower())
            self.tile_area.set_items(self.items)
            self._apply_filters()
            print(f"[INFO] LibraryPage: {len(self.items)} items from {items_root}, {sum(1 for item in self.items if item['image_path'])} with pictures")
            return len(self.items)
        except Exception as e:
            print(f"[ERROR] LibraryPage: Could not load the downloaded server files: {e}")
            return 0

    def load_items_from(self, content_folder):
        """Reads every item from a game Content folder and fills the grid. Read-only. Returns how many loaded."""
        self.items = load_items(content_folder)
        self.tile_area.set_items(self.items)
        self._apply_filters()
        return len(self.items)

    def _apply_filters(self, *args):
        """Shows only tiles that match the search text and (if any are on) the lit filter buttons."""
        try:

            ## Blueprints have no data yet, so their tab shows the empty text.
            if self.active_tab != "items":
                self.tile_area.show_only([])
                self.tile_area.setVisible(False)
                self.lbl_grid_empty.setVisible(True)
                return
            search_text = self.txt_search.text().strip().lower()
            lit_filters = {btn.text() for btn in self.filter_buttons if btn.isChecked()}
            shown_tiles = []
            for tile in self.tile_area.tiles:
                item = tile.item
                if lit_filters and item["filter_group"] not in lit_filters:
                    continue
                if search_text and search_text not in (item["display_name"] + " " + item["name"] + " " + item["id"]).lower():
                    continue
                shown_tiles.append(tile)
            self.tile_area.show_only(shown_tiles)
            self.tile_area.setVisible(bool(shown_tiles))
            self.lbl_grid_empty.setVisible(not shown_tiles)
            if self.items and not shown_tiles:
                self.lbl_grid_empty.setText("No items match.")
            else:
                self.lbl_grid_empty.setText(TAB_EMPTY_TEXT.get(self.active_tab, ""))
        except Exception as e:
            print(f"[ERROR] LibraryPage: Failed to filter items: {e}")

    def _on_tile_picked(self, item):
        """Fills the detail card with the picked item and turns on VIEW ALL STATS."""
        self.picked_item = item
        self.lbl_detail_picture.setPixmap(make_hex_pixmap(80, item["filter_group"], item["display_name"], item.get("image_path")))
        self.lbl_detail_name.setText(item["display_name"])
        self.lbl_detail_id.setText("ID:  " + item["id"])
        self.lbl_detail_stack.setText("STACK SIZE:  " + item["stack_size"])
        self.lbl_detail_category.setText("CATEGORY:  " + (item["filter_group"] or item["category"] or "--"))
        self.btn_view_stats.setEnabled(True)
        self.btn_view_stats.setToolTip("See every stat for " + item["display_name"] + ".")

        ## If the stats window is already open, switch it to the new item.
        if self.stats_dialog is not None and self.stats_dialog.isVisible():
            self._show_item_stats()
        self._refresh_give_buttons()

    def _show_item_stats(self):
        """Opens the full stats window for the picked item (one window at a time)."""
        if self.picked_item is None:
            return
        if self.stats_dialog is not None:
            self.stats_dialog.close()
            self.stats_dialog.deleteLater()
        self.stats_dialog = ItemStatsDialog(self.picked_item, self.picked_item.get("own_keys"), self)
        self.stats_dialog.show()

    # endregion

    # region Give Item and Templates

    def _wire_give_and_templates(self):
        try:
            self.btn_add_pending.clicked.connect(self._on_give_clicked)
            self.btn_add_template.clicked.connect(self._on_add_template_clicked)
            self.cmb_player.currentIndexChanged.connect(lambda index: self._refresh_give_buttons())
            self._show_templates()
            self._refresh_give_buttons()
        except Exception as e:
            print(f"[ERROR] LibraryPage: Could not wire GIVE ITEM and templates: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        try:
            self._show_templates()
            self._refresh_give_buttons()
            if server_actions.bridge_is_connected(self):
                server_actions.read_bridge("plys", "PLAYER_CACHE", self._on_players_read,
                                           lambda message: print(f"[ERROR] LibraryPage: plys failed: {message}"))
        except Exception as e:
            print(f"[ERROR] LibraryPage: Could not read players on show: {e}")

    def _on_players_read(self, reply):
        try:
            picked = self.cmb_player.currentData()
            self.cmb_player.blockSignals(True)
            self.cmb_player.clear()
            for player in (reply or {}).get("player_list") or []:
                if isinstance(player, dict) and player.get("status") == "Online" and str(player.get("entityId", "")).isdigit():
                    entity_id = int(player["entityId"])
                    self.cmb_player.addItem(str(player.get("name", "?")), entity_id)
                    if entity_id == picked:
                        self.cmb_player.setCurrentIndex(self.cmb_player.count() - 1)

            ## With placeholder text Qt picks nothing by itself, so the first player is picked.
            if self.cmb_player.currentIndex() < 0 and self.cmb_player.count() > 0:
                self.cmb_player.setCurrentIndex(0)
            self.cmb_player.blockSignals(False)
            self.cmb_player.setEnabled(self.cmb_player.count() > 0)
            self._refresh_give_buttons()
        except Exception as e:
            print(f"[ERROR] LibraryPage: Could not read players: {e}")

    def _refresh_give_buttons(self):
        try:
            item_ok = self.active_tab == "items" and self.picked_item is not None and str(self.picked_item.get("id", "")).isdigit()
            reason = server_actions.block_reason(self, "give_item") or ("" if item_ok else "Pick an item first.")
            if not reason and self.cmb_player.currentData() is None:
                reason = "Pick an online player first."
            self.btn_add_pending.setEnabled(reason == "")
            self.btn_add_pending.setToolTip(reason or "Adds this item to that player (Safety Flow).")
            self.btn_add_template.setEnabled(item_ok)
            self.btn_add_template.setToolTip("Adds this item and quantity to a template on this PC." if item_ok else "Pick an item first.")
        except Exception as e:
            print(f"[ERROR] LibraryPage: Could not refresh GIVE ITEM buttons: {e}")

    def _on_give_clicked(self):
        try:
            if self.picked_item is None or self.cmb_player.currentData() is None or not self.btn_add_pending.isEnabled():
                return
            item = self.picked_item
            entity_id = int(self.cmb_player.currentData())
            command = server_actions.api_command("Request_Player_AddItem", {"id": entity_id,
                "item": {"id": int(item["id"]), "count": self.spn_quantity.value()}})
            server_actions.run_server_action(self, "give_item", "Give an item", command,
                                             lambda ok, reply: print(f"[{'SUCCESS' if ok else 'ERROR'}] LibraryPage: Give: {server_actions.reply_text(reply)}"),
                                             explanation=f"Gives {self.spn_quantity.value()} x {item['display_name']} to {self.cmb_player.currentText()}.")
        except Exception as e:
            print(f"[ERROR] LibraryPage: Give failed: {e}")

    def _show_templates(self):
        templates = loadouts.load_templates()
        self.lbl_templates_empty.setText("\n".join(f"{name}   {len(templates[name])} item(s)" for name in loadouts.TEMPLATE_NAMES))

    def _on_add_template_clicked(self):
        try:
            if self.picked_item is None or not self.btn_add_template.isEnabled():
                return
            name, accepted = QInputDialog.getItem(self, "Add to template", "Template:", loadouts.TEMPLATE_NAMES, 0, False)
            if not accepted or name not in loadouts.TEMPLATE_NAMES:
                return
            loadouts.add_to_template(name, int(self.picked_item["id"]), self.picked_item["display_name"], self.spn_quantity.value())
            self._show_templates()
            print(f"[SUCCESS] LibraryPage: Added {self.picked_item['display_name']} to {name}")
        except Exception as e:
            print(f"[ERROR] LibraryPage: Add to template failed: {e}")

    # endregion

# endregion
