## =====================================================================
## MODULE: features/server_files/download_worker.py
## DESCRIPTION: Background thread that copies the server's editable files to this PC through ZeroGBridge.
## READ-ONLY: it only sends files:info, files:list and files:get. It never changes anything on the server,
## and it never deletes anything on this PC (old local copies stay; changed files are replaced).
## It runs in a QThread, so the window never freezes. Progress and the result come back as Qt signals.
## =====================================================================

# region Imports

import base64
import os
import traceback
from collections import deque

from PyQt6.QtCore import QThread, pyqtSignal

from features.bridge.server_settings import get_active_profile
from features.server_files.file_client import ServerFilesError, ServerFilesSession, SUPPORTED_PROTOCOL
from features.server_files.file_store import (
    ROOT_NAMES, load_manifest, local_target_path, save_manifest, scenario_folder,
)

# endregion


# region Constants

## Items asked for in one files:get request. The bridge caps one reply by bytes, so small files fill a reply
## and the rest come back "deferred" and are asked for again.
BATCH_ITEMS = 40

## Entries asked for in one files:list page.
LIST_PAGE_SIZE = 1000

## A file that changes on the server while it is being copied is restarted at most this many times.
MAX_RESTARTS_PER_FILE = 2

## Replies in a row that move nothing forward before the download gives up (stops an endless loop).
MAX_STALLED_REPLIES = 3

# endregion


# region Worker

