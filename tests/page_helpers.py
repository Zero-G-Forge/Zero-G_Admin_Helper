## =====================================================================
## TEST HELPERS: tests/page_helpers.py
## Shared stand-ins for the page tests: a fake cockpit, a fake bridge (no network at all), and an
## automatic answer for the Safety Flow. Nothing here can reach a real server.
## =====================================================================

# region Imports

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QApplication, QMainWindow

from features.shared import server_actions
from features.shared.roles import has_role_at_least

# endregion


# region Stand-ins

## Windows built by a test stay referenced here, so Python does not delete them while Qt still uses them.
KEEP_ALIVE = []


class FakeCockpit(QMainWindow):
    ## Stands in for MainCockpit: the signal and the attributes the pages read.
    bridge_status_changed = pyqtSignal(str, bool)

    def __init__(self, role="developer", connected=True):
        super().__init__()
        self.signed_in_role = role
        self.signed_in_live_files = False
        self.bridge_connected = connected
        self.bridge_server_name = "Test"
        self.live_mode = False
        KEEP_ALIVE.append(self)

    def user_has_role(self, needed_role):
        return has_role_at_least(self.signed_in_role, needed_role)


class FakeBridge:
    ## Records every command and answers from a table: {command prefix: reply dict}.
    def __init__(self, replies=None):
        self.sent = []
        self.replies = replies or {}

    def __call__(self, command, want_types, profile=None):
        self.sent.append(command)
        for prefix, reply in self.replies.items():
            if command.startswith(prefix):
                return reply(command) if callable(reply) else reply
        return {"type": "RESPONSE", "status": "Sent"}


def install(monkeypatch, tmp_path, replies=None, safety_answer=True):
    ## Fake bridge, Safety Flow answer, and an audit file in the temporary folder.
    bridge = FakeBridge(replies)
    monkeypatch.setattr(server_actions, "SEND_FUNCTION", bridge)
    monkeypatch.setattr(server_actions, "AUDIT_FILE", str(tmp_path / "audit.jsonl"))
    asked = []
    monkeypatch.setattr(server_actions, "ask_safety_flow",
                        lambda parent, title, preview, explanation="": asked.append(preview) or safety_answer)
    bridge.asked = asked
    return bridge


def settle(qapp):
    ## Lets background reads finish and their answers arrive on the window thread.
    from features.zgb_portal.live_client import wait_for_tasks
    for _ in range(3):
        wait_for_tasks(5000)
        for _ in range(10):
            qapp.processEvents()


def host(page, role="developer", connected=True):
    cockpit = FakeCockpit(role, connected)
    cockpit.setCentralWidget(page)
    cockpit.resize(1300, 800)
    cockpit.show()
    return cockpit


def get_qapp():
    return QApplication.instance() or QApplication([])

# endregion
