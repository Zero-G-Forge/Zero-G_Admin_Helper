## ==========================================
## ZERO-G ADMIN HELPER - QT TYPE HELPERS
## Small wrappers for Qt calls that the PyQt6 type stubs say "may return None" but that never do in ZAH,
## e.g. a table's horizontalHeader() or a scroll area's viewport(). Each one hands back the very same
## object Qt gave; cast() only tells the type checker (Pylance) what it already is. Nothing here
## changes how ZAH runs.
## ==========================================

# region Imports

from typing import Optional, TypeVar, cast

from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import QHeaderView, QWidget

# endregion


# region Helpers

T = TypeVar("T")


def not_none(value: Optional[T]) -> T:
    """Hands back the very same object; only tells the type checker it is not None, e.g. table.item(row, col)."""
    return cast(T, value)

def horizontal_header(table) -> QHeaderView:
    """The table's column header (same object as table.horizontalHeader())."""
    return cast(QHeaderView, table.horizontalHeader())


def vertical_header(table) -> QHeaderView:
    """The table's row header (same object as table.verticalHeader())."""
    return cast(QHeaderView, table.verticalHeader())


def layout_item_widget(item) -> QWidget | None:
    """The widget inside a layout item, or None for a spacer (same as item.widget())."""
    return item.widget()


def global_thread_pool() -> QThreadPool:
    """Qt's shared thread pool (same object as QThreadPool.globalInstance())."""
    return cast(QThreadPool, QThreadPool.globalInstance())


def viewport_of(area) -> QWidget:
    """The scrolling area's viewport (same object as area.viewport())."""
    return cast(QWidget, area.viewport())

# endregion
