## =====================================================================
## MODULE: tools/set_owner_login.py
## DESCRIPTION: One-time setup for the offline owner login (Ray only).
## Run from the ZAH folder:  .venv/bin/python tools/set_owner_login.py
## The password is typed hidden and only its hash is saved to data/owner_login.json.
## =====================================================================

## region: Imports

import os
import sys
from getpass import getpass

## Lets this script find the features/ package when run from tools/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from features.login.owner_login import save_owner_login

## endregion


## region: Setup Steps

def main():
    print("[INFO] SetOwnerLogin: Offline owner login setup")
    username = input("Owner username: ").strip()

    ## Asked twice, so a typo can't lock the owner out.
    first_try = getpass("Owner password (hidden): ")
    second_try = getpass("Type it again: ")
    if first_try != second_try:
        print("[ERROR] SetOwnerLogin: Passwords did not match, nothing saved")
        return
    ## Input check: very short passwords are too easy to guess.
    if len(first_try) < 8:
        print("[ERROR] SetOwnerLogin: Password must be at least 8 characters, nothing saved")
        return

    save_owner_login(username, first_try)

## endregion


## Runs main() only when this file is started directly, not when it is imported.
if __name__ == "__main__":
    main()