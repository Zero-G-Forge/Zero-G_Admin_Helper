## ==========================================
## ZERO-G ADMIN HELPER - USERS PAGE
## Owners (and Ray's developer login) see, add, edit and remove the online login users in ZAH-DB.
## The login service checks the owner's token or the developer key itself, so ZAH can't be tricked.
## ==========================================

# region Imports

from datetime import datetime
import json

from features.paths import data_path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
                             QDialog, QMessageBox, QFormLayout, QLineEdit, QComboBox, QDialogButtonBox)

## Guarded import: if online_login is missing, the page just says the users can't be loaded.
try:
    from features.login.online_login import fetch_users, save_user, remove_user, load_dev_key
except Exception as e:
    print(f"[ERROR] UsersPage: Could not load online_login: {e}")
    fetch_users = None
    save_user = None
    remove_user = None
    load_dev_key = None

# endregion


# region Constants

## Column headings for the users table, left to right.
USER_COLUMNS = ["USERNAME", "ROLE", "ADDED"]

## Roles an owner can give, lowest first. "developer" is never offered; the service refuses it anyway.
ROLE_CHOICES = ["moderator", "admin", "owner"]

## The order users are shown under each server: owners first, then admins, then moderators.
ROLE_DISPLAY_ORDER = ["owner", "admin", "moderator"]

# endregion


# region Helpers

## Turns the service's UTC date into a local date, e.g. "Nov 22, 2026". Users from the test file have no date, so they show "--".
def make_readable_date(created_at):
    try:
        return datetime.fromisoformat(str(created_at)).astimezone().strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return "--"

## Reads your saved servers from data/server_config.json as a list of (server_name, "ip:port").
## Only the name, IP and port are read. A missing or broken file gives an empty list (fails closed).
def load_server_choices():
    try:
        with open(data_path("server_config.json"), "r", encoding="utf-8") as file_handle:
            saved_servers = json.load(file_handle).get("servers", [])
        return [(str(server.get("server_name", "")), f"{server.get('input_ip', '')}:{server.get('input_port', '')}")
                for server in saved_servers]
    except Exception as e:
        print(f"[WARNING] UsersPage: Could not read the saved servers ({type(e).__name__})")
        return []

## The name to show for a user: their display name with capitals, or the lower-case username for older users.
def shown_name(user):
    return str(user.get("display_name") or user.get("username", ""))

## Groups users for the table as a list of (server_name, server_address, users).
## Servers are sorted by name with UNASSIGNED (blank) last. Inside each: owner, admin, moderator, then name.
def group_users_by_server(users):
    server_groups = {}
    for user in users:
        server_key = (str(user.get("server_name") or ""), str(user.get("server_address") or ""))
        server_groups.setdefault(server_key, []).append(user)

    ## A role that isn't in ROLE_DISPLAY_ORDER sorts after moderator.
    def role_rank(user):
        user_role = str(user.get("role", ""))
        return ROLE_DISPLAY_ORDER.index(user_role) if user_role in ROLE_DISPLAY_ORDER else len(ROLE_DISPLAY_ORDER)

    ## server_key[0] == "" is False for real servers and True for UNASSIGNED, so UNASSIGNED sorts last.
    sorted_keys = sorted(server_groups, key=lambda server_key: (server_key[0] == "", server_key[0].lower(), server_key[1]))
    return [(server_name, server_address,
             sorted(server_groups[(server_name, server_address)], key=lambda user: (role_rank(user), str(user.get("username", "")))))
            for server_name, server_address in sorted_keys]

# endregion


# region Background Task

## Runs one service call on its own thread, so the page doesn't freeze while it waits.
## task_function is any function that returns a (result, data) tuple, like fetch_users does.
class UserTaskRunner(QThread):

    ## Sends back (result, data). "object" lets data be a list, a message or None.
    task_done = pyqtSignal(str, object)

    def __init__(self, task_function, parent=None):
        super().__init__(parent)
        self.task_function = task_function

    ## Never touch widgets in here. Any crash is sent back as "error" (fails closed).
    def run(self):
        try:
            task_result, task_data = self.task_function()
        except Exception as e:
            print(f"[ERROR] UserTaskRunner: Task failed: {e}")
            task_result, task_data = "error", None
        self.task_done.emit(task_result, task_data)

