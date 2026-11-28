## =====================================================================
## TEST: tests/test_local_files.py
## DESCRIPTION: Checks that the Library, ECF Editor and PDA Editor read the DOWNLOADED server files
## (data/server_files/<scenario>/), whatever the scenario is called, and show the empty-state text
## when nothing is downloaded. Item pictures: Images then Bundles/ItemIcons, <ItemName> then CustomIcon,
## .jpg then .png, else the drawn hex.
## Run from the app root:  QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q
## Everything happens in a temporary folder; the real data/ folder is never touched.
## =====================================================================

# region Imports

import json
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from features.server_files import file_store, local_files
from features.settings import app_settings

# endregion


# region Helpers

ITEMS_ECF = """{ +Item Id: 1, Name: Flashlight
  Category: Devices
  StackSize: 1
}
{ +Item Id: 2, Name: AdrenalineShot
  Category: Medical
  StackSize: 10
}
{ +Item Id: 3, Name: HiddenThing
  ShowUser: No
}
"""


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    ## Server files and app settings live in a temporary folder for every test.
    monkeypatch.setattr(file_store, "SERVER_FILES_DIR", str(tmp_path / "server_files"))
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", str(tmp_path / "app_settings.json"))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def write_picture(path, color):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(color)
    assert image.save(path)


## A downloaded scenario named like the live one, with a save copy that must win over the scenario copy.
def build_download(tmp_path, scenario_name="Default Multiplayer"):
    folder = os.path.join(file_store.SERVER_FILES_DIR, scenario_name)
    write(os.path.join(folder, "_manifest.json"), json.dumps({"files": {}, "scenario": scenario_name}))
    write(os.path.join(folder, "scenario", "Content", "Configuration", "ItemsConfig.ecf"), "{ +Item Id: 9, Name: Old\n}\n")
    write(os.path.join(folder, "save", "Content", "Configuration", "ItemsConfig.ecf"), ITEMS_ECF)
    write(os.path.join(folder, "scenario", "Content", "Extras", "Localization.csv"), "KEY,English\nFlashlight,Torch\n")
    write(os.path.join(folder, "scenario", "Content", "Configuration", "TraderNPCConfig.ecf"), "{ Trader Name: T\n}\n")
    write(os.path.join(folder, "save", "Content", "Configuration", "GalaxyConfig.ecf"), "{ Galaxy\n}\n")
    write(os.path.join(folder, "scenario", "SharedData", "Content", "Extras", "PDA", "PDA.yaml"), "Chapters:\n  - ChapterTitle: pda_1\n")
    write(os.path.join(folder, "scenario", "SharedData", "Content", "Extras", "PDA", "PDA.csv"), "KEY,English\npda_1,First Steps\n")
    write_picture(os.path.join(folder, "scenario", "SharedData", "Content", "Images", "AdrenalineShot.png"), 0xff0000)
    write_picture(os.path.join(folder, "scenario", "SharedData", "Content", "Images", "AdrenalineShot.jpg"), 0x00ff00)
    app_settings.save_app_setting("server_files_local_folder", folder)
    return folder

# endregion


# region Folder and File Lookups

def test_no_download_gives_none():
    assert local_files.current_scenario_folder() is None


def test_scenario_folder_follows_whatever_name_the_server_reported(tmp_path):
    folder = build_download(tmp_path, "Ascension-Reborn")
    assert local_files.current_scenario_folder() == os.path.abspath(folder)


def test_scenario_folder_found_without_the_setting(tmp_path):
    folder = build_download(tmp_path)
    app_settings.save_app_setting("server_files_local_folder", "")
    assert local_files.current_scenario_folder() == os.path.abspath(folder)


def test_setting_outside_server_files_is_ignored(tmp_path):
    build_download(tmp_path)
    app_settings.save_app_setting("server_files_local_folder", str(tmp_path))
    assert local_files.current_scenario_folder().endswith("Default Multiplayer")


def test_save_copy_wins(tmp_path):
    folder = build_download(tmp_path)
    root, path = local_files.find_file(folder, local_files.ITEMS_FILE)
    assert root == "save" and path.endswith(os.path.join("save", "Content", "Configuration", "ItemsConfig.ecf"))


def test_list_files_both_roots_and_folder_filter(tmp_path):
    folder = build_download(tmp_path)
    ecf_paths = [(entry["root"], entry["path"]) for entry in local_files.list_files(folder, (".ecf",))]
    assert ("save", "Content/Configuration/ItemsConfig.ecf") in ecf_paths
    assert ("scenario", "Content/Configuration/ItemsConfig.ecf") not in ecf_paths
    assert ("save", "Content/Configuration/GalaxyConfig.ecf") in ecf_paths
    pda = local_files.list_files(folder, (".yaml", ".csv"), under=("SharedData/Content/Extras/PDA",))
    assert [entry["path"].split("/")[-1] for entry in pda] == ["PDA.csv", "PDA.yaml"]


