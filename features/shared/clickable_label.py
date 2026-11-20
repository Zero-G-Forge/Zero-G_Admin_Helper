## =====================================================================
## MODULE: features/shared/clickable_label.py
## DESCRIPTION: A QLabel that can be clicked, like a button, but keeps label styling.
## =====================================================================

# region Imports

from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import Qt, pyqtSignal

# endregion

# region ClickableLabel Class

class ClickableLabel(QLabel):
    ## A signal is a message the label sends out. Anything can connect() to it,
    ## the same way setup_bridge connects to CommandPipe.connection_changed.
    clicked = pyqtSignal()

    def __init__(self, text="", parent=None):
        ## super().__init__ builds the normal QLabel first, so all its features still work.
        super().__init__(text, parent)
        ## The pointing-hand cursor tells the user this label can be clicked.
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    ## Qt calls mousePressEvent every time the mouse is pressed on this label.
    ## Writing our own version here "overrides" the built-in one.
    def mousePressEvent(self, event):
        ## Only the left mouse button counts as a click.
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        ## Hand the event back to QLabel so its normal behaviour still happens.
        super().mousePressEvent(event)

# endregion