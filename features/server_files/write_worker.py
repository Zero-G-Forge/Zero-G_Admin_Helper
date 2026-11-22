## =====================================================================
## MODULE: features/server_files/write_worker.py
## DESCRIPTION: The steps that WRITE to the server through ZeroGBridge core 1.6.2, run on a background thread.
##   put_file      files:put in chunks: replaces one existing file; the bridge backs up the old one first
##                 and refuses when the server copy no longer matches base_sha256.
##   upload_core   coreupload:put: the .pdb (when there is one) and then the .dll go into the mod's Updates/.
##                 Nothing loads until a separate, confirmed hot:reload.
##   fetch_file    files:get for one file (LIVE MODE opens the server's current copy).
## The confirmations and the role gate happen on the page BEFORE a worker is started (upload_flow.py).
## The bridge password is only ever written to the socket by ServerFilesSession; it is never printed.
## =====================================================================

# region Imports

import base64
import hashlib
import os
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from features.bridge.server_settings import get_active_profile
from features.server_files.file_client import ServerFilesError, ServerFilesSession

# endregion


# region Constants

## Raw bytes per chunk. The bridge accepts up to 128 KB; this stays under it.
CHUNK_BYTES = 120 * 1024

## Most files:get calls for one file before giving up (16 MB / 192 KB is about 86).
MAX_GET_CALLS = 120

## Threads still running, so they outlive the page that started them.
RUNNING_WRITES = []

# endregion


# region Steps

def put_file(session, root, path, data, base_sha256, report=None):
    """Sends data in chunks with files:put. Returns the final reply ({done, size, sha256, backup})."""
    total = len(data)
    sha_text = hashlib.sha256(data).hexdigest()
    offset = 0
    reply = None
    while True:
        chunk = data[offset:offset + CHUNK_BYTES]
        reply = session.request("put", {
            "root": root, "path": path, "offset": offset, "total": total,
            "sha256": sha_text, "base_sha256": base_sha256,
            "data": base64.b64encode(chunk).decode("ascii"),
        })
        offset += len(chunk)
        if report:
            report(min(offset, total), total, f"Uploading {path.split('/')[-1]}")
        if reply.get("done") is True:
            return reply
        if offset >= total:
            raise ServerFilesError("protocol", "The server did not confirm the upload.")
        if reply.get("next_offset") != offset:
            raise ServerFilesError("protocol", "The server lost track of the upload.")


def upload_core(session, dll_path, report=None):
    """Sends ZeroGBridge.Core.pdb (when it sits next to the dll) and then the dll. Returns the dll's final reply."""
    pdb_path = os.path.splitext(dll_path)[0] + ".pdb"
    if os.path.isfile(pdb_path):
        with open(pdb_path, "rb") as file_handle:
            _send_core_part(session, "pdb", file_handle.read(), report)
    with open(dll_path, "rb") as file_handle:
        return _send_core_part(session, "dll", file_handle.read(), report)


def _send_core_part(session, which, data, report):
    total = len(data)
    sha_text = hashlib.sha256(data).hexdigest()
    offset = 0
    while True:
        chunk = data[offset:offset + CHUNK_BYTES]
        reply = session.request("put", {
            "file": which, "offset": offset, "total": total, "sha256": sha_text,
            "data": base64.b64encode(chunk).decode("ascii"),
        }, prefix="coreupload")
        offset += len(chunk)
        if report:
            report(min(offset, total), total, f"Uploading core {which}")
        if reply.get("done") is True:
            return reply
        if offset >= total:
            raise ServerFilesError("protocol", "The server did not confirm the core upload.")


def fetch_file(session, root, path):
    """Reads one file from the server with files:get. Returns its bytes."""
    received = bytearray()
    for _ in range(MAX_GET_CALLS):
        reply = session.request("get", {"root": root, "items": [{"path": path, "offset": len(received)}]})
        row = (reply.get("files") or [{}])[0]
        if row.get("error"):
            raise ServerFilesError("refused", f"The server would not send the file: {row['error']}.", row["error"])
        if row.get("deferred"):
            continue
        received.extend(base64.b64decode(row.get("data") or ""))
        if row.get("eof") is True:
            return bytes(received)
    raise ServerFilesError("protocol", "The file did not finish arriving.")

# endregion


# region Worker

class ServerWriteWorker(QThread):
    """Runs one job(session, report) on a background thread with its own bridge session."""

    ## done bytes, total bytes, short text.
    progress = pyqtSignal(int, int, str)

    ## The job's result dictionary.
    finished_ok = pyqtSignal(dict)

    ## kind ("refused", "offline", ...), bridge error code ("" when none), plain message.
    failed = pyqtSignal(str, str, str)

    def __init__(self, job, profile_provider=None, parent=None):
        super().__init__(parent)
        self.job = job

        ## Tests hand in their own provider; the real app reads the active server profile.
        self.profile_provider = profile_provider or get_active_profile

    def run(self):
        try:
            profile = self.profile_provider()
            if not isinstance(profile, dict):
                raise ServerFilesError("config", "No active server is saved in ZAH.")
            with ServerFilesSession(profile) as session:
                result = self.job(session, self.progress.emit)
            self.finished_ok.emit(result if isinstance(result, dict) else {"result": result})
        except ServerFilesError as e:
            print(f"[ERROR] ServerWrite: {e.kind}: {e}")
            self.failed.emit(e.kind, e.code or "", str(e))
        except Exception as e:
            print(f"[ERROR] ServerWrite: Unexpected {type(e).__name__}: {e}")
            print(traceback.format_exc())
            self.failed.emit("exception", "", f"Stopped by an unexpected error ({type(e).__name__}).")


def start_write_worker(worker):
    """Keeps the thread alive in RUNNING_WRITES until it ends, then starts it."""
    RUNNING_WRITES.append(worker)
    worker.finished.connect(lambda w=worker: RUNNING_WRITES.remove(w) if w in RUNNING_WRITES else None)
    worker.start()
    return worker

# endregion
