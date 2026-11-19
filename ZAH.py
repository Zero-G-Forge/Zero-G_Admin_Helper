## =====================================================================
## ZAH.py
## DESCRIPTION: Program entry point. Applies the main stylesheet, shows the
##              loading screen, then opens the MainCockpit window.
## =====================================================================

## region: Imports

import os
import sys
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtGui import QIcon

from features.paths import asset_path

## endregion

## region: Feature Modules

## Each feature import is guarded by try/except, so a missing module is logged
## instead of stopping the program.

## Load the main window shell. Later steps will add the loader, login, and bridge.
try:
    from features.dashboard.main_cockpit import MainCockpit
    print("[SUCCESS] Package: MainCockpit Loaded")
except ImportError as e:
    print(f"[ERROR] Could not load MainCockpit: {e}")
    MainCockpit = None

## Load Screen 1 (The Application Loader Component)
try:
    from features.loading.loading_screen import ApplicationLoader
    print("[SUCCESS] Package: ApplicationLoader Loaded")
except ImportError as e:
    print(f"[ERROR] Could not load ApplicationLoader: {e}")
    ApplicationLoader = None

## endregion


## region: Entry Point

def main():
    """
    Primary application entry point.
    Initializes the QApplication, applies the main window stylesheet,
    shows the ApplicationLoader, and opens the MainCockpit shell.
    """
    print("[DEBUG] Initializing Zero-G Admin Helper (PyQt6 Mode)...")

    ## QApplication is the engine behind every window. It must exist before any widget is built.
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

    ## Apply the main stylesheet (colours, fonts, borders) to every window in the program.
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

    ## Without the main window class there is nothing to open, so the program stops here.
    if MainCockpit is None:
        print("[ERROR] MainCockpit not found. Halting.")
        sys.exit(1)

    ## PHASE 1: Loading screen. It builds the MainCockpit during its
    ## "BUILDING MAIN WINDOW" stage. If the loader fails for any reason,
    ## the error is logged and the main window still opens.
    main_cockpit = None
    loader_result = QDialog.DialogCode.Accepted
    if ApplicationLoader is not None:
        try:
            print("[DEBUG] Instantiating Screen 1: Application Loading Screen...")
            loader = ApplicationLoader(build_main_window=MainCockpit)
            loader.show()
            loader.start_boot_sequence()
            loader_result = loader.exec()
            main_cockpit = loader.main_window
            loader.deleteLater()
        except Exception as e:
            print(f"[ERROR] Loading screen failed: {e}. Opening MainCockpit anyway.")
            loader_result = QDialog.DialogCode.Accepted
    else:
        print("[ERROR] ApplicationLoader not found. Opening MainCockpit without it.")

    ## The user closed the loading screen before it finished
    if loader_result != QDialog.DialogCode.Accepted:
        print("[STATUS] Initialization halted. Shutting down.")
        sys.exit(0)

    ## PHASE 2: Dashboard Handoff
    try:
        if main_cockpit is None:
            main_cockpit = MainCockpit()
        print("[DEBUG] Passing control to MainCockpit...")
        main_cockpit.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"[ERROR] Failed to launch MainCockpit: {e}")
        sys.exit(1)

## endregion


## region: Script Start

## Runs main() only when this file is started directly (not when it is imported).
if __name__ == "__main__":
    main()

## endregion
