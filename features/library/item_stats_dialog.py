## ==========================================
## ZERO-G ADMIN HELPER - ITEM STATS WINDOW
## Opened by VIEW ALL STATS on the Library page. Shows everything ItemsConfig.ecf says about one item:
##   GENERAL       price, stack size, mass, volume, durability, unlock level...
##   MODE 1, 2...  each weapon or tool mode (the { Child } blocks): damage, rate of fire, range, ammo...
##   OTHER         every remaining stat
##   FILE DETAILS  mesh and sound paths and other file-only lines (folded shut)
## Values marked "(from Template)" come from the item's Ref parent, not its own block.
## The window is split in half vertically. The top half is 50/50: a large full item picture
## on the left (it grows with the window), and Name, FILE NAME, ID, CATEGORY and TEMPLATE
## on the right. The bottom half is only the STAT / VALUE tree. Read-only.
## ==========================================

# region Imports

import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
                             QHeaderView, QAbstractItemView, QSizePolicy, QWidget)

from features.dashboard.dashboard_page import make_card
from features.library.item_tiles import make_fit_pixmap

# endregion


# region Constants

## Shown first, in this order, under GENERAL.
GENERAL_KEYS = ["MarketPrice", "StackSize", "Mass", "Volume", "Durability", "DegradationProb",
                "UnlockLevel", "UnlockCost", "TechTreeNames", "TechTreeParent", "XpFactor", "Category"]

## File-only lines that don't matter to an admin, folded away under FILE DETAILS.
FILE_DETAIL_KEYS = {"Meshfile", "DropMeshfile", "Material", "HoldType", "Canhold", "ShowUser", "Info",
                    "CustomIcon", "PickupToToolbar", "LifetimeOnDrop", "Model", "Template"}

## Unit added after a value, from its 'formatter:' attribute.
FORMATTER_UNITS = {"Kilogram": " kg", "Liter": " L", "ROF": " s", "WattHour": " Wh"}

# endregion


# region Helpers

def readable_key(key):
    """'MarketPrice' -> 'Market Price', 'ROF' stays 'ROF'."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", key)


def readable_value(prop):
    """The value plus its unit, e.g. '6.51 kg'."""
    return prop["value"] + FORMATTER_UNITS.get(prop["attrs"].get("formatter", ""), "")

# endregion


# region ItemStatsDialog Class

class ItemStatsDialog(QDialog):

    def __init__(self, item, own_keys=None, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the window.
        self.setObjectName("ItemStatsDialog")
        self.setWindowTitle("Item Stats - " + item["display_name"])
        self.resize(860, 760)
        self._stats_item = item
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        stats_card, stats_layout = make_card()

        # region Header

        ## Top half of the card: picture and details each take half the width and grow on resize.
        header_box = QWidget()
        header_box.setObjectName("ItemStatsHeader")
        header_row = QHBoxLayout(header_box)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(16)
        self.lbl_picture = QLabel()
        self.lbl_picture.setObjectName("ItemStatsPicture")
        self.lbl_picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_picture.setMinimumSize(160, 160)
        self.lbl_picture.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        header_row.addWidget(self.lbl_picture, stretch=1)
        text_box = QWidget()
        text_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        header_text = QVBoxLayout(text_box)
        header_text.setContentsMargins(0, 0, 0, 0)
        header_text.setSpacing(4)
        lbl_name = QLabel(item["display_name"])
        lbl_name.setObjectName("PlayerNameLabel")
        header_text.addWidget(lbl_name)
        header_lines = [
            "FILE NAME:  " + item["name"],
            "ID:  " + item["id"],
            "CATEGORY:  " + (item["category"] or "--"),
            "TEMPLATE:  " + (item.get("ref") or "--"),
        ]
        for header_line in header_lines:
            lbl_line = QLabel(header_line)
            lbl_line.setObjectName("PlayerInfoLabel")
            header_text.addWidget(lbl_line)
        header_text.addStretch()
        header_row.addWidget(text_box, stretch=1)
        stats_layout.addWidget(header_box, stretch=1)

        # endregion

        # region Stats Tree

        ## Two columns: STAT and VALUE. Section rows (GENERAL, MODE 1...) fold open and shut.
        self.tree_stats = QTreeWidget()
        self.tree_stats.setObjectName("ItemStatsTree")
        self.tree_stats.setColumnCount(2)
        self.tree_stats.setHeaderLabels(["STAT", "VALUE"])
        self.tree_stats.setRootIsDecorated(True)
        self.tree_stats.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree_stats.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree_stats.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        stats_layout.addWidget(self.tree_stats, stretch=1)

        ## own_keys = the item's own lines; anything else was inherited from its Ref template.
        self.own_keys = own_keys
        props = item["props"]
        used_keys = set()
        general_rows = [(key, props[key]) for key in GENERAL_KEYS if key in props]
        used_keys.update(key for key, prop in general_rows)
        self._add_section("GENERAL", general_rows, expanded=True)
        for mode_number, child in enumerate(item["children"], start=1):
            mode_class = child["props"].get("Class", {}).get("value", "")
            mode_title = "MODE " + str(mode_number) + ("  -  " + mode_class if mode_class else "")
            self._add_section(mode_title, list(child["props"].items()), expanded=True, mark_inherited=False)
        other_rows = [(key, prop) for key, prop in props.items()
                      if key not in used_keys and key not in FILE_DETAIL_KEYS and not key.startswith("Sfx")]
        used_keys.update(key for key, prop in other_rows)
        self._add_section("OTHER", other_rows, expanded=True)
        file_rows = [(key, prop) for key, prop in props.items() if key not in used_keys]
        self._add_section("FILE DETAILS", file_rows, expanded=False)

        # endregion

        outer_layout.addWidget(stats_card)

    def showEvent(self, event):
        super().showEvent(event)
        self._refit_picture()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refit_picture()

    def _refit_picture(self):
        ## Fit the whole picture into the current left-half box, keeping its aspect ratio.
        item = self._stats_item
        box_w = max(16, self.lbl_picture.width() - 8)
        box_h = max(16, self.lbl_picture.height() - 8)
        self.lbl_picture.setPixmap(make_fit_pixmap(box_w, box_h, item["filter_group"], item["display_name"], item.get("image_path")))

    def _add_section(self, section_title, rows, expanded, mark_inherited=True):
        """Adds one fold-out section with a row per stat. Skips sections with nothing in them."""
        if not rows:
            return
        section_row = QTreeWidgetItem([section_title, ""])
        section_font = section_row.font(0)
        section_font.setBold(True)
        section_row.setFont(0, section_font)

        ## A section row spans both columns.
        self.tree_stats.addTopLevelItem(section_row)
        section_row.setFirstColumnSpanned(True)
        for key, prop in rows:
            value_text = readable_value(prop)
            if mark_inherited and self.own_keys is not None and key not in self.own_keys:
                value_text += "   (from Template)"
            stat_row = QTreeWidgetItem([readable_key(key), value_text])
            stat_row.setToolTip(0, key)
            section_row.addChild(stat_row)
        section_row.setExpanded(expanded)

# endregion
