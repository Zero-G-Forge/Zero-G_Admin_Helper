## ==========================================
## ZERO-G ADMIN HELPER - SETTINGS PAGE
## ZAH's own options. Each change is saved right away to data/app_settings.json.
## SERVER FILES: pulls the server's editable files (ECF, PDA, item images, save files) through ZeroGBridge,
## and the LIVE MODE switch for editing files straight on the server. The download button works (read-only,
## enabled only while the bridge is connected). Core 1.6.4: a scenario/save picker and file-type ticks
## sit above the download button. They fail closed to the old behaviour when the core is older or catalog fails.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QLabel, QCheckBox, QVBoxLayout, QHBoxLayout, QPushButton, QProgressBar,
    QMessageBox, QComboBox,
)

from features.bridge.server_settings import get_active_profile
from features.settings.app_settings import load_app_settings, save_app_setting
from features.server_files.download_settings import (
    FILE_TYPE_KEYS, DEFAULT_TYPES, PREFERRED_SCENARIO, PREFERRED_SAVE,
    first_available_name, load_server_download_settings, save_server_download_settings,
    selection_for_download, types_from_saved,
)
from features.server_files.download_worker import ServerFileDownloadWorker
from features.server_files.file_client import ServerFilesError, ServerFilesSession
from features.server_files.file_store import format_last_pulled, now_iso

# endregion


# region Running Downloads

## Download threads that are still running. A thread must not be thrown away while it runs (Qt would abort),
## so this list keeps it alive even if the user leaves the Settings page mid-download. Each one removes itself when done.
RUNNING_DOWNLOADS = []

## Tests set this to False so the Settings page never opens a catalog thread against a real server.
AUTO_FETCH_CATALOG = True

# endregion


# region Catalog Fetch

## Tests replace this function so the Settings page never talks to a real server.
def fetch_file_catalog(profile):
    with ServerFilesSession(profile) as session:
        return session.request("catalog")


class CatalogWorker(QThread):

    ## The files:catalog reply.
    finished_ok = pyqtSignal(dict)

    ## One plain reason the picker must stay off.
    failed = pyqtSignal(str)

    def __init__(self, profile_provider=None, parent=None):
        super().__init__(parent)
        self.profile_provider = profile_provider or get_active_profile

    def run(self):
        try:
            profile = self.profile_provider()
            if not isinstance(profile, dict):
                raise ServerFilesError("config", "No active server is saved in ZAH.")
            reply = fetch_file_catalog(profile)
            if not isinstance(reply, dict) or reply.get("ok") is not True:
                raise ServerFilesError("refused", "The server did not return a usable folder list.")
            self.finished_ok.emit(reply)
        except ServerFilesError as exc:
            self.failed.emit(_catalog_fail_message(exc))
        except Exception as exc:
            print(f"[ERROR] CatalogWorker: {type(exc).__name__}: {exc}")
            self.failed.emit("Could not list the server's scenarios and saves. The download will use the names in the server config.")


