# connection.py

import os
import socket

from PyQt6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt

from features.network.bridge_session import login_failure_message
from features.network.server_config import add_server_profile, get_active_profile

# Live check on the game port. Not the ZeroGBridge port.
GAME_CHECK_TIMEOUT = 5.0

# ---------------------------------------------------
# Network Configuration Validation Function (Ping Check + Config File Integrity)
# ---------------------------------------------------

def describe_game_check_failure(ip, port, err):
    """Dialog and [ERROR] text for a failed game-port live check."""
    detail = login_failure_message(ip, port, err)
    prefix = "Could not reach "
    if detail.startswith(prefix):
        return "Could not reach game server " + detail[len(prefix):]
    return f"Could not reach game server {ip}:{port}: {err}"


def check_game_server(ip, port, timeout=GAME_CHECK_TIMEOUT):
    """
    Live check that the game port accepts TCP. This does not speak to ZeroGBridge
    and does not send auth:<token>. Returns (True, None) or (False, error).
    """
    label = f"{ip}:{port}"
    print(f"[STATUS] Checking game server {label} is up (timeout {timeout:.0f}s)...")
    try:
        with socket.create_connection((str(ip), int(port)), timeout=timeout):
            print(f"[SUCCESS] Game server {label} is up.")
            return True, None
    except Exception as err:
        reason = describe_game_check_failure(ip, port, err)
        print(f"[ERROR] {reason}")
        return False, err


def is_network_ready(config_path=None, timeout=GAME_CHECK_TIMEOUT):
    """
    Performs a diagnostic ping of the game port to verify the server is up.
    Returns True if that port accepts TCP, False otherwise.
    Reads the active profile, including a server_config.json that was just
    migrated from the single-server format. This does not open ZeroGBridge.
    """
    try:
        config = get_active_profile(config_path)
    except Exception as err:
        print(f"[WARNING] Ping diagnostic failed: {err}")
        return False

    if not config:
        return False

    # input_port is the game port typed in the wizard, not bridge_port.
    raw_ip = config.get("input_ip")
    raw_port = config.get("input_port") or 30500

    if not raw_ip or not raw_port:
        print("[DEBUG] Config exists but fields are empty or missing.")
        return False

    try:
        ip = str(raw_ip)
        port = int(raw_port)
    except (TypeError, ValueError) as err:
        print(f"[WARNING] Ping diagnostic failed: {err}")
        return False

    print(f"[DEBUG] Initiating network diagnostic: Pinging game server {ip}:{port} with a {timeout}s timeout...")
    ready, _err = check_game_server(ip, port, timeout=timeout)
    return ready
    
# ---------------------------------------------------
# Network Configuration Existence Check (Post-Ping)
# ---------------------------------------------------

