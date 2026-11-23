## =====================================================================
## MODULE: features/shared/server_actions.py
## DESCRIPTION: The one path every page uses to talk to ZeroGBridge outside the cockpit's own pipe.
##   read_bridge          read-only commands (lists, stats, inventories): no confirmation, run in the background.
##   run_server_action    anything that changes the game or the server:
##                          1. role check (fail closed) and a connected bridge
##                          2. for a major live change (MAJOR_ACTIONS): the ZAH Safety Flow
##                             (preview, the word CONFIRM typed by hand, a 15 second countdown with Cancel)
##                          3. the send, then one audit log line (data/audit/server_actions.jsonl)
##                        Minor actions (give item, messages, teleport, ban/user edits) skip CONFIRM and the delay.
## Tests swap SEND_FUNCTION for a stand-in, so no test can ever reach the live server.
## The bridge password is only ever written to the socket by live_client; it is never logged here.
## =====================================================================

# region Imports

import json
import os
from datetime import datetime

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QHBoxLayout, QVBoxLayout

from features.paths import DATA_DIR

# endregion


# region Constants

## Seconds between typing CONFIRM and the send. Cancel stops it at any moment.
SAFETY_DELAY_SEC = 15

## The word that must be typed, exactly, before the countdown can start.
CONFIRM_WORD = "CONFIRM"

## One JSON line per server action, newest at the bottom. data/ is git-ignored.
AUDIT_FILE = os.path.join(DATA_DIR, "audit", "server_actions.jsonl")

## Lowest role allowed for each action. An action missing from this table is refused (fail closed).
ACTION_ROLES = {
    "player_message": "moderator",
    "player_kick": "moderator",
    "player_ban": "admin",
    "player_unban": "admin",
    "player_warp": "admin",
    "player_inventory": "admin",
    "player_loadout": "admin",
    "give_item": "admin",
    "chat_send": "moderator",
    "chat_warn": "moderator",
    "announce": "moderator",
    "structure_teleport": "admin",
    "structure_destroy": "admin",
    "playfield_unload": "owner",
    "playfield_restart": "owner",
    "playfield_wipe": "owner",
    "multi_broadcast": "admin",
    "alert_ban": "admin",
}

## Major live changes keep CONFIRM and the 15 second delay. Everything else in ACTION_ROLES
## runs at once after the role check, and is still written to the audit log.
## Kick, ban, wipe, stopping or restarting a playfield, and destroying a structure.
## LIVE MODE file uploads (files:put), core upload/reload, and mod install/remove keep their
## own confirmation (upload_flow and the portal) and are not sent through this table yet.
MAJOR_ACTIONS = {
    "player_kick",
    "player_ban",
    "alert_ban",
    "playfield_wipe",
    "playfield_unload",
    "playfield_restart",
    "structure_destroy",
}

## Reply statuses that mean the bridge did what was asked.
OK_STATUSES = {"ok", "sent", "success", "acknowledged", "synced", "loading", "queued"}

## Reply types a write may answer with (ERROR included, so a refusal comes back instead of a timeout).
WRITE_REPLY_TYPES = ("RESPONSE", "API_RESULT", "CONSOLE_RESULT", "ALERT_ACK", "ERROR")

# endregion


# region Cockpit Lookups

## Walks up from a widget to the cockpit (the window that has user_has_role). None when not found.
def find_cockpit(widget):
    try:
        window = widget.window() if widget is not None else None
        return window if callable(getattr(window, "user_has_role", None)) else None
    except Exception:
        return None


## True only when the signed-in role is at least the role the action needs. Unknown action = no.
def user_may(widget, action_key):
    needed_role = ACTION_ROLES.get(action_key)
    cockpit = find_cockpit(widget)
    if needed_role is None or cockpit is None:
        return False
    try:
        return bool(cockpit.user_has_role(needed_role))
    except Exception as e:
        print(f"[ERROR] ServerActions: Role check failed, treated as no: {e}")
        return False


## True only when the cockpit says the bridge is connected right now.
def bridge_is_connected(widget):
    cockpit = find_cockpit(widget)
    return cockpit is not None and getattr(cockpit, "bridge_connected", None) is True


## Short text for a disabled button's tooltip, or "" when the action may be used.
def block_reason(widget, action_key):
    if not user_may(widget, action_key):
        return f"Needs the {ACTION_ROLES.get(action_key, 'unknown')} role or higher."
    if not bridge_is_connected(widget):
        return "Connect to the server first."
    return ""

# endregion


# region Sending

## The real send: one short bridge session per command (live_client). Tests replace SEND_FUNCTION.
def _live_send(command, want_types, profile=None):
    from features.bridge.server_settings import get_active_profile
    from features.zgb_portal.live_client import bridge_request
    return bridge_request(profile or get_active_profile(), command, want_types)


SEND_FUNCTION = _live_send


