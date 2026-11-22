## ==========================================
## ZERO-G ADMIN HELPER - SETTINGS PAGE
## ZAH's own options. Each change is saved right away to data/app_settings.json.
## SERVER FILES: pulls the server's editable files (ECF, PDA, item images, save files) through ZeroGBridge,
## and the LIVE MODE switch for editing files straight on the server. The download button works (read-only,
## enabled only while the bridge is connected); LIVE MODE is layout only for now (disabled).
## ==========================================

# region Imports

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QLabel, QCheckBox, QVBoxLayout, QPushButton, QProgressBar, QMessageBox

from features.settings.app_settings import load_app_settings, save_app_setting
from features.server_files.download_worker import ServerFileDownloadWorker
from features.server_files.file_store import format_last_pulled, now_iso

# endregion


# region Running Downloads

## Download threads that are still running. A thread must not be thrown away while it runs (Qt would abort),
## so this list keeps it alive even if the user leaves the Settings page mid-download. Each one removes itself when done.
RUNNING_DOWNLOADS = []

# endregion


# region SettingsPage Class

class SettingsPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)
        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("SettingsPage")
        ## The download thread while one is running, otherwise None.
        self.download_worker = None
        ## Builds the download thread. A test can swap this for a fake one.
        self.create_download_worker = ServerFileDownloadWorker
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

        ## Where the copies are kept and when they were last pulled. Both start from what was saved last time.
        saved_settings = load_app_settings()
        saved_folder = saved_settings["server_files_local_folder"]
        self.lbl_files_folder = QLabel(f"LOCAL COPY:  {saved_folder or 'none yet'}")
        self.lbl_files_folder.setObjectName("SettingsNote")
        ## A long folder path wraps onto a second line instead of stretching the page.
        self.lbl_files_folder.setWordWrap(True)
        layout.addWidget(self.lbl_files_folder)
        saved_pulled = saved_settings["server_files_last_pulled"]
        self.lbl_files_pulled = QLabel(f"LAST PULLED:  {format_last_pulled(saved_pulled) if saved_pulled else 'never'}")
        self.lbl_files_pulled.setObjectName("SettingsNote")
        layout.addWidget(self.lbl_files_pulled)

        ## Read-only: copies the active scenario's Configuration, PDA and Images folders plus the save files
        ## down through ZeroGBridge. Greyed out unless the bridge is connected (see _refresh_download_state).
        self.btn_download_files = QPushButton("DOWNLOAD SERVER FILES (READ-ONLY)")
        self.btn_download_files.setObjectName("DashActionButton")
        self.btn_download_files.setFixedHeight(36)
        self.btn_download_files.setFixedWidth(360)
        self.btn_download_files.setEnabled(False)
        self.btn_download_files.setToolTip("Connect to the server first.")
        self.btn_download_files.clicked.connect(self._on_download_clicked)
        layout.addWidget(self.btn_download_files)

        ## Progress while downloading. Hidden until a download starts.
        self.bar_download_progress = QProgressBar()
        self.bar_download_progress.setObjectName("SettingsProgressBar")
        self.bar_download_progress.setFixedHeight(10)
        self.bar_download_progress.setFixedWidth(360)
        self.bar_download_progress.setTextVisible(False)
        self.bar_download_progress.setVisible(False)
        layout.addWidget(self.bar_download_progress)

        ## One line that says what the download is doing, or why it stopped.
        self.lbl_download_status = QLabel("")
        self.lbl_download_status.setObjectName("SettingsNote")
        self.lbl_download_status.setWordWrap(True)
        self.lbl_download_status.setVisible(False)
        layout.addWidget(self.lbl_download_status)

        ## LIVE MODE: the editors read and write the server's files directly instead of the local copies.
        ## Never saved: always starts off, every time ZAH opens. Developer and owner only, unless an owner
        ## gives an admin or moderator the "Live file editing" permission on the Users page.
        self.chk_live_mode = QCheckBox("LIVE MODE: edit files directly on the server")
        self.chk_live_mode.setObjectName("SettingsCheckBox")
        self.chk_live_mode.setChecked(False)
        self.chk_live_mode.setEnabled(False)
        self.chk_live_mode.setToolTip("Coming in a later step.")
        self.chk_live_mode.toggled.connect(self._on_live_mode_toggled)
        layout.addWidget(self.chk_live_mode)

        ## The warning that explains what live saves will ask for.
        self.lbl_live_note = QLabel("Every live save asks three times: the changes preview, an online-players warning, "
                                    "then typing the file name. The bridge backs up the old file first.")
        self.lbl_live_note.setObjectName("SettingsNote")
        self.lbl_live_note.setWordWrap(True)
        layout.addWidget(self.lbl_live_note)

        # endregion

    # endregion

    # region Server Files

    ## Qt calls showEvent each time the page appears, so the button state is fresh every time it opens.
    def showEvent(self, event):
        super().showEvent(event)
        self._setup_listening()
        self._refresh_download_state()
        self._refresh_live_mode_state()

    ## Connects to the cockpit's bridge_status_changed signal once, so the button follows the connection live.
    ## Qt drops the link by itself when this page is closed and deleted.
    def _setup_listening(self):
        if self.is_listening:
            return
        signal = getattr(self.window(), "bridge_status_changed", None)
        if signal is None:
            return
        signal.connect(self._on_bridge_status_changed)
        self.is_listening = True

    def _on_bridge_status_changed(self, server_name, is_connected):
        self._refresh_download_state()
        self._refresh_live_mode_state()

    ## LIVE MODE is usable only for users the role gate allows, with the bridge connected (fail closed).
    ## The tick itself lives on the cockpit (live_mode) and is never saved.
    def _refresh_live_mode_state(self):
        try:
            cockpit = self.window()
            check = getattr(cockpit, "can_edit_live_files", None)
            allowed = bool(check()) if callable(check) else False
            connected = getattr(cockpit, "bridge_connected", None) is True
            self.chk_live_mode.blockSignals(True)
            self.chk_live_mode.setChecked(getattr(cockpit, "live_mode", False) is True and allowed)
            self.chk_live_mode.blockSignals(False)
            self.chk_live_mode.setEnabled(allowed and connected)
            if not allowed:
                self.chk_live_mode.setToolTip("Developer and owner only, or an admin/moderator given Live file editing.")
            elif not connected:
                self.chk_live_mode.setToolTip("Connect to the server first.")
            else:
                self.chk_live_mode.setToolTip("Editors read the server's copy when a file opens, and SAVE also uploads "
                                              "after the three confirmations. Off again every time ZAH starts.")
            if not allowed and getattr(cockpit, "live_mode", False) is True:
                cockpit.live_mode = False
        except Exception as e:
            print(f"[ERROR] SettingsPage: Failed to refresh LIVE MODE: {e}")
            self.chk_live_mode.setEnabled(False)

    ## Turning LIVE MODE on asks first (No is the default); turning it off never asks.
    def _on_live_mode_toggled(self, is_checked):
        try:
            cockpit = self.window()
            if is_checked:
                check = getattr(cockpit, "can_edit_live_files", None)
                allowed = bool(check()) if callable(check) else False
                answer = QMessageBox.StandardButton.No
                if allowed:
                    answer = QMessageBox.question(
                        self, "Turn on LIVE MODE?",
                        "While LIVE MODE is on, SAVE in the ECF and PDA editors also uploads to the server "
                        "(after the changes preview, the online-players warning and typing the file name).\n\n"
                        "Turn it on?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    self.chk_live_mode.blockSignals(True)
                    self.chk_live_mode.setChecked(False)
                    self.chk_live_mode.blockSignals(False)
                    return
            cockpit.live_mode = bool(is_checked)
            print(f"[INFO] SettingsPage: LIVE MODE {'on' if is_checked else 'off'}")
        except Exception as e:
            print(f"[ERROR] SettingsPage: LIVE MODE switch failed: {e}")

    ## Turns the download button on only when the cockpit says the bridge is connected, and never during a download.
    ## Fails closed: if the cockpit has no news (or isn't found), the button stays off.
    def _refresh_download_state(self):
        try:
            if self.download_worker is not None:
                self.btn_download_files.setEnabled(False)
                return
            is_connected = getattr(self.window(), "bridge_connected", None)
            if is_connected is True:
                self.btn_download_files.setEnabled(True)
                self.btn_download_files.setToolTip("Copies the server's editable files to this PC. Nothing on the server is changed.")
            else:
                self.btn_download_files.setEnabled(False)
                self.btn_download_files.setToolTip("Connect to the server first.")
        except Exception as e:
            print(f"[ERROR] SettingsPage: Failed to refresh the download button: {e}")
            self.btn_download_files.setEnabled(False)

    ## Starts the download thread. The button is switched off at once so it can't be started twice.
    def _on_download_clicked(self):
        try:
            if self.download_worker is not None:
                return
            self.btn_download_files.setEnabled(False)
            self.btn_download_files.setText("DOWNLOADING")
            self.lbl_download_status.setText("Connecting to the server")
            self.lbl_download_status.setVisible(True)
            ## Range 0 to 0 makes the bar show a moving "busy" stripe until real numbers arrive.
            self.bar_download_progress.setRange(0, 0)
            self.bar_download_progress.setVisible(True)

            self.download_worker = self.create_download_worker()
            RUNNING_DOWNLOADS.append(self.download_worker)
            ## The list entry is removed when the thread ends, on whatever page object is still alive.
            self.download_worker.finished.connect(lambda worker=self.download_worker: _forget_download(worker))
            self.download_worker.progress.connect(self._on_download_progress)
            self.download_worker.finished_ok.connect(self._on_download_finished)
            self.download_worker.failed.connect(self._on_download_failed)
            ## finished fires after run() ends, success or not: the cleanup point.
            self.download_worker.finished.connect(self._on_download_thread_ended)
            self.download_worker.start()
        except Exception as e:
            print(f"[ERROR] SettingsPage: Could not start the download: {e}")
            self._on_download_failed("Could not start the download.")
            self._on_download_thread_ended()

    ## Runs on the page's thread each time the worker reports progress.
    def _on_download_progress(self, done, total, text):
        self.lbl_download_status.setText(text)
        if total > 0:
            self.bar_download_progress.setRange(0, total)
            self.bar_download_progress.setValue(min(done, total))
        else:
            self.bar_download_progress.setRange(0, 0)

    ## The download finished. Records the folder, and the time when every file arrived.
    def _on_download_finished(self, summary):
        failed_count = len(summary.get("failed", []))
        folder = summary.get("folder", "")
        if folder:
            save_app_setting("server_files_local_folder", folder)
            self.lbl_files_folder.setText(f"LOCAL COPY:  {folder}")
        if failed_count == 0:
            pulled_at = now_iso()
            save_app_setting("server_files_last_pulled", pulled_at)
            self.lbl_files_pulled.setText(f"LAST PULLED:  {format_last_pulled(pulled_at)}")
            self.lbl_download_status.setText(
                f"Done. {summary.get('downloaded', 0)} new or changed, {summary.get('skipped', 0)} already up to date.")
        else:
            self.lbl_download_status.setText(
                f"Finished, but the server would not send {failed_count} file(s). LAST PULLED was not updated. "
                f"Details are in the terminal.")
            for row in summary.get("failed", [])[:20]:
                print(f"[WARNING] SettingsPage: Not downloaded: {row.get('path')} ({row.get('error')})")

    ## The download stopped with a problem. The message is already plain English.
    def _on_download_failed(self, message):
        self.lbl_download_status.setText(f"Download failed: {message}")
        self.lbl_download_status.setVisible(True)

    ## Always runs last: puts the button and bar back so another download can start.
    def _on_download_thread_ended(self):
        self.download_worker = None
        self.bar_download_progress.setVisible(False)
        self.btn_download_files.setText("DOWNLOAD SERVER FILES (READ-ONLY)")
        self._refresh_download_state()

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


# region Download Bookkeeping

## Drops a finished thread from RUNNING_DOWNLOADS.
def _forget_download(worker):
    if worker in RUNNING_DOWNLOADS:
        RUNNING_DOWNLOADS.remove(worker)

# endregion


# region Page Entry

## page_loader calls this to build the page.
def create_page():
    return SettingsPage()

# endregion