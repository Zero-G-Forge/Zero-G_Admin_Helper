## ==========================================
## ZERO-G ADMIN HELPER - LIBRARY ITEM BROWSER
## The search box, category buttons, FILTER checkbox menu, "Choose a Category"
## empty state, and picture tile grid used by the Library page and by the
## BUILD ITEM TEMPLATE window. The grid stays empty until a category is
## clicked. A plain click shows only that category. The FILTER button is the
## only way to pick more than one, through a checkbox menu.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout,
                             QPushButton, QButtonGroup, QLineEdit, QMenu, QSizePolicy)

from features.library.item_tiles import TileFlowArea

# endregion


# region ItemBrowser Class

class ItemBrowser(QWidget):
    ## Emitted when a visible tile is clicked. The value is the item dict on that tile.
    tile_picked = pyqtSignal(dict)

    def __init__(self, parent=None, log_name="ItemBrowser"):
        super().__init__(parent)
        self.setObjectName("ItemBrowser")
        self.log_name = log_name
        self.filter_buttons = []
        self.filter_actions = {}
        self.btn_multi_filter = None
        self.filter_menu = None
        self._syncing_filters = False
        self.empty_unloaded = ""
        self.empty_pick_category = "Choose a Category"
        self.empty_no_match = "No items match."
        self._loaded = False
        self._setup_widgets()

    def _setup_widgets(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        ## Search box, same look as the ECF Editor's trader search.
        self.txt_search = QLineEdit()
        self.txt_search.setObjectName("EcfSearchBox")
        self.txt_search.setPlaceholderText("Search")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.setMaximumWidth(300)
        layout.addWidget(self.txt_search)

        ## Typing in the search box narrows the grid straight away.
        self.txt_search.textChanged.connect(self.apply_filters)

        ## Filter buttons. They are rebuilt by rebuild_filters, since each caller has its own set.
        self.filter_row = QHBoxLayout()
        self.filter_row.setSpacing(8)
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(False)
        layout.addLayout(self.filter_row)

        ## Tile grid: each item or blueprint will be a hex tile with its picture, name and ID.
        self.grid_box = QFrame()
        self.grid_box.setObjectName("DashInnerBox")
        grid_box_layout = QVBoxLayout(self.grid_box)
        grid_box_layout.setContentsMargins(12, 12, 12, 12)

        ## TileFlowArea scrolls and fits as many tile columns as the width allows.
        self.tile_area = TileFlowArea()
        self.tile_area.tile_picked.connect(self.tile_picked.emit)
        grid_box_layout.addWidget(self.tile_area, stretch=1)
        self.lbl_grid_empty = QLabel("")
        self.lbl_grid_empty.setObjectName("DashEmptyLabel")
        self.lbl_grid_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_grid_empty.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        grid_box_layout.addWidget(self.lbl_grid_empty, stretch=1)
        layout.addWidget(self.grid_box, stretch=1)

    def set_empty_texts(self, unloaded, pick_category, no_match):
        ## The three empty-grid messages: nothing loaded, no category yet, or no match.
        self.empty_unloaded = unloaded
        self.empty_pick_category = pick_category
        self.empty_no_match = no_match

    def set_items(self, items):
        """Fills the grid from a list of item dicts. The grid stays empty until a category is picked."""
        self._loaded = bool(items)
        self.tile_area.set_items(items or [])
        self.apply_filters()

    def rebuild_filters(self, filter_names):
        """Rebuilds the category buttons and the FILTER checkbox menu for the given names."""
        for btn_old in self.filter_buttons:
            self.filter_group.removeButton(btn_old)
            self.filter_row.removeWidget(btn_old)

            ## Hide and unparent now; deleteLater alone leaves the old buttons visible
            ## in their last position until the event loop runs.
            btn_old.hide()
            btn_old.setParent(None)
            btn_old.deleteLater()
        self.filter_buttons = []
        if self.btn_multi_filter is not None:
            self.filter_row.removeWidget(self.btn_multi_filter)
            self.btn_multi_filter.hide()
            self.btn_multi_filter.setParent(None)
            self.btn_multi_filter.deleteLater()
            self.btn_multi_filter = None
        if self.filter_menu is not None:
            self.filter_menu.deleteLater()
            self.filter_menu = None
        self.filter_actions = {}
        while self.filter_row.count() > 0:
            self.filter_row.takeAt(0)
        for filter_text in filter_names:
            btn_filter = QPushButton(filter_text)
            btn_filter.setObjectName("StructFilterButton")
            btn_filter.setCheckable(True)
            btn_filter.setFixedHeight(30)
            btn_filter.setCursor(Qt.CursorShape.PointingHandCursor)

            ## A plain click shows only this category; more than one is chosen in FILTER.
            btn_filter.clicked.connect(lambda _checked, btn=btn_filter: self._on_category_clicked(btn))
            self.filter_group.addButton(btn_filter)
            self.filter_buttons.append(btn_filter)
            self.filter_row.addWidget(btn_filter)
        self.filter_row.addStretch()
        self.filter_menu = QMenu(self)
        self.filter_menu.setObjectName("LibraryFilterMenu")
        for filter_text in filter_names:
            action = self.filter_menu.addAction(filter_text)
            action.setCheckable(True)
            action.toggled.connect(self._on_filter_menu_toggled)
            self.filter_actions[filter_text] = action
        self.btn_multi_filter = QPushButton("FILTER")
        self.btn_multi_filter.setObjectName("StructFilterButton")
        self.btn_multi_filter.setFixedHeight(30)
        self.btn_multi_filter.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_multi_filter.setToolTip("Pick more than one category.")
        self.btn_multi_filter.clicked.connect(self._show_filter_menu)
        self.filter_row.addWidget(self.btn_multi_filter)

    def _on_category_clicked(self, btn):
        """A plain category click is a single choice: only that button stays on."""
        if self._syncing_filters:
            return
        self._syncing_filters = True
        try:
            for other in self.filter_buttons:
                other.setChecked(other is btn)
            for text, action in self.filter_actions.items():
                action.setChecked(text == btn.text())
        finally:
            self._syncing_filters = False
        self.apply_filters()

    def _on_filter_menu_toggled(self, *args):
        """Applies the FILTER checkboxes. Category buttons only light when exactly one is checked."""
        if self._syncing_filters:
            return
        self._syncing_filters = True
        try:
            lit = {text for text, action in self.filter_actions.items() if action.isChecked()}
            for btn in self.filter_buttons:
                btn.setChecked(len(lit) == 1 and btn.text() in lit)
        finally:
            self._syncing_filters = False
        self.apply_filters()

    def _show_filter_menu(self):
        """Opens the FILTER checkbox menu under the FILTER button."""
        if self.filter_menu is None or self.btn_multi_filter is None:
            return
        pos = self.btn_multi_filter.mapToGlobal(QPoint(0, self.btn_multi_filter.height()))
        self.filter_menu.popup(pos)

    def selected_groups(self):
        """The categories currently checked in FILTER (kept in sync with a single category click)."""
        if self.filter_actions:
            return {text for text, action in self.filter_actions.items() if action.isChecked()}
        return {btn.text() for btn in self.filter_buttons if btn.isChecked()}

    def apply_filters(self, *args):
        """Shows only tiles that match the selected categories and the search text. Nothing shows until a category is picked."""
        try:
            search_text = self.txt_search.text().strip().lower()
            lit_filters = self.selected_groups()
            shown_tiles = []
            if lit_filters:
                for tile in self.tile_area.tiles:
                    item = tile.item
                    if item.get("filter_group") not in lit_filters:
                        continue
                    if search_text and search_text not in (item["display_name"] + " " + item["name"] + " " + item["id"]).lower():
                        continue
                    shown_tiles.append(tile)
            self.tile_area.show_only(shown_tiles)
            self.tile_area.setVisible(bool(shown_tiles))
            self.lbl_grid_empty.setVisible(not shown_tiles)
            if not self._loaded:
                self.lbl_grid_empty.setText(self.empty_unloaded)
            elif not lit_filters:
                self.lbl_grid_empty.setText(self.empty_pick_category)
            elif not shown_tiles:
                self.lbl_grid_empty.setText(self.empty_no_match)
            else:
                self.lbl_grid_empty.setText(self.empty_unloaded)
        except Exception as e:
            print(f"[ERROR] {self.log_name}: Failed to filter items: {e}")

# endregion
