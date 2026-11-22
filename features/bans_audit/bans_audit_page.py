## ==========================================
## ZERO-G ADMIN HELPER - BANS & AUDIT PAGE
## Starts with the FAILED LOGINS section: the newest failed logins from the online login service.
## Owners only. The service checks the owner's login token itself, so ZAH can't be tricked into showing it.
## Bans and the rest of the audit tools will be added here later.
## ==========================================

# region Imports

from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QCoreApplication
from PyQt6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)

## Guarded import: if online_login is missing, the section just says the log can't be loaded.
try:
    from features.login.online_login import fetch_failed_logins, load_dev_key
except Exception as e:
    print(f"[ERROR] BansAuditPage: Could not load online_login: {e}")
    fetch_failed_logins = None
    load_dev_key = None

# endregion


# region Constants

## Column headings for the failed login table, left to right.
FAILED_LOGIN_COLUMNS = ["TIME", "USERNAME", "ADDRESS", "REASON"]

## How many entries to ask the service for (it allows up to 200).
FAILED_LOGIN_LIMIT = 100

# endregion


# region Helpers

## Turns the service's UTC text into local time, e.g. "Nov 21, 2026 02:15 AM CST".
## Anything that isn't a real time is shown as it came, so nothing is hidden.

def make_readable_time(failed_at):
    try:
        return datetime.fromisoformat(str(failed_at)).astimezone().strftime("%b %d, %Y %I:%M %p %Z")
    except (ValueError, TypeError):
        return str(failed_at)

# endregion


# region Background Fetch

## Runs fetch_failed_logins on its own thread, so the page doesn't freeze while it waits.
## QThread calls run() on the new thread; the signal carries the answer back to the page.
class FailedLoginFetcher(QThread):

    ## Sends back (fetch_result, entries). "object" lets it carry a list or None.
    fetch_done = pyqtSignal(str, object)

    def __init__(self, session_token, limit, parent=None, dev_key=None):
        super().__init__(parent)
        self.session_token = session_token
        self.limit = limit

        ## Only set for the offline developer login. Never printed.
        self.dev_key = dev_key

    ## Never touch widgets in here: only the main thread may change the screen.
    ## Fails closed: any crash is sent back as "error", which the page shows as refused.
    def run(self):

        ## Also clears Pylance's warning: it now knows fetch_failed_logins isn't None below this.
        if fetch_failed_logins is None:
            self.fetch_done.emit("error", None)
            return
        try:
            fetch_result, entries = fetch_failed_logins(self.session_token, self.limit, dev_key=self.dev_key)
        except Exception as e:
            print(f"[ERROR] FailedLoginFetcher: Fetch failed: {e}")
            fetch_result, entries = "error", None
        self.fetch_done.emit(fetch_result, entries)

# endregion


# region BansAuditPage Class

class BansAuditPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("BansAuditPage")

        ## True once the log has been loaded for this visit, so it isn't fetched twice in a row.
        self.has_loaded = False

        ## The helper thread while a fetch is running, None otherwise. Keeping it here stops Python from deleting it mid-fetch.
        self.fetch_thread = None
        self.setup_widgets()

    def setup_widgets(self):

        ## Top-to-bottom stack.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        ## Section heading with the REFRESH button on the right.
        title_row = QHBoxLayout()
        self.lbl_failed_title = QLabel("FAILED LOGINS")
        self.lbl_failed_title.setObjectName("BansAuditSectionTitle")
        title_row.addWidget(self.lbl_failed_title)
        title_row.addStretch()

        ## Starts greyed out; refresh_failed_logins turns it on only for a signed-in owner.
        self.btn_failed_refresh = QPushButton("REFRESH")
        self.btn_failed_refresh.setObjectName("BansAuditButton")
        self.btn_failed_refresh.setEnabled(False)
        self.btn_failed_refresh.clicked.connect(self.refresh_failed_logins)
        title_row.addWidget(self.btn_failed_refresh)
        layout.addLayout(title_row)

        ## One line that says what is going on: loading, how many entries, or why there is nothing.
        self.lbl_failed_status = QLabel("--")
        self.lbl_failed_status.setObjectName("BansAuditNote")
        self.lbl_failed_status.setWordWrap(True)
        layout.addWidget(self.lbl_failed_status)

        ## The table. It is read-only: no editing, and a click selects the whole row.
        self.tbl_failed_logins = QTableWidget(0, len(FAILED_LOGIN_COLUMNS))
        self.tbl_failed_logins.setObjectName("BansAuditTable")
        self.tbl_failed_logins.setHorizontalHeaderLabels(FAILED_LOGIN_COLUMNS)
        self.tbl_failed_logins.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_failed_logins.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        ## Qt's type notes say the headers might be None, so each is checked before use (clears Pylance's warnings).
        row_header = self.tbl_failed_logins.verticalHeader()
        if row_header is not None:
            row_header.setVisible(False)

        ## Stretch makes the columns share the full width of the page.
        column_header = self.tbl_failed_logins.horizontalHeader()
        if column_header is not None:
            column_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        ## Puts the table on the page; stretch=1 lets it fill the space below the status line.
        layout.addWidget(self.tbl_failed_logins, stretch=1)

    # endregion


    # region Failed Logins

    ## Qt calls showEvent each time the page appears, so the log is fresh every time it opens.
    ## The page isn't inside the cockpit yet when it's built, which is why this isn't in setup_widgets.
    def showEvent(self, event):
        super().showEvent(event)
        if not self.has_loaded:
            self.has_loaded = True
            self.refresh_failed_logins()

    ## Clears the table and shows one message in the status line.
    def _show_failed_message(self, message_text):
        self.tbl_failed_logins.setRowCount(0)
        self.lbl_failed_status.setText(message_text)

    ## Asks the service for the newest failed logins and fills the table. Fails closed: any problem shows an empty table and a message.
    def refresh_failed_logins(self):
        try:

            ## window() is the top-level window this page sits in: the MainCockpit.
            cockpit = self.window()
            user_has_role = getattr(cockpit, "user_has_role", None)
            session_token = getattr(cockpit, "session_token", None)

            ## Owners and up only. Anyone else gets a greyed button and an empty table.
            if not (user_has_role and user_has_role("owner")):
                self.btn_failed_refresh.setEnabled(False)
                self._show_failed_message("Owners only.")
                return

            ## No token? The developer login can use the developer key instead, if this computer has one.
            dev_key = None
            if not session_token and user_has_role("developer") and load_dev_key is not None:
                dev_key = load_dev_key()

            ## The offline developer login has no online token, and the service needs one.
            if not session_token and not dev_key:
                self.btn_failed_refresh.setEnabled(False)
                self._show_failed_message("Sign in online as an owner to see this log.")
                return

            ## Already fetching: let that one finish instead of starting a second.
            if self.fetch_thread is not None:
                return
            self.btn_failed_refresh.setEnabled(True)

            if fetch_failed_logins is None:
                self._show_failed_message("Login log could not be loaded, see log.")
                return

            ## The helper thread does the waiting, so the window keeps working. REFRESH is greyed until the answer comes back.
            self.lbl_failed_status.setText("Loading...")
            self.btn_failed_refresh.setEnabled(False)

            ## The thread belongs to the app, not this page. Clicking to another page deletes the page,
            ## and a QThread deleted while still running crashes ZAH ("QThread: Destroyed while thread is still running").
            ## The app lives until ZAH closes, so the thread can finish safely and deleteLater frees it.
            self.fetch_thread = FailedLoginFetcher(session_token, FAILED_LOGIN_LIMIT, QCoreApplication.instance(), dev_key=dev_key)
            self.fetch_thread.fetch_done.connect(self._on_fetch_done)

            ## finished is QThread's own signal; deleteLater frees the thread once it has fully stopped.
            self.fetch_thread.finished.connect(self.fetch_thread.deleteLater)
            self.fetch_thread.start()

        except Exception as e:
            print(f"[ERROR] BansAuditPage: Could not start the failed login fetch: {e}")
            self.fetch_thread = None
            self._show_failed_message("Login log could not be loaded, see log.")

    ## Runs on the main thread when the helper thread sends its answer back, so it's safe to fill the table here.
    def _on_fetch_done(self, fetch_result, entries):
        self.fetch_thread = None
        self.btn_failed_refresh.setEnabled(True)
        try:

            if fetch_result == "offline":
                self._show_failed_message("Login service unreachable, try REFRESH later.")
                return
            if fetch_result != "ok" or entries is None:
                self._show_failed_message("The login service refused. Sign out and back in as an owner.")
                return

            ## One row per entry, newest first (the service already sorts them).
            self.tbl_failed_logins.setRowCount(len(entries))
            for row_number, entry in enumerate(entries):

                ## .get with "" keeps a broken entry from stopping the whole table.
                row_values = [
                    make_readable_time(entry.get("failed_at", "")),
                    str(entry.get("username", "")),
                    str(entry.get("source", "")),
                    str(entry.get("reason", "")),
                ]
                for column_number, cell_text in enumerate(row_values):
                    self.tbl_failed_logins.setItem(row_number, column_number, QTableWidgetItem(cell_text))

            if entries:
                self.lbl_failed_status.setText(f"{len(entries)} failed logins in the last 30 days (newest first).")
            else:
                self.lbl_failed_status.setText("No failed logins in the last 30 days.")
            print(f"[INFO] BansAuditPage: Showing {len(entries)} failed logins")

        except Exception as e:
            print(f"[ERROR] BansAuditPage: Could not show failed logins: {e}")
            self._show_failed_message("Login log could not be loaded, see log.")

    # endregion

# endregion


# region Page Entry

## page_loader calls this to build the page.
def create_page():
    return BansAuditPage()

# endregion
