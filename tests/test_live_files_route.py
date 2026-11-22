## =====================================================================
## MODULE: tests/test_live_files_route.py
## DESCRIPTION: The login service's /users/live_files route and the Users page checkbox.
## The service runs on 127.0.0.1 with a free port and stand-in user data; no real database is touched.
## =====================================================================

# region Imports

import json
import os
import sys
import threading
import urllib.error
import urllib.request

import pytest

SERVICE_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "login_service")
if SERVICE_FOLDER not in sys.path:
    sys.path.insert(0, SERVICE_FOLDER)

# endregion


# region Service Fixture

USERS = [
    {"username": "boss", "role": "owner", "server_name": "S1", "server_address": "1.1.1.1"},
    {"username": "adam", "role": "admin", "server_name": "S1", "server_address": "1.1.1.1"},
    {"username": "mo", "role": "moderator", "server_name": "S1", "server_address": "1.1.1.1"},
    {"username": "far", "role": "moderator", "server_name": "S2", "server_address": "2.2.2.2"},
]


@pytest.fixture
def service(monkeypatch):
    import main as service_main
    from http.server import ThreadingHTTPServer
    saved = []
    column = {"present": True}
    roles = {"owner-token": ("boss", "owner"), "admin-token": ("adam", "admin")}
    monkeypatch.setattr(service_main, "list_users", lambda: [dict(user) for user in USERS])
    monkeypatch.setattr(service_main, "get_live_file_editing", lambda name: name == "mo")
    monkeypatch.setattr(service_main, "check_session", lambda token: {"username": roles[token][0], "role": roles[token][1]} if token in roles else None)

    def fake_set(name, enabled):
        if not column["present"]:
            return None
        saved.append((name, enabled))
        return any(user["username"] == name for user in USERS)
    monkeypatch.setattr(service_main, "set_live_file_editing", fake_set)
    server = ThreadingHTTPServer(("127.0.0.1", 0), service_main.LoginRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", saved, column
    server.shutdown()
    server.server_close()


def post(base_url, route, fields):
    request = urllib.request.Request(base_url + route, data=json.dumps(fields).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as reply:
            return reply.status, json.loads(reply.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))

# endregion


# region Route Tests

def test_owner_sets_live_files_for_own_server_user(service):
    base_url, saved, column = service
    status, reply = post(base_url, "/users/live_files", {"token": "owner-token", "username": "adam", "enabled": True})
    assert status == 200 and reply["live_file_editing"] is True and saved == [("adam", True)]


def test_admin_is_refused(service):
    base_url, saved, column = service
    status, reply = post(base_url, "/users/live_files", {"token": "admin-token", "username": "mo", "enabled": True})
    assert status == 403 and saved == []


def test_missing_column_fails_closed(service):
    base_url, saved, column = service
    column["present"] = False
    status, reply = post(base_url, "/users/live_files", {"token": "owner-token", "username": "mo", "enabled": True})
    assert status == 409 and "column" in reply["message"] and saved == []


def test_other_server_unknown_user_and_bad_value(service):
    base_url, saved, column = service
    assert post(base_url, "/users/live_files", {"token": "owner-token", "username": "far", "enabled": True})[0] == 403
    assert post(base_url, "/users/live_files", {"token": "owner-token", "username": "nobody", "enabled": True})[0] == 404
    assert post(base_url, "/users/live_files", {"token": "owner-token", "username": "mo", "enabled": "yes"})[0] == 400
    assert post(base_url, "/users/live_files", {"token": "bad", "username": "mo", "enabled": True})[0] == 403
    assert saved == []


def test_user_list_shows_the_flag_to_owners_only(service):
    base_url, saved, column = service
    status, reply = post(base_url, "/users", {"token": "owner-token"})
    assert status == 200 and {user["username"]: user["live_file_editing"] for user in reply["users"]}["mo"] is True
    status, reply = post(base_url, "/users", {"token": "admin-token"})
    assert status == 200 and all("live_file_editing" not in user for user in reply["users"])


def test_set_live_file_editing_without_database_is_none(monkeypatch):
    import user_store
    monkeypatch.setattr(user_store, "DATABASE_URL", "")
    assert user_store.set_live_file_editing("mo", True) is None

# endregion


# region Users Page Checkbox

def test_dialog_checkbox_follows_who_is_editing():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    qapp = QApplication.instance() or QApplication([])
    from features.users.users_page import UserEditDialog
    owner_view = UserEditDialog("mo", "moderator", None, live_file_editing=True, can_set_live_files=True)
    assert owner_view.chk_live_files.isEnabled() and owner_view.chk_live_files.isChecked()
    admin_view = UserEditDialog("mo", "moderator", None, live_file_editing=False, can_set_live_files=False)
    assert not admin_view.chk_live_files.isEnabled() and "owner" in admin_view.chk_live_files.toolTip()
    owner_view.deleteLater()
    admin_view.deleteLater()
    qapp.processEvents()

# endregion