def test_image_index_prefers_jpg_and_is_case_blind(tmp_path):
    folder = build_download(tmp_path)
    assert local_files.find_item_image(folder, "adrenalineshot").endswith("AdrenalineShot.jpg")
    assert local_files.find_item_image(folder, "Flashlight") is None
    assert local_files.find_item_image(None, "Flashlight") is None


def test_image_index_reads_itemicons_when_images_has_no_match(tmp_path):
    folder = build_download(tmp_path)
    write_picture(os.path.join(folder, "scenario", "SharedData", "Content", "Bundles", "ItemIcons", "Flashlight.png"), 0x0000ff)
    write_picture(os.path.join(folder, "scenario", "SharedData", "Content", "Bundles", "ItemIcons", "AdrenalineShot.png"), 0xffffff)
    assert local_files.find_item_image(folder, "Flashlight").endswith(os.path.join("ItemIcons", "Flashlight.png"))
    ## Images already has AdrenalineShot.jpg, so that copy still wins over the ItemIcons png.
    assert local_files.find_item_image(folder, "AdrenalineShot").endswith("AdrenalineShot.jpg")


def test_find_item_image_falls_back_to_custom_icon(tmp_path):
    folder = build_download(tmp_path)
    write_picture(os.path.join(folder, "scenario", "SharedData", "Content", "Bundles", "ItemIcons", "ZeroAkua.png"), 0x00ffff)
    assert local_files.find_item_image(folder, "AkuaWine", custom_icon="ZeroAkua").endswith("ZeroAkua.png")
    assert local_files.find_item_image(folder, "AkuaWine") is None

# endregion


# region Pages

def test_library_reads_download_with_pictures(tmp_path, qapp):
    from features.library.library_page import LibraryPage
    build_download(tmp_path)
    page = LibraryPage()
    names = {item["name"]: item for item in page.items}
    assert set(names) == {"Flashlight", "AdrenalineShot"}
    assert names["Flashlight"]["display_name"] == "Torch"
    assert names["AdrenalineShot"]["image_path"].endswith("AdrenalineShot.jpg")
    assert names["Flashlight"]["image_path"] is None
    page._on_tile_picked(names["AdrenalineShot"])
    assert not page.lbl_detail_picture.pixmap().isNull()
    page.deleteLater()


def test_library_uses_custom_icon_and_itemicons(tmp_path, qapp):
    from features.library.library_page import LibraryPage
    folder = build_download(tmp_path)
    write(
        os.path.join(folder, "save", "Content", "Configuration", "ItemsConfig.ecf"),
        ITEMS_ECF + "{ +Item Id: 4, Name: AkuaWine\n  Category: Food\n  CustomIcon: ZeroAkua\n  StackSize: 5\n}\n",
    )
    write_picture(os.path.join(folder, "scenario", "SharedData", "Content", "Bundles", "ItemIcons", "Flashlight.png"), 0x0000ff)
    write_picture(os.path.join(folder, "scenario", "SharedData", "Content", "Bundles", "ItemIcons", "ZeroAkua.png"), 0x00ffff)
    page = LibraryPage()
    names = {item["name"]: item for item in page.items}
    assert names["Flashlight"]["image_path"].endswith(os.path.join("ItemIcons", "Flashlight.png"))
    assert names["AkuaWine"]["image_path"].endswith("ZeroAkua.png")
    assert names["AdrenalineShot"]["image_path"].endswith("AdrenalineShot.jpg")
    page.deleteLater()


def test_library_empty_state(qapp):
    from features.library.library_page import LibraryPage
    page = LibraryPage()
    assert page.items == []
    assert page.lbl_grid_empty.text() == local_files.NO_FILES_TEXT
    page.deleteLater()


def test_ecf_editor_lists_and_opens_downloaded_files(tmp_path, qapp):
    from features.ecf_editor.ecf_editor_page import EcfEditorPage
    build_download(tmp_path)
    page = EcfEditorPage()
    labels = [page.cmb_file.itemText(row) for row in range(page.cmb_file.count())]
    assert "ItemsConfig.ecf  (save)" in labels and "TraderNPCConfig.ecf  (scenario)" in labels
    page.cmb_file.setCurrentIndex(labels.index("ItemsConfig.ecf  (save)"))
    assert page.code_editor.toPlainText() == ITEMS_ECF
    assert page.current_entry["root"] == "save" and page.original_text == ITEMS_ECF
    page.deleteLater()


