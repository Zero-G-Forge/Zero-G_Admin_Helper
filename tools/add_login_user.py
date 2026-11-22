## =====================================================================
## MODULE: tools/add_login_user.py
## DESCRIPTION: Adds a user to the login service's user file.
## Run from the ZAH folder:  python tools/add_login_user.py
## The password is typed hidden and is never printed or logged.
## =====================================================================

# region Imports

import os
import sys
import json
import getpass

## Your saved servers, the same file ZAH reads. Only the name, IP and port are used here.
SERVER_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "server_config.json")

## The login service folder is added to Python's search path so user_store can be imported.
SERVICE_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "login_service")
sys.path.insert(0, os.path.abspath(SERVICE_FOLDER))

from user_store import add_user, ALLOWED_ROLES  # pyright: ignore[reportMissingImports]

# endregion


# region Main

## Shows the saved servers as a numbered list and returns (server_name, server_address) for the pick.
## 0, a blank answer or a missing file means unassigned: ("", "").
def pick_server():
    try:
        with open(SERVER_CONFIG_FILE, "r", encoding="utf-8") as file_handle:
            saved_servers = json.load(file_handle).get("servers", [])
    except Exception as e:
        print(f"[WARNING] AddLoginUser: Could not read the saved servers ({type(e).__name__}), user will be unassigned")
        return "", ""
    print("  0. UNASSIGNED")
    for server_number, server in enumerate(saved_servers, start=1):
        print(f"  {server_number}. {server.get('server_name', '')}  {server.get('input_ip', '')}:{server.get('input_port', '')}")
    picked_text = input("Server number: ").strip()
    if not picked_text.isdigit() or not 1 <= int(picked_text) <= len(saved_servers):
        return "", ""
    picked_server = saved_servers[int(picked_text) - 1]
    return str(picked_server.get("server_name", "")), f"{picked_server.get('input_ip', '')}:{picked_server.get('input_port', '')}"

def main():
    print("[INFO] AddLoginUser: Add a user to the ZAH login service")
    username = input("Username: ").strip()
    if not username:
        print("[ERROR] AddLoginUser: Username cannot be empty")
        return 1

    ## Which server this user belongs to (shown as its heading on the USERS page).
    server_name, server_address = pick_server()

    ## The role list comes from user_store, so this tool always matches the service.
    role = input(f"Role ({', '.join(ALLOWED_ROLES)}): ").strip().lower()
    if role not in ALLOWED_ROLES:
        print(f"[ERROR] AddLoginUser: Role must be one of: {', '.join(ALLOWED_ROLES)}")
        return 1

    ## getpass hides the typing; the password is asked twice to catch typos.
    password_text = getpass.getpass("Password (8+ characters): ")
    password_again = getpass.getpass("Type it again: ")
    if password_text != password_again:
        print("[ERROR] AddLoginUser: Passwords did not match")
        return 1

    ## add_user returns True when saved and False when refused (it prints the reason itself).
    if not add_user(username, password_text, role, server_name, server_address):
        return 1
    print(f"[SUCCESS] AddLoginUser: {username} can now sign in")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# endregion

