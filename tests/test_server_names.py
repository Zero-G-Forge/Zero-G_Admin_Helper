# test_server_names.py
"""Server display names, switch-list labels, and themed dialog buttons."""

import json

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

from features.network.server_config import (
    get_active_profile,
    list_server_profiles,
    set_server_name,
    switch_list_label,
)
from features.network.server_switch import ServerNameDialog, ServerSwitchDialog


def _write(path, payload):
    path.write_text(json.dumps(payload, indent=4) + "\n", encoding="utf-8")


def test_switch_list_label_uses_name_and_ip_without_ports():
    named = {
        "server_name": "Season 4",
        "input_ip": "104.192.227.34",
        "input_port": "30004",
        "bridge_port": "30500",
        "input_pass": "do-not-print",
    }
    plain = {
        "input_ip": "66.23.236.138",
        "input_port": "30004",
        "bridge_port": "30500",
        "input_pass": "do-not-print",
    }
    assert switch_list_label(named) == "Season 4 - 104.192.227.34"
    assert switch_list_label(plain) == "66.23.236.138"
    assert "30004" not in switch_list_label(named)
    assert "30500" not in switch_list_label(plain)
    print("[SUCCESS] Switch list labels are name and IP, with no ports.")


def test_old_profile_without_server_name_still_loads(tmp_path):
    path = tmp_path / "server_config.json"
    _write(path, {
        "active_index": 1,
        "servers": [
            {"input_ip": "66.23.236.138", "input_port": "30004", "input_pass": "alpha", "bridge_port": "30500"},
            {"input_ip": "104.192.227.34", "input_port": "30004", "input_pass": "beta", "bridge_port": "30500"},
        ],
    })
    before = path.read_text(encoding="utf-8")
    servers, active_index = list_server_profiles(str(path))
    assert active_index == 1
    assert servers[1]["input_ip"] == "104.192.227.34"
    assert servers[1].get("server_name", "") == ""
    assert get_active_profile(str(path))["input_pass"] == "beta"
    assert path.read_text(encoding="utf-8") == before
    print("[SUCCESS] Profiles without server_name still load, and active_index 1 stays put.")


def test_set_server_name_persists_without_touching_the_token(tmp_path):
    path = tmp_path / "server_config.json"
    _write(path, {
        "active_index": 0,
        "servers": [
            {"input_ip": "66.23.236.138", "input_port": "30004", "input_pass": "alpha-token", "bridge_port": "30500"},
        ],
    })
    updated = set_server_name("66.23.236.138", "30004", "Home", config_path=str(path))
    assert updated["server_name"] == "Home"
    assert updated["input_pass"] == "alpha-token"
    servers, _active = list_server_profiles(str(path))
    assert servers[0]["server_name"] == "Home"
    assert servers[0]["input_pass"] == "alpha-token"
    cleared = set_server_name("66.23.236.138", "30004", "   ", config_path=str(path))
    assert cleared["server_name"] == ""
    print("[SUCCESS] Rename persisted and the auth token was left alone.")


def test_switch_dialog_selects_active_profile_and_hides_ports(qapp):
    del qapp
    servers = [
        {
            "input_ip": "66.23.236.138",
            "input_port": "30004",
            "bridge_port": "30500",
            "input_pass": "alpha-token",
        },
        {
            "server_name": "Season",
            "input_ip": "104.192.227.34",
            "input_port": "30004",
            "bridge_port": "30500",
            "input_pass": "beta-token",
        },
    ]
    dialog = ServerSwitchDialog(servers, active_index=1)
    dialog.show()
    QApplication.processEvents()
    try:
        assert dialog.server_picker.currentIndex() == 1
        assert dialog.server_picker.currentText() == "Season - 104.192.227.34 (active)"
        assert dialog.server_picker.itemText(0) == "66.23.236.138"
        assert "30004" not in dialog.server_picker.currentText()
        assert "30500" not in dialog.server_picker.itemText(0)
        assert "30500" not in dialog.server_picker.currentText()
        print("[SUCCESS] Active index 1 is the selected row and the list hides ports.")
    finally:
        dialog.close()


def test_switch_and_login_buttons_are_not_transparent(qapp):
    del qapp
    app = QApplication.instance()
    dialog = ServerSwitchDialog(
        [{"input_ip": "10.0.0.1", "input_port": "30004", "bridge_port": "30500", "input_pass": "secret"}],
        active_index=0,
    )
    dialog.show()
    app.processEvents()
    try:
        for button in (dialog.btn_switch, dialog.btn_rename, dialog.btn_cancel):
            button.ensurePolished()
            color = button.palette().color(button.foregroundRole())
            assert color.alpha() > 0
            assert color != QColor(0, 0, 0, 0)
            assert button.objectName()
        assert dialog.btn_switch.objectName() == "SwitchServerButton"
        assert dialog.btn_rename.objectName() == "RenameServerButton"
        assert dialog.btn_cancel.objectName() == "CancelSwitchButton"
        print("[SUCCESS] Switch dialog buttons keep a visible text color.")
    finally:
        dialog.close()


def test_rename_button_saves_the_selected_name(qapp, tmp_path, monkeypatch):
    del qapp
    path = tmp_path / "server_config.json"
    _write(path, {
        "active_index": 1,
        "servers": [
            {"input_ip": "66.23.236.138", "input_port": "30004", "input_pass": "alpha-token", "bridge_port": "30500"},
            {"input_ip": "104.192.227.34", "input_port": "30004", "input_pass": "beta-token", "bridge_port": "30500"},
        ],
    })
    monkeypatch.setattr(
        "features.network.server_config._resolve_config_path",
        lambda config_path=None: config_path if config_path else str(path),
    )
    servers, active_index = list_server_profiles()
    dialog = ServerSwitchDialog(servers, active_index=active_index)
    dialog.show()
    QApplication.processEvents()

    def _fill_name():
        for widget in QApplication.instance().allWidgets():
            if isinstance(widget, ServerNameDialog) and widget.isVisible() and not widget.property("test_handled"):
                widget.setProperty("test_handled", True)
                widget.name_input.setText("Season")
                widget.btn_save.click()

    from PyQt6.QtCore import QTimer
    QTimer.singleShot(0, _fill_name)
    try:
        dialog.btn_rename.click()
        saved, active = list_server_profiles()
        assert active == 1
        assert saved[1]["server_name"] == "Season"
        assert saved[1]["input_pass"] == "beta-token"
        assert saved[0]["input_pass"] == "alpha-token"
        assert "Season - 104.192.227.34 (active)" == dialog.server_picker.currentText()
        print("[SUCCESS] Rename saved the active profile's display name.")
    finally:
        dialog.close()
