## ==========================================
## ZERO-G ADMIN HELPER - ITEM & BLUEPRINT LIBRARY PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Item_BP_Library.jpg:
## ITEMS / BLUEPRINTS tabs with a search box, filter buttons and a grid of tiles on the left;
## the picked tile's details, GIVE ITEM and LOADOUT TEMPLATES on the right.
## The ITEMS and BP EDITOR nav entries both open this page, each starting on its own tab.
## ITEMS reads a game Content folder (ItemsConfig.ecf + Localization.csv) through load_items_from; read-only.
## (Nov 22, 2026: on opening, ITEMS reads the downloaded server files through load_server_files, never the
## local base game. Pictures come from the downloaded Images and Bundles/ItemIcons folders,
## matched to the item Name, then to CustomIcon, as <name>.jpg or .png.)
## BLUEPRINTS reads .epb files from Prefabs in those same downloaded files (save copy first).
## Both lists stay empty until a category button is clicked. A plain click shows only that
## category. The FILTER button is the only way to pick more than one, through a checkbox menu.
## GIVE ITEM changes a live player, so its button stays off until Ray OKs that step.
## Wired (Nov 22, 2026): GIVE ITEM sends api:Request_Player_AddItem through the Safety Flow (admin and up), to
## an online player from plys. ADD TO TEMPLATE saves the picked item and quantity on this PC (loadouts.py).
## The old ADD TO PENDING EDITS button is now labelled GIVE ITEM (there is no separate pending-edit queue).
## BUILD ITEM TEMPLATE (Nov 23, 2026) opens a window with the same item grid as this page
## (search, category buttons, FILTER, Choose a Category) to name and fill a pack. Packs are
## saved on this PC next to STARTER, EXPLORER and BUILDER, including any custom names.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QPushButton, QButtonGroup, QLineEdit, QSpinBox, QComboBox, QInputDialog, QMenu,
                             QSizePolicy, QDialog)

## Read-only bridge reads, the Safety Flow, and loadout templates saved on this PC.
from features.shared import server_actions, loadouts

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

## Item data, the hex tile grid and the full stats window.
from features.library.item_library import load_items
from features.library.blueprint_library import load_blueprints
from features.library.item_tiles import TileFlowArea, make_fit_pixmap
from features.library.item_stats_dialog import ItemStatsDialog
from features.library.item_browser import ItemBrowser
from features.library.item_pack_dialog import ItemPackDialog

## Where the downloaded server files are, and the item pictures inside them.
from features.server_files.local_files import (NO_FILES_TEXT, ITEMS_FILE, NAMES_FILE, current_scenario_folder,
                                               find_file, build_image_index, find_item_image,
                                               load_block_index, item_give_reason, item_give_warning)

# endregion


# region Constants

## Tabs across the top: (key, text).
LIBRARY_TABS = [("items", "ITEMS"), ("blueprints", "BLUEPRINTS")]

## Filter buttons under the search box, different for each tab.
TAB_FILTERS = {
    "items": ["WEAPONS", "ARMOR", "MEDICAL", "AMMO", "COMPONENTS", "ORES", "DEVICES", "FOOD"],
    "blueprints": ["BA", "CV", "SV", "HV", "POI"],
}

## What the empty grid says on each tab when nothing is loaded.
TAB_EMPTY_TEXT = {
    "items": "No items loaded yet.",
    "blueprints": "No blueprints loaded yet.",
}

## Shown when files are loaded but no category is selected yet.
PICK_CATEGORY_TEXT = {
    "items": "Choose a Category",
    "blueprints": "Choose a Category",
}