def _catalog_fail_message(exc):
    code = getattr(exc, "code", None)
    kind = getattr(exc, "kind", None)
    if kind == "unsupported" or code == "unknown_command":
        return ("This needs bridge core 1.6.4 or later. "
                "The download will use the scenario and save named in the server config.")
    text = str(exc).strip() or "Could not list the server's scenarios and saves."
    return f"{text} The download will use the scenario and save named in the server config."

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
        ## Catalog thread while a folder list is being asked for, otherwise None.
        self.catalog_worker = None
        ## True when files:catalog succeeded and the combos may be used for the next download.
        self.picker_ready = False
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

        ## 1.6.4 picker: which scenario and save to pull, and which file types. Disabled until
        ## files:catalog succeeds. Fail closed: the download then uses the names in the server config.
        self.lbl_scenario = QLabel("SCENARIO")
        self.lbl_scenario.setObjectName("SettingsNote")
        layout.addWidget(self.lbl_scenario)
        self.cmb_scenario = QComboBox()
        self.cmb_scenario.setObjectName("SettingsFileCombo")
        self.cmb_scenario.setFixedHeight(32)
        self.cmb_scenario.setFixedWidth(360)
        self.cmb_scenario.setEnabled(False)
        self.cmb_scenario.setToolTip("Connect to the server first.")
        self.cmb_scenario.currentTextChanged.connect(self._on_picker_changed)
        layout.addWidget(self.cmb_scenario)

        self.lbl_save = QLabel("SAVE")
        self.lbl_save.setObjectName("SettingsNote")
        layout.addWidget(self.lbl_save)
        self.cmb_save = QComboBox()
        self.cmb_save.setObjectName("SettingsFileCombo")
        self.cmb_save.setFixedHeight(32)
        self.cmb_save.setFixedWidth(360)
        self.cmb_save.setEnabled(False)
        self.cmb_save.setToolTip("Connect to the server first.")
        self.cmb_save.currentTextChanged.connect(self._on_picker_changed)
        layout.addWidget(self.cmb_save)

        self.lbl_types = QLabel("FILE TYPES")
        self.lbl_types.setObjectName("SettingsNote")
        layout.addWidget(self.lbl_types)
        types_row = QHBoxLayout()
        types_row.setSpacing(16)
        types_row.setContentsMargins(0, 0, 0, 0)
        self.chk_types = {}
        type_labels = {"ecf": ".ecf", "yaml": ".yaml / .yml", "csv": ".csv", "images": "images"}
        for key in FILE_TYPE_KEYS:
            box = QCheckBox(type_labels[key])
            box.setObjectName("SettingsCheckBox")
            box.setChecked(True)
            box.setEnabled(False)
            box.setToolTip("Connect to the server first.")
            box.toggled.connect(self._on_picker_changed)
            self.chk_types[key] = box
            types_row.addWidget(box)
        types_row.addStretch(1)
        layout.addLayout(types_row)

        self.lbl_catalog_status = QLabel("The folder list appears once the bridge is connected and the server has core 1.6.4 or later.")
        self.lbl_catalog_status.setObjectName("SettingsNote")
        self.lbl_catalog_status.setWordWrap(True)
        layout.addWidget(self.lbl_catalog_status)

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

        ## CANCEL stops a running download at the next safe point (between two requests). Hidden otherwise.
        self.btn_cancel_download = QPushButton("CANCEL DOWNLOAD")
        self.btn_cancel_download.setObjectName("DashActionButton")
        self.btn_cancel_download.setFixedHeight(30)
        self.btn_cancel_download.setFixedWidth(360)
        self.btn_cancel_download.setToolTip("Stops the download. Files already finished stay; half-finished ones are thrown away.")
        self.btn_cancel_download.setVisible(False)
        self.btn_cancel_download.clicked.connect(self._on_cancel_download_clicked)
        layout.addWidget(self.btn_cancel_download)

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
        self.chk_live_mode.setToolTip("Connect to the server first.")
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
        self._refresh_catalog()

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
        self._refresh_catalog()

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

    ## Asks the connected server for its scenario and save folders. Fail closed when offline
    ## or when the command is missing. Tests replace fetch_file_catalog so this never hits a live host.
    def _refresh_catalog(self):
        try:
            connected = getattr(self.window(), "bridge_connected", None) is True
            if not connected:
                self._set_picker_unavailable("Connect to the server first.")
                return
            if not AUTO_FETCH_CATALOG:
                self._set_picker_unavailable(
                    "This needs bridge core 1.6.4 or later. "
                    "The download will use the scenario and save named in the server config.")
                return
            if self.catalog_worker is not None and self.catalog_worker.isRunning():
                return
            self.picker_ready = False
            self.lbl_catalog_status.setText("Asking the server for its scenario and save folders")
            worker = CatalogWorker()
            self.catalog_worker = worker
            worker.finished_ok.connect(self._on_catalog_ready)
            worker.failed.connect(self._on_catalog_failed)
            worker.finished.connect(lambda w=worker: self._on_catalog_thread_ended(w))
            worker.start()
        except Exception as exc:
            print(f"[ERROR] SettingsPage: Could not start the folder list: {exc}")
            self._set_picker_unavailable("Could not list the server's scenarios and saves. The download will use the names in the server config.")

    def _on_catalog_thread_ended(self, worker):
        if self.catalog_worker is worker:
            self.catalog_worker = None

    def _on_catalog_failed(self, message):
        self._set_picker_unavailable(message)

    def _on_catalog_ready(self, reply):
        try:
            scenarios = [name for name in (reply.get("scenarios") or []) if isinstance(name, str) and name]
            saves = [name for name in (reply.get("saves") or []) if isinstance(name, str) and name]
            if not scenarios and not saves:
                self._set_picker_unavailable(
                    "The server did not report any scenario or save folders. "
                    "The download will use the names in the server config.")
                return
            current = reply.get("current") if isinstance(reply.get("current"), dict) else {}
            profile = get_active_profile()
            server_name = profile.get("server_name") if isinstance(profile, dict) else ""
            saved = load_server_download_settings(server_name)
            ## The two lists are independent. Preference order: saved choice, detected origin,
            ## the known live pair when those folders exist, then the names files:info reported.
            origin = reply.get("originScenario") if isinstance(reply.get("originScenario"), str) else ""
            self._fill_combo(self.cmb_scenario, scenarios,
                             saved.get("scenario"), origin, PREFERRED_SCENARIO, current.get("scenario"))
            self._fill_combo(self.cmb_save, saves,
                             saved.get("save"), PREFERRED_SAVE, current.get("save"))
            types = types_from_saved(saved.get("types"))
            for key, box in self.chk_types.items():
                box.blockSignals(True)
                box.setChecked(types[key])
                box.setEnabled(True)
                box.setToolTip("Choose which file types to pull. This is remembered for this server.")
                box.blockSignals(False)
            tooltip = "Choose which scenario and save to download. This is remembered for this server."
            self.cmb_scenario.setToolTip(tooltip)
            self.cmb_save.setToolTip(tooltip)
            self.cmb_scenario.setEnabled(self.cmb_scenario.count() > 0)
            self.cmb_save.setEnabled(self.cmb_save.count() > 0)
            self.picker_ready = self.cmb_scenario.count() > 0 and self.cmb_save.count() > 0
            if self.picker_ready:
                self.lbl_catalog_status.setText("Pick the scenario and save to download. The choice is kept for this server.")
                self._save_picker_now()
            else:
                self.lbl_catalog_status.setText(
                    "The server listed folders, but a scenario or a save is missing. "
                    "The download will use the names in the server config.")
        except Exception as exc:
            print(f"[ERROR] SettingsPage: Could not apply the folder list: {exc}")
            self._set_picker_unavailable("Could not list the server's scenarios and saves. The download will use the names in the server config.")

    def _fill_combo(self, combo, names, *preferences):
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(names)
        chosen = first_available_name(names, *preferences)
        if chosen:
            combo.setCurrentText(chosen)
        combo.blockSignals(False)

    def _set_picker_unavailable(self, message):
        self.picker_ready = False
        for combo in (self.cmb_scenario, self.cmb_save):
            combo.blockSignals(True)
            combo.setEnabled(False)
            combo.setToolTip(message)
            combo.blockSignals(False)
        for box in self.chk_types.values():
            box.blockSignals(True)
            box.setEnabled(False)
            box.setToolTip(message)
            box.blockSignals(False)
        self.lbl_catalog_status.setText(message)

    def _active_server_name(self):
        try:
            profile = get_active_profile()
            name = profile.get("server_name") if isinstance(profile, dict) else ""
            return name if isinstance(name, str) else ""
        except Exception:
            return ""

    def _current_types(self):
        return {key: box.isChecked() for key, box in self.chk_types.items()}

    def _current_selection(self):
        return selection_for_download(
            self._active_server_name(),
            self.picker_ready,
            self.cmb_scenario.currentText(),
            self.cmb_save.currentText(),
            self._current_types(),
        )

    def _on_picker_changed(self, *args):
        self._save_picker_now()

    def _save_picker_now(self):
        if not self.picker_ready:
            return
        save_server_download_settings(
            self._active_server_name(),
            scenario=self.cmb_scenario.currentText(),
            save=self.cmb_save.currentText(),
            types=self._current_types(),
        )

    def _on_download_clicked_guard(self):
        types = self._current_types()
        if self.picker_ready and not any(types.values()):
            self.lbl_download_status.setText("Pick at least one file type to download.")
            self.lbl_download_status.setVisible(True)
            return False
        return True

    ## Starts the download thread. The button is switched off at once so it can't be started twice.
    def _on_download_clicked(self):
        try:
            if self.download_worker is not None:
                return
            if not self._on_download_clicked_guard():
                return
            self.btn_download_files.setEnabled(False)
            self.btn_download_files.setText("DOWNLOADING")
            self.lbl_download_status.setText("Connecting to the server")
            self.lbl_download_status.setVisible(True)
            ## Range 0 to 0 makes the bar show a moving "busy" stripe until real numbers arrive.
            self.bar_download_progress.setRange(0, 0)
            self.bar_download_progress.setVisible(True)

            try:
                self.download_worker = self.create_download_worker(selection=self._current_selection())
            except TypeError:
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
            self.btn_cancel_download.setEnabled(True)
            self.btn_cancel_download.setVisible(True)
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

    ## Asks the running download to stop. The worker ends with "Download stopped." through failed.
    def _on_cancel_download_clicked(self):
        try:
            worker = self.download_worker
            if worker is not None and hasattr(worker, "request_stop"):
                worker.request_stop()
                self.btn_cancel_download.setEnabled(False)
                self.lbl_download_status.setText("Stopping after the current file")
        except Exception as e:
            print(f"[ERROR] SettingsPage: Could not cancel the download: {e}")

    ## Always runs last: puts the button and bar back so another download can start.
    def _on_download_thread_ended(self):
        self.download_worker = None
        self.btn_cancel_download.setVisible(False)
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