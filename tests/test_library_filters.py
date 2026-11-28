## =====================================================================
## TEST: tests/test_library_filters.py
## DESCRIPTION: Checks the shared Item & Blueprint Library filters: the grid stays empty
## until a category button is clicked, a plain click shows only that category, and more
## than one category can be chosen only through the FILTER checkbox menu. The search box
## still narrows the current selection. Also checks that BLUEPRINTS loads .epb files and
## has a POI button. Uses a temporary download folder; the real data/ folder is never touched.
## Run from the app root:  QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_library_filters.py -q
## =====================================================================

# region Imports

import json
import os
import struct
import sys
from typing import Any

import pytest
from PyQt6.QtCore import Qt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication

from features.library.library_page import LibraryPage, TAB_FILTERS
from features.server_files import file_store, local_files
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


def write_epb(path, type_byte):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = b"\x45\x52\x94\x78" + struct.pack("<I", 29) + struct.pack("<I", type_byte)
    with open(path, "wb") as handle:
        handle.write(header)


ITEMS_ECF = """{ +Item Id: 1, Name: PulseRifle
  Category: Weapons/Items
  StackSize: 1
}
{ +Item Id: 2, Name: AdrenalineShot
  Category: Medical
  StackSize: 10
}
{ +Item Id: 3, Name: IronOre
  Category: Ingredients
  StackSize: 100
}
"""


def build_library_download(tmp_path):
    folder = os.path.join(file_store.SERVER_FILES_DIR, "Ascension-Reborn")
    write(os.path.join(folder, "_manifest.json"), json.dumps({"files": {}, "scenario": "Ascension-Reborn"}))
    write(os.path.join(folder, "save", "Content", "Configuration", "ItemsConfig.ecf"), ITEMS_ECF)
    write(os.path.join(folder, "scenario", "Content", "Extras", "Localization.csv"),
          "KEY,English\nPulseRifle,Pulse Rifle\nIronOre,Iron Ore\n")
    write_epb(os.path.join(folder, "scenario", "Prefabs", "BA_Outpost.epb"), 2)
    write_epb(os.path.join(folder, "scenario", "Prefabs", "RCV_Freighter.epb"), 8)
    write_epb(os.path.join(folder, "scenario", "Prefabs", "Eden_SVO_Beacon1.epb"), 4)
    write_epb(os.path.join(folder, "scenario", "Prefabs", "HV_Speeder.epb"), 16)
    write_epb(os.path.join(folder, "scenario", "Prefabs", "ATL_Statue4.epb"), 2)
    return folder


def visible_names(page):
    return [tile.item["name"] for tile in page.tile_area.visible_tiles]


def click_category(page, text):
    for btn in page.filter_buttons:
        if btn.text() == text:
            btn.click()
            return
    raise AssertionError("No category button named " + text)


def set_filter_checks(page, names):
    wanted = set(names)
    for text, action in page.filter_actions.items():
        action.setChecked(text in wanted)

# endregion


# region Tests

def test_nothing_shows_until_a_category_is_clicked(tmp_path, qapp):
    build_library_download(tmp_path)
    page = LibraryPage()
    assert {item["name"] for item in page.items} == {"PulseRifle", "AdrenalineShot", "IronOre"}
    assert visible_names(page) == []
    assert page.lbl_grid_empty.text() == "Choose a Category"
    page.show()
    page.resize(1280, 800)
    qapp.processEvents()
    assert page.lbl_grid_empty.isVisible()
    assert page.lbl_grid_empty.alignment() == Qt.AlignmentFlag.AlignCenter
    grid_box: Any = page.lbl_grid_empty.parent()
    margins = grid_box.layout().contentsMargins()
    inner_h = grid_box.height() - margins.top() - margins.bottom()
    assert page.lbl_grid_empty.height() >= inner_h - 8
    empty_center = page.lbl_grid_empty.geometry().center()
    assert abs(empty_center.x() - grid_box.rect().center().x()) <= 16
    assert abs(empty_center.y() - grid_box.rect().center().y()) <= 16
    page.hide()
    click_category(page, "WEAPONS")
    assert visible_names(page) == ["PulseRifle"]
    click_category(page, "ORES")
    assert visible_names(page) == ["IronOre"]
    page.deleteLater()


def test_filter_menu_is_the_only_way_to_pick_more_than_one(tmp_path, qapp):
    build_library_download(tmp_path)
    page = LibraryPage()
    click_category(page, "WEAPONS")
    set_filter_checks(page, ["WEAPONS", "MEDICAL"])
    assert set(visible_names(page)) == {"PulseRifle", "AdrenalineShot"}
    lit_buttons = [btn.text() for btn in page.filter_buttons if btn.isChecked()]
    assert lit_buttons == []
    page.txt_search.setText("pulse")
    assert visible_names(page) == ["PulseRifle"]
    page.deleteLater()


def test_blueprints_load_and_poi_filter(tmp_path, qapp):
    build_library_download(tmp_path)
    page = LibraryPage(start_tab="blueprints")
    assert TAB_FILTERS["blueprints"] == ["BA", "CV", "SV", "HV", "POI"]
    assert [btn.text() for btn in page.filter_buttons] == ["BA", "CV", "SV", "HV", "POI"]
    assert page.btn_multi_filter is not None and page.btn_multi_filter.text() == "FILTER"
    by_name = {item["name"]: item for item in page.blueprints}
    assert by_name["BA_Outpost"]["filter_group"] == "BA"
    assert by_name["RCV_Freighter"]["filter_group"] == "CV"
    assert by_name["Eden_SVO_Beacon1"]["filter_group"] == "SV"
    assert by_name["HV_Speeder"]["filter_group"] == "HV"
    assert by_name["ATL_Statue4"]["filter_group"] == "POI"
    assert visible_names(page) == []
    click_category(page, "POI")
    assert visible_names(page) == ["ATL_Statue4"]
    click_category(page, "BA")
    assert visible_names(page) == ["BA_Outpost"]
    set_filter_checks(page, ["BA", "CV"])
    assert set(visible_names(page)) == {"BA_Outpost", "RCV_Freighter"}
    page.deleteLater()


def test_switching_tabs_removes_old_category_buttons(tmp_path, qapp):
    build_library_download(tmp_path)
    page = LibraryPage()
    assert [btn.text() for btn in page.filter_buttons] == TAB_FILTERS["items"]
    page._on_tab_clicked("blueprints")
    assert [btn.text() for btn in page.filter_buttons] == ["BA", "CV", "SV", "HV", "POI"]
    row_texts = []
    for index in range(page.filter_row.count()):
        widget: Any = page.filter_row.itemAt(index).widget()
        if widget is not None:
            row_texts.append(widget.text())
    assert row_texts == ["BA", "CV", "SV", "HV", "POI", "FILTER"]
    page.deleteLater()


def test_empty_download_still_tells_you_to_download(qapp):
    page = LibraryPage()
    assert page.items == [] and page.blueprints == []
    assert page.lbl_grid_empty.text() == local_files.NO_FILES_TEXT
    page.deleteLater()

# endregion