## One Eleon request line, e.g. api:Request_InGameMessage_AllPlayers {"msg": "Hi"}.
## json.dumps keeps quotes and backslashes in the text safe.
## Messages use these real requests, not the old msg: / msgfaction: / broadcast: / destroystruct: shorthands,
## which only write a log line on the server and send nothing.
def api_command(request_name, params):
    return f"api:{request_name} {json.dumps(params)}"


## HUD message lines for one player, one faction, or everyone.
def message_player_command(entity_id, text):
    return api_command("Request_InGameMessage_SinglePlayer", {"id": int(entity_id), "msg": text})


def message_faction_command(faction_id, text):
    return api_command("Request_InGameMessage_Faction", {"id": int(faction_id), "msg": text})


def message_all_command(text):
    return api_command("Request_InGameMessage_AllPlayers", {"msg": text})


## True when a reply says the command worked.
def reply_ok(reply):
    if not isinstance(reply, dict) or reply.get("type") == "ERROR":
        return False
    if reply.get("ok") is False:
        return False
    return str(reply.get("status", "ok")).strip().lower() in OK_STATUSES


## One plain line explaining a reply, for labels and the audit log.
def reply_text(reply):
    if not isinstance(reply, dict):
        return "no reply"
    detail = reply.get("message") or reply.get("error") or reply.get("status") or reply.get("type")
    return str(detail)[:200]


## Runs a read-only command in the background. on_ok(reply) or on_error(message) run on the window thread.
def read_bridge(command, want_types, on_ok, on_error, profile=None):
    from features.zgb_portal.live_client import run_async
    try:
        run_async(lambda: SEND_FUNCTION(command, want_types, profile), on_ok, lambda kind, message: on_error(message))
    except Exception as e:
        print(f"[ERROR] ServerActions: Read {command.split(':')[0]} failed to start: {e}")
        on_error(str(e))

# endregion


# region Audit Log

## Appends one line to the audit log. A failing audit write is printed, never raised.
def write_audit(widget, action_key, command, result_ok, detail):
    try:
        cockpit = find_cockpit(widget)
        entry = {
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "user": str(getattr(cockpit, "lbl_admin_name", None).text()) if getattr(cockpit, "lbl_admin_name", None) else "--",
            "role": getattr(cockpit, "signed_in_role", None),
            "server": getattr(cockpit, "bridge_server_name", None),
            "action": action_key,
            "command": command if isinstance(command, str) else " ; ".join(command),
            "ok": bool(result_ok),
            "detail": str(detail)[:200],
        }
        os.makedirs(os.path.dirname(AUDIT_FILE), exist_ok=True)
        with open(AUDIT_FILE, "a", encoding="utf-8") as audit_handle:
            audit_handle.write(json.dumps(entry) + "\n")
        print(f"[INFO] ServerActions: Audit {action_key} ok={bool(result_ok)}")
    except Exception as e:
        print(f"[ERROR] ServerActions: Audit line not written: {e}")


## The newest audit lines, newest first. A missing or broken file gives [].
def read_audit(limit=200):
    try:
        with open(AUDIT_FILE, encoding="utf-8") as audit_handle:
            rows = [json.loads(line) for line in audit_handle if line.strip()]
        return list(reversed(rows))[:limit]
    except (OSError, ValueError):
        return []

# endregion


# region Safety Flow Dialog

class SafetyFlowDialog(QDialog):
    """Command preview, then CONFIRM typed by hand, then a countdown with Cancel. Accepted = send."""

    def __init__(self, title, command_preview, explanation="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setObjectName("SafetyFlowDialog")
        self.setMinimumWidth(520)

        ## Readable on its own until the popup theming pass (dark navy, light text).
        self.setStyleSheet("QDialog#SafetyFlowDialog { background: #0e1a26; } QLabel { color: #d8e6f0; } "
                           "QPlainTextEdit, QLineEdit { background: #08121b; color: #7fe3ff; border: 1px solid #2c4a60; } "
                           "QPushButton { color: #d8e6f0; background: #16293a; border: 1px solid #2fa8e0; padding: 6px 14px; } "
                           "QPushButton:disabled { color: #6b7c88; border-color: #2c3e4c; }")
        self.seconds_left = SAFETY_DELAY_SEC
        layout = QVBoxLayout(self)
        lbl_title = QLabel(explanation or "This changes the live server. Check the command below.")
        lbl_title.setWordWrap(True)
        layout.addWidget(lbl_title)

        ## Step 1: the exact command that will be sent.
        layout.addWidget(QLabel("COMMAND PREVIEW"))
        self.txt_preview = QPlainTextEdit(command_preview)
        self.txt_preview.setReadOnly(True)
        self.txt_preview.setFixedHeight(70)
        layout.addWidget(self.txt_preview)

        ## Step 2: type CONFIRM.
        layout.addWidget(QLabel(f"Type {CONFIRM_WORD} to continue:"))
        self.txt_confirm = QLineEdit()
        self.txt_confirm.textChanged.connect(self._on_confirm_typed)
        layout.addWidget(self.txt_confirm)

        ## Step 3: the countdown line and the two buttons.
        self.lbl_countdown = QLabel(f"The command is sent {SAFETY_DELAY_SEC} seconds after START.")
        layout.addWidget(self.lbl_countdown)
        button_row = QHBoxLayout()
        button_row.addStretch()
        self.btn_start = QPushButton("START")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self._start_countdown)
        self.btn_cancel = QPushButton("CANCEL")
        self.btn_cancel.clicked.connect(self._cancel)
        button_row.addWidget(self.btn_start)
        button_row.addWidget(self.btn_cancel)
        layout.addLayout(button_row)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

    def _on_confirm_typed(self, typed_text):
        self.btn_start.setEnabled(typed_text.strip() == CONFIRM_WORD and not self.timer.isActive())

    def _start_countdown(self):
        try:
            if self.txt_confirm.text().strip() != CONFIRM_WORD:
                return
            self.txt_confirm.setEnabled(False)
            self.btn_start.setEnabled(False)
            self.seconds_left = SAFETY_DELAY_SEC
            self.lbl_countdown.setText(f"Sending in {self.seconds_left} s. CANCEL stops it.")
            if self.seconds_left <= 0:
                self.accept()
                return
            self.timer.start()
        except Exception as e:
            print(f"[ERROR] SafetyFlow: Countdown failed: {e}")
            self.reject()

    def _tick(self):
        self.seconds_left -= 1
        if self.seconds_left <= 0:
            self.timer.stop()
            self.accept()
            return
        self.lbl_countdown.setText(f"Sending in {self.seconds_left} s. CANCEL stops it.")

    def _cancel(self):
        self.timer.stop()
        print("[INFO] SafetyFlow: Cancelled. Nothing was sent.")
        self.reject()