def test_ecf_editor_empty_state(qapp):
    from features.ecf_editor.ecf_editor_page import EcfEditorPage
    page = EcfEditorPage()
    assert page.cmb_file.count() == 0 and not page.cmb_file.isEnabled()
    assert page.code_editor.placeholderText() == local_files.NO_FILES_TEXT
    page.deleteLater()


def test_pda_editor_reads_download_and_chapter_names(tmp_path, qapp):
    from features.pda_editor.pda_editor_page import PdaEditorPage
    build_download(tmp_path)
    page = PdaEditorPage()
    labels = [page.cmb_file.itemText(row) for row in range(page.cmb_file.count())]
    page.cmb_file.setCurrentIndex(labels.index("PDA.yaml  (scenario)"))
    assert page.lst_chapters.count() == 1 and page.lst_chapters.item(0).text() == "First Steps"
    page.deleteLater()


def test_pda_editor_empty_state(qapp):
    from features.pda_editor.pda_editor_page import PdaEditorPage
    page = PdaEditorPage()
    assert page.cmb_file.count() == 0
    assert page.code_editor.placeholderText() == local_files.NO_FILES_TEXT
    page.deleteLater()


def test_library_uses_only_the_selected_scenario_and_blocks_ungiveable_ids(tmp_path, monkeypatch):
    from features.bridge import server_settings
    from features.library.item_library import load_items
    from features.server_files import download_settings

    default_folder = build_download(tmp_path, "Default Multiplayer")
    write(os.path.join(default_folder, "save", "Content", "Configuration", "ItemsConfig.ecf"),
          "{ +Item Id: 99, Name: OnlyInDefault\n  Category: Food\n}\n")
    chosen_folder = build_download(tmp_path, "Ascension-Reborn")
    write(os.path.join(chosen_folder, "save", "Content", "Configuration", "ItemsConfig.ecf"),
          "{ +Item Id: 1402, Name: AlienCookie, Ref: FoodTemplate\n  Category: Food\n}\n"
          "{ +Item Id: 1617, Name: Soup, Ref: FoodTemplate\n  Category: Food\n}\n"
          "{ +Item Id: 88, Name: OnlyInAscension\n  Category: Devices\n}\n")
    write(os.path.join(chosen_folder, "scenario", "Content", "Configuration", "BlocksConfig.ecf"),
          "{ +Block Id: 1402, Name: CoreNoCPU, Ref: Core\n  Class: Core\n  ForceMaxCount: true\n}\n"
          "{ +Block Id: 1617, Name: ModularWingLongL\n  Category: BuildingBlocks\n}\n")
    ## Last download points at Default Multiplayer; Settings still says Ascension-Reborn.
    app_settings.save_app_setting("server_files_local_folder", default_folder)
    monkeypatch.setattr(server_settings, "get_active_profile", lambda: {"server_name": "Zero-G Forge Reborn"})
    monkeypatch.setattr(download_settings, "load_server_download_settings",
                        lambda name: {"scenario": "Ascension-Reborn"})
    folder = local_files.current_scenario_folder()
    assert os.path.abspath(folder) == os.path.abspath(chosen_folder)  # pyright: ignore[reportArgumentType, reportCallIssue]
    root, items_path = local_files.find_file(folder, local_files.ITEMS_FILE)
    text = open(items_path, encoding="utf-8").read()  # pyright: ignore[reportArgumentType]
    assert "OnlyInAscension" in text and "OnlyInDefault" not in text
    items = load_items(None, items_path=items_path, names_path="")
    names = {item["name"] for item in items}
    assert names == {"AlienCookie", "Soup", "OnlyInAscension"}
    blocks = local_files.load_block_index(folder)
    cookie_reason = local_files.item_give_reason({"id": "1402", "name": "AlienCookie", "display_name": "Alien Cookie"}, blocks)
    assert cookie_reason and "CoreNoCPU" in cookie_reason and "Alien Cookie" in cookie_reason
    assert local_files.item_give_reason({"id": "88", "name": "OnlyInAscension", "display_name": "Only In Ascension"}, blocks) is None
    assert local_files.item_give_reason({"id": "1617", "name": "Soup", "display_name": "Soup"}, blocks) is None
    warning = local_files.item_give_warning({"id": "1617", "name": "Soup", "display_name": "Soup"}, blocks)
    assert "ModularWingLongL" in warning

# endregion
