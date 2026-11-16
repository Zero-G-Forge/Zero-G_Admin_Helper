# test_server_config.py
"""Profile storage and legacy server_config.json migration."""

import json
import os

from features.network.connection import is_network_ready
from features.network.server_config import (
    add_server_profile,
    get_active_profile,
    list_server_profiles,
    load_server_store,
    registry_cache_for,
    set_active_server,
)
from tests.mock_bridge import MockBridge


def _write(path, payload):
    path.write_text(json.dumps(payload, indent=4) + "\n", encoding="utf-8")


def test_legacy_single_server_migrates_and_keeps_token(tmp_path):
    path = tmp_path / "server_config.json"
    _write(path, {
        "input_ip": "10.1.1.1",
        "input_port": 30004,
        "input_pass": "legacy-token-value",
    })

    active = get_active_profile(str(path))
    assert active["input_ip"] == "10.1.1.1"
    assert active["input_port"] == "30004"
    assert active["input_pass"] == "legacy-token-value"
    assert active["bridge_port"] == "30500"

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["active_index"] == 0
    assert len(stored["servers"]) == 1
    assert stored["servers"][0]["input_pass"] == "legacy-token-value"
    assert stored["servers"][0]["input_port"] == "30004"
    assert stored["servers"][0]["bridge_port"] == "30500"
    assert "input_ip" not in stored
    print("[SUCCESS] Legacy server_config.json migrated without dropping input_pass.")


def test_missing_bridge_port_is_filled_and_game_port_stays(tmp_path):
    path = tmp_path / "server_config.json"
    _write(path, {
        "active_index": 0,
        "servers": [
            {"input_ip": "10.0.0.5", "input_port": "30004", "input_pass": "kept"},
        ],
    })
    active = get_active_profile(str(path))
    assert active["input_port"] == "30004"
    assert active["input_pass"] == "kept"
    assert active["bridge_port"] == "30500"
    stable = path.read_text(encoding="utf-8")
    assert get_active_profile(str(path))["bridge_port"] == "30500"
    assert path.read_text(encoding="utf-8") == stable
    print("[SUCCESS] Profiles without bridge_port gained 30500 and kept the game port.")


def test_new_format_is_not_rewritten_on_load(tmp_path):
    path = tmp_path / "server_config.json"
    _write(path, {
        "active_index": 1,
        "servers": [
            {"input_ip": "10.0.0.1", "input_port": "30004", "input_pass": "alpha", "bridge_port": "30500"},
            {"input_ip": "10.0.0.2", "input_port": "30005", "input_pass": "beta", "bridge_port": "30501"},
        ],
    })
    before = path.read_text(encoding="utf-8")
    active = get_active_profile(str(path))
    assert active["input_ip"] == "10.0.0.2"
    assert active["input_pass"] == "beta"
    assert path.read_text(encoding="utf-8") == before


def test_add_server_profile_keeps_existing_profiles(tmp_path):
    path = tmp_path / "server_config.json"
    _write(path, {
        "input_ip": "10.0.0.1",
        "input_port": "30500",
        "input_pass": "keep-me",
    })

    add_server_profile("10.0.0.2", "30501", "second-token", config_path=str(path))
    servers, active_index = list_server_profiles(str(path))

    assert len(servers) == 2
    assert servers[0]["input_ip"] == "10.0.0.1"
    assert servers[0]["input_pass"] == "keep-me"
    assert servers[0]["bridge_port"] == "30500"
    assert servers[1]["input_ip"] == "10.0.0.2"
    assert servers[1]["input_pass"] == "second-token"
    assert servers[1]["bridge_port"] == "30500"
    assert active_index == 1
    print("[SUCCESS] Additional server profile saved without overwriting the first.")


def test_same_endpoint_updates_token_without_a_duplicate(tmp_path):
    path = tmp_path / "server_config.json"
    add_server_profile("10.0.0.1", "30500", "first", config_path=str(path))
    add_server_profile("10.0.0.8", "30500", "other", make_active=False, config_path=str(path))
    add_server_profile("10.0.0.1", "30500", "replaced", make_active=False, config_path=str(path))

    servers, active_index = list_server_profiles(str(path))
    assert len(servers) == 2
    assert servers[0]["input_pass"] == "replaced"
    assert servers[1]["input_pass"] == "other"
    assert active_index == 0


def test_set_active_server_selects_a_saved_profile(tmp_path):
    path = tmp_path / "server_config.json"
    add_server_profile("10.0.0.1", "30500", "alpha", config_path=str(path))
    add_server_profile("10.0.0.2", "30500", "beta", config_path=str(path))

    selected = set_active_server("10.0.0.1", "30500", config_path=str(path))
    assert selected["input_pass"] == "alpha"
    assert get_active_profile(str(path))["input_ip"] == "10.0.0.1"

    servers, _active_index = list_server_profiles(str(path))
    assert [item["input_ip"] for item in servers] == ["10.0.0.1", "10.0.0.2"]
    assert set_active_server("10.9.9.9", "30500", config_path=str(path)) is None


def test_corrupt_file_does_not_wipe_the_path(tmp_path):
    path = tmp_path / "server_config.json"
    path.write_text("{ not json", encoding="utf-8")
    assert get_active_profile(str(path)) == {}
    assert path.read_text(encoding="utf-8") == "{ not json"
    assert load_server_store(str(path))["servers"] == []


def test_registry_cache_files_stay_separate(tmp_path, monkeypatch):
    path = tmp_path / "server_config.json"
    monkeypatch.setattr("features.network.server_config.DATA_DIR", str(tmp_path))
    add_server_profile("10.0.0.1", "30500", "alpha", config_path=str(path))
    add_server_profile("10.0.0.2", "30500", "beta", config_path=str(path))
    (tmp_path / "player_registry_cache.json").write_text("[]", encoding="utf-8")

    first = registry_cache_for(
        {"input_ip": "10.0.0.1", "input_port": "30500"},
        config_path=str(path),
    )
    second = registry_cache_for(
        {"input_ip": "10.0.0.2", "input_port": "30500"},
        config_path=str(path),
    )
    assert os.path.basename(first) == "player_registry_cache.json"
    assert "10.0.0.2" in os.path.basename(second)
    assert first != second


def test_is_network_ready_uses_migrated_active_profile(tmp_path):
    bridge = MockBridge("ping-token").start()
    path = tmp_path / "server_config.json"
    try:
        _write(path, {
            "input_ip": "127.0.0.1",
            "input_port": bridge.port,
            "input_pass": "ping-token",
        })
        assert is_network_ready(str(path), timeout=2.0) is True
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["servers"][0]["input_pass"] == "ping-token"
        assert stored["servers"][0]["input_ip"] == "127.0.0.1"
        print("[SUCCESS] Network check reads the migrated active profile.")
    finally:
        bridge.stop()
