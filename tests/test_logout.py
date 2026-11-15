# test_logout.py
"""Log Out closes the ZeroGBridge session and opens the login flow again."""

import os

from PyQt6.QtWidgets import QDialog

from features.auth.persistence import (
    check_for_persistent_user,
    create_user_profile,
    is_session_valid,
    save_account_data,
    save_persistence_state,
    save_session,
)
from features.dashboard.main_cockpit import MainCockpit
from features.loading.loading_screen import ApplicationLoader
from features.network.server_config import add_server_profile
from features.paths import DATA_DIR
from tests.mock_bridge import MockBridge


def _visible(text):
    return text.replace("&", "")


def _logout_action(window):
    for action in window.menuBar().actions():
        menu = action.menu()
        if menu is None or _visible(action.text()) != "File":
            continue
        for item in menu.actions():
            if _visible(item.text()) == "Log Out of ZAH":
                return item
    return None


def test_logout_closes_session_and_returns_to_login(qapp, tmp_path, monkeypatch):
    del qapp
    bridge = MockBridge("logout-token").start()
    config_path = tmp_path / "server_config.json"
    session_path = tmp_path / "session.json"
    users_path = tmp_path / "users.json"
    window = None
    try:
        add_server_profile(
            "127.0.0.1",
            str(bridge.port),
            "logout-token",
            config_path=str(config_path),
        )
        saved_profiles = config_path.read_text(encoding="utf-8")
        saved_path = str(config_path)

        def _resolve(path=None):
            # Default reads and writes stay on the temp profile file.
            if path:
                return path
            return saved_path

        monkeypatch.setattr("features.network.server_config._resolve_config_path", _resolve)

        monkeypatch.setattr("features.auth.persistence.USERS_FILE", str(users_path))
        monkeypatch.setattr("features.auth.persistence.file_path", str(users_path))
        monkeypatch.setattr("features.auth.persistence.SESSION_FILE", str(session_path))
        save_account_data(create_user_profile("admin", "passkey", "Admin", "0"))
        save_persistence_state("admin", True)
        save_session("admin")
        assert is_session_valid()
        assert check_for_persistent_user()

        monkeypatch.setattr(
            "features.dashboard.main_cockpit.registry_cache_for",
            lambda profile, config_path=None: os.path.join(DATA_DIR, "player_registry_cache.json"),
        )
        monkeypatch.setattr(
            "features.loading.loading_screen.is_network_ready",
            lambda *args, **kwargs: False,
        )

        seen = {}

        def _login_exec(self):
            seen["login"] = True
            seen["bridge_closed"] = bridge.wait_until_all_closed(timeout=2.0)
            seen["session_cleared"] = not os.path.exists(session_path)
            return QDialog.DialogCode.Rejected

        def _wizard_exec(self):
            seen["wizard"] = True
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr("features.loading.loading_screen.LoginWindow.exec", _login_exec)
        monkeypatch.setattr(
            "features.loading.loading_screen.NetworkWizardOverlay.exec",
            _wizard_exec,
        )

        original_start = ApplicationLoader.start_boot_sequence

        def _fast_start(self):
            original_start(self)
            self.boot_timer.setInterval(1)

        monkeypatch.setattr(ApplicationLoader, "start_boot_sequence", _fast_start)

        window = MainCockpit({
            "input_ip": "127.0.0.1",
            "input_port": str(bridge.port),
            "input_pass": "logout-token",
        })
        assert bridge.wait_until_authenticated()
        assert bridge.wait_for_command("plys")

        logout = _logout_action(window)
        assert logout is not None
        logout.trigger()

        assert seen.get("login") is True
        assert seen.get("bridge_closed") is True
        assert seen.get("session_cleared") is True
        assert seen.get("wizard") is not True
        assert is_session_valid() is False
        assert check_for_persistent_user() is False
        assert config_path.read_text(encoding="utf-8") == saved_profiles
        assert "logout-token" in saved_profiles
        print("[SUCCESS] Log Out closed the bridge session and returned to the login window.")
    finally:
        if window is not None:
            window.close()
        bridge.stop()
