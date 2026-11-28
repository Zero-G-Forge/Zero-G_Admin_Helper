## ==========================================
## ZERO-G ADMIN HELPER - QT TYPE HELPERS
## Small wrappers for Qt calls that the PyQt6 type stubs say "may return None" but that never do in ZAH,
## e.g. a table's horizontalHeader() or a scroll area's viewport(). Each one hands back the very same
## object Qt gave; cast() only tells the type checker (Pylance) what it already is. Nothing here
## changes how ZAH runs.
## ==========================================

# region Imports

from typing import cast

from PyQt6.QtWidgets import QHeaderView, QWidget

# endregion


# region Helpers

def horizontal_header(table) -> QHeaderView:
    """The table's column header (same object as table.horizontalHeader())."""
    return cast(QHeaderView, table.horizontalHeader())


def vertical_header(table) -> QHeaderView:
    """The table's row header (same object as table.verticalHeader())."""
    return cast(QHeaderView, table.verticalHeader())


def layout_item_widget(item) -> QWidget | None:
    """The widget inside a layout item, or None for a spacer (same as item.widget())."""
    return item.widget()


def viewport_of(area) -> QWidget:
    """The scrolling area's viewport (same object as area.viewport())."""
    return cast(QWidget, area.viewport())

# endregion
