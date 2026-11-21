## =====================================================================
## MODULE: features/login/login_window.py
## DESCRIPTION: Modal login dialog shown by the loader at 30%.
## For now it checks the offline owner login; the online login service is added in 5b.
## =====================================================================

# region Imports

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout, QApplication, QCheckBox, QComboBox
)
from PyQt6.QtCore import Qt
from features.login.owner_login import check_owner_login
from features.login.online_login import check_online_login
from features.login.saved_session import save_session_token

# endregion


# region Constants

## After this many wrong tries the dialog closes and ZAH quits.
MAX_LOGIN_ATTEMPTS = 5

# endregion


# region LoginWindow Class

class LoginWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LoginWindow")
        self.setWindowTitle("Zero-G Admin Helper - Login")
        self.setFixedSize(380, 275)
        self.failed_attempts = 0
        ## The signed-in username is kept here so later steps can show it.
        ## Role and session token from the online service; the offline developer login leaves these as developer / None.
        self.signed_in_role = None
        self.session_token = None
        self.setup_widgets()

    def setup_widgets(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        self.lbl_title = QLabel("ADMIN LOGIN")
        self.lbl_title.setObjectName("LoginTitle")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.input_username = QLineEdit()
        self.input_username.setObjectName("LoginUsername")
        self.input_username.setPlaceholderText("Username")

        ## EchoMode.Password shows dots instead of the typed letters.
        self.input_password = QLineEdit()
        self.input_password.setObjectName("LoginPassword")
        self.input_password.setPlaceholderText("Password")
        self.input_password.setEchoMode(QLineEdit.EchoMode.Password)
        ## Pressing Enter in the password box works the same as clicking LOGIN.
        self.input_password.returnPressed.connect(self._on_login_clicked)

        ## "Keep me logged in" row: a checkbox plus a dropdown for how long.
        remember_row = QHBoxLayout()
        self.chk_remember = QCheckBox("Keep me logged in")
        self.chk_remember.setObjectName("LoginRemember")
        self.combo_remember = QComboBox()
        self.combo_remember.setObjectName("LoginRememberTime")

        ## addItem(shown text, hidden data). The hidden data must match the service's REMEMBER_CHOICES keys exactly.
        self.combo_remember.addItem("8 hours", "8h")
        self.combo_remember.addItem("12 hours", "12h")
        self.combo_remember.addItem("1 day", "1d")
        self.combo_remember.addItem("7 days", "7d")
        self.combo_remember.addItem("Unlimited", "unlimited")

        ## The dropdown stays greyed out until the box is ticked. toggled sends True or False, which goes straight into setEnabled.
        self.combo_remember.setEnabled(False)
        self.chk_remember.toggled.connect(self.combo_remember.setEnabled)
        remember_row.addWidget(self.chk_remember)
        remember_row.addWidget(self.combo_remember)

        self.lbl_message = QLabel("")
        self.lbl_message.setObjectName("LoginMessage")
        self.lbl_message.setAlignment(Qt.AlignmentFlag.AlignCenter)

        button_row = QHBoxLayout()
        self.btn_cancel = QPushButton("CANCEL")
        self.btn_cancel.setObjectName("LoginCancel")
        ## reject() closes the dialog with a "no" result; the loader then quits ZAH.
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_login = QPushButton("LOGIN")
        self.btn_login.setObjectName("LoginButton")
        self.btn_login.setDefault(True)
        self.btn_login.clicked.connect(self._on_login_clicked)
        button_row.addWidget(self.btn_cancel)
        button_row.addWidget(self.btn_login)

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.input_username)
        layout.addWidget(self.input_password)
        layout.addLayout(remember_row)
        layout.addWidget(self.lbl_message)
        layout.addLayout(button_row)

    def _on_login_clicked(self):
        try:
            username = self.input_username.text().strip()
            password_text = self.input_password.text()
            ## Input check: both boxes must be filled in.
            if not username or not password_text:
                self.lbl_message.setText("Enter a username and password")
                return

            ## Step 1: the offline owner login is checked first, so Ray can sign in with no internet.
            if check_owner_login(username, password_text):
                
                ## The offline login is Ray's alone, so it signs in as developer (the top role).
                print(f"[SUCCESS] LoginWindow: Signed in as {username} (developer, offline)")
                self.signed_in_user = username
                self.signed_in_role = "developer"
                ## accept() closes the dialog with a "yes" result.
                self.accept()
                return

            ## Step 2: everyone else is checked by the online login service.
            self.lbl_message.setText("Checking login...")

            ## processEvents() lets the label redraw before the network call waits.
            QApplication.processEvents()

            ## Only send a remember choice when the box is ticked. currentData() gives the hidden value, like "7d".
            remember_choice = None
            if self.chk_remember.isChecked():
                remember_choice = self.combo_remember.currentData()
            login_result, login_details = check_online_login(username, password_text, remember_choice)

            if login_result == "ok" and login_details is not None:
                self.signed_in_user = username
                self.signed_in_role = login_details["role"]
                self.session_token = login_details["token"]

                ## "Keep me logged in" was ticked, so the token is saved for the next start.
                if remember_choice:
                    save_session_token(self.session_token)
                print(f"[SUCCESS] LoginWindow: Signed in as {username} ({self.signed_in_role}, online)")
                self.accept()
                return

            if login_result == "offline":
                ## A dead service is not the user's fault, so it does not count as a wrong try.
                self.input_password.clear()
                self.lbl_message.setText("Login service unreachable, try again")
                return
            self.failed_attempts += 1
            
            ## The password box is cleared after every wrong try; the password is never logged.
            self.input_password.clear()
            print(f"[WARNING] LoginWindow: Failed login {self.failed_attempts}/{MAX_LOGIN_ATTEMPTS}")
            if self.failed_attempts >= MAX_LOGIN_ATTEMPTS:
                self.reject()
                return
            self.lbl_message.setText("Wrong username or password")
        except Exception as e:
            print(f"[ERROR] LoginWindow: Login check failed: {e}")
            self.lbl_message.setText("Login error, see log")

# endregion