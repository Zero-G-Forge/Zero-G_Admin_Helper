## =====================================================================
## MODULE: features/server_files/edit_store.py
## DESCRIPTION: Where the editors keep their edited copies, and the backups SAVE makes, on this PC.
## The downloaded file is never changed by SAVE, so the Changes Preview can always compare against it:
##   data/server_files/<scenario>/<root>/<path>               the downloaded copy (made by the download)
##   data/server_files/<scenario>/_edits/<root>/<path>        the edited copy (made by SAVE)
##   data/server_files/<scenario>/_backups/<root>/<path>.<yyyyMMdd-HHmmss>.bak   the edited copy before each SAVE
##   data/server_files/<scenario>/_edits/_bases.json          sha256 of the downloaded copy each edit started from
## Nothing here deletes a file. Writes go to a .part file first and are swapped in with os.replace,
## so a crash never leaves a half-written copy.
## =====================================================================

# region Imports

import hashlib
import json
import os
from datetime import datetime

from features.server_files.file_store import local_target_path, load_manifest, save_manifest

# endregion


# region Constants

EDITS_FOLDER = "_edits"
BACKUPS_FOLDER = "_backups"
BASES_FILE = "_bases.json"

# endregion


# region Paths

## Key of one file inside a scenario folder, e.g. "save/Content/Configuration/ItemsConfig.ecf".
def entry_key(entry):
    return entry["root"] + "/" + entry["path"]


## Full path of the edited copy, or None when the entry's path is unsafe.
def edit_path(folder, entry):
    return local_target_path(os.path.join(folder, EDITS_FOLDER, entry["root"]), entry["path"])


def has_edit(folder, entry):
    path = edit_path(folder, entry) if folder else None
    return bool(path) and os.path.isfile(path)

# endregion


# region Reading

## The text to show in the editor: the edited copy when there is one, else the downloaded copy.
## Returns (text, came_from_edit).
def load_editor_text(folder, entry):
    path = edit_path(folder, entry) if folder else None
    if path and os.path.isfile(path):
        return read_text(path), True
    return read_text(entry["full"]), False


## Reads a text file the way the editors do: UTF-8 with odd bytes replaced, line ends as \n.
def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as file_handle:
        return file_handle.read()


## "\r\n" when the file uses Windows line ends (the server's files do), else "\n".
def detect_newline(path):
    try:
        with open(path, "rb") as file_handle:
            sample = file_handle.read(65536)
        return "\r\n" if b"\r\n" in sample else "\n"
    except OSError:
        return "\n"


## sha256 of a file's bytes as 64 lower-case hex characters.
def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file_handle:
        for block in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


## The bytes an upload sends: the text encoded as UTF-8 with the downloaded file's line ends.
def text_to_bytes(text, newline):
    return text.replace("\r\n", "\n").replace("\n", newline).encode("utf-8")

# endregion


# region Saving

## SAVE: writes the edited text to the edited copy. If an edited copy already exists, it is copied to
## _backups first. Returns {"saved": path, "backup": path or None}. Raises OSError/ValueError on failure.
def save_edit(folder, entry, text):
    target = edit_path(folder, entry)
    if target is None:
        raise ValueError("unsafe path")
    backup = None
    if os.path.isfile(target):
        backup = backup_file(folder, entry, target)
    else:

        ## First save of this file: remember which downloaded copy the edit started from.
        backup = backup_file(folder, entry, entry["full"])
        _remember_base(folder, entry, file_sha256(entry["full"]))
    write_text_atomic(target, text, detect_newline(entry["full"]))
    return {"saved": target, "backup": backup}


## Copies a file to _backups/<root>/<path>.<stamp>.bak (a number is added if that name exists). Returns the backup path.
def backup_file(folder, entry, source_path):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = local_target_path(os.path.join(folder, BACKUPS_FOLDER, entry["root"]), entry["path"] + "." + stamp)
    if base is None:
        raise ValueError("unsafe path")
    backup = base + ".bak"
    number = 2
    while os.path.exists(backup):
        backup = f"{base}_{number}.bak"
        number += 1
    os.makedirs(os.path.dirname(backup), exist_ok=True)
    with open(source_path, "rb") as source, open(backup, "xb") as copy:
        copy.write(source.read())
    return backup


## Writes text through a .part file and swaps it in with os.replace (one step).
def write_text_atomic(target, text, newline):
    os.makedirs(os.path.dirname(target), exist_ok=True)
    part = target + ".part"
    with open(part, "wb") as file_handle:
        file_handle.write(text_to_bytes(text, newline))
    os.replace(part, target)

# endregion


# region Upload Bookkeeping

## The sha256 the server copy must still have for an upload: the downloaded copy the edit started from.
## Falls back to the downloaded copy as it is now.
def base_sha256(folder, entry):
    bases = _load_bases(folder)
    return bases.get(entry_key(entry)) or file_sha256(entry["full"])


## After a successful upload the server has the new text, so the downloaded copy is brought up to date
## (its old version is backed up first), the base becomes the new hash, and the manifest entry is marked
## so the next download fetches the file again. The edited copy stays as it is (never deleted).
def record_upload(folder, entry, uploaded_bytes):
    backup_file(folder, entry, entry["full"])
    part = entry["full"] + ".part"
    with open(part, "wb") as file_handle:
        file_handle.write(uploaded_bytes)
    os.replace(part, entry["full"])
    _remember_base(folder, entry, hashlib.sha256(uploaded_bytes).hexdigest())
    manifest = load_manifest(folder)
    manifest["files"][entry_key(entry)] = {"size": len(uploaded_bytes), "mtime": ""}
    save_manifest(folder, manifest)

## Before an editor changes a downloaded file in place, this
## remembers the server's version of it (its sha256), once.
## UPLOAD later uses it as the base the server
## must still match.
def remember_original(folder, entry):
    if entry_key(entry) not in _load_bases(folder):
        sha = file_sha256(entry["full"])
        _remember_base(folder, entry, sha)


def _load_bases(folder):
    try:
        with open(os.path.join(folder, EDITS_FOLDER, BASES_FILE), encoding="utf-8") as file_handle:
            bases = json.load(file_handle)
        return bases if isinstance(bases, dict) else {}
    except (OSError, ValueError):
        return {}


def _remember_base(folder, entry, sha_text):
    bases = _load_bases(folder)
    bases[entry_key(entry)] = sha_text
    path = os.path.join(folder, EDITS_FOLDER, BASES_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".part", "w", encoding="utf-8") as file_handle:
        json.dump(bases, file_handle, indent=1)
    os.replace(path + ".part", path)

# endregion
