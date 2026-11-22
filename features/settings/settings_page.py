## ==========================================
## ZERO-G ADMIN HELPER - SETTINGS PAGE
## ZAH's own options. Each change is saved right away to data/app_settings.json.
## SERVER FILES: pulls the server's editable files (ECF, PDA, item images, save files) through ZeroGBridge,
## and the LIVE MODE switch for editing files straight on the server. Both are layout only for now (disabled).
## ==========================================

# region Imports

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QLabel, QCheckBox, QVBoxLayout, QPushButton

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

        # region Server Files

        ## Section heading, with a little gap above it to split it from ZEROGBRIDGE.
        layout.addSpacing(12)
        self.lbl_files_title = QLabel("SERVER FILES")
        self.lbl_files_title.setObjectName("SettingsSectionTitle")
        layout.addWidget(self.lbl_files_title)

        ## Where the copies are kept and when they were last pulled. Filled in once downloading works.
        self.lbl_files_folder = QLabel("LOCAL COPY:  none yet")
        self.lbl_files_folder.setObjectName("SettingsNote")
        layout.addWidget(self.lbl_files_folder)
        self.lbl_files_pulled = QLabel("LAST PULLED:  never")
        self.lbl_files_pulled.setObjectName("SettingsNote")
        layout.addWidget(self.lbl_files_pulled)

        ## Read-only: copies the active scenario's Configuration, PDA and Images folders plus the save files
        ## down through ZeroGBridge. Disabled until the bridge has a file-send command.
        self.btn_download_files = QPushButton("DOWNLOAD SERVER FILES (READ-ONLY)")
        self.btn_download_files.setObjectName("DashActionButton")
        self.btn_download_files.setFixedHeight(36)
        self.btn_download_files.setFixedWidth(360)
        self.btn_download_files.setEnabled(False)
        self.btn_download_files.setToolTip("Coming in a later step.")
        layout.addWidget(self.btn_download_files)

        ## LIVE MODE: the editors read and write the server's files directly instead of the local copies.
        ## Never saved: always starts off, every time ZAH opens. Developer and owner only, unless an owner
        ## gives an admin or moderator the "Live file editing" permission on the Users page.
        self.chk_live_mode = QCheckBox("LIVE MODE: edit files directly on the server")
        self.chk_live_mode.setObjectName("SettingsCheckBox")
        self.chk_live_mode.setChecked(False)
        self.chk_live_mode.setEnabled(False)
        self.chk_live_mode.setToolTip("Coming in a later step.")
        layout.addWidget(self.chk_live_mode)

        ## The warning that explains what live saves will ask for.
        self.lbl_live_note = QLabel("Every live save asks three times: the changes preview, an online-players warning, "
                                    "then typing the file name. The bridge backs up the old file first.")
        self.lbl_live_note.setObjectName("SettingsNote")
        self.lbl_live_note.setWordWrap(True)
        layout.addWidget(self.lbl_live_note)

        # endregion

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