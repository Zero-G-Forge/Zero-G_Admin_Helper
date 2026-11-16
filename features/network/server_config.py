# server_config.py
"""
Saved ZeroGBridge server profiles in data/server_config.json.

Older builds stored one server at the top level (input_ip, input_port,
input_pass). The file now keeps every server under "servers" and records the
selected one in "active_index". A file still in the old shape is rewritten
the first time it is loaded. The auth token stays in input_pass and is never
printed.
"""

import json
import os

from features.paths import DATA_DIR


def _resolve_config_path(config_path=None):
    """Absolute path of server_config.json, from the app root unless overridden."""
    if config_path:
        return config_path
    return os.path.join(DATA_DIR, "server_config.json")


def _empty_store():
    return {"active_index": 0, "servers": []}


def _profile_from_mapping(raw):
    """Copies the three wizard fields. Missing fields become empty strings."""
    if not isinstance(raw, dict):
        return {"input_ip": "", "input_port": "", "input_pass": ""}
    return {
        "input_ip": str(raw.get("input_ip", "")).strip(),
        "input_port": str(raw.get("input_port", "")).strip(),
        "input_pass": str(raw.get("input_pass", "")).strip(),
    }


def _is_legacy_store(data):
    """True when the file is the original single-server object."""
    if not isinstance(data, dict):
        return False
    if isinstance(data.get("servers"), list):
        return False
    return any(key in data for key in ("input_ip", "input_port", "input_pass"))


def _filename_piece(value):
    """Keeps a host or port safe to use inside a cache file name."""
    cleaned = []
    for char in str(value).strip():
        if char.isalnum() or char in (".", "-"):
            cleaned.append(char)
        else:
            cleaned.append("_")
    return "".join(cleaned) or "x"


def profile_label(profile):
    """Host:port text used in the window title and the switch list."""
    if not isinstance(profile, dict):
        return "unknown"
    ip = str(profile.get("input_ip", "")).strip() or "unknown"
    port = str(profile.get("input_port", "")).strip() or "30500"
    return f"{ip}:{port}"


def same_server_endpoint(left, right):
    """True when both profiles point at the same host and port."""
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    return (
        str(left.get("input_ip", "")).strip() == str(right.get("input_ip", "")).strip()
        and str(left.get("input_port", "")).strip() == str(right.get("input_port", "")).strip()
    )


def load_server_store(config_path=None):
    """
    Loads the profile list. A legacy single-server file is migrated in place
    before the new shape is returned. A missing file yields an empty store
    and is not created here.
    """
    path = _resolve_config_path(config_path)
    if not os.path.exists(path):
        return _empty_store()

    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as err:
        print(f"[WARNING] Could not parse server_config.json: {err}")
        return _empty_store()

    if _is_legacy_store(data):
        store = {"active_index": 0, "servers": [_profile_from_mapping(data)]}
        save_server_store(store, path)
        print("[SUCCESS] Migrated server_config.json from the single-server format.")
        return store

    if not isinstance(data, dict):
        print("[WARNING] server_config.json did not contain a profile object.")
        return _empty_store()

    servers = []
    for entry in data.get("servers") or []:
        if isinstance(entry, dict):
            servers.append(_profile_from_mapping(entry))

    active_index = data.get("active_index", 0)
    if not isinstance(active_index, int) or active_index < 0 or (servers and active_index >= len(servers)):
        active_index = 0

    return {"active_index": active_index, "servers": servers}


def save_server_store(store, config_path=None):
    """Writes the profile list with the same indentation the network wizard used."""
    path = _resolve_config_path(config_path)
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    body = {
        "active_index": int(store.get("active_index", 0) or 0),
        "servers": list(store.get("servers") or []),
    }
    formatted_json = json.dumps(body, indent=4)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(formatted_json + "\n")


def get_active_profile(config_path=None):
    """
    Returns the selected server as input_ip / input_port / input_pass.
    An empty dict means there is nothing to connect to.
    """
    store = load_server_store(config_path)
    servers = store.get("servers") or []
    if not servers:
        return {}

    active_index = store.get("active_index", 0)
    if not isinstance(active_index, int) or active_index < 0 or active_index >= len(servers):
        active_index = 0
    return dict(servers[active_index])


def list_server_profiles(config_path=None):
    """Returns (profiles, active_index). Profiles are copies."""
    store = load_server_store(config_path)
    servers = [dict(entry) for entry in (store.get("servers") or [])]
    active_index = store.get("active_index", 0)
    if not isinstance(active_index, int) or active_index < 0 or active_index >= len(servers):
        active_index = 0
    return servers, active_index


def add_server_profile(ip, port, token, make_active=True, config_path=None):
    """
    Inserts a server profile. The same host and port updates input_pass in
    place so the other saved servers stay on disk. make_active selects it.
    """
    store = load_server_store(config_path)
    servers = list(store.get("servers") or [])
    incoming = _profile_from_mapping({
        "input_ip": ip,
        "input_port": port,
        "input_pass": token,
    })

    found = None
    for index, server in enumerate(servers):
        if same_server_endpoint(server, incoming):
            found = index
            break

    if found is None:
        servers.append(incoming)
        found = len(servers) - 1
        print(f"[SUCCESS] Saved additional server profile {profile_label(incoming)}")
    else:
        servers[found]["input_pass"] = incoming["input_pass"]
        print(f"[SUCCESS] Updated saved server profile {profile_label(incoming)}")

    store["servers"] = servers
    if make_active or len(servers) == 1:
        store["active_index"] = found
    save_server_store(store, config_path)
    return dict(servers[found])


def set_active_server(ip, port, config_path=None):
    """Selects a profile that is already saved. Returns the profile, or None."""
    store = load_server_store(config_path)
    servers = store.get("servers") or []
    target = {"input_ip": ip, "input_port": port}
    for index, server in enumerate(servers):
        if same_server_endpoint(server, target):
            store["active_index"] = index
            save_server_store(store, config_path)
            print(f"[SUCCESS] Active server set to {profile_label(server)}")
            return dict(server)

    print(f"[WARNING] No saved server profile for {profile_label(target)}")
    return None


def registry_cache_for(profile, config_path=None):
    """
    Player-registry file for this server.

    The original profile keeps data/player_registry_cache.json when that file
    is already on disk. Every other server gets its own cache so a switch does
    not mix rosters.
    """
    safe_ip = _filename_piece(profile.get("input_ip", ""))
    safe_port = _filename_piece(profile.get("input_port", ""))
    dedicated_name = f"player_registry_{safe_ip}_{safe_port}.json"
    dedicated = os.path.join(DATA_DIR, dedicated_name)
    legacy = os.path.join(DATA_DIR, "player_registry_cache.json")

    store = load_server_store(config_path)
    matched = None
    for index, server in enumerate(store.get("servers") or []):
        if same_server_endpoint(server, profile):
            matched = index
            break

    if matched == 0 and os.path.exists(legacy) and not os.path.exists(dedicated):
        return legacy
    return dedicated