class NetworkWizardOverlay(QDialog):
    def __init__(self, parent=None, persist_profile=True):
        super().__init__(parent)
        # Accept writes the server into server_config.json when this is set.
        # File -> Log into another server passes False and stores the profile
        # only after the bridge accepts the auth handshake.
        self.persist_profile = persist_profile
        self.entered_profile = None
        
        # Enforce strict 512x512 square viewport bounds
        self.win_size = 512
        
        self.setWindowTitle("Zero-G Admin Helper - Network Wizard")
        self.setFixedSize(self.win_size, self.win_size)
        
        # Initialize background canvas container
        self.bg_canvas = QLabel(self)
        self.bg_canvas.setGeometry(0, 0, self.win_size, self.win_size)
        self.bg_canvas.setScaledContents(True)
        
        # Discover project folder directory root path dynamically
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
        
        # Resolve target graphic asset location
        img_path = os.path.join(project_root, "assets", "backgrounds", "network_connection_wizard.png")
        
        if os.path.exists(img_path):
            self.bg_canvas.setPixmap(QPixmap(img_path))
            print("[INFO] Screen 1: Network Connection Wizard layout rendered successfully.")
        else:
            print(f"[ERROR] Asset path lookup failure at: {img_path}")
            self.bg_canvas.setText("Missing background image asset.")
            self.bg_canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.bg_canvas.setStyleSheet("color: #00ffff; background-color: #0c1020; font-size: 14px;")

        # FIXED QSS: Explicitly forcing placeholder text layers to render visibly
        field_qss = """
            QLineEdit {
                border: none;
                background: transparent;
                color: #00ffff;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 14px;
                padding-left: 5px;
            }
            QLineEdit::placeholder {
                color: rgba(0, 255, 255, 100); /* Semi-transparent cyan placeholder */
            }
        """
        
        # Exact input coordinates matching your placement adjustments
        self.input_ip = QLineEdit(self)
        self.input_ip.setGeometry(120, 170, 320, 30)
        self.input_ip.setStyleSheet(field_qss)
        self.input_ip.setPlaceholderText("IP Address")
        
        self.input_port = QLineEdit(self)
        self.input_port.setGeometry(120, 247, 320, 30)
        self.input_port.setStyleSheet(field_qss)
        self.input_port.setPlaceholderText("Game Port")
        
        self.input_pass = QLineEdit(self)
        self.input_pass.setGeometry(120, 325, 320, 30)
        self.input_pass.setStyleSheet(field_qss)
        self.input_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_pass.setPlaceholderText("Enter Auth Token (Password)")

        # Completely transparent button styling parameters
        btn_qss = "QPushButton { border: none; background: transparent; }"
        
        # Accept Button (Processes input variables)
        self.btn_accept = QPushButton(self)
        self.btn_accept.setGeometry(65, 400, 135, 35)
        self.btn_accept.setStyleSheet(btn_qss)
        self.btn_accept.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_accept.clicked.connect(self.accept_action_callback)
        
        self.btn_accept.setDefault(True)
     
        # Cancel Button (Safely terminates process loop)
        self.btn_cancel = QPushButton(self)
        self.btn_cancel.setGeometry(220, 400, 135, 35)
        self.btn_cancel.setStyleSheet(btn_qss)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.cancel_action_callback)

        # Reset Button (Clears user inputs and restores placeholder visibility)
        self.btn_reset = QPushButton(self)
        self.btn_reset.setGeometry(380, 400, 70, 35)
        self.btn_reset.setStyleSheet(btn_qss)
        self.btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset.clicked.connect(self.reset_action_callback)   
    
    def secure_password_typing_callback(self, text_value):
        """Dynamic slot that applies password dots only when text characters are present."""
        if text_value:
            self.input_pass.setEchoMode(QLineEdit.EchoMode.Password)
        else:
            self.input_pass.setEchoMode(QLineEdit.EchoMode.Normal)

    def reset_action_callback(self):
        print("[UI EVENT] Clear input fields executed. Restoring placeholder strings.")

        self.input_ip.clear()
        self.input_port.clear()

        self.input_pass.blockSignals(True)
        self.input_pass.clear()
        self.input_pass.setEchoMode(QLineEdit.EchoMode.Normal)
        self.input_pass.blockSignals(False)

        self.input_ip.update()
        self.input_port.update()
        self.input_pass.update()
        self.update()

    def cancel_action_callback(self):
        """Rejects modal dialog and terminates network setup loop cleanly."""
        print("[UI EVENT] Cancel clicked. Shutting down application loop cleanly...")
        self.close()

    def accept_action_callback(self):
        print("\n==========================================")
        print("PRODUCTION WIZARD DATA INGESTION SUMMARY:")
        print("==========================================")
        print(f"Game IP       : {self.input_ip.text() if self.input_ip.text() else 'BLANK'}")
        print(f"Game Port     : {self.input_port.text() if self.input_port.text() else 'BLANK'}")
        print(f"Auth Token    : {'SET' if self.input_pass.text() else 'BLANK'}")
        print("Bridge Port   : 30500 (not typed; ZeroGBridge connects in the background)")
        print("==================================================")

        # 1. Capture Data - Keys MUST match is_network_ready() dictionary lookup
        config_data = {
            "input_ip": self.input_ip.text().strip(),
            "input_port": self.input_port.text().strip(),
            "input_pass": self.input_pass.text().strip(),
        }
        self.entered_profile = config_data
        print(
            f"[STATUS] Network wizard accepted for game server "
            f"{config_data['input_ip'] or 'BLANK'}:{config_data['input_port'] or 'BLANK'}. "
            f"ZeroGBridge port is not entered here."
        )

        # 2. Persistence - add or update this server and keep every other profile.
        # File > Log into another server leaves this False and saves after the
        # cockpit shows the result dialog.
        if self.persist_profile:
            add_server_profile(
                config_data["input_ip"],
                config_data["input_port"],
                config_data["input_pass"],
            )
            print("[SUCCESS] Network configuration saved as a server profile.")
        else:
            print("[STATUS] Wizard handed the server to the cockpit. It is not saved yet.")

        # 3. Handoff
        self.accept()