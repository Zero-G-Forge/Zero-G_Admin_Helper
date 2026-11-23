## =====================================================================
## MODULE: features/server_files/download_manager.py
## DESCRIPTION: Owns the one read-only server-files download (files:list / files:get)
## so it can keep running after the Settings page is closed. The cockpit deletes
## the old page on every nav change, and the page loader reload()s the Settings
## module, which would empty a list kept in settings_page.py. This module is not
## a page, so it is not reloaded. LAST PULLED is recorded here when the copy
## finishes, even if Settings is not on screen. Nothing on a server is changed.
## =====================================================================

# region Imports

from PyQt6.QtCore import QObject, pyqtSignal

# endregion


# region DownloadManager

class DownloadManager(QObject):

    ## done files, total files, short text for the status line.
    progress = pyqtSignal(int, int, str)

    ## The finished summary dictionary (see ServerFileDownloadWorker).
    finished_ok = pyqtSignal(dict)

    ## One short, plain message for the user.
    failed = pyqtSignal(str)

    ## Fires after the thread ends, success or not, once the worker slot is clear.
    thread_ended = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.workers = []
        self.last_progress_values = None
        self.last_status_text = ""
        self.last_summary = None
        self.last_error = None
        self.stopping = False

    def is_running(self):
        return self.worker is not None and self.worker.isRunning()

    def start(self, factory, selection=None):
        """Starts one download. Returns False when a download is already running."""
        if self.is_running():
            return False
        self.last_progress_values = (0, 0, "Connecting to the server")
        self.last_status_text = "Connecting to the server"
        self.last_summary = None
        self.last_error = None
        self.stopping = False
        try:
            worker = factory(selection=selection)
        except TypeError:
            worker = factory()
        self.worker = worker
        self.workers.append(worker)
        worker.progress.connect(self._on_progress)
        worker.finished_ok.connect(self._on_finished_ok)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_thread_ended)
        worker.start()
        return True

    def request_stop(self):
        """Asks the running download to stop at the next safe point. Returns False when none is running."""
        worker = self.worker
        if worker is None or not hasattr(worker, "request_stop"):
            return False
        self.stopping = True
        worker.request_stop()
        self.last_status_text = "Stopping after the current file"
        return True

    def _on_progress(self, done, total, text):
        self.last_progress_values = (done, total, text)
        self.last_status_text = text
        self.progress.emit(done, total, text)

    def _on_finished_ok(self, summary):
        self.last_summary = summary
        self.last_error = None
        failed = summary.get("failed") or []
        folder = summary.get("folder") or ""
        if folder:
            from features.settings.app_settings import save_app_setting
            save_app_setting("server_files_local_folder", folder)
        if not failed:
            from features.settings.app_settings import save_app_setting
            from features.server_files.file_store import now_iso
            save_app_setting("server_files_last_pulled", now_iso())
            self.last_status_text = (
                f"Done. {summary.get('downloaded', 0)} new or changed, "
                f"{summary.get('skipped', 0)} already up to date.")
        else:
            failed_count = len(failed)
            self.last_status_text = (
                f"Finished, but the server would not send {failed_count} file(s). "
                f"LAST PULLED was not updated. Details are in the terminal.")
        self.finished_ok.emit(summary)

    def _on_failed(self, message):
        self.last_error = message
        self.last_status_text = f"Download failed: {message}"
        self.failed.emit(message)

    def _on_thread_ended(self):
        worker = self.worker
        self.worker = None
        self.stopping = False
        if worker in self.workers:
            self.workers.remove(worker)
        self.thread_ended.emit()

    def reset(self):
        """Test helper: drops remembered state. Stops a leftover worker if one is still running."""
        worker = self.worker
        if worker is not None and worker.isRunning() and hasattr(worker, "request_stop"):
            worker.request_stop()
            worker.wait(2000)
        self.worker = None
        self.workers = []
        self.last_progress_values = None
        self.last_status_text = ""
        self.last_summary = None
        self.last_error = None
        self.stopping = False

# endregion


# region Module Singleton

_MANAGER = None


def get_manager():
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = DownloadManager()
    return _MANAGER


def is_running():
    return get_manager().is_running()


def start(factory, selection=None):
    return get_manager().start(factory, selection)


def request_stop():
    return get_manager().request_stop()


def current_worker():
    return get_manager().worker


def running_workers():
    return list(get_manager().workers)


def reset():
    if _MANAGER is not None:
        _MANAGER.reset()

# endregion
