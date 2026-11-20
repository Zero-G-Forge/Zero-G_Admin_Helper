## =====================================================================
## MODULE: features/zgb_portal/server_config.py
## DESCRIPTION: Read-only stand-in for the legacy features/network/server_config.py.
## The copied ZeroGBridge Portal only needs these three helpers. Nothing here writes
## server_config.json, and input_pass (the auth token) is never printed.
## =====================================================================

# region Imports

import json

from features.paths import data_path
from features.bridge.server_settings import DEFAULT_BRIDGE_PORT, SERVER_CONFIG_FILE
from features.bridge.server_settings import get_active_profile as _new_get_active_profile

# endregion


# region Helpers

## ZeroGBridge port for a profile. Missing or blank becomes 30500 (same as legacy).
def bridge_port_of(profile):
    if not isinstance(profile, dict):
        return DEFAULT_BRIDGE_PORT
    text = str(profile.get("bridge_port", "")).strip()
    return text or DEFAULT_BRIDGE_PORT


## The active server, read by new ZAH's own server_settings. Returns a copy, or None.
def get_active_profile(config_path=None):
    profile = _new_get_active_profile()
    return dict(profile) if isinstance(profile, dict) else None


## Returns (profiles, active_index), like legacy. Profiles are copies. Read-only.
def list_server_profiles(config_path=None):
    try:
        with open(config_path or data_path(SERVER_CONFIG_FILE), "r", encoding="utf-8") as file_handle:
            server_store = json.load(file_handle)
        servers = [dict(entry) for entry in (server_store.get("servers") or []) if isinstance(entry, dict)]
        active_index = server_store.get("active_index", 0)
        if not isinstance(active_index, int) or not 0 <= active_index < len(servers):
            active_index = 0
        return servers, active_index
    except Exception as e:
        print(f"[ERROR] PortalServerConfig: Failed to read server list: {type(e).__name__}")
        return [], 0

# endregion
