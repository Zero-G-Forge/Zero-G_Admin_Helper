## =====================================================================
## MODULE: tools/add_login_user.py
## DESCRIPTION: Adds a user to the login service's user file.
## Run from the ZAH folder:  python tools/add_login_user.py
## The password is typed hidden and is never printed or logged.
## =====================================================================

# region Imports

import os
import sys
import getpass

## The login service folder is added to Python's search path so user_store can be imported.
SERVICE_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "login_service")
sys.path.insert(0, os.path.abspath(SERVICE_FOLDER))

from user_store import add_user, ALLOWED_ROLES  # pyright: ignore[reportMissingImports]

# endregion


# region Main

def main():
    print("[INFO] AddLoginUser: Add a user to the ZAH login service")
    username = input("Username: ").strip()
    if not username:
        print("[ERROR] AddLoginUser: Username cannot be empty")
        return 1

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
    if not add_user(username, password_text, role):
        return 1
    print(f"[SUCCESS] AddLoginUser: {username} can now sign in")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# endregion