## ==========================================
## ZERO-G ADMIN HELPER - SETTINGS PAGE
## ZAH's own options. Each change is saved right away to data/app_settings.json.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QLabel, QCheckBox, QVBoxLayout

from features.settings.app_settings import load_app_settings, save_app_setting

# endregion


# region SettingsPage Class

class SettingsPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)
        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("SettingsPage")
        self.setup_widgets()

    def setup_widgets(self):
        ## Top-to-bottom stack, pushed to the top of the page.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        ## Section heading.
        self.lbl_bridge_title = QLabel("ZEROGBRIDGE")
        self.lbl_bridge_title.setObjectName("SettingsSectionTitle")
        layout.addWidget(self.lbl_bridge_title)

        ## The checkbox starts at whatever was saved last time (off by default).
        self.chk_bridge_auto_connect = QCheckBox("Auto-connect to ZeroGBridge when ZAH starts")
        self.chk_bridge_auto_connect.setObjectName("SettingsCheckBox")
        self.chk_bridge_auto_connect.setChecked(load_app_settings()["bridge_auto_connect"])
        ## toggled fires with True or False every time the box is clicked.
        self.chk_bridge_auto_connect.toggled.connect(self._on_bridge_auto_connect_toggled)
        layout.addWidget(self.chk_bridge_auto_connect)

        ## A plain note so nobody is surprised by what this switch does.
        self.lbl_bridge_note = QLabel("Takes effect next time ZAH starts. When on, ZAH connects to the active server's bridge.")
        self.lbl_bridge_note.setObjectName("SettingsNote")
        self.lbl_bridge_note.setWordWrap(True)
        layout.addWidget(self.lbl_bridge_note)

    # endregion

    # region Handlers

    ## Saves the new value. If the save fails, the box flips back so it never shows a setting that isn't real.
    def _on_bridge_auto_connect_toggled(self, is_checked):
        if not save_app_setting("bridge_auto_connect", is_checked):
            ## blockSignals stops the flip-back from triggering this handler again.
            self.chk_bridge_auto_connect.blockSignals(True)
            self.chk_bridge_auto_connect.setChecked(not is_checked)
            self.chk_bridge_auto_connect.blockSignals(False)

    # endregion

# endregion


# region Page Entry

## page_loader calls this to build the page.
def create_page():
    return SettingsPage()

# endregion