# endregion


# region User Dialog

## The small ADD USER / EDIT USER window. It only collects the values; the page sends them.
class UserEditDialog(QDialog):

    def __init__(self, username="", role="moderator", parent=None, server_name="", server_address=""):
        super().__init__(parent)

        ## A name means editing an existing user; a blank name means adding a new one.
        self.is_edit = bool(username)
        self.setWindowTitle("EDIT USER" if self.is_edit else "ADD USER")
        form = QFormLayout(self)

        ## A name can't change once made. To rename, add the new name and remove the old one.
        ## When editing, only its capitals can change (particlewave to ParticleWave), checked in _check_and_accept.
        self.original_name = str(username).lower()
        self.txt_username = QLineEdit(username)
        form.addRow("USERNAME", self.txt_username)
        self.cmb_role = QComboBox()
        self.cmb_role.addItems(ROLE_CHOICES)
        if role in ROLE_CHOICES:
            self.cmb_role.setCurrentText(role)
        form.addRow("ROLE", self.cmb_role)

        ## Which server this user belongs to. Each item keeps (name, address) hidden as its data.
        self.cmb_server = QComboBox()
        self.cmb_server.addItem("UNASSIGNED", ("", ""))
        for choice_name, choice_address in load_server_choices():
            self.cmb_server.addItem(f"{choice_name}  {choice_address}", (choice_name, choice_address))

            ## Picks this user's current server when it matches one in the list.
            if (choice_name, choice_address) == (server_name, server_address):
                self.cmb_server.setCurrentIndex(self.cmb_server.count() - 1)

        ## A server that isn't in this computer's list is still added, so editing never drops it by accident.
        if server_name and self.cmb_server.currentIndex() == 0:
            self.cmb_server.addItem(f"{server_name}  {server_address}", (server_name, server_address))
            self.cmb_server.setCurrentIndex(self.cmb_server.count() - 1)
        form.addRow("SERVER", self.cmb_server)

        ## Password mode shows dots instead of letters. When editing, blank keeps the old password.
        self.txt_password = QLineEdit()
        self.txt_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_password.setPlaceholderText("leave blank to keep the password" if self.is_edit else "8 or more characters")
        form.addRow("PASSWORD", self.txt_password)

        ## Shows what's wrong without closing the window.
        self.lbl_error = QLabel("")
        form.addRow(self.lbl_error)
        dialog_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        dialog_buttons.accepted.connect(self._check_and_accept)
        dialog_buttons.rejected.connect(self.reject)
        form.addRow(dialog_buttons)

    ## Checks the fields before closing with OK. The service checks them again, so this is only for a quick answer.
    def _check_and_accept(self):
        username, role, password = self.get_values()
        if not username:
            self.lbl_error.setText("A username is needed.")
            return
        if self.is_edit and username.lower() != self.original_name:
            self.lbl_error.setText("Only the capitals of a name can change.")
            return
        if (not self.is_edit or password) and len(password) < 8:
            self.lbl_error.setText("Passwords need 8 or more characters.")
            return
        self.accept()

    ## Returns (username, role, password). Names keep their capitals; the service lowers them for sign-in.
    def get_values(self):
        return self.txt_username.text().strip(), self.cmb_role.currentText(), self.txt_password.text()

    ## Returns (server_name, server_address) for the picked server. ("", "") means UNASSIGNED.
    def get_server(self):
        server_choice = self.cmb_server.currentData()
        return server_choice if server_choice else ("", "")

# endregion


# region UsersPage Class

class UsersPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("UsersPage")

        ## True once the list has been loaded for this visit, so it isn't fetched twice in a row.
        self.has_loaded = False

        ## The helper thread while a service call is running, None otherwise.
        self.task_thread = None

        ## The users from the last refresh, so EDIT and REMOVE know who each row is.
        self.user_list = []

        ## One entry per table row: the user on that row, or None for a heading row.
        self.row_users = []

        self.setup_widgets()

    def setup_widgets(self):

        ## Top-to-bottom stack.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        ## Section heading with the buttons on the right.
        title_row = QHBoxLayout()
        self.lbl_users_title = QLabel("LOGIN USERS")
        self.lbl_users_title.setObjectName("BansAuditSectionTitle")
        title_row.addWidget(self.lbl_users_title)
        title_row.addStretch()

        ## ADD, EDIT and REMOVE work on the login users; EDIT and REMOVE use the selected row.
        self.btn_users_add = QPushButton("ADD")
        self.btn_users_add.setObjectName("BansAuditButton")
        self.btn_users_add.clicked.connect(self.add_user_clicked)
        title_row.addWidget(self.btn_users_add)
        self.btn_users_edit = QPushButton("EDIT")
        self.btn_users_edit.setObjectName("BansAuditButton")
        self.btn_users_edit.clicked.connect(self.edit_user_clicked)
        title_row.addWidget(self.btn_users_edit)
        self.btn_users_remove = QPushButton("REMOVE")
        self.btn_users_remove.setObjectName("BansAuditButton")
        self.btn_users_remove.clicked.connect(self.remove_user_clicked)
        title_row.addWidget(self.btn_users_remove)

        ## Starts greyed out; refresh_users turns it on only for an owner who can reach the service.
        self.btn_users_refresh = QPushButton("REFRESH")
        self.btn_users_refresh.setObjectName("BansAuditButton")
        self.btn_users_refresh.clicked.connect(self.refresh_users)
        title_row.addWidget(self.btn_users_refresh)
        layout.addLayout(title_row)

        ## Every button that sends something to the service. They are all greyed while a call runs.
        self.action_buttons = [self.btn_users_add, self.btn_users_edit, self.btn_users_remove, self.btn_users_refresh]
        self._set_buttons_enabled(False)

        ## One line that says what is going on: loading, how many users, or why there is nothing.
        self.lbl_users_status = QLabel("--")
        self.lbl_users_status.setObjectName("BansAuditNote")
        self.lbl_users_status.setWordWrap(True)
        layout.addWidget(self.lbl_users_status)

        ## The table. It is read-only, and a click selects one whole row.
        ## One extra column on the left holds the server name, so users sit indented under it.
        self.tbl_users = QTableWidget(0, len(USER_COLUMNS) + 1)
        self.tbl_users.setObjectName("BansAuditTable")
        self.tbl_users.setHorizontalHeaderLabels([""] + USER_COLUMNS)
        self.tbl_users.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_users.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_users.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        ## Qt's type notes say the headers might be None, so each is checked before use.
        row_header = self.tbl_users.verticalHeader()
        if row_header is not None:
            row_header.setVisible(False)

            ## Taller rows so the table isn't cramped. The row header is hidden but still sets row height.
            row_header.setDefaultSectionSize(34)

        ## Stretch makes the columns share the full width of the page.
        column_header = self.tbl_users.horizontalHeader()
        if column_header is not None:
            column_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

            ## The server name column is only as wide as the longest server name.
            column_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)

            ## Hidden because each server group gets its own USERNAME / ROLE / ADDED row.
            column_header.setVisible(False)

        ## stretch=1 lets the table fill the space below the status line.
        layout.addWidget(self.tbl_users, stretch=1)

    # endregion


    # region Access

    ## Works out how to talk to the service: (session_token, dev_key), or None if this login can't manage users.
    ## When it can't, the reason goes in the status line.
    def _get_access(self):

        ## window() is the top-level window this page sits in: the MainCockpit.
        cockpit = self.window()
        user_has_role = getattr(cockpit, "user_has_role", None)
        session_token = getattr(cockpit, "session_token", None)

        ## Owners and up only.
        if not (user_has_role and user_has_role("owner")):
            self._show_message("Owners only.")
            return None

        ## No token? The developer login can use the developer key instead, if this computer has one.
        dev_key = None
        if not session_token and user_has_role("developer") and load_dev_key is not None:
            dev_key = load_dev_key()
        if not session_token and not dev_key:
            self._show_message("Sign in online as an owner to manage users.")
            return None
        return session_token, dev_key

    # endregion


    # region User List

    ## Qt calls showEvent each time the page appears; the list loads the first time it opens.
    def showEvent(self, event):
        super().showEvent(event)
        if not self.has_loaded:
            self.has_loaded = True
            self.refresh_users()

    ## Clears the table and shows one message in the status line.
    def _show_message(self, message_text):
        self.tbl_users.setRowCount(0)
        self.row_users = []
        self.lbl_users_status.setText(message_text)

    ## Adds one row to the bottom of the table. row_user is the user on it, or None for a heading row.
    ## row_kind sets the look: "server" is big and bold, "columns" is small and underlined, "user" is plain.
    ## first_column is where the cells start: 0 for the server row, 1 for the rows under it.
    ## Heading rows can't be selected, so EDIT and REMOVE never pick one.
    def _add_table_row(self, cell_texts, row_user=None, row_kind="user", first_column=0):
        row_number = self.tbl_users.rowCount()
        self.tbl_users.insertRow(row_number)
        self.row_users.append(row_user)
        for column_number, cell_text in enumerate(cell_texts):
            cell_item = QTableWidgetItem(cell_text)
            cell_font = cell_item.font()

            ## pointSizeF is -1 when the font size was set in pixels, so 10 is used as the base then.
            base_size = cell_font.pointSizeF() if cell_font.pointSizeF() > 0 else 10.0
            if row_kind == "server":
                cell_font.setPointSizeF(base_size + 3)
                cell_font.setBold(True)
            elif row_kind == "columns":
                cell_font.setPointSizeF(base_size - 1)
                cell_font.setUnderline(True)
            cell_item.setFont(cell_font)
            if row_user is None:
                cell_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tbl_users.setItem(row_number, first_column + column_number, cell_item)

        ## The server row is a bit taller so it stands out as the start of a group.
        if row_kind == "server":
            self.tbl_users.setRowHeight(row_number, 42)

    ## Turns every service button on or off together.
    def _set_buttons_enabled(self, enabled):
        for action_button in self.action_buttons:
            action_button.setEnabled(enabled)

    ## Starts one service call on the helper thread. Only one runs at a time, so a double click can't send twice.
    def _run_task(self, task_function, done_slot, busy_text):
        if self.task_thread is not None:
            return
        self.lbl_users_status.setText(busy_text)
        self._set_buttons_enabled(False)
        self.task_thread = UserTaskRunner(task_function, self)
        self.task_thread.task_done.connect(done_slot)

        ## finished is QThread's own signal; deleteLater frees the thread once it has fully stopped.
        self.task_thread.finished.connect(self.task_thread.deleteLater)
        self.task_thread.start()

    def refresh_users(self):
        try:
            access = self._get_access()
            if access is None:
                self._set_buttons_enabled(False)
                return

            ## A local copy, so Pylance knows it isn't None inside the lambda below.
            users_function = fetch_users
            if users_function is None:
                self._show_message("Users could not be loaded, see log.")
                return
            session_token, dev_key = access

            ## lambda wraps the call so the helper thread can run it later, with these values.
            self._run_task(lambda: users_function(session_token, dev_key=dev_key), self._on_users_loaded, "Loading...")
        except Exception as e:
            print(f"[ERROR] UsersPage: Could not start loading users: {e}")
            self.task_thread = None
            self._show_message("Users could not be loaded, see log.")

    ## Runs on the main thread when the list comes back, so it's safe to fill the table here.
    def _on_users_loaded(self, task_result, users):
        self.task_thread = None
        self._set_buttons_enabled(True)
        try:
            if task_result == "offline":
                self._show_message("Login service unreachable, try REFRESH later.")
                return
            if task_result != "ok" or users is None:
                self._show_message("The login service refused. Sign out and back in as an owner.")
                return

            ## Each server gets a heading row (name and IP), a USERNAME / ROLE / ADDED row, then its users.
            self.user_list = users
            self._show_message("")
            for group_number, (server_name, server_address, server_users) in enumerate(group_users_by_server(users)):

                ## An empty row between groups gives each server some breathing room.
                if group_number > 0:
                    self._add_table_row([], None, "spacer")
                self._add_table_row([server_name.upper() or "UNASSIGNED", server_address], None, "server")
                self._add_table_row(USER_COLUMNS, None, "columns", 1)
                for user in server_users:

                    ## .get with "" keeps a broken entry from stopping the whole table.
                    self._add_table_row([
                        shown_name(user),
                        str(user.get("role", "")).upper(),
                        make_readable_date(user.get("created_at", "")),
                    ], user, "user", 1)
            self.lbl_users_status.setText(f"{len(users)} login users.")
            print(f"[INFO] UsersPage: Showing {len(users)} users")

        except Exception as e:
            print(f"[ERROR] UsersPage: Could not show users: {e}")
            self._show_message("Users could not be loaded, see log.")

    # endregion


    # region Add Edit Remove

    ## The user on the selected row, or None if no row is picked.
    def _selected_user(self):
        selected_row = self.tbl_users.currentRow()
        if 0 <= selected_row < len(self.row_users):
            return self.row_users[selected_row]
        return None
    def add_user_clicked(self):
        self._open_user_dialog("", "moderator")
    def edit_user_clicked(self):
        picked_user = self._selected_user()
        if picked_user is None:
            self.lbl_users_status.setText("Pick a user in the table first.")
            return
        self._open_user_dialog(shown_name(picked_user), str(picked_user.get("role", "")),
                               str(picked_user.get("server_name", "")), str(picked_user.get("server_address", "")))

    ## Shows the dialog, then sends the save on the helper thread. Cancel changes nothing.
    def _open_user_dialog(self, username, role, server_name="", server_address=""):
        try:
            access = self._get_access()
            save_function = save_user
            if access is None:
                return
            if save_function is None:
                self.lbl_users_status.setText("Users can't be changed, see log.")
                return
            user_dialog = UserEditDialog(username, role, self, server_name, server_address)

            ## exec() waits here until OK or Cancel is pressed.
            if user_dialog.exec() != QDialog.DialogCode.Accepted:
                return
            new_name, new_role, new_password = user_dialog.get_values()
            new_server_name, new_server_address = user_dialog.get_server()
            session_token, dev_key = access
            self._run_task(lambda: save_function(session_token, new_name, new_role, new_password, dev_key=dev_key,
                                                 server_name=new_server_name, server_address=new_server_address),
                           self._on_change_done, "Saving...")
        except Exception as e:
            print(f"[ERROR] UsersPage: Could not save user: {e}")
            self.task_thread = None
            self._set_buttons_enabled(True)
            self.lbl_users_status.setText("User could not be saved, see log.")

    def remove_user_clicked(self):
        try:
            picked_user = self._selected_user()
            if picked_user is None:
                self.lbl_users_status.setText("Pick a user in the table first.")
                return
            access = self._get_access()
            remove_function = remove_user
            if access is None:
                return
            if remove_function is None:
                self.lbl_users_status.setText("Users can't be changed, see log.")
                return
            username = str(picked_user.get("username", ""))

            ## Asks first, with No as the default, because removing can't be undone.
            answer = QMessageBox.question(self, "REMOVE USER", f"Remove {username}? They won't be able to sign in anymore.",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            session_token, dev_key = access
            self._run_task(lambda: remove_function(session_token, username, dev_key=dev_key), self._on_change_done, "Removing...")
        except Exception as e:
            print(f"[ERROR] UsersPage: Could not remove user: {e}")
            self.task_thread = None
            self._set_buttons_enabled(True)
            self.lbl_users_status.setText("User could not be removed, see log.")

    ## Runs on the main thread when a save or remove comes back. On success it reloads the list.
    def _on_change_done(self, task_result, refused_message):
        self.task_thread = None
        self._set_buttons_enabled(True)
        if task_result == "ok":
            self.refresh_users()
            return
        if task_result == "offline":
            self.lbl_users_status.setText("Login service unreachable, nothing was changed.")
            return
        self.lbl_users_status.setText(f"Not changed: {refused_message or 'refused'}.")

    # endregion

# endregion


# region Page Entry

## page_loader calls this to build the page.
def create_page():
    return UsersPage()

# endregion