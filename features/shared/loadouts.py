## =====================================================================
## MODULE: features/shared/loadouts.py
## DESCRIPTION: Loadout templates (STARTER, EXPLORER, BUILDER) kept on this PC in data/loadout_templates.json.
## The Library's ADD TO TEMPLATE puts the picked item in a template; the Players page gives a whole template
## to a player through the Safety Flow (one Request_Player_AddItem per item). data/ is git-ignored.
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

# endregion


# region Load and Save

## Every template, with any missing one added as an empty list. A broken file gives empty templates.
def load_templates():
    templates = {name: [] for name in TEMPLATE_NAMES}
    try:
        with open(TEMPLATES_FILE, encoding="utf-8") as file_handle:
            saved = json.load(file_handle)
        for name in TEMPLATE_NAMES:
            rows = saved.get(name) if isinstance(saved, dict) else None
            if isinstance(rows, list):
                templates[name] = [row for row in rows if isinstance(row, dict) and isinstance(row.get("id"), int)
                                   and isinstance(row.get("count"), int) and row["count"] > 0]
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


## Adds count of one item to a template (an item already in it gets the count added). Returns the template.
def add_to_template(template_name, item_id, item_name, count):
    if template_name not in TEMPLATE_NAMES or not isinstance(item_id, int) or int(count) <= 0:
        raise ValueError("bad template, item or count")
    templates = load_templates()
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
