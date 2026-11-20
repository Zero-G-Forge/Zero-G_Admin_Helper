## =====================================================================
## MODULE: features/bridge/server_settings.py
## DESCRIPTION: Reads the active server profile from data/server_config.json.
## The auth token (input_pass) is used for the bridge login and is never printed.
## =====================================================================

# region Imports

## json reads the settings file; data_path builds a safe path into the data/ folder
## on both Linux and Windows.
import json
from features.paths import data_path

# endregion


# region Constants

## The settings file name inside data/. Kept out of git by .gitignore.
SERVER_CONFIG_FILE = "server_config.json"

## ZeroGBridge listens on this port unless a profile stores a different bridge_port.
DEFAULT_BRIDGE_PORT = "30500"

# endregion



# region Profile Loading

## Reads data/server_config.json and returns the chosen server as a dictionary,
## or None if the file is missing, unreadable, or has no servers saved.
def get_active_profile():
    try:
        config_file = data_path(SERVER_CONFIG_FILE)

        ## "with open(...)" opens the file and closes it again automatically,
        ## even if reading fails part way through.
        with open(config_file, "r", encoding="utf-8") as file_handle:
            server_store = json.load(file_handle)

        ## Input check: the file must hold a "servers" list with at least one entry.
        server_list = server_store.get("servers", [])
        if not isinstance(server_list, list) or len(server_list) == 0:
            print("[WARNING] ServerSettings: No saved servers in server_config.json")
            return None

        ## active_index says which saved server is chosen. A bad or out-of-range
        ## number falls back to the first server (index 0).
        active_index = server_store.get("active_index", 0)
        if not isinstance(active_index, int) or not 0 <= active_index < len(server_list):
            print(f"[WARNING] ServerSettings: active_index {active_index} invalid, using 0")
            active_index = 0

        active_profile = server_list[active_index]

        ## A blank bridge_port falls back to the default 30500.
        if not str(active_profile.get("bridge_port", "")).strip():
            active_profile["bridge_port"] = DEFAULT_BRIDGE_PORT

        ## Only the name, address and port are logged. input_pass (the token) never is.
        print(f"[INFO] ServerSettings: Active server: {active_profile.get('server_name', '?')} "
              f"at {active_profile.get('input_ip', '?')}:{active_profile['bridge_port']}")
        return active_profile

    ## A missing file is normal on a fresh install, so it gets its own message.
    except FileNotFoundError:
        print(f"[WARNING] ServerSettings: {SERVER_CONFIG_FILE} not found in data/")
        return None
    except Exception as e:
        print(f"[ERROR] ServerSettings: Could not read {SERVER_CONFIG_FILE}: {e}")
        return None

# endregion