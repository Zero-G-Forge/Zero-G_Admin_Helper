## =====================================================================
## TEST: tests/test_item_pictures.py
## DESCRIPTION: Checks that the Library detail card and the Item Stats window show the
## whole item picture (aspect ratio kept, not cropped to a hex), while the grid still
## uses the hex tile. Uses a temporary download folder; the real data/ folder is never touched.
## Run from the app root:  QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_item_pictures.py -q
## =====================================================================

# region Imports

import json
import os
import sys
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication

from features.library.item_stats_dialog import ItemStatsDialog
from features.library.item_tiles import make_fit_pixmap, make_hex_pixmap
from features.library.library_page import LibraryPage
from features.server_files import file_store
from features.settings import app_settings

# endregion


# region Fixtures

@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(file_store, "SERVER_FILES_DIR", str(tmp_path / "server_files"))
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", str(tmp_path / "app_settings.json"))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def write_wide_picture(path):
    """A 40x20 picture: left half red, right half blue, so a crop or stretch would show."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image = QImage(40, 20, QImage.Format.Format_RGB32)
    for x in range(40):
        color = QColor(255, 0, 0) if x < 20 else QColor(0, 0, 255)
        for y in range(20):
            image.setPixelColor(x, y, color)
    assert image.save(path)


ITEMS_ECF = """{ +Item Id: 1, Name: PulseRifle
  Category: Weapons/Items
  Ref: WeaponTemplate
  StackSize: 1
}
"""


def build_wide_download(tmp_path):
    folder = os.path.join(file_store.SERVER_FILES_DIR, "Ascension-Reborn")
    write(os.path.join(folder, "_manifest.json"), json.dumps({"files": {}, "scenario": "Ascension-Reborn"}))
    write(os.path.join(folder, "save", "Content", "Configuration", "ItemsConfig.ecf"), ITEMS_ECF)
    write(os.path.join(folder, "scenario", "Content", "Extras", "Localization.csv"),
          "KEY,English\nPulseRifle,Pulse Rifle\n")
    write_wide_picture(os.path.join(folder, "scenario", "SharedData", "Content", "Bundles", "ItemIcons", "PulseRifle.png"))
    return folder, os.path.join(folder, "scenario", "SharedData", "Content", "Bundles", "ItemIcons", "PulseRifle.png")

# endregion


# region Tests

def test_fit_pixmap_keeps_aspect_and_both_sides(tmp_path, qapp):
    folder, path = build_wide_download(tmp_path)
    fitted = make_fit_pixmap(80, 80, "WEAPONS", "Pulse Rifle", path)
    assert fitted.width() == 80 and fitted.height() == 80

    ## A 40x20 picture fitted into 80x80 should be 80x40, centred, so y=0 and y=79 stay empty
    ## and the mid-left is red and the mid-right is blue (not cropped to a square).
    assert fitted.toImage().pixelColor(40, 0).alpha() == 0
    assert fitted.toImage().pixelColor(40, 79).alpha() == 0
    mid_y = 40
    assert fitted.toImage().pixelColor(10, mid_y).red() > 200
    assert fitted.toImage().pixelColor(70, mid_y).blue() > 200


def test_detail_card_and_stats_use_the_full_picture(tmp_path, qapp):
    build_wide_download(tmp_path)
    page = LibraryPage()
    item = page.items[0]
    page._on_tile_picked(item)
    detail = page.lbl_detail_picture.pixmap()
    assert detail is not None and not detail.isNull()
    assert page.lbl_detail_picture.width() == 120
    assert detail.toImage().pixelColor(10, 60).red() > 200
    assert detail.toImage().pixelColor(110, 60).blue() > 200
    dialog = ItemStatsDialog(item, item.get("own_keys"), page)
    dialog.show()
    dialog.resize(800, 720)
    qapp.processEvents()
    ## Top half is 50/50: the picture box and the details box share the header width.
    header_box: Any = dialog.lbl_picture.parent()
    text_box = header_box.layout().itemAt(1).widget()
    assert abs(dialog.lbl_picture.width() - text_box.width()) < 40
    assert dialog.lbl_picture.width() > 250
    ## Bottom half is the stats tree, about the same height as the header.
    assert abs(dialog.tree_stats.height() - header_box.height()) < 80
    stats_pic = dialog.lbl_picture.pixmap()
    assert stats_pic is not None and not stats_pic.isNull()
    pic = stats_pic.toImage()
    mid_y = pic.height() // 2
    left_x = max(1, pic.width() // 8)
    right_x = pic.width() - 1 - max(1, pic.width() // 8)
    assert pic.pixelColor(left_x, mid_y).red() > 200
    assert pic.pixelColor(right_x, mid_y).blue() > 200
    from PyQt6.QtWidgets import QLabel
    labels = [widget.text() for widget in dialog.findChildren(QLabel)]
    assert any(text.startswith("FILE NAME:") for text in labels)
    assert any(text.startswith("ID:") for text in labels)
    assert any(text.startswith("CATEGORY:") for text in labels)
    assert any(text.startswith("TEMPLATE:") for text in labels)
    dialog.close()
    page.deleteLater()

# endregion
