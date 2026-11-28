## =====================================================================
## MODULE: features/server_files/upload_flow.py
## DESCRIPTION: The three confirmations every server file upload goes through, and the role gate.
##   1. Changes preview: the real diff, Continue or Cancel.
##   2. Online players: a fresh read-only player count; any online player gives a red warning.
##      If the count cannot be read, the upload stops (fail closed).
##   3. Type the file name: the exact file name must be typed, or nothing is sent.
## The ask_* functions are module-level so the tests can answer them without clicking.
## =====================================================================

# region Imports

from PyQt6.QtWidgets import QInputDialog, QLineEdit, QMessageBox

from features.shared.edit_tools import diff_counts


## Reads the online players (read-only plys) for confirmation 2. Tests swap this for a fake.
def fetch_players_for_upload():
    from features.bridge.server_settings import get_active_profile
    from features.zgb_portal.live_client import fetch_players
    return fetch_players(get_active_profile())

# endregion


# region Role Gate

## Asks the cockpit (found by walking up from a widget) whether the signed-in user may write server files.
## No cockpit, or no answer, means no (fail closed).
def user_can_write_server_files(widget):
    try:
        window = widget.window() if widget is not None else None
        check = getattr(window, "can_edit_live_files", None)
        return bool(check()) if callable(check) else False
    except Exception as e:
        print(f"[ERROR] UploadFlow: Role check failed, treated as no: {e}")
        return False


## True only when the cockpit says the bridge is connected right now.
def bridge_is_connected(widget):
    try:
        window = widget.window() if widget is not None else None
        return getattr(window, "bridge_connected", None) is True
    except Exception:
        return False


## True while the cockpit's LIVE MODE switch is on (never saved; off at every start).
def live_mode_on(widget):
    try:
        window = widget.window() if widget is not None else None
        return getattr(window, "live_mode", False) is True
    except Exception:
        return False

# endregion


# region Player Count

## (online count, names) from a plys reply, or (None, []) when it cannot be read (fail closed).
def count_online(players_payload):
    try:
        rows = players_payload.get("player_list") if isinstance(players_payload, dict) else None
        if not isinstance(rows, list):
            return None, []
        online = [row for row in rows if isinstance(row, dict) and str(row.get("status", "")).lower() == "online"]
        return len(online), [str(row.get("name") or row.get("entityId") or "?") for row in online]
    except Exception:
        return None, []

# endregion


# region Confirmations

def ask_changes(parent, file_name, diff_lines):
    """Confirmation 1: shows the diff. True = Continue."""
    added, removed = diff_counts(diff_lines)
    box = QMessageBox(QMessageBox.Icon.Question, "Upload step 1 of 3: changes",
                      f"Upload these changes to {file_name} on the server?\n{added} line(s) added, {removed} line(s) removed.",
                      parent=parent)
    box.setDetailedText("\n".join(line.rstrip("\n") for line in diff_lines))
    btn_continue = box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
    btn_cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(btn_cancel)
    box.exec()
    return box.clickedButton() is btn_continue


def ask_files(parent, file_names, skipped):
    ## Confirmation 1 for blueprints: the file names.
    ## True = Continue.
    count = str(len(file_names))
    text = ("Upload " + count + " file(s) to the server?\n\n" + "\n".join(file_names) + "\n\nEach one differs from the server copy.")
    if skipped:
        text += "\n\nSkipped:\n" + "\n".join(skipped)
    box = QMessageBox(QMessageBox.Icon.Question, "Upload step 1 of 3: files", text, parent=parent)
    accept = QMessageBox.ButtonRole.AcceptRole
    reject = QMessageBox.ButtonRole.RejectRole
    btn_continue = box.addButton("Continue", accept)
    btn_cancel = box.addButton("Cancel", reject)
    box.setDefaultButton(btn_cancel)
    box.exec()
    return box.clickedButton() is btn_continue


def ask_players(parent, online_count, names):
    """Confirmation 2: the online-players warning. True = Continue. None count = stop."""
    if online_count is None:
        QMessageBox.warning(parent, "Upload stopped", "The online player count could not be read, so nothing was sent.")
        return False
    if online_count == 0:
        text = "No players are online right now."
        icon = QMessageBox.Icon.Question
    else:
        shown = ", ".join(names[:10]) + (" and more" if len(names) > 10 else "")
        text = (f"WARNING: {online_count} player(s) are online right now ({shown}).\n"
                "A changed config file can affect them. Continue anyway?")
        icon = QMessageBox.Icon.Warning
    box = QMessageBox(icon, "Upload step 2 of 3: players", text, parent=parent)
    btn_continue = box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
    btn_cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(btn_cancel)
    box.exec()
    return box.clickedButton() is btn_continue


def ask_type_name(parent, file_name):
    """Confirmation 3: the exact file name must be typed. True = it matched."""
    typed, accepted = QInputDialog.getText(parent, "Upload step 3 of 3: confirm",
                                           f"Type the file name to upload it to the server:\n{file_name}",
                                           QLineEdit.EchoMode.Normal, "")
    return bool(accepted) and typed.strip() == file_name

# endregion
