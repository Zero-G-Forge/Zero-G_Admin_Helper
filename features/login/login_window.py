## =====================================================================
## MODULE: features/login/login_window.py
## DESCRIPTION: Modal login dialog shown by the loader at 30%.
## For now it checks the offline owner login; the online login service is added in 5b.
## =====================================================================

## region: Imports

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout
)
from PyQt6.QtCore import Qt
from features.login.owner_login import check_owner_login

## endregion


## region: Constants

## After this many wrong tries the dialog closes and ZAH quits.
MAX_LOGIN_ATTEMPTS = 5

## endregion


## region: LoginWindow Class

class LoginWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LoginWindow")
        self.setWindowTitle("Zero-G Admin Helper - Login")
        self.setFixedSize(380, 240)
        self.failed_attempts = 0
        ## The signed-in username is kept here so later steps can show it.
        self.signed_in_user = None
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

            if check_owner_login(username, password_text):
                print(f"[SUCCESS] LoginWindow: Signed in as {username}")
                self.signed_in_user = username
                ## accept() closes the dialog with a "yes" result.
                self.accept()
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

## endregion