## Shows the Safety Flow and returns True only when the countdown finished. Tests replace this.
def ask_safety_flow(parent, title, command_preview, explanation=""):
    dialog = SafetyFlowDialog(title, command_preview, explanation, parent)
    return dialog.exec() == QDialog.DialogCode.Accepted

# endregion


# region Server Action

def run_server_action(widget, action_key, title, command, on_done=None, explanation="", want_types=WRITE_REPLY_TYPES,
                      profile=None, preview=None, gap_sec=0.5, profiles=None):
    """Role check, Safety Flow for a major action, send in the background, audit line, then on_done(ok, reply_or_message).
    Returns False when it stopped before sending (no role, no bridge, cancelled)."""
    try:
        if not command:
            return False
        reason = block_reason(widget, action_key) if profile is None and not profiles else ("" if user_may(widget, action_key) else "no role")
        if reason:
            print(f"[WARN] ServerActions: {action_key} refused before sending: {reason}")
            return False
        if action_key in MAJOR_ACTIONS:
            if not ask_safety_flow(widget, title, preview or (command if isinstance(command, str) else "\n".join(command)), explanation):
                write_audit(widget, action_key, command, False, "cancelled before sending")
                return False

            ## Asked again right before the send, in case the role or the bridge changed during the countdown.
            if not user_may(widget, action_key):
                return False

        def finished(reply):
            ok = reply_ok(reply)
            write_audit(widget, action_key, command, ok, reply_text(reply))
            if on_done:
                on_done(ok, reply)

        def failed(message):
            write_audit(widget, action_key, command, False, message)
            if on_done:
                on_done(False, message)

        ## profiles: the same command goes to several saved servers (BROADCAST TO ALL SERVERS), one after another.
        ## Each server gets its own audit line; one server failing does not stop the others.
        if profiles:
            targets = list(profiles)

            def send_each():
                results = []
                for one_profile in targets:
                    name = str(one_profile.get("server_name", "?"))
                    try:
                        one_reply = SEND_FUNCTION(command, want_types, one_profile)
                    except Exception as send_error:
                        one_reply = {"type": "ERROR", "message": str(send_error)}
                    results.append((name, one_reply))
                return results

            def finished_each(results):
                for name, one_reply in results:
                    write_audit(widget, action_key, command, reply_ok(one_reply), f"{name}: {reply_text(one_reply)}")
                if on_done:
                    on_done(all(reply_ok(one_reply) for name, one_reply in results), results)

            from features.zgb_portal.live_client import run_async
            run_async(send_each, finished_each, lambda kind, message: failed(message))
            return True

        ## A list of commands is sent one after another, gap_sec apart; the first refusal stops the rest.
        if isinstance(command, (list, tuple)):
            commands = list(command)

            def send_all():
                import time
                last_reply = None
                for number, one_command in enumerate(commands):
                    if number:
                        time.sleep(gap_sec)
                    last_reply = SEND_FUNCTION(one_command, want_types, profile)
                    if not reply_ok(last_reply):
                        return last_reply
                return last_reply

            from features.zgb_portal.live_client import run_async
            run_async(send_all, finished, lambda kind, message: failed(message))
            return True
        read_bridge(command, want_types, finished, failed, profile)
        return True
    except Exception as e:
        print(f"[ERROR] ServerActions: {action_key} failed: {e}")
        return False

# endregion
