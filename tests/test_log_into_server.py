# test_log_into_server.py
"""File > Log into another server, then File > Switch servers, against the mock bridge."""

import os

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from features.dashboard.main_cockpit import MainCockpit
from features.network.connection import NetworkWizardOverlay
from features.network.server_config import list_server_profiles
from features.network.server_switch import ServerLoginDialog, ServerSwitchDialog
from features.paths import DATA_DIR
from tests.mock_bridge import MockBridge


def _visible(text):
    return text.replace("&", "")


def _menu_action(window, label):
    for action in window.menuBar().actions():
        menu = action.menu()
        if menu is None or _visible(action.text()) != "File":
            continue
        for item in menu.actions():
            if _visible(item.text()) == label:
                return item
    return None


def _start_driver(state):
    """Clicks the real wizard, result dialog, and switch list while their event loops run."""

    def pump():
        app = QApplication.instance()
        if app is None:
            return
        for widget in app.allWidgets():
            if isinstance(widget, NetworkWizardOverlay) and widget.isVisible():
                if widget.property("test_handled"):
                    continue
                widget.setProperty("test_handled", True)
                widget.input_ip.setText(state["ip"])
                widget.input_port.setText(state["port"])
                widget.input_pass.setText(state["token"])
                widget.btn_accept.click()
            elif isinstance(widget, ServerLoginDialog) and widget.isVisible():
                if widget.property("test_handled"):
                    continue
                widget.setProperty("test_handled", True)
                state["messages"].append(widget.lbl_message.text())
                if widget.lbl_question is not None:
                    state["questions"].append(widget.lbl_question.text())
                if widget.ask_to_save:
                    if state["save_anyway"]:
                        widget.btn_save.click()
                    else:
                        widget.btn_cancel.click()
                elif widget.btn_ok is not None:
                    widget.btn_ok.click()
            elif (
                state.get("capture_switch")
                and isinstance(widget, ServerSwitchDialog)
                and widget.isVisible()
            ):
                if widget.property("test_handled"):
                    continue
                widget.setProperty("test_handled", True)
                state["labels"] = [
                    widget.server_picker.itemText(index)
                    for index in range(widget.server_picker.count())
                ]
                widget.btn_cancel.click()

    timer = QTimer()
    timer.timeout.connect(pump)
    timer.start(20)
    return timer


def _login_then_list_switch(qapp, tmp_path, monkeypatch, target, token, save_anyway):
    """
    Opens the real File actions.
    Returns the dialog messages and the Switch servers labels.
    """
    del qapp
    home = MockBridge("home-token").start()
    config_path = tmp_path / "server_config.json"
    window = None
    timer = None
    try:
        monkeypatch.setattr(
            "features.network.server_config._resolve_config_path",
            lambda path=None: path if path else str(config_path),
        )
        monkeypatch.setattr(
            "features.dashboard.main_cockpit.registry_cache_for",
            lambda profile, config_path=None: os.path.join(DATA_DIR, "player_registry_cache.json"),
        )
        from features.network.server_config import add_server_profile
        add_server_profile("127.0.0.1", str(home.port), "home-token")

        window = MainCockpit({
            "input_ip": "127.0.0.1",
            "input_port": str(home.port),
            "input_pass": "home-token",
        })
        assert home.wait_until_authenticated()

        state = {
            "ip": "127.0.0.1",
            "port": str(target.port),
            "token": token,
            "save_anyway": save_anyway,
            "messages": [],
            "questions": [],
            "labels": [],
            "capture_switch": False,
        }
        timer = _start_driver(state)
        login_action = _menu_action(window, "Log into another server")
        assert login_action is not None
        login_action.trigger()

        state["capture_switch"] = True
        switch_action = _menu_action(window, "Switch servers")
        assert switch_action is not None
        switch_action.trigger()
        return state
    finally:
        if timer is not None:
            timer.stop()
        if window is not None:
            window.close()
        home.stop()


def test_login_success_shows_the_server_in_switch_list(qapp, tmp_path, monkeypatch):
    target = MockBridge("beta-token").start()
    try:
        state = _login_then_list_switch(qapp, tmp_path, monkeypatch, target, "beta-token", True)
        assert any(message.startswith(f"Connected to 127.0.0.1:{target.port}.") for message in state["messages"])
        assert any(f"127.0.0.1:{target.port}" in label for label in state["labels"])
        saved, _active = list_server_profiles()
        assert any(entry.get("input_pass") == "beta-token" for entry in saved)
        print("[SUCCESS] Auth success saved the server and Switch servers listed it.")
    finally:
        target.stop()


def test_login_auth_failure_save_anyway_lists_the_server(qapp, tmp_path, monkeypatch):
    target = MockBridge("good-token").start()
    try:
        state = _login_then_list_switch(qapp, tmp_path, monkeypatch, target, "wrong-token", True)
        assert f"Authentication was rejected for 127.0.0.1:{target.port}." in state["messages"]
        assert "Save this server anyway?" in state["questions"]
        assert any(f"127.0.0.1:{target.port}" in label for label in state["labels"])
        saved, _active = list_server_profiles()
        assert any(
            entry.get("input_ip") == "127.0.0.1" and entry.get("input_port") == str(target.port)
            for entry in saved
        )
        print("[SUCCESS] Auth failure offered Save this server anyway? and the profile was listed.")
    finally:
        target.stop()


def test_login_timeout_save_anyway_lists_the_server(qapp, tmp_path, monkeypatch):
    target = MockBridge("unused-token", silent=True).start()
    try:
        state = _login_then_list_switch(qapp, tmp_path, monkeypatch, target, "timeout-token", True)
        expected = f"Could not reach 127.0.0.1:{target.port}: connection timed out"
        assert expected in state["messages"]
        assert "Save this server anyway?" in state["questions"]
        assert any(f"127.0.0.1:{target.port}" in label for label in state["labels"])
        saved, _active = list_server_profiles()
        assert any(entry.get("input_pass") == "timeout-token" for entry in saved)
        print("[SUCCESS] Timeout showed the reachability error and saved the server anyway.")
    finally:
        target.stop()
