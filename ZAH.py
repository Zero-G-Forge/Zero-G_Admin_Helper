## ZAH.py

import os
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from features.paths import asset_path

## Load the main window shell. Later steps will add the loader, login, and bridge.
try:
    from features.dashboard.main_cockpit import MainCockpit
    print("[SUCCESS] Package: MainCockpit Loaded")
except ImportError as e:
    print(f"[ERROR] Could not load MainCockpit: {e}")
    MainCockpit = None


def main():
    """
    Primary application entry point.
    Initializes the QApplication, applies the main window stylesheet,
    and opens the MainCockpit shell.
    """
    print("[DEBUG] Initializing Zero-G Admin Helper (PyQt6 Mode)...")

    try:
        app = QApplication(sys.argv)
    except Exception as e:
        print(f"[ERROR] Failed to initialize QApplication: {e}")
        sys.exit(1)

    ## Assets and data/ resolve from the app root (the folder that holds ZAH.py),
    ## never from the current working directory.
    icon_path = asset_path("branding", "ZG_AdminHelper.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
        print("[SUCCESS] Application icon applied: ZG_AdminHelper.png")
    else:
        print(f"[WARNING] Application icon missing at: {icon_path}")

    css_path = asset_path("ZAH_main.css")
    if os.path.exists(css_path):
        try:
            with open(css_path, "r", encoding="utf-8") as stream:
                css_rules = stream.read()
                app.setStyleSheet(css_rules)
            print("[SUCCESS] Central layout stylesheet applied: ZAH_main.css, Cyan-Theme")
        except Exception as e:
            print(f"[ERROR] Failed to read central stylesheet: {e}")
    else:
        print(f"[WARNING] Local asset missing at: {css_path}. Using default system styles.")

    if MainCockpit is None:
        print("[ERROR] MainCockpit not found. Halting.")
        sys.exit(1)

    try:
        print("[DEBUG] Passing control to MainCockpit...")
        main_cockpit = MainCockpit()
        main_cockpit.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"[ERROR] Failed to launch MainCockpit: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
