# test_log_into_server.py
"""File > Log into another server checks the game port, then lists the profile."""

import os
import socket
import threading

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from features.dashboard.main_cockpit import MainCockpit
from features.network.connection import NetworkWizardOverlay
from features.network.server_config import list_server_profiles
from features.network.server_switch import ServerLoginDialog, ServerNameDialog, ServerSwitchDialog
from features.paths import DATA_DIR
from tests.mock_bridge import MockBridge


class GamePort:
    """Accepts TCP and closes it. This is the game-port live check, not ZeroGBridge."""

    def __init__(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="game-port", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.close()
            except OSError:
                pass

    def stop(self):
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=1.0)


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
            elif isinstance(widget, ServerNameDialog) and widget.isVisible():
                if widget.property("test_handled"):
                    continue
                widget.setProperty("test_handled", True)
                if state.get("server_name"):
                    widget.name_input.setText(state["server_name"])
                widget.btn_save.click()
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


def _login_then_list_switch(qapp, tmp_path, monkeypatch, ip, port, token, save_anyway, server_name=""):
    """
    Opens the real File actions against a home bridge on bridge_port.
    The wizard port is the game port and is not used for the bridge handshake.
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
        add_server_profile("127.0.0.1", "30004", "home-token")

        window = MainCockpit({
            "input_ip": "127.0.0.1",
            "input_port": "30004",
            "input_pass": "home-token",
            "bridge_port": str(home.port),
        })
        assert home.wait_until_authenticated()

        state = {
            "ip": ip,
            "port": str(port),
            "token": token,
            "save_anyway": save_anyway,
            "server_name": server_name,
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


def test_login_success_saves_game_port_and_lists_it(qapp, tmp_path, monkeypatch):
    game = GamePort()
    try:
        state = _login_then_list_switch(
            qapp, tmp_path, monkeypatch, "127.0.0.1", game.port, "beta-token", True, server_name="Beta"
        )
        expected = (
            f"Game server 127.0.0.1:{game.port} is up. The profile was saved. "
            f"ZeroGBridge will connect to 127.0.0.1:30500 in the background."
        )
        assert expected in state["messages"]
        assert any(label.replace(" (active)", "") == "Beta - 127.0.0.1" for label in state["labels"])
        assert all(str(game.port) not in label and "30500" not in label for label in state["labels"])
        saved, _active = list_server_profiles()
        match = [
            entry for entry in saved
            if entry.get("input_port") == str(game.port)
        ]
        assert match
        assert match[0]["bridge_port"] == "30500"
        assert match[0]["input_pass"] == "beta-token"
        assert match[0]["server_name"] == "Beta"
        print("[SUCCESS] Game port check saved the profile and Switch servers listed it.")
    finally:
        game.stop()


def test_login_game_port_refused_save_anyway_lists_the_server(qapp, tmp_path, monkeypatch):
    closed = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    closed.bind(("127.0.0.1", 0))
    refused_port = closed.getsockname()[1]
    closed.close()
    state = _login_then_list_switch(
        qapp, tmp_path, monkeypatch, "127.0.0.1", refused_port, "refused-token", True
    )
    assert f"Could not reach game server 127.0.0.1:{refused_port}: host unreachable" in state["messages"]
    assert "Save this server anyway?" in state["questions"]
    assert any(label.replace(" (active)", "") == "127.0.0.1" for label in state["labels"])
    assert all(str(refused_port) not in label and "30500" not in label for label in state["labels"])
    saved, _active = list_server_profiles()
    match = [entry for entry in saved if entry.get("input_port") == str(refused_port)]
    assert match
    assert match[0]["bridge_port"] == "30500"
    assert match[0]["input_pass"] == "refused-token"
    print("[SUCCESS] A down game port offered Save this server anyway? and the profile was listed.")


def test_login_game_port_timeout_save_anyway_lists_the_server(qapp, tmp_path, monkeypatch):
    state = _login_then_list_switch(
        qapp, tmp_path, monkeypatch, "192.0.2.1", 9, "timeout-token", True
    )
    assert "Could not reach game server 192.0.2.1:9: connection timed out" in state["messages"]
    assert "Save this server anyway?" in state["questions"]
    assert any(label.replace(" (active)", "") == "192.0.2.1" for label in state["labels"])
    assert all(":9" not in label and "30500" not in label for label in state["labels"])
    saved, _active = list_server_profiles()
    match = [entry for entry in saved if entry.get("input_ip") == "192.0.2.1"]
    assert match
    assert match[0]["input_port"] == "9"
    assert match[0]["bridge_port"] == "30500"
    print("[SUCCESS] Game-port timeout showed the error and saved the server anyway.")
