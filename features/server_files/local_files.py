## =====================================================================
## MODULE: features/server_files/local_files.py
## DESCRIPTION: Finds things inside the downloaded server files on this PC, for the Library and the editors.
## Everything here only reads data/server_files/<scenario>/; it never reads the local base game, never
## changes a file, and never mixes files from another downloaded scenario. The folder is the Settings
## scenario choice for the active server when that download exists, otherwise the last download
## (app_settings), otherwise the newest manifest.
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
## SharedData/Content/Images holds mostly UI and PDA jpgs. The item pngs live in Bundles/ItemIcons.
IMAGES_FOLDER = ("SharedData", "Content", "Images")
IMAGES_FOLDERS = (
    IMAGES_FOLDER,
    ("SharedData", "Content", "Bundles", "ItemIcons"),
)
IMAGE_TYPES = (".jpg", ".jpeg", ".png")

## The items file and its English names, relative to a root.
ITEMS_FILE = ("Content", "Configuration", "ItemsConfig.ecf")
BLOCKS_FILE = ("Content", "Configuration", "BlocksConfig.ecf")
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
        base_full = os.path.abspath(file_store.SERVER_FILES_DIR)
        selected = _selected_scenario_folder(base_full)
        if selected:
            return selected
        saved = load_app_settings().get("server_files_local_folder", "")
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


## The Settings scenario choice for the active server, if that download is still on this PC.
def _selected_scenario_folder(base_full):
    try:
        from features.bridge.server_settings import get_active_profile
        from features.server_files.download_settings import load_server_download_settings
        profile = get_active_profile()
        name = profile.get("server_name") if isinstance(profile, dict) else None
        if not name:
            return None
        chosen = load_server_download_settings(name).get("scenario")
        if not chosen:
            return None
        folder = os.path.abspath(file_store.scenario_folder(chosen))
        if os.path.dirname(folder) == base_full and _has_downloaded_files(folder):
            return folder
    except Exception:
        return None
    return None

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
## The item Name is tried first, then CustomIcon when the name has no file.
## Only the downloaded Images and ItemIcons folders are searched; the local base game is never looked at.
def find_item_image(folder, item_name, image_index=None, custom_icon=None):
    if not folder or not (item_name or custom_icon):
        return None
    if image_index is None:
        image_index = build_image_index(folder)
    if item_name:
        path = image_index.get(str(item_name).lower())
        if path:
            return path
    if custom_icon:
        return image_index.get(str(custom_icon).lower())
    return None


## {lower-case file stem: full path} for every picture in the downloaded Images and ItemIcons folders.
## Built once per load, so a Library with thousands of items does not check the disk per item.
## The save copy wins over the scenario copy; Images wins over ItemIcons; .jpg / .jpeg wins over .png.
def build_image_index(folder):
    image_index = {}
    if not folder:
        return image_index
    for root in ROOT_ORDER:
        for relative in IMAGES_FOLDERS:
            images_folder = os.path.join(folder, root, *relative)
            if not os.path.isdir(images_folder):
                continue
            try:
                names = sorted(
                    os.listdir(images_folder),
                    key=lambda name: (os.path.splitext(name)[1].lower() not in (".jpg", ".jpeg"), name),
                )
            except OSError:
                continue
            for file_name in names:
                stem, extension = os.path.splitext(file_name)
                if extension.lower() in IMAGE_TYPES and stem.lower() not in image_index:
                    image_index[stem.lower()] = os.path.join(images_folder, file_name)
    return image_index


## {item or block id: block dict} from BlocksConfig.ecf in this scenario folder only (save copy first).
def load_block_index(folder):
    block_index = {}
    root, path = find_file(folder, BLOCKS_FILE)
    if path is None:
        return block_index
    try:
        from features.shared.ecf_parser import parse_ecf_blocks, resolve_refs
        with open(path, encoding="utf-8", errors="replace") as handle:
            blocks = resolve_refs(parse_ecf_blocks(handle.read()))
    except Exception as e:
        print(f"[ERROR] LocalServerFiles: Could not read BlocksConfig.ecf: {e}")
        return block_index
    for block in blocks:
        if block.get("type") != "Block":
            continue
        block_id = str((block.get("header") or {}).get("Id") or "").strip()
        if not block_id.isdigit():
            continue
        props = block.get("props") or {}
        def _val(key):
            prop = props.get(key)
            return prop.get("value") if prop else ""
        block_index[block_id] = {
            "id": block_id,
            "name": (block.get("header") or {}).get("Name", ""),
            "class": _val("Class"),
            "force_max_count": _val("ForceMaxCount"),
            "can_pickup": _val("CanPickup"),
            "root": root,
        }
    return block_index


def block_is_giveable(block):
    """False for cores and ForceMaxCount blocks, which Request_Player_AddItem will not put in an inventory."""
    if not block:
        return False
    if str(block.get("class") or "").strip().lower() == "core":
        return False
    if str(block.get("force_max_count") or "").strip().lower() in ("true", "1", "yes"):
        return False
    return True


## None when GIVE ITEM may send this ID. Otherwise a short reason for the button tooltip.
def item_give_reason(item, block_index):
    if not item:
        return "Pick an item first."
    item_id = str(item.get("id") or "").strip()
    if not item_id.isdigit():
        return "Pick an item first."
    block = (block_index or {}).get(item_id)
    if not block:
        return None
    item_name = item.get("display_name") or item.get("name") or "that item"
    block_name = block.get("name") or "a block"
    if not block_is_giveable(block):
        return ("ID " + item_id + " is the block " + block_name
                + " in this scenario, not " + item_name
                + ". The game will not add it to an inventory.")
    return None


## Extra tooltip when the ID is also a giveable block (the game may add the block, not the item).
def item_give_warning(item, block_index):
    if not item:
        return ""
    item_id = str(item.get("id") or "").strip()
    block = (block_index or {}).get(item_id)
    if not block or not block_is_giveable(block):
        return ""
    block_name = block.get("name") or "a block"
    return ("ID " + item_id + " is also the block " + block_name
            + " in this scenario. The game may add that block.")

# endregion
