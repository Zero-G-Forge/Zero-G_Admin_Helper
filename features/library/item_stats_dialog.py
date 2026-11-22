## ==========================================
## ZERO-G ADMIN HELPER - ITEM STATS WINDOW
## Opened by VIEW ALL STATS on the Library page. Shows everything ItemsConfig.ecf says about one item:
##   GENERAL       price, stack size, mass, volume, durability, unlock level...
##   MODE 1, 2...  each weapon or tool mode (the { Child } blocks): damage, rate of fire, range, ammo...
##   OTHER         every remaining stat
##   FILE DETAILS  mesh and sound paths and other file-only lines (folded shut)
## Values marked "(from Template)" come from the item's Ref parent, not its own block.
## Read-only.
## ==========================================

# region Imports

import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
                             QHeaderView, QAbstractItemView)

from features.dashboard.dashboard_page import make_card
from features.library.item_tiles import make_hex_pixmap

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
        self.resize(620, 640)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        stats_card, stats_layout = make_card()

        # region Header

        ## Big hex on the left, the item's names and ID on the right.
        header_row = QHBoxLayout()
        header_row.setSpacing(16)
        lbl_picture = QLabel()
        lbl_picture.setPixmap(make_hex_pixmap(84, item["filter_group"], item["display_name"]))
        lbl_picture.setFixedSize(84, 84)
        header_row.addWidget(lbl_picture, alignment=Qt.AlignmentFlag.AlignTop)
        header_text = QVBoxLayout()
        header_text.setSpacing(4)
        lbl_name = QLabel(item["display_name"])
        lbl_name.setObjectName("PlayerNameLabel")
        header_text.addWidget(lbl_name)
        header_lines = ["FILE NAME:  " + item["name"], "ID:  " + item["id"],
                        "CATEGORY:  " + (item["category"] or "--")]
        if item["ref"]:
            header_lines.append("TEMPLATE:  " + item["ref"])
        for header_line in header_lines:
            lbl_line = QLabel(header_line)
            lbl_line.setObjectName("PlayerInfoLabel")
            header_text.addWidget(lbl_line)
        header_text.addStretch()
        header_row.addLayout(header_text, stretch=1)
        stats_layout.addLayout(header_row)

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
