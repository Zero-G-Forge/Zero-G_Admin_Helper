## ==========================================
## ZERO-G ADMIN HELPER - BP EDITOR PAGE
## Opens the shared Item & Blueprint Library page (features/library/library_page.py) on its BLUEPRINTS tab.
## ==========================================

# region Imports

from features.library.library_page import LibraryPage

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return LibraryPage(start_tab="blueprints")

# endregion
