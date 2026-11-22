## ==========================================
## ZERO-G ADMIN HELPER - PAGE LOADER
## Loads one page module at a time when its nav button is clicked.
## If a page fails, an ErrorCard is shown instead and ZAH keeps running.
## ==========================================

# region Imports

import importlib
import traceback

from features.shared.error_card import ErrorCard

# endregion

# region Page Table

## `{ }` is a dictionary, which is a lookup table. The left side is the key (the nav button's name), and the right side is where that page's code lives.
## `"features.players.players_page"` is a path with dots instead of slashes. It means the file `features/players/players_page.py`.
## Every page follows the same pattern: a folder named after the page, with a `<name>_page.py` file inside. To add a page later, you just add one line here.

## Which module holds each page. The key matches NAV_PAGES in main_cockpit.py.
PAGE_MODULES = {
    "dashboard": "features.dashboard.dashboard_page",
    "chat": "features.chat.chat_page",
    "players": "features.players.players_page",
    "factions": "features.factions.factions_page",
    "structures": "features.structures.structures_page",
    "playfields": "features.playfields.playfields_page",
    "scheduler": "features.scheduler.scheduler_page",
    "zerogbridge": "features.zerogbridge.zerogbridge_page",
    "settings": "features.settings.settings_page",
    "alerts": "features.alerts.alerts_page",
    "bans_audit": "features.bans_audit.bans_audit_page",
    "users": "features.users.users_page",
    "ecf_editor": "features.ecf_editor.ecf_editor_page",
    "backups": "features.backups.backups_page",
    "bp_editor": "features.bp_editor.bp_editor_page",
    "items": "features.items.items_page",
}

# endregion


# region Page Loading

## Builds the page for one nav button.
## Returns the page widget, or an ErrorCard if anything goes wrong.
def load_page(page_key):
    ## try: attempt everything indented below. If any line fails, Python
    ## jumps to except: instead of crashing. This keeps ZAH alive.
    try:
        ## Look the page up in PAGE_MODULES. A key that isn't listed fails here too.
        module_path = PAGE_MODULES[page_key]

        ## Load the page file. reload() loads it fresh each time,
        ## so Retry picks up your fixes without restarting ZAH.
        page_module = importlib.import_module(module_path)
        importlib.reload(page_module)

        ## Rule for every page file: it must have create_page(),
        ## which builds and returns the page.
        page_widget = page_module.create_page()
        print(f"[INFO] PageLoader: Loaded {page_key}")
        return page_widget

    ## Catch the failure and call it "error".
    except Exception as error:
        print(f"[ERROR] PageLoader: {page_key} failed to load")
        ## Full error details in the terminal, so you can find the broken line.
        print(traceback.format_exc())
        ## Short version on the card, e.g. "ModuleNotFoundError: No module named ..."
        return ErrorCard(page_key, f"{type(error).__name__}: {error}")

# endregion
