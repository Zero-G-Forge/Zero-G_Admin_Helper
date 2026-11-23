## =====================================================================
## MODULE: features/shared/loadouts.py
## DESCRIPTION: Loadout templates (STARTER, EXPLORER, BUILDER, plus any custom
## item packs built with BUILD ITEM TEMPLATE) kept on this PC in data/loadout_templates.json.
## The Library's ADD TO TEMPLATE puts the picked item in a template; BUILD ITEM TEMPLATE
## names a new pack and fills it from the Library item grid. The Players page gives a whole
## template or custom pack to a player through the Safety Flow (one Request_Player_AddItem
## per item). data/ is git-ignored.
## =====================================================================

# region Imports

import json
import os

from features.paths import DATA_DIR

# endregion


# region Constants

## Where the templates are saved.
TEMPLATES_FILE = os.path.join(DATA_DIR, "loadout_templates.json")

## The three templates in the mockups. Each one is a list of {"id", "name", "count"}.
TEMPLATE_NAMES = ["STARTER", "EXPLORER", "BUILDER"]

## Longest allowed pack name after trim and upper-case.
MAX_PACK_NAME_LEN = 32

# endregion


# region Load and Save

## Rows that have a whole-number id and a count of 1 or more.
def valid_rows(rows):
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and isinstance(row.get("id"), int)
            and isinstance(row.get("count"), int) and row["count"] > 0]


## Trimmed, upper-cased pack name, or ValueError when it is empty or too long.
def normalize_pack_name(name):
    if not isinstance(name, str):
        raise ValueError("bad pack name")
    cleaned = name.strip().upper()
    if not cleaned or len(cleaned) > MAX_PACK_NAME_LEN:
        raise ValueError("bad pack name")
    return cleaned


## Default names first, then any custom pack names in A-Z order.
def list_template_names(templates=None):
    if templates is None:
        templates = load_templates()
    custom = [name for name in templates if name not in TEMPLATE_NAMES]
    custom.sort()
    return list(TEMPLATE_NAMES) + custom


## Every template, with the three defaults always present. A broken file gives empty defaults.
## Custom packs from the file are kept when their name is valid.
def load_templates():
    templates = {name: [] for name in TEMPLATE_NAMES}
    try:
        with open(TEMPLATES_FILE, encoding="utf-8") as file_handle:
            saved = json.load(file_handle)
        for name in TEMPLATE_NAMES:
            rows = saved.get(name) if isinstance(saved, dict) else None
            if isinstance(rows, list):
                templates[name] = valid_rows(rows)
        if isinstance(saved, dict):
            for name, rows in saved.items():
                if name in TEMPLATE_NAMES:
                    continue
                try:
                    cleaned = normalize_pack_name(name)
                except ValueError:
                    continue
                if cleaned in TEMPLATE_NAMES or not isinstance(rows, list):
                    continue
                templates[cleaned] = valid_rows(rows)
    except (OSError, ValueError):
        pass
    return templates


## Writes all templates (a .part file first, then one rename, so a crash never leaves half a file).
def save_templates(templates):
    os.makedirs(os.path.dirname(TEMPLATES_FILE), exist_ok=True)
    part = TEMPLATES_FILE + ".part"
    with open(part, "w", encoding="utf-8") as file_handle:
        json.dump(templates, file_handle, indent=2)
    os.replace(part, TEMPLATES_FILE)


## Replaces one pack (default or custom) with the given rows. The name is trimmed and upper-cased.
def save_pack(name, rows):
    cleaned = normalize_pack_name(name)
    if not isinstance(rows, list):
        raise ValueError("bad pack rows")
    stored = []
    for row in rows:
        if not (isinstance(row, dict) and isinstance(row.get("id"), int)
                and isinstance(row.get("count"), int) and row["count"] > 0):
            raise ValueError("bad pack rows")
        stored.append({"id": int(row["id"]), "name": str(row.get("name", "")), "count": int(row["count"])})
    templates = load_templates()
    templates[cleaned] = stored
    save_templates(templates)
    return stored


## Adds count of one item to a template (an item already in it gets the count added). Returns the template.
def add_to_template(template_name, item_id, item_name, count):
    templates = load_templates()
    if template_name not in templates or not isinstance(item_id, int) or int(count) <= 0:
        raise ValueError("bad template, item or count")
    rows = templates[template_name]
    for row in rows:
        if row["id"] == item_id:
            row["count"] += int(count)
            break
    else:
        rows.append({"id": item_id, "name": str(item_name), "count": int(count)})
    save_templates(templates)
    return rows

# endregion
