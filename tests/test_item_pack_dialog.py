## =====================================================================
## TEST: tests/test_item_pack_dialog.py
## DESCRIPTION: Offscreen checks for BUILD ITEM TEMPLATE: the Library button
## stays off until items are loaded, the pack window reuses the Library item
## grid (search, category buttons, FILTER, Choose a Category), only giveable
## items are listed, SAVE writes a custom pack, and the Players page can give
## that pack through the same player_loadout path. No real server is used.
## Run from the app root:  QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_item_pack_dialog.py -q
## =====================================================================

# region Imports

import os
import sys

import pytest
from PyQt6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.page_helpers import get_qapp, host, install, settle
from tests.test_library_filters import build_library_download, click_category, visible_names
from tests.test_server_actions import players_page
from features.library import library_page
from features.library.item_pack_dialog import ItemPackDialog
from features.shared import loadouts

# endregion


# region Fixtures

@pytest.fixture(scope="session")
def qapp():
    return get_qapp()


SAMPLE_ITEMS = [
    {"id": "101", "name": "PulseRifle", "display_name": "Pulse Rifle", "filter_group": "WEAPONS",
     "category": "Weapons/Items", "stack_size": "1"},
    {"id": "202", "name": "AdrenalineShot", "display_name": "Adrenaline Shot", "filter_group": "MEDICAL",
     "category": "Medical", "stack_size": "10"},
    {"id": "303", "name": "IronOre", "display_name": "Iron Ore", "filter_group": "ORES",
     "category": "Ingredients", "stack_size": "100"},
]

# endregion


# region Tests

def test_item_pack_dialog_grid_and_save(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(loadouts, "TEMPLATES_FILE", str(tmp_path / "templates.json"))
    dialog = ItemPackDialog(SAMPLE_ITEMS)
    assert [btn.text() for btn in dialog.item_browser.filter_buttons] == [
        "WEAPONS", "ARMOR", "MEDICAL", "AMMO", "COMPONENTS", "ORES", "DEVICES", "FOOD",
    ]
    assert dialog.item_browser.btn_multi_filter is not None
    assert dialog.item_browser.btn_multi_filter.text() == "FILTER"
    assert visible_names(dialog.item_browser) == []
    assert dialog.item_browser.lbl_grid_empty.text() == "Choose a Category"
    dialog.show()
    dialog.resize(1280, 820)
    qapp.processEvents()
    assert dialog.item_browser.lbl_grid_empty.isVisible()
    click_category(dialog.item_browser, "WEAPONS")
    assert visible_names(dialog.item_browser) == ["PulseRifle"]
    dialog._on_tile_picked(SAMPLE_ITEMS[0])
    dialog.spn_quantity.setValue(2)
    dialog._on_add_clicked()
    dialog._on_tile_picked(SAMPLE_ITEMS[0])
    dialog.spn_quantity.setValue(3)
    dialog._on_add_clicked()
    assert dialog.pack_rows() == [{"id": 101, "name": "Pulse Rifle", "count": 5}]
    dialog.txt_name.setText("  raid kit ")
    dialog._on_save_clicked()
    assert dialog.result() == dialog.DialogCode.Accepted
    templates = loadouts.load_templates()
    assert templates["RAID KIT"] == [{"id": 101, "name": "Pulse Rifle", "count": 5}]
    dialog.deleteLater()


def test_build_item_template_button_needs_loaded_items(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(loadouts, "TEMPLATES_FILE", str(tmp_path / "templates.json"))
    monkeypatch.setattr(library_page.LibraryPage, "load_server_files", lambda self: None)
    install(monkeypatch, tmp_path)
    page = library_page.LibraryPage()
    cockpit = host(page, role="admin")
    settle(qapp)
    assert not page.btn_build_template.isEnabled()
    assert "Load items" in page.btn_build_template.toolTip()
    page.items = list(SAMPLE_ITEMS)
    page._refresh_give_buttons()
    assert page.btn_build_template.isEnabled()
    cockpit.close()


def test_library_uses_shared_item_browser_and_lists_custom_packs(qapp, tmp_path, monkeypatch):
    from features.server_files import file_store
    from features.settings import app_settings
    monkeypatch.setattr(file_store, "SERVER_FILES_DIR", str(tmp_path / "server_files"))
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", str(tmp_path / "app_settings.json"))
    monkeypatch.setattr(loadouts, "TEMPLATES_FILE", str(tmp_path / "templates.json"))
    build_library_download(tmp_path)
    loadouts.save_pack("RAID KIT", [{"id": 101, "name": "Pulse Rifle", "count": 1}])
    install(monkeypatch, tmp_path)
    page = library_page.LibraryPage()
    cockpit = host(page, role="admin")
    settle(qapp)
    assert page.item_browser is not None
    assert page.txt_search is page.item_browser.txt_search
    assert page.tile_area is page.item_browser.tile_area
    assert "RAID KIT   1 item(s)" in page.lbl_templates_empty.text()
    assert page.btn_build_template.isEnabled()
    cockpit.close()


def test_ungiveable_ids_are_left_out_of_the_pack_window(qapp, tmp_path, monkeypatch):
    from features.server_files.local_files import item_give_reason
    core = {"id": "1402", "name": "AlienCookie", "display_name": "Alien Cookie",
            "filter_group": "FOOD", "category": "Food", "stack_size": "10"}
    block_index = {"1402": {"id": "1402", "name": "CoreNoCPU", "class": "Core", "force_max_count": ""}}
    assert item_give_reason(core, block_index)
    giveable = [item for item in SAMPLE_ITEMS + [core] if not item_give_reason(item, block_index)]
    dialog = ItemPackDialog(giveable)
    names = {tile.item["name"] for tile in dialog.item_browser.tile_area.tiles}
    assert names == {"PulseRifle", "AdrenalineShot", "IronOre"}
    assert "AlienCookie" not in names
    dialog.deleteLater()


def test_players_give_pack_uses_the_same_loadout_path(qapp, monkeypatch, tmp_path):
    from features.shared import loadouts as loadouts_mod
    page, bridge = players_page(qapp, monkeypatch, tmp_path, "admin")
    assert not page.btn_give_pack.isEnabled()
    loadouts_mod.save_pack("RAID KIT", [{"id": 201, "name": "Rifle", "count": 1},
                                        {"id": 202, "name": "Ammo", "count": 20}])
    page._refresh_buttons()
    assert page.cmb_custom_pack.findData("RAID KIT") >= 0
    page.cmb_custom_pack.setCurrentIndex(page.cmb_custom_pack.findData("RAID KIT"))
    page._refresh_buttons()
    assert page.btn_give_pack.isEnabled()
    page._on_give_pack_clicked()
    settle(qapp)
    adds = [c for c in bridge.sent if c.startswith("api:Request_Player_AddItem")]
    assert adds == ['api:Request_Player_AddItem {"id":1001,"item":{"id":201,"count":1}}',
                    'api:Request_Player_AddItem {"id":1001,"item":{"id":202,"count":20}}']
    assert not any("CONFIRM" in str(preview) for preview in bridge.asked)

# endregion