class ServerFileDownloadWorker(QThread):

    ## done files, total files, short text for the status line.
    progress = pyqtSignal(int, int, str)

    ## The finished summary dictionary (see _run_download for its keys).
    finished_ok = pyqtSignal(dict)

    ## One short, plain message for the user.
    failed = pyqtSignal(str)

    def __init__(self, profile_provider=None, parent=None):
        super().__init__(parent)
        ## Tests hand in their own provider; the real app reads the active server profile.
        self.profile_provider = profile_provider or get_active_profile
        self._stop_requested = False

    ## Asks the thread to stop at the next safe point (between two requests).
    def request_stop(self):
        self._stop_requested = True

    # region Thread Entry

    ## QThread calls run() on the new thread after start(). Every error is caught here so none escapes the thread.
    def run(self):
        try:
            summary = self._run_download()
            self.finished_ok.emit(summary)
        except ServerFilesError as e:
            print(f"[ERROR] ServerFileDownload: {e.kind}: {e}")
            self.failed.emit(str(e))
        except Exception as e:
            print(f"[ERROR] ServerFileDownload: Unexpected {type(e).__name__}: {e}")
            print(traceback.format_exc())
            self.failed.emit(f"Download stopped by an unexpected error ({type(e).__name__}).")

    # endregion

    # region Download Steps

    def _run_download(self):
        profile = self.profile_provider()
        if not isinstance(profile, dict):
            raise ServerFilesError("config", "No active server is saved in ZAH.")

        with ServerFilesSession(profile) as session:
            ## Step 1: ask what the server offers. An old bridge fails here with the "unsupported" message.
            self.progress.emit(0, 0, "Asking the server what it offers")
            info = session.request("info")
            if info.get("protocol") != SUPPORTED_PROTOCOL:
                raise ServerFilesError("unsupported", "This server's file commands are a different version than this ZAH expects.")
            scenario_name = str(info.get("scenario") or "")
            if not scenario_name:
                raise ServerFilesError("refused", "The server has not reported its active scenario yet. Try again in a minute.")
            available_roots = [row.get("root") for row in (info.get("roots") or [])
                               if isinstance(row, dict) and row.get("available") and row.get("root") in ROOT_NAMES]
            if not available_roots:
                raise ServerFilesError("refused", "The server has no readable scenario or save folder yet. Try again in a minute.")

            folder = scenario_folder(scenario_name)
            manifest = load_manifest(folder)
            manifest["scenario"] = scenario_name
            manifest["save"] = info.get("saveName")
            print(f"[INFO] ServerFileDownload: Scenario '{scenario_name}', roots {available_roots}, local folder {folder}")

            ## Step 2: list every file, and keep the ones that are new or changed.
            wanted, skipped, listed_total = self._collect_wanted(session, available_roots, folder, manifest)
            summary = {
                "scenario": scenario_name, "save": info.get("saveName"), "folder": folder,
                "listed": listed_total, "downloaded": 0, "skipped": skipped, "failed": [], "bytes": 0,
            }

            ## Step 3: copy them. The manifest is saved even if this step stops early, so a retry skips what already arrived.
            try:
                self._download_files(session, folder, manifest, wanted, summary)
            finally:
                save_manifest(folder, manifest)

        print(f"[SUCCESS] ServerFileDownload: {summary['downloaded']} downloaded, {summary['skipped']} unchanged, "
              f"{len(summary['failed'])} failed, {summary['bytes']} bytes")
        return summary

    ## Lists all files of the available roots. Returns (items to fetch, count unchanged, count listed).
    def _collect_wanted(self, session, roots, folder, manifest):
        wanted = []
        skipped = 0
        listed_total = 0
        for root in roots:
            offset = 0
            while offset is not None:
                self._check_stop()
                self.progress.emit(0, 0, f"Listing {root} files ({listed_total} so far)")
                reply = session.request("list", {"root": root, "offset": offset, "limit": LIST_PAGE_SIZE})
                for entry in reply.get("files") or []:
                    path = entry.get("path")
                    size = entry.get("size")
                    mtime = entry.get("mtime")
                    if not isinstance(path, str) or not isinstance(size, int) or isinstance(size, bool):
                        continue
                    listed_total += 1
                    key = f"{root}/{path}"
                    target = local_target_path(os.path.join(folder, root), path)
                    if target is None:
                        print(f"[WARNING] ServerFileDownload: Skipped unsafe path from server: {path!r}")
                        continue
                    saved = manifest["files"].get(key)
                    if (isinstance(saved, dict) and saved.get("size") == size and saved.get("mtime") == mtime
                            and os.path.isfile(target) and os.path.getsize(target) == size):
                        skipped += 1
                        continue
                    wanted.append({"root": root, "path": path, "size": size, "mtime": mtime, "target": target})
                next_offset = reply.get("next")
                offset = next_offset if isinstance(next_offset, int) and next_offset > offset else None
        return wanted, skipped, listed_total

    ## Copies the wanted files, one root at a time, in batches.
    def _download_files(self, session, folder, manifest, wanted, summary):
        total = len(wanted) + summary["skipped"]
        done = summary["skipped"]
        self.progress.emit(done, total, f"Downloading {done} of {total} files")

        for root in ROOT_NAMES:
            ## Each queue entry is one file plus where its next chunk starts.
            queue = deque({"item": item, "offset": 0, "restarts": 0} for item in wanted if item["root"] == root)
            stalled = 0
            while queue:
                self._check_stop()
                batch = [queue.popleft() for _ in range(min(BATCH_ITEMS, len(queue)))]
                reply = session.request("get", {
                    "root": root,
                    "items": [{"path": entry["item"]["path"], "offset": entry["offset"]} for entry in batch],
                })
                results = {row.get("path"): row for row in (reply.get("files") or []) if isinstance(row, dict)}
                requeue = []
                moved = False

                for entry in batch:
                    item = entry["item"]
                    row = results.get(item["path"])
                    if row is None or row.get("deferred"):
                        requeue.append(entry)
                        continue
                    if row.get("error"):
                        summary["failed"].append({"path": f"{root}/{item['path']}", "error": str(row.get("error"))})
                        print(f"[WARNING] ServerFileDownload: Server refused {root}/{item['path']}: {row.get('error')}")
                        done += 1
                        moved = True
                        continue
                    outcome = self._store_chunk(entry, row, folder, manifest, summary)
                    moved = True
                    if outcome == "done":
                        done += 1
                    elif outcome == "more" or outcome == "restart":
                        requeue.append(entry)
                    elif outcome == "failed":
                        done += 1

                ## Unfinished files go back to the front of the line, in their old order.
                for entry in reversed(requeue):
                    queue.appendleft(entry)

                stalled = 0 if moved else stalled + 1
                if stalled >= MAX_STALLED_REPLIES:
                    raise ServerFilesError("protocol", "The server stopped sending file data.")
                self.progress.emit(done, total, f"Downloading {done} of {total} files")

    ## Writes one chunk of one file. Returns "done", "more", "restart" or "failed".
    def _store_chunk(self, entry, row, folder, manifest, summary):
        item = entry["item"]
        target = item["target"]
        part_path = target + ".part"
        try:
            chunk = base64.b64decode(row.get("data") or "", validate=True)
            size = row.get("size")
            mtime = row.get("mtime")
            chunk_offset = row.get("offset")
            if not isinstance(size, int) or chunk_offset != entry["offset"] or len(chunk) != row.get("length"):
                raise ValueError("chunk does not match the request")

            ## A file that changed on the server since the last chunk is restarted from byte 0.
            if entry["offset"] > 0 and (size != entry.get("size") or mtime != entry.get("mtime")):
                return self._restart(entry, part_path, item, summary)
            entry["size"], entry["mtime"] = size, mtime

            os.makedirs(os.path.dirname(target), exist_ok=True)
            if entry["offset"] == 0:
                mode = "wb"
            else:
                ## Appending is only right when the part file is exactly as long as what was received so far.
                if not os.path.isfile(part_path) or os.path.getsize(part_path) != entry["offset"]:
                    return self._restart(entry, part_path, item, summary)
                mode = "ab"
            with open(part_path, mode) as file_handle:
                file_handle.write(chunk)
            summary["bytes"] += len(chunk)
            entry["offset"] += len(chunk)

            if row.get("eof") is True:
                if os.path.getsize(part_path) != size:
                    return self._restart(entry, part_path, item, summary)
                ## replace() puts the finished file in place in one step.
                os.replace(part_path, target)
                manifest["files"][f"{item['root']}/{item['path']}"] = {"size": size, "mtime": mtime}
                summary["downloaded"] += 1
                return "done"
            return "more"
        except Exception as e:
            summary["failed"].append({"path": f"{item['root']}/{item['path']}", "error": f"{type(e).__name__}"})
            print(f"[ERROR] ServerFileDownload: Could not store {item['root']}/{item['path']}: {type(e).__name__}: {e}")
            self._remove_quietly(part_path)
            return "failed"

    ## Starts a file over, up to MAX_RESTARTS_PER_FILE times, then gives up on it.
    def _restart(self, entry, part_path, item, summary):
        self._remove_quietly(part_path)
        entry["restarts"] += 1
        entry["offset"] = 0
        entry.pop("size", None)
        entry.pop("mtime", None)
        if entry["restarts"] > MAX_RESTARTS_PER_FILE:
            summary["failed"].append({"path": f"{item['root']}/{item['path']}", "error": "changed_while_copying"})
            return "failed"
        return "restart"

    ## Removes only this download's own temporary .part file.
    def _remove_quietly(self, path):
        try:
            if os.path.isfile(path) and path.endswith(".part"):
                os.remove(path)
        except OSError:
            pass

    def _check_stop(self):
        if self._stop_requested:
            raise ServerFilesError("closed", "Download stopped.")

    # endregion

# endregion
