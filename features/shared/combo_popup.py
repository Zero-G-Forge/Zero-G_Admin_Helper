## ==========================================
## ZERO-G ADMIN HELPER - COMBO POPUP OUTLINE
## Qt only applies QComboBox ::item stylesheet
## rules when the popup uses a
## QStyledItemDelegate. The built-in popup
## does not, so the cyan box would never
## appear. This installs that delegate on
## every combo, including ones created later.
## ==========================================

# region Imports

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QStyledItemDelegate)

# endregion


# region Install

class _ComboPopupFilter(QObject):
    def eventFilter(self, obj, event):
        is_combo = isinstance(obj, QComboBox)
        polished = event.type() in (
            QEvent.Type.Polish,
            QEvent.Type.Show,
        )
        if is_combo and polished:
            _use_styled_delegate(obj)
        return False


def _use_styled_delegate(combo):
    view = combo.view()
    if view is None:
        return
    delegate = view.itemDelegate()
    if isinstance(delegate, QStyledItemDelegate):
        return
    view.setItemDelegate(
        QStyledItemDelegate(view))


def install_combo_popup_outline(app=None):
    """Honor the cyan ::item box on every combo."""
    app = app or QApplication.instance()
    if not isinstance(app, QApplication):
        return
    if getattr(app, "_combo_popup_filter", None):
        return
    popup_filter = _ComboPopupFilter(app)
    setattr(app, "_combo_popup_filter", popup_filter)
    app.installEventFilter(popup_filter)
    for widget in app.allWidgets():
        if isinstance(widget, QComboBox):
            _use_styled_delegate(widget)

# endregion
