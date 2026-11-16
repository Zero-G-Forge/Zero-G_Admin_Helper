# test_file_menu.py
"""ZAH imports, and the File menu builds without a display or a live bridge."""

import os
import subprocess
import sys

from PyQt6.QtWidgets import QApplication

from features.dashboard.main_cockpit import MainCockpit
from features.dashboard.telemetry_worker import TelemetryWorker
from features.network.server_switch import ServerSwitchDialog
from features.paths import APP_ROOT, DATA_DIR


def _visible(text):
    return text.replace("&", "")


def test_zah_module_imports():
    import ZAH

    assert callable(ZAH.main)
    root = os.path.dirname(os.path.abspath(ZAH.__file__))
    assert os.path.abspath(APP_ROOT) == root
    assert os.path.abspath(DATA_DIR) == os.path.join(root, "data")
    print("[SUCCESS] ZAH.py imported.")


def test_zah_finds_data_dir_from_another_working_directory(tmp_path):
    """Launch-style import: cwd is not the app folder, data/ still is."""
    other = tmp_path / "elsewhere"
    other.mkdir()
    app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    code = r"""
import os, sys, runpy
other, app_root = sys.argv[1], sys.argv[2]
os.chdir(other)
sys.path.insert(0, app_root)
ns = runpy.run_path(os.path.join(app_root, "ZAH.py"), run_name="zah_path_check")
root = os.path.dirname(os.path.abspath(ns["__file__"]))
assert root == os.path.abspath(app_root)
assert os.getcwd() != root
from features.paths import APP_ROOT, DATA_DIR
assert os.path.abspath(APP_ROOT) == root
assert os.path.abspath(DATA_DIR) == os.path.join(root, "data")
assert os.path.abspath(DATA_DIR) != os.path.join(os.getcwd(), "data")
print("[SUCCESS] data/ resolves from the app root, not the working directory")
"""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    subprocess.check_call(
        [sys.executable, "-c", code, str(other), app_root],
        cwd=str(other),
        env=env,
    )


def test_file_menu_lists_server_actions(qapp, monkeypatch):
    """Builds MainCockpit offscreen. Must not open a ZeroGBridge socket."""
    del qapp

    monkeypatch.setattr(TelemetryWorker, "start", lambda self: None)
    monkeypatch.setattr(
        "features.dashboard.main_cockpit.registry_cache_for",
        lambda profile, config_path=None: os.path.join(DATA_DIR, "player_registry_cache.json"),
    )

    window = MainCockpit({
        "input_ip": "127.0.0.1",
        "input_port": "9",
        "input_pass": "menu-test-token",
    })
    try:
        file_menu = None
        for action in window.menuBar().actions():
            if _visible(action.text()) == "File":
                file_menu = action.menu()
                break
        assert file_menu is not None

        labels = [_visible(action.text()) for action in file_menu.actions() if action.text()]
        assert "Log into another server" in labels
        assert "Switch servers" in labels
        assert window.windowTitle() == "Zero-G Admin Helper - Dashboard (127.0.0.1)"
        assert "127.0.0.1:9" in window.telemetry_widget.lbl_target_ip.text()
        print("[SUCCESS] File menu built with Log into another server and Switch servers.")
    finally:
        window.close()


def test_switch_dialog_builds_offscreen(qapp):
    del qapp
    dialog = ServerSwitchDialog(
        [
            {"input_ip": "127.0.0.1", "input_port": "30500", "input_pass": "one"},
            {"input_ip": "127.0.0.1", "input_port": "30501", "input_pass": "two"},
        ],
        active_index=0,
    )
    try:
        assert dialog.server_picker.count() == 2
        assert "active" in dialog.server_picker.itemText(0)
        dialog.server_picker.setCurrentIndex(1)
        dialog._accept_selection()
        assert dialog.selected_profile["input_port"] == "30501"
        assert dialog.result() == dialog.DialogCode.Accepted
    finally:
        dialog.close()


def test_qapplication_exists_for_headless_checks(qapp):
    assert isinstance(qapp, QApplication)
