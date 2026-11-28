## =====================================================================
## MODULE: features/multi_server/server_monitor.py
## DESCRIPTION: Read-only poll of every saved server (data/server_config.json) for the SERVERS page.
## Each poll asks hot:status, plys and api:Request_Dedi_Stats over ONE short connection (bridge_request_many).
## Nothing here changes a server, and input_pass (the auth token) is never printed.
## =====================================================================

# region Imports

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from features.shared import server_actions
from features.dashboard.dashboard_page import is_flagged

# endregion


# region Constants

## Seconds between polls.
POLL_SEC = 30

## Test hooks: the saved server list and the hot:status call.
def _list_profiles():
    from features.zgb_portal.server_config import list_server_profiles
    return list_server_profiles()[0]


def _fetch_status(profile):
    from features.zgb_portal.live_client import fetch_status
    return fetch_status(profile)


## The three polls over one login. Used only while STATUS_FUNCTION and SEND_FUNCTION are the real ones.
def _ask_all(profile):
    from features.zgb_portal import live_client
    return live_client.bridge_request_many(profile, [live_client.hot_item("status"),
                                                     ("plys", "PLAYER_CACHE"),
                                                     ("api:Request_Dedi_Stats", ("API_RESULT", "ERROR"))])


LIST_PROFILES = _list_profiles
STATUS_FUNCTION = _fetch_status
MANY_FUNCTION = _ask_all

# endregion


# region Poll

## Reads one server. Returns a plain dict the page can draw; "online" is False when nothing answered.
def poll_server(profile):
    result = {"name": str(profile.get("server_name", "?")), "profile": profile, "online": False, "core": "--",
              "players_online": None, "players_total": None, "fps": None, "mem": None, "uptime": None, "flagged": []}
    ## One login for all three reads, unless a test replaced the hooks (then each goes through its own hook).
    replies = None
    if STATUS_FUNCTION is _fetch_status and server_actions.SEND_FUNCTION is server_actions._live_send:
        try:
            replies = MANY_FUNCTION(profile)
        except Exception as e:
            print(f"[WARN] ServerMonitor: {result['name']} status failed: {type(e).__name__}")
            return result

    ## The reply for one of the three reads: from the shared login, or from its own call.
    def reply_for(index, own_call):
        if replies is None:
            return own_call()
        if isinstance(replies[index], Exception):
            raise replies[index]
        return replies[index]

    try:
        from features.zgb_portal.data_source import parse_status
        state = parse_status(reply_for(0, lambda: STATUS_FUNCTION(profile)), profile)
        result["core"] = state.core_release or state.core_version or "--"
        result["online"] = True
    except Exception as e:
        print(f"[WARN] ServerMonitor: {result['name']} status failed: {type(e).__name__}")
        return result
    try:
        players = reply_for(1, lambda: server_actions.SEND_FUNCTION("plys", "PLAYER_CACHE", profile))
        rows = [row for row in (players or {}).get("player_list") or [] if isinstance(row, dict)]
        result["players_total"] = len(rows)
        result["players_online"] = sum(1 for row in rows if row.get("status") == "Online")
        result["flagged"] = [str(row.get("name", "?")) for row in rows if is_flagged(row)]
    except Exception as e:
        print(f"[WARN] ServerMonitor: {result['name']} plys failed: {type(e).__name__}")
    try:
        stats = reply_for(2, lambda: server_actions.SEND_FUNCTION("api:Request_Dedi_Stats", ("API_RESULT", "ERROR"), profile))
        data = (stats or {}).get("data") or {}
        for key in ("fps", "mem", "uptime"):
            if isinstance(data.get(key), (int, float)):
                result[key] = data[key]
    except Exception as e:
        print(f"[WARN] ServerMonitor: {result['name']} stats failed: {type(e).__name__}")
    return result


def poll_all():
    return [poll_server(profile) for profile in LIST_PROFILES()]

# endregion


# region ServerMonitor Class

class ServerMonitor(QObject):
    """Polls every saved server in the background. servers_updated carries the list of results."""

    servers_updated = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.results = []
        self.busy = False
        self.timer = QTimer(self)
        self.timer.setInterval(POLL_SEC * 1000)
        self.timer.timeout.connect(self.poll_now)

    def start(self):
        try:
            if not self.timer.isActive():
                self.timer.start()
            self.poll_now()
        except Exception as e:
            print(f"[ERROR] ServerMonitor: Could not start: {e}")

    def stop(self):
        self.timer.stop()

    def poll_now(self):
        try:
            if self.busy:
                return
            self.busy = True
            from features.zgb_portal.live_client import run_async
            run_async(poll_all, self._on_polled, self._on_failed)
        except Exception as e:
            self.busy = False
            print(f"[ERROR] ServerMonitor: Poll failed to start: {e}")

    def _on_polled(self, results):
        self.busy = False
        self.results = list(results)
        self.servers_updated.emit(self.results)

    def _on_failed(self, kind, message):
        self.busy = False
        print(f"[ERROR] ServerMonitor: Poll failed: {message}")

    def online_count(self):
        return sum(1 for result in self.results if result.get("online"))

# endregion
