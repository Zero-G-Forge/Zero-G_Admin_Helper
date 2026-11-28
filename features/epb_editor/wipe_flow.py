## ==========================================
## ZERO-G ADMIN HELPER - WIPE FLOW
## The steps behind the Wipe playfields button on the EPB
## Editor page. Only a POI wipe is ever sent, never "all"
## or "player" (those remove player bases and ships).
##   1. Pick the playfields (ticks).
##   2. Online players on those playfields: warning.
##   3. Safety Flow: type CONFIRM, then a countdown.
##   4. Send in the background, one result per playfield.
## The ask_* functions are module-level so a test can
## answer them without clicking.
## ==========================================

# region Imports

import time

from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QLabel, QMessageBox, QVBoxLayout)

## Role check, Safety Flow, sending and the audit log.
from features.shared import server_actions

## Runs a function on a background thread.
from features.zgb_portal.live_client import run_async

# endregion


# region Constants

## The only wipe type this flow sends.
WIPE_TYPE = "poi"

## The role and audit key in server_actions (owner and up).
WIPE_ACTION = "playfield_wipe"

## Seconds between two playfields.
GAP_SEC = 0.5

# endregion


# region Command

## One console line, e.g.  con:wipe 'Akua Lo' poi
## A name with spaces goes in single quotes, the same way
## the bridge sends say 'text'.
def wipe_command(name):
    clean = name.replace('"', "").replace("'", "").strip()
    if " " in clean:
        clean = "'" + clean + "'"
    return "con:wipe " + clean + " " + WIPE_TYPE

# endregion


# region Players

## {playfield name: [online player names]} for the picked
## playfields only. None when the plys reply cannot be
## read (the caller stops: fail closed).
def online_on_playfields(players_payload, names):
    rows = None
    if isinstance(players_payload, dict):
        rows = players_payload.get("player_list")
    if not isinstance(rows, list):
        return None
    wanted = {}
    for name in names:
        wanted[name.lower()] = name
    found = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("status", "")).lower() != "online":
            continue
        where = str(row.get("playfield", "")).lower()
        if where in wanted:
            who = str(row.get("name") or "?")
            found.setdefault(wanted[where], []).append(who)
    return found

# endregion


# region Results Popup

## The upload results popup. True only when the Wipe
## playfields button was clicked. The button only exists
## when at least one file went up.
def ask_results(parent, text, can_wipe):
    icon = QMessageBox.Icon.Information
    title = "Upload results"
    box = QMessageBox(icon, title, text, parent=parent)
    ok_role = QMessageBox.ButtonRole.AcceptRole
    box.addButton("OK", ok_role)
    wipe_button = None
    if can_wipe:
        role = QMessageBox.ButtonRole.ActionRole
        wipe_button = box.addButton("Wipe playfields", role)
    box.exec()
    if wipe_button is None:
        return False
    return box.clickedButton() is wipe_button

# endregion


# region Pick Playfields

## Step 1: the playfields that use the uploaded prefabs,
## each with a tick (all off at first). Returns the ticked
## names, or [] when cancelled or nothing is ticked.
def ask_playfields(parent, rows, missing):
    if not rows:
        text = "No playfield uses these prefabs."
        title = "Wipe playfields"
        QMessageBox.information(parent, title, text)
        return []
    dialog = QDialog(parent)
    dialog.setWindowTitle("Wipe playfields (POIs only)")
    layout = QVBoxLayout(dialog)
    text = ("Tick the playfields to wipe. Only POIs are wiped: player bases and ships stay. Every POI on a ticked playfield comes back fresh from its prefab, when that playfield next loads.")
    label = QLabel(text)
    label.setWordWrap(True)
    layout.addWidget(label)
    boxes = []
    for name, prefabs in rows:
        used = ", ".join(prefabs)
        box = QCheckBox(name + "   (" + used + ")")
        layout.addWidget(box)
        boxes.append((box, name))
    if missing:
        lost = ", ".join(missing)
        note = "No playfield found for: " + lost
        layout.addWidget(QLabel(note))
    standard = QDialogButtonBox.StandardButton
    both = standard.Ok | standard.Cancel
    buttons = QDialogButtonBox(both)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return []
    return [name for box, name in boxes if box.isChecked()]

# endregion
