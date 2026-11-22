## ==========================================
## ZERO-G ADMIN HELPER - ITEM LIBRARY DATA
## Builds the list of items for the Library page from a game Content folder:
##   Content/Configuration/ItemsConfig.ecf   -> ids, categories, stats (with Ref templates filled in)
##   Content/Extras/Localization.csv          -> readable English names
## Read-only: nothing on disk or on a server is changed.
## ==========================================

# region Imports

import os

from features.shared.ecf_parser import parse_ecf_blocks, resolve_refs, read_english_names

# endregion


# region Constants

## Filter button each item falls under. Items that fit none still show when no filter is picked.
FILTER_ORDER = ["WEAPONS", "ARMOR", "MEDICAL", "AMMO", "COMPONENTS", "ORES", "DEVICES", "FOOD"]

# endregion


# region Loading

def _prop_value(item_block, key, default=""):
    """The value of one property, or default if the item doesn't have it."""
    prop = item_block["props"].get(key)
    return prop["value"] if prop else default


def _filter_group(item_name, category, ammo_names):
    """Which filter button an item belongs to, from its category and name."""
    lower_name = item_name.lower()
    if category == "Medical":
        return "MEDICAL"
    if item_name in ammo_names:
        return "AMMO"
    if "armor" in lower_name:
        return "ARMOR"
    if lower_name.endswith("ore"):
        return "ORES"
    if category == "Weapons/Items":
        return "WEAPONS"
    if category in ("Components", "Ingredients"):
        return "COMPONENTS"
    if category == "Devices":
        return "DEVICES"
    if category == "Food":
        return "FOOD"
    return ""


def load_items(content_folder):
    """Returns a list of item dicts sorted by name, or [] if ItemsConfig.ecf can't be read."""
    items_path = os.path.join(content_folder, "Configuration", "ItemsConfig.ecf")
    try:
        with open(items_path, encoding="utf-8", errors="replace") as items_file:
            file_text = items_file.read()
    except OSError as e:
        print(f"[ERROR] ItemLibrary: Could not read {items_path}: {e}")
        return []
    english_names = read_english_names(os.path.join(content_folder, "Extras", "Localization.csv"))
    item_blocks = [block for block in resolve_refs(parse_ecf_blocks(file_text)) if block["type"] == "Item"]

    ## Every name used as AmmoType by a weapon mode counts as ammo.
    ammo_names = set()
    for item_block in item_blocks:
        for child in item_block["children"]:
            ammo_prop = child["props"].get("AmmoType")
            if ammo_prop:
                ammo_names.add(ammo_prop["value"])
    items = []
    for item_block in item_blocks:

        ## ShowUser: No marks templates and hidden items players never see.
        if _prop_value(item_block, "ShowUser").lower() == "no":
            continue
        item_name = item_block["header"].get("Name", "")
        category = _prop_value(item_block, "Category").strip()
        items.append({
            "id": item_block["header"].get("Id", ""),
            "name": item_name,
            "display_name": english_names.get(item_name, item_name),
            "category": category,
            "stack_size": _prop_value(item_block, "StackSize", "--"),
            "filter_group": _filter_group(item_name, category, ammo_names),
            "ref": item_block["header"].get("Ref", ""),
            "props": item_block["props"],
            "children": item_block["children"],
            "own_keys": item_block.get("own_keys"),
        })
    items.sort(key=lambda item: item["display_name"].lower())
    return items

# endregion
