## ==========================================
## ZERO-G ADMIN HELPER - ZEROGBRIDGE PAGE
## Shows the ZeroGBridge connection for the active server.
## Opened from the ZEROGBRIDGE nav button or by clicking the bridge field in the status bar.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QPushButton, QHBoxLayout

# endregion


# region ZeroGBridgePage Class

class ZeroGBridgePage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)
        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("ZeroGBridgePage")
        ## True once this page is listening to the cockpit's bridge_status_changed signal.
        self.is_listening = False
        self.setup_widgets()

    def setup_widgets(self):
        ## Top-to-bottom stack, pushed to the top of the page.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        ## Section heading.
        self.lbl_bridge_title = QLabel("CONNECTION")
        self.lbl_bridge_title.setObjectName("ZeroGBridgeSectionTitle")
        layout.addWidget(self.lbl_bridge_title)

        ## Server name and state. They start as "--" and get real values in refresh_status().
        self.lbl_bridge_server = QLabel("SERVER: --")
        self.lbl_bridge_server.setObjectName("ZeroGBridgeServerLabel")
        layout.addWidget(self.lbl_bridge_server)

        self.lbl_bridge_state = QLabel("STATUS: --")
        self.lbl_bridge_state.setObjectName("ZeroGBridgeStateLabel")
        layout.addWidget(self.lbl_bridge_state)

        ## Connect / Disconnect side by side. Both start disabled until the real state is known.
        button_row = QHBoxLayout()
        button_row.setSpacing(12)
        self.btn_bridge_connect = QPushButton("CONNECT")
        self.btn_bridge_connect.setObjectName("ZeroGBridgeButton")
        self.btn_bridge_connect.setEnabled(False)
        ## clicked fires each time the button is pressed.
        self.btn_bridge_connect.clicked.connect(self._on_connect_clicked)
        button_row.addWidget(self.btn_bridge_connect)

        self.btn_bridge_disconnect = QPushButton("DISCONNECT")
        self.btn_bridge_disconnect.setObjectName("ZeroGBridgeButton")
        self.btn_bridge_disconnect.setEnabled(False)
        self.btn_bridge_disconnect.clicked.connect(self._on_disconnect_clicked)
        button_row.addWidget(self.btn_bridge_disconnect)

        ## Opens the full ZeroGBridge Portal window (LOADER and BRIDGE tabs).
        ## Always clickable: the portal has its own Live / Examples switch and works offline too.
        self.btn_open_zgb_portal = QPushButton("OPEN ZGB PORTAL")
        self.btn_open_zgb_portal.setObjectName("ZeroGBridgeButton")
        self.btn_open_zgb_portal.clicked.connect(self._on_open_zgb_portal_clicked)
        button_row.addWidget(self.btn_open_zgb_portal)

        ## addStretch pushes the two buttons to the left instead of stretching them wide.
        button_row.addStretch()
        layout.addLayout(button_row)

        ## A plain note about what this page does today.
        self.lbl_bridge_note = QLabel("Connect only logs in to the active server's bridge. No commands are sent. Bridge tools from the legacy portal will follow.")
        self.lbl_bridge_note.setObjectName("ZeroGBridgeNote")
        self.lbl_bridge_note.setWordWrap(True)
        layout.addWidget(self.lbl_bridge_note)

    # endregion

    # region Status

    ## Qt calls showEvent each time the page appears, so the status is fresh every time it opens.
    def showEvent(self, event):
        super().showEvent(event)
        self.setup_listening()
        self.refresh_status()

    ## Connects to the cockpit's signal once, so the page updates live while it is open.
    ## Qt drops the link by itself when this page is closed and deleted.
    def setup_listening(self):
        if self.is_listening:
            return
        cockpit = self.window()
        signal = getattr(cockpit, "bridge_status_changed", None)
        if signal is None:
            return
        signal.connect(self._on_bridge_status_changed)
        self.is_listening = True

    ## Reads the real state from the main window (MainCockpit).
    def refresh_status(self):
        try:
            ## window() is the top-level window this page sits in: the MainCockpit.
            cockpit = self.window()
            ## Fail closed: if the cockpit hasn't recorded any bridge news, say UNKNOWN, never a guess.
            server_name = getattr(cockpit, "bridge_server_name", None)
            is_connected = getattr(cockpit, "bridge_connected", None)
            if server_name is None or is_connected is None:
                self.lbl_bridge_server.setText("SERVER: --")
                self.lbl_bridge_state.setText("STATUS: UNKNOWN")
                ## Unknown state: both buttons stay off (fail closed).
                self.btn_bridge_connect.setEnabled(False)
                self.btn_bridge_disconnect.setEnabled(False)
                return
            self.lbl_bridge_server.setText(f"SERVER: {str(server_name).upper()}")
            self.lbl_bridge_state.setText("STATUS: CONNECTED" if is_connected else "STATUS: DISCONNECTED")
            ## Only the button that makes sense right now is clickable.
            self.btn_bridge_connect.setEnabled(not is_connected)
            self.btn_bridge_disconnect.setEnabled(bool(is_connected))
        except Exception as e:
            print(f"[ERROR] ZeroGBridgePage: Failed to refresh status: {e}")
            self.lbl_bridge_state.setText("STATUS: UNKNOWN")

    ## Runs every time the cockpit sends bridge_status_changed.
    def _on_bridge_status_changed(self, server_name, is_connected):
        self.refresh_status()

    # endregion

    # region Handlers

    ## Asks the cockpit to connect. The real result arrives later through bridge_status_changed.
    def _on_connect_clicked(self):
        cockpit = self.window()
        connect_bridge = getattr(cockpit, "connect_bridge", None)
        if connect_bridge is None:
            print("[ERROR] ZeroGBridgePage: Cockpit has no connect_bridge, cannot connect")
            return
        print("[INFO] ZeroGBridgePage: Connect clicked")
        if connect_bridge():
            ## While the login runs in the background, both buttons are off so it can't be double-clicked.
            self.lbl_bridge_state.setText("STATUS: CONNECTING...")
            self.btn_bridge_connect.setEnabled(False)
            self.btn_bridge_disconnect.setEnabled(False)

    ## Asks the cockpit to disconnect. disconnect_bridge sends the signal, which refreshes this page.
    def _on_disconnect_clicked(self):
        cockpit = self.window()
        disconnect_bridge = getattr(cockpit, "disconnect_bridge", None)
        if disconnect_bridge is None:
            print("[ERROR] ZeroGBridgePage: Cockpit has no disconnect_bridge, cannot disconnect")
            return
        print("[INFO] ZeroGBridgePage: Disconnect clicked")
        disconnect_bridge()

    ## Asks the cockpit to open the portal (or bring it to the front if it's already open).
    def _on_open_zgb_portal_clicked(self):
        cockpit = self.window()
        open_zgb_portal = getattr(cockpit, "open_zgb_portal", None)
        if open_zgb_portal is None:
            print("[ERROR] ZeroGBridgePage: Cockpit has no open_zgb_portal, cannot open portal")
            return
        print("[INFO] ZeroGBridgePage: Open ZGB Portal clicked")
        open_zgb_portal()


    # endregion

# endregion


# region Page Entry

## page_loader calls this to build the page.
def create_page():
    return ZeroGBridgePage()

# endregion