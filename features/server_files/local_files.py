## =====================================================================
## MODULE: features/server_files/local_files.py
## DESCRIPTION: Finds things inside the downloaded server files on this PC, for the Library and the editors.
## Everything here only reads data/server_files/<scenario>/; it never reads the local base game and never
## changes a file. The scenario folder is the one the last download went to (app_settings), so it works
## with whatever scenario name the server reported (for example "Default Multiplayer" or "Ascension-Reborn").
## Layout (made by the download):
##   data/server_files/<scenario>/scenario/<path on the server>
##   data/server_files/<scenario>/save/<path on the server>
## When the same path exists in both, the save copy wins, because the running game uses the save's copy.
## =====================================================================

# region Imports

import os

## file_store is imported as a module so SERVER_FILES_DIR is read at call time (tests point it at a temp folder).
from features.server_files import file_store
from features.server_files.file_store import MANIFEST_NAME, ROOT_NAMES
from features.settings.app_settings import load_app_settings

# endregion


# region Constants

## Text every page shows when nothing has been downloaded yet.
NO_FILES_TEXT = "No server files yet. Use Settings > DOWNLOAD SERVER FILES."

## Where the game keeps item pictures, relative to the scenario (or save) root. Named <ItemName>.jpg or .png.
IMAGES_FOLDER = ("SharedData", "Content", "Images")
IMAGE_TYPES = (".jpg", ".png")

## The items file and its English names, relative to a root.
ITEMS_FILE = ("Content", "Configuration", "ItemsConfig.ecf")
NAMES_FILE = ("Content", "Extras", "Localization.csv")

## Folder names inside a scenario folder that are ZAH's own (never server files).
OWN_FOLDERS = ("_edits", "_backups")

## The save root first, so its copy wins over the scenario's.
ROOT_ORDER = ("save", "scenario")

# endregion


# region Scenario Folder

## Returns the local folder of the downloaded scenario, or None when nothing has been downloaded.
## The folder saved by the last download is used when it is still inside data/server_files.
## Otherwise the newest folder there that has a manifest is used (fail closed: None if there is none).
def current_scenario_folder():
    try:
        saved = load_app_settings().get("server_files_local_folder", "")
        base_full = os.path.abspath(file_store.SERVER_FILES_DIR)
        if saved:
            saved_full = os.path.abspath(saved)
            if os.path.dirname(saved_full) == base_full and _has_downloaded_files(saved_full):
                return saved_full
        if not os.path.isdir(base_full):
            return None
        candidates = []
        for name in os.listdir(base_full):
            folder = os.path.join(base_full, name)
            if _has_downloaded_files(folder):
                candidates.append((os.path.getmtime(os.path.join(folder, MANIFEST_NAME)), folder))
        if not candidates:
            return None
        candidates.sort()
        return candidates[-1][1]
    except Exception as e:
        print(f"[ERROR] LocalServerFiles: Could not find the downloaded scenario folder: {e}")
        return None


## True when the folder has a manifest and at least one root sub-folder from a download.
def _has_downloaded_files(folder):
    if not os.path.isfile(os.path.join(folder, MANIFEST_NAME)):
        return False
    return any(os.path.isdir(os.path.join(folder, root)) for root in ROOT_NAMES)


## Name shown to people: the scenario folder's name, or "" when there is none.
def scenario_label(folder):
    return os.path.basename(folder) if folder else ""

# endregion


# region Finding Files

## Full local path of one server file by its parts, e.g. ("Content", "Configuration", "ItemsConfig.ecf").
## Checks the save copy first, then the scenario copy. Returns (root, full path) or (None, None).
def find_file(folder, parts):
    if not folder:
        return None, None
    for root in ROOT_ORDER:
        full_path = os.path.join(folder, root, *parts)
        if os.path.isfile(full_path):
            return root, full_path
    return None, None


## Every downloaded file whose type is in extensions (and, if given, whose path starts with one of
## the folders in under). Each entry: {"root", "path" (server path with /), "full", "label"}.
## A file found in both roots is listed once, as the save copy.
def list_files(folder, extensions, under=None):
    found = {}
    if not folder:
        return []
    wanted_types = tuple(ext.lower() for ext in extensions)
    for root in ROOT_ORDER:
        root_folder = os.path.join(folder, root)
        if not os.path.isdir(root_folder):
            continue
        for dir_path, dir_names, file_names in os.walk(root_folder):

            ## Sorting keeps the order the same every time. Half-finished .part downloads never match a file type.
            dir_names.sort()
            for file_name in sorted(file_names):
                if not file_name.lower().endswith(wanted_types):
                    continue
                full_path = os.path.join(dir_path, file_name)
                server_path = os.path.relpath(full_path, root_folder).replace(os.sep, "/")
                if under and not any(server_path.lower().startswith(prefix.lower() + "/") for prefix in under):
                    continue
                if server_path.lower() in found:
                    continue
                found[server_path.lower()] = {
                    "root": root,
                    "path": server_path,
                    "full": full_path,
                    "label": server_path.split("/")[-1] + "  (" + root + ")",
                }
    return sorted(found.values(), key=lambda entry: entry["path"].lower())


## Full path of an item's picture (<ItemName>.jpg, then .png), or None so the drawn hex is used.
## Only the downloaded Images folder is searched; the local base game is never looked at.
def find_item_image(folder, item_name, image_index=None):
    if not folder or not item_name:
        return None
    if image_index is None:
        image_index = build_image_index(folder)
    return image_index.get(str(item_name).lower())


## {lower-case item name: full path} for every picture in the downloaded Images folders.
## Built once per load, so a Library with thousands of items does not check the disk per item.
## The save copy wins over the scenario copy; .jpg wins over .png.
def build_image_index(folder):
    image_index = {}
    if not folder:
        return image_index
    for root in ROOT_ORDER:
        images_folder = os.path.join(folder, root, *IMAGES_FOLDER)
        if not os.path.isdir(images_folder):
            continue
        try:
            names = sorted(os.listdir(images_folder), key=lambda name: (os.path.splitext(name)[1].lower() != ".jpg", name))
        except OSError:
            continue
        for file_name in names:
            stem, extension = os.path.splitext(file_name)
            if extension.lower() in IMAGE_TYPES and stem.lower() not in image_index:
                image_index[stem.lower()] = os.path.join(images_folder, file_name)
    return image_index

# endregion