## Shown when the current category (and search text) matches nothing.
NO_MATCH_TEXT = {
    "items": "No items match.",
    "blueprints": "No blueprints match.",
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

        ## Loaded items and blueprints, and the one picked in the grid (None until a tile is clicked).
        self.items = []
        self.blueprints = []
        self.picked_item = None
        self.stats_dialog = None

        ## The downloaded scenario folder the items came from (None = nothing downloaded).
        self.server_folder = None
        self.block_index = {}
        self.setup_widgets()

        ## Fill ITEMS and BLUEPRINTS from the downloaded server files (or show how to download them) before the first tab shows.
        self.load_server_files()
        self._on_tab_clicked(self.active_tab)
        self._wire_give_and_templates()

    @property
    def txt_search(self):
        return self.item_browser.txt_search

    @property
    def filter_row(self):
        return self.item_browser.filter_row

    @property
    def filter_group(self):
        return self.item_browser.filter_group

    @property
    def filter_buttons(self):
        return self.item_browser.filter_buttons

    @property
    def filter_actions(self):
        return self.item_browser.filter_actions

    @property
    def btn_multi_filter(self):
        return self.item_browser.btn_multi_filter

    @property
    def filter_menu(self):
        return self.item_browser.filter_menu

    @property
    def tile_area(self):
        return self.item_browser.tile_area

    @property
    def lbl_grid_empty(self):
        return self.item_browser.lbl_grid_empty

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

        ## Search box, category buttons, FILTER menu and the tile grid live in ItemBrowser,
        ## shared with the BUILD ITEM TEMPLATE window. Typing in the search box still
        ## narrows the grid straight away, and the filters are rebuilt by _on_tab_clicked.
        self.item_browser = ItemBrowser(log_name="LibraryPage", parent=self)
        self.item_browser.set_empty_texts(
            TAB_EMPTY_TEXT.get(self.active_tab, ""),
            PICK_CATEGORY_TEXT.get(self.active_tab, ""),
            NO_MATCH_TEXT.get(self.active_tab, ""),
        )
        self.item_browser.tile_picked.connect(self._on_tile_picked)
        self.item_browser.txt_search.textChanged.disconnect()
        self.item_browser.txt_search.textChanged.connect(self._apply_filters)
        library_layout.addWidget(self.item_browser, stretch=1)
        page_grid.addWidget(library_card, 0, 0, 3, 1)

        # endregion

        # region Detail Card

        ## The picked tile: the whole picture on the left (not cropped to a hex), NAME / ID / STACK SIZE / CATEGORY on the right.
        detail_card, detail_layout = make_card()
        detail_row = QHBoxLayout()
        detail_row.setSpacing(14)
        self.lbl_detail_picture = QLabel("")
        self.lbl_detail_picture.setObjectName("LibraryPictureBox")
        self.lbl_detail_picture.setFixedSize(120, 120)
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
        self.btn_build_template = QPushButton("BUILD ITEM TEMPLATE")
        self.btn_build_template.setObjectName("DashActionButton")
        self.btn_build_template.setFixedHeight(38)
        self.btn_build_template.setEnabled(False)
        self.btn_build_template.setToolTip(LATER_TIP)
        templates_layout.addWidget(self.btn_build_template)
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
            self._rebuild_filter_row(tab_key)

            ## Each tab has its own list; the grid starts empty until a category is clicked.
            if tab_key == "blueprints":
                self.tile_area.set_items(self.blueprints)
            else:
                self.tile_area.set_items(self.items)
            self.lbl_grid_empty.setText(TAB_EMPTY_TEXT.get(tab_key, ""))
            self._apply_filters()
        except Exception as e:
            print(f"[ERROR] LibraryPage: Failed to switch tab to {tab_key}: {e}")

    def _rebuild_filter_row(self, tab_key):
        """Rebuilds the category buttons and the FILTER checkbox menu for the active tab."""
        self.item_browser.rebuild_filters(TAB_FILTERS.get(tab_key, []))

    def _on_category_clicked(self, btn):
        """A plain category click is a single choice: only that button stays on."""
        self.item_browser._on_category_clicked(btn)

    def _on_filter_menu_toggled(self, *args):
        """Applies the FILTER checkboxes. Category buttons only light when exactly one is checked."""
        self.item_browser._on_filter_menu_toggled(*args)

    def _show_filter_menu(self):
        """Opens the FILTER checkbox menu under the FILTER button."""
        self.item_browser._show_filter_menu()

    def _selected_groups(self):
        """The categories currently checked in FILTER (kept in sync with a single category click)."""
        return self.item_browser.selected_groups()

    # endregion

    # region Items

    def load_server_files(self, folder=None):
        """Loads ITEMS and BLUEPRINTS from the downloaded server files. folder=None uses the selected or last download. Returns how many items loaded."""
        try:
            if folder is None:
                folder = current_scenario_folder()
            self.server_folder = folder
            self.block_index = load_block_index(folder) if folder else {}
            items_root, items_path = (None, None)
            if folder is not None:
                items_root, items_path = find_file(folder, ITEMS_FILE)
            if items_path is None:

                ## Nothing downloaded (or no ItemsConfig.ecf in it): the grid says how to get the files.
                TAB_EMPTY_TEXT["items"] = NO_FILES_TEXT if folder is None else "The downloaded server files have no ItemsConfig.ecf."
                self.items = []
            else:
                TAB_EMPTY_TEXT["items"] = "No items loaded yet."

                ## Localization.csv may be missing (the scenario then shows internal names).
                names_root, names_path = find_file(folder, NAMES_FILE)
                self.items = load_items(None, items_path=items_path, names_path=names_path or "")
                image_index = build_image_index(folder)
                for item in self.items:
                    custom_prop = (item.get("props") or {}).get("CustomIcon")
                    custom_icon = custom_prop.get("value") if custom_prop else None
                    item["image_path"] = find_item_image(folder, item["name"], image_index, custom_icon=custom_icon)
            if folder is None:
                TAB_EMPTY_TEXT["blueprints"] = NO_FILES_TEXT
                self.blueprints = []
            else:
                self.blueprints = load_blueprints(folder)
                if self.blueprints:
                    TAB_EMPTY_TEXT["blueprints"] = "No blueprints loaded yet."
                else:
                    TAB_EMPTY_TEXT["blueprints"] = "No blueprint files in the downloaded server files."
            if self.active_tab == "blueprints":
                self.tile_area.set_items(self.blueprints)
            else:
                self.tile_area.set_items(self.items)
            self._apply_filters()
            print(f"[INFO] LibraryPage: {len(self.items)} items from {items_root}, {sum(1 for item in self.items if item['image_path'])} with pictures, {len(self.blueprints)} blueprints")
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
        """Shows only tiles that match the selected categories and the search text. Nothing shows until a category is picked."""
        loaded = self.blueprints if self.active_tab == "blueprints" else self.items
        self.item_browser._loaded = bool(loaded)
        self.item_browser.set_empty_texts(
            TAB_EMPTY_TEXT.get(self.active_tab, ""),
            PICK_CATEGORY_TEXT.get(self.active_tab, ""),
            NO_MATCH_TEXT.get(self.active_tab, ""),
        )
        self.item_browser.apply_filters()

    def _on_tile_picked(self, item):
        """Fills the detail card with the picked item and turns on VIEW ALL STATS."""
        self.picked_item = item
        self.lbl_detail_picture.setPixmap(make_fit_pixmap(116, 116, item["filter_group"], item["display_name"], item.get("image_path")))
        self.lbl_detail_name.setText(item["display_name"])
        self.lbl_detail_id.setText("ID:  " + item["id"])
        self.lbl_detail_stack.setText("STACK SIZE:  " + item["stack_size"])
        self.lbl_detail_category.setText("CATEGORY:  " + (item["filter_group"] or item["category"] or "--"))
        if self.active_tab == "items":
            self.btn_view_stats.setEnabled(True)
            self.btn_view_stats.setToolTip("See every stat for " + item["display_name"] + ".")
        else:
            self.btn_view_stats.setEnabled(False)
            self.btn_view_stats.setToolTip("Stats are for items.")

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
            self.btn_build_template.clicked.connect(self._on_build_template_clicked)
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
            if not reason and item_ok:
                reason = item_give_reason(self.picked_item, self.block_index) or ""
            warning = item_give_warning(self.picked_item, self.block_index) if item_ok else ""
            self.btn_add_pending.setEnabled(reason == "")
            self.btn_add_pending.setToolTip(reason or warning or "Adds this item to that player (Safety Flow).")
            self.btn_add_template.setEnabled(item_ok)
            self.btn_add_template.setToolTip("Adds this item and quantity to a template on this PC." if item_ok else "Pick an item first.")
            items_loaded = any(str(item.get("id", "")).isdigit() for item in self.items)
            self.btn_build_template.setEnabled(items_loaded)
            self.btn_build_template.setToolTip(
                "Build or edit a named item pack on this PC." if items_loaded
                else "Load items from the downloaded server files first.")
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
        names = loadouts.list_template_names(templates)
        self.lbl_templates_empty.setText("\n".join(f"{name}   {len(templates[name])} item(s)" for name in names))

    def _on_add_template_clicked(self):
        try:
            if self.picked_item is None or not self.btn_add_template.isEnabled():
                return
            names = loadouts.list_template_names()
            name, accepted = QInputDialog.getItem(self, "Add to template", "Template:", names, 0, False)
            if not accepted or name not in names:
                return
            loadouts.add_to_template(name, int(self.picked_item["id"]), self.picked_item["display_name"], self.spn_quantity.value())
            self._show_templates()
            print(f"[SUCCESS] LibraryPage: Added {self.picked_item['display_name']} to {name}")
        except Exception as e:
            print(f"[ERROR] LibraryPage: Add to template failed: {e}")

    def _on_build_template_clicked(self):
        try:
            if not self.btn_build_template.isEnabled():
                return
            giveable = [item for item in self.items if not item_give_reason(item, self.block_index)]
            dialog = ItemPackDialog(giveable, parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._show_templates()
        except Exception as e:
            print(f"[ERROR] LibraryPage: Build item template failed: {e}")

    # endregion

# endregion
