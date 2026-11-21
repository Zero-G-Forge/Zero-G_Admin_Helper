## =====================================================================
## MODULE: features/dashboard/main_cockpit.py
## DESCRIPTION: Core Main Cockpit Window Shell (Pure Layout & CSS Core)
## =====================================================================

# region Imports

import os
import sys
from features.paths import asset_path
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QButtonGroup, QSizePolicy, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt, QTimer, QTime, QSize, pyqtSignal
from PyQt6.QtGui import QPainter, QPixmap, QFont

# endregion

# region Optional Modules

## Guarded import: if nav_icons is missing, the window still opens without icons.
try:
    from features.dashboard.nav_icons import build_nav_icon, build_logo_pixmap
except ImportError as e:
    print(f"[ERROR] MainCockpit: Could not load nav_icons: {e}")
    build_nav_icon = None
    build_logo_pixmap = None

try:
    from features.shared.page_loader import load_page
    from features.shared.error_card import ErrorCard
except ImportError as e:
    print(f"[ERROR] MainCockpit: Could not load page_loader: {e}")
    load_page = None
    ErrorCard = None


## Guarded import: if the bridge module is missing, the window still opens, just OFFLINE.
try:
    from features.bridge.command_pipe import CommandPipe
except ImportError as e:
    print(f"[ERROR] MainCockpit: Could not load command_pipe: {e}")
    CommandPipe = None

## Guarded import: if app_settings is missing, auto-connect stays off.
try:
    from features.settings.app_settings import load_app_settings
except ImportError as e:
    print(f"[ERROR] MainCockpit: Could not load app_settings: {e}")
    load_app_settings = None

    load_app_settings = None

## Guarded import: if clickable_label is missing, the bridge field is a plain label (not clickable).
try:
    from features.shared.clickable_label import ClickableLabel
except ImportError as e:
    print(f"[ERROR] MainCockpit: Could not load clickable_label: {e}")
    ClickableLabel = None


## Guarded import: if zgb_portal is missing, ZAH still runs, the portal just can't open.
try:
    from features.zgb_portal import ZeroGBridgePortal
except ImportError as e:
    print(f"[ERROR] MainCockpit: Could not load zgb_portal: {e}")
    ZeroGBridgePortal = None

## Guarded import: if roles is missing, every role check says no (fail closed).
try:
    from features.shared.roles import has_role_at_least
except ImportError as e:
    print(f"[ERROR] MainCockpit: Could not load roles: {e}")
    has_role_at_least = None

## Guarded import: if login_window is missing, logout closes ZAH instead (fail closed).
try:
    from features.login.login_window import LoginWindow
except ImportError as e:
    print(f"[ERROR] MainCockpit: Could not load login_window: {e}")
    LoginWindow = None

# endregion


# region Constants

## Nav pages in the mockup order: (page key, button text)
NAV_PAGES = [
    ("dashboard", "DASHBOARD"),
    ("players", "PLAYERS"),
    ("factions", "FACTIONS"),
    ("structures", "STRUCTURES"),
    ("playfields", "PLAYFIELDS"),
    ("chat", "CHAT"),
    ("alerts", "ALERTS & ANTI-CHEAT"),
    ("scheduler", "SCHEDULER"),
    ("bans_audit", "BANS & AUDIT"),
    ("zerogbridge", "ZEROGBRIDGE"),
    ("settings", "SETTINGS"),
]

## Font used by every label (Inter on Zorin, DejaVu Sans as a fallback)
CORE_FONT_FAMILIES = ["Inter", "DejaVu Sans"]

# endregion


# region MainCockpit Class

class MainCockpit(QMainWindow):
    """
    Core Main Administration Cockpit Dashboard Shell.
    Maintains clean layout scaffolding and centralized CSS lookups.
    """

    ## (server_name, is_connected): sent every time the bridge state changes,
    ## so any page (like ZeroGBridge) can connect() to it and update itself live.
    ## The pipe is rebuilt on each Connect, so pages listen here, not to the pipe.
    bridge_status_changed = pyqtSignal(str, bool)

    # region Window Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        try:

            ## 1. Base UI Setup
            print("[DEBUG] MainCockpit: Initializing Structural Window...")
            self.setObjectName("MainCockpitCanvas")
            self.setWindowTitle("Zero-G Admin Helper")
            self.resize(1400, 850)
            self.setMinimumSize(1100, 700)

            ## Page state: nav buttons by page key, and the page shown now
            self.nav_buttons = {}
            self.active_page = "dashboard"

            ## Nobody is signed in yet, so there is no role; every role check says no until set_signed_in_user runs.
            self.signed_in_role = None

            ## 2. Central UI Canvas
            self.central_widget = QWidget()
            self.central_widget.setObjectName("CentralWidgetCanvas")
            self.setCentralWidget(self.central_widget)

            ## Empty picture until _load_background() reads the hexgrid image.
            self.background = QPixmap()
            self._load_background()

            ## 3. Master Layout & Scaffolding
            self.master_layout = QVBoxLayout()
            self.master_layout.setObjectName("MasterLayout")
            self.master_layout.setContentsMargins(14, 10, 14, 10)
            self.master_layout.setSpacing(10)
            self.central_widget.setLayout(self.master_layout)

            ## 4. Construct Layout Zones
            print("[DEBUG] MainCockpit: Constructing Layout Zones...")
            self.setup_zones()

            ## 5. Apply External QSS Theme
            print("[DEBUG] MainCockpit: Applying CSS Styles...")
            self.apply_theme()
            self.apply_letter_spacing()

            ## 6. Live header clock (local time only, no server contact)
            self.setup_clock_timer()

            ## 7. Bridge connection (background thread; only starts if the switch is on)
            self.setup_bridge()

            print("[SUCCESS] Main Cockpit Dashboard structure initialized.")
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to initialize the main window: {e}")
            raise

    def _load_background(self):
        """Loads the hexgrid background from assets/new_backgrounds/hexgrid.jpg."""
        try:
            bg_path = asset_path("new_backgrounds", "hexgrid.jpg")
            if os.path.exists(bg_path):
                self.background = QPixmap(bg_path)
                if self.background.isNull():
                    print(f"[ERROR] MainCockpit: Background image could not be read: {bg_path}")
                else:
                    print(f"[SUCCESS] MainCockpit: Background loaded: {bg_path}")
            else:
                print(f"[WARNING] MainCockpit: Background missing at: {bg_path}")
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to load background: {e}")

    # endregion

    # region Layout Zones

    def setup_zones(self):
        """Constructs layout zones across the central dashboard canvas."""

        ## Each zone builds inside its own try/except, so one failure
        ## leaves the other zones on screen.

        ## Top Header Bar
        self.setup_header_bar()

        ## Content Row: left navigation column + central content area
        self.content_columns_layout = QHBoxLayout()
        self.content_columns_layout.setObjectName("ContentColumnsLayout")
        self.content_columns_layout.setSpacing(14)

        ## Left Column: empty navigation placeholder (pages arrive in a later step)
        ## The column now holds the page buttons; the pages themselves still arrive later.
        self.setup_nav_column()

        ## Central Content Area: pages will load here in a later step
        self.setup_content_area()

        ## Bottom Status Bar
        self.setup_status_bar()

        ## Canvas Consolidation Assembly
        try:
            if getattr(self, "header_bar", None) is not None:
                self.master_layout.addWidget(self.header_bar)
            if getattr(self, "nav_column", None) is not None:
                self.content_columns_layout.addWidget(self.nav_column)
            if getattr(self, "content_area", None) is not None:
                self.content_columns_layout.addWidget(self.content_area, stretch=1)
            self.master_layout.addLayout(self.content_columns_layout, stretch=1)
            if getattr(self, "status_bar", None) is not None:
                self.master_layout.addWidget(self.status_bar)
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to assemble layout zones: {e}")

    # endregion

    # region Header Bar

    def setup_header_bar(self):
        """Builds the header: logo, title + subtitle, server status, CTRL+K, clock, admin name."""
        self.header_bar = None
        try:
            self.header_bar = QFrame()
            self.header_bar.setObjectName("HeaderBar")
            self.header_bar.setFixedHeight(72)
            self.header_layout = QHBoxLayout(self.header_bar)
            self.header_layout.setObjectName("TopHeaderLayout")
            self.header_layout.setContentsMargins(14, 6, 18, 6)
            self.header_layout.setSpacing(14)

            ## Round logo
            self.lbl_app_logo = QLabel()
            self.lbl_app_logo.setObjectName("AppLogoLabel")
            self.lbl_app_logo.setFixedSize(46, 46)
            if build_logo_pixmap is not None:
                self.lbl_app_logo.setPixmap(build_logo_pixmap(44))
            self.lbl_app_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.header_layout.addWidget(self.lbl_app_logo)

            ## Title with the small cyan subtitle below it
            self.title_block_layout = QVBoxLayout()
            self.title_block_layout.setObjectName("TitleBlockLayout")
            self.title_block_layout.setSpacing(0)
            self.title_block_layout.setContentsMargins(0, 0, 0, 0)

            self.lbl_app_title = QLabel("ZERO-G ADMIN HELPER")
            self.lbl_app_title.setObjectName("AppTitleLabel")
            self.lbl_app_title.setAlignment(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            )
            self.lbl_app_subtitle = QLabel("ANTI-CHEAT PANEL")
            self.lbl_app_subtitle.setObjectName("AppSubtitleLabel")

            self.title_block_layout.addStretch()
            self.title_block_layout.addWidget(self.lbl_app_title)
            self.title_block_layout.addWidget(self.lbl_app_subtitle)
            self.title_block_layout.addStretch()
            self.header_layout.addLayout(self.title_block_layout)
            self.header_layout.addSpacing(30)

            ## Server name + status dot (not connected until the bridge module exists)
            self.lbl_server_name = QLabel("NO SERVER")
            self.lbl_server_name.setObjectName("ServerNameLabel")
            self.header_layout.addWidget(self.lbl_server_name)

            self.lbl_server_status_dot = QLabel()
            self.lbl_server_status_dot.setObjectName("ServerStatusDot")
            self.lbl_server_status_dot.setFixedSize(10, 10)
            self.lbl_server_status_dot.setProperty("state", "idle")
            self.header_layout.addWidget(self.lbl_server_status_dot)

            self.header_layout.addStretch()

            ## Right side: CTRL+K | clock | admin
            self.lbl_ctrl_k = QLabel("CTRL+K")
            self.lbl_ctrl_k.setObjectName("CtrlKLabel")
            self.header_layout.addWidget(self.lbl_ctrl_k)
            self.header_layout.addWidget(self._make_header_divider())

            self.lbl_clock = QLabel("--:--")
            self.lbl_clock.setObjectName("ClockLabel")
            self.header_layout.addWidget(self.lbl_clock)
            self.header_layout.addWidget(self._make_header_divider())

            ## Starts blank; set_signed_in_user() fills in the real name after login.
            self.lbl_admin_name = QLabel("USER: --")
            self.lbl_admin_name.setObjectName("AdminNameLabel")
            self.header_layout.addWidget(self.lbl_admin_name)

            ## LOGOUT is for every role, so anyone using "Keep me logged in" can still sign out.
            self.btn_logout = QPushButton("LOGOUT")
            self.btn_logout.setObjectName("LogoutButton")
            self.btn_logout.clicked.connect(self._on_logout_clicked)
            self.header_layout.addWidget(self.btn_logout)

            print("[INFO] MainCockpit: Header bar built")
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to build header bar: {e}")

    def _make_header_divider(self):
        """Returns a thin vertical divider line for the header."""
        divider = QFrame()
        divider.setObjectName("HeaderDivider")
        divider.setFixedSize(1, 30)
        return divider

    # endregion

    # region Signed-In User
    def set_signed_in_user(self, username, role):

        ## Shows who is signed in, e.g. "ADMIN: PARTICLEWAVE" or "OWNER: RAY".
        try:

            ## Keep the role (lowercase, like the database) so pages can check it later.
            self.signed_in_role = str(role).strip().lower() if role else None
            shown_role = str(role or "user").upper()
            shown_name = str(username or "--").upper()
            self.lbl_admin_name.setText(f"{shown_role}: {shown_name}")
            print(f"[INFO] MainCockpit: Signed-in user shown as {shown_role}: {shown_name}")
        except Exception as e:
            print(f"[ERROR] MainCockpit: Could not show signed-in user: {e}")
    def user_has_role(self, needed_role):

        ## Pages ask the cockpit, e.g. user_has_role("developer"), instead of checking role names themselves.
        ## If roles.py failed to load, the answer is always no (fail closed).
        if has_role_at_least is None:
            return False
        return has_role_at_least(self.signed_in_role, needed_role)

    def _on_logout_clicked(self):

        ## Signs the current user out. No role check: every user may log out.
        try:
            confirm = QMessageBox.question(
                self, "Log out", "Log out of Zero-G Admin Helper?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            ## No is the default, so a stray Enter key doesn't log anyone out.
            if confirm != QMessageBox.StandardButton.Yes:
                return
            
            ## Close the portal first, so nothing stays open for the next user.
            zgb_portal = getattr(self, "zgb_portal", None)
            if zgb_portal is not None:
                zgb_portal.close()

            ## Drop the bridge connection; the next user connects again themselves.
            self.disconnect_bridge()

            ## Clearing the role makes every role check say no (fail closed).
            self.set_signed_in_user(None, None)

            ## Reload the page on screen so its buttons grey out for "no one signed in".
            self._show_page(self.active_page)
            print("[INFO] MainCockpit: User logged out")

            ## Hide the cockpit while nobody is signed in.
            self.hide()

            ## Fail closed: without the login window, nobody can sign back in, so ZAH closes.
            if LoginWindow is None:
                print("[ERROR] MainCockpit: Login window missing, closing ZAH")
                app = QApplication.instance()
                if app is not None:
                    app.quit()
                return
            
            login = LoginWindow()

            ## exec() waits here until the login window closes with a yes (signed in) or a no (cancel).
            if login.exec() != LoginWindow.DialogCode.Accepted:
                print("[STATUS] MainCockpit: Login cancelled after logout, closing ZAH")
                app = QApplication.instance()
                if app is not None:
                    app.quit()
                return
            
            ## Signed in again: show the new user, reload the page for their role, and bring the cockpit back.
            self.set_signed_in_user(login.signed_in_user, login.signed_in_role)
            self._show_page(self.active_page)
            self.show()

        except Exception as e:
            print(f"[ERROR] MainCockpit: Logout failed: {e}")

    # endregion


    # region Nav Column

    def setup_nav_column(self):
        """Builds the left nav column: one checkable button per page, DASHBOARD selected."""
        self.nav_column = None
        try:
            self.nav_column = QFrame()
            self.nav_column.setObjectName("NavColumn")
            self.nav_column.setFixedWidth(250)
            self.left_column = QVBoxLayout(self.nav_column)
            self.left_column.setObjectName("LeftColumnLayout")
            self.left_column.setContentsMargins(0, 0, 0, 0)
            self.left_column.setSpacing(8)

            ## Exclusive button group: only one nav button can be checked at a time.
            self.nav_button_group = QButtonGroup(self)
            self.nav_button_group.setExclusive(True)

            ## One button per entry in NAV_PAGES. A button that fails to build is skipped.
            for page_key, page_text in NAV_PAGES:
                btn = self._make_nav_button(page_key, page_text)
                if btn is None:
                    continue
                self.nav_buttons[page_key] = btn
                self.nav_button_group.addButton(btn)
                self.left_column.addWidget(btn)

            self.left_column.addStretch()

            ## DASHBOARD starts selected.
            if "dashboard" in self.nav_buttons:
                self.nav_buttons["dashboard"].setChecked(True)
            print(f"[INFO] MainCockpit: Nav column built with {len(self.nav_buttons)} buttons")
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to build nav column: {e}")

    def _make_nav_button(self, page_key, page_text):
        """Builds one nav button. ALERTS & ANTI-CHEAT also gets the red alert badge."""
        try:

            ## '&' is doubled so Qt shows it instead of making a shortcut key;
            ## the leading spaces open a gap between the icon and the text
            btn = QPushButton("   " + page_text.replace("&", "&&"))
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(50)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if build_nav_icon is not None:
                btn.setIcon(build_nav_icon(page_key))
                btn.setIconSize(QSize(22, 22))

            ## The lambda passes this button's page key to _on_nav_clicked.
            ## key=page_key locks in the value for each button inside the loop.
            btn.clicked.connect(lambda checked, key=page_key: self._on_nav_clicked(key))

            if page_key == "alerts":

                ## Longest label: smaller text (like the mockup) so it fits beside the badge
                btn.setProperty("compact", "true")

                ## Red alert count badge, hidden while the count is 0
                badge_layout = QHBoxLayout(btn)
                badge_layout.setContentsMargins(0, 0, 10, 0)
                badge_layout.addStretch()
                self.lbl_alert_badge = QLabel("0")
                self.lbl_alert_badge.setObjectName("AlertBadge")
                self.lbl_alert_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.lbl_alert_badge.setFixedSize(18, 18)
                self.lbl_alert_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                badge_layout.addWidget(self.lbl_alert_badge, alignment=Qt.AlignmentFlag.AlignVCenter)
                self.lbl_alert_badge.hide()
            return btn
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to build nav button {page_text}: {e}")
            return None

    # endregion

    # region Content Area

    def setup_content_area(self):
        """Builds the content area: one glass panel with the page title and a placeholder."""
        self.content_area = None
        try:
            self.content_area = QFrame()
            self.content_area.setObjectName("ContentArea")
            self.content_layout = QVBoxLayout(self.content_area)
            self.content_layout.setObjectName("ContentAreaLayout")
            self.content_layout.setContentsMargins(0, 0, 0, 0)
            self.content_layout.setSpacing(0)

            ## Glass panel that holds the page title and the page placeholder.
            self.content_panel = QFrame()
            self.content_panel.setObjectName("ContentPanel")
            self.content_panel_layout = QVBoxLayout(self.content_panel)
            self.content_panel_layout.setObjectName("ContentPanelLayout")
            self.content_panel_layout.setContentsMargins(24, 20, 24, 20)
            self.content_panel_layout.setSpacing(10)

            self.lbl_content_header = QLabel(self._page_title("dashboard"))
            self.lbl_content_header.setObjectName("ContentHeaderLabel")
            self.lbl_content_header.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.content_panel_layout.addWidget(self.lbl_content_header)

            self.lbl_content_placeholder = QLabel("PAGE LOADS HERE")
            self.lbl_content_placeholder.setObjectName("ContentPlaceholderLabel")
            self.lbl_content_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.content_panel_layout.addWidget(self.lbl_content_placeholder, stretch=1)

            self.content_layout.addWidget(self.content_panel)
            print("[INFO] MainCockpit: Content area built")
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to build content area: {e}")

    # endregion

    # region Status Bar

    def setup_status_bar(self):
        """Builds the bottom status bar: 5 evenly spaced fields, '--' until the bridge module exists."""
        self.status_bar = None
        try:
            self.status_bar = QFrame()
            self.status_bar.setObjectName("StatusBar")
            self.status_bar.setFixedHeight(48)
            self.status_layout = QHBoxLayout(self.status_bar)
            self.status_layout.setObjectName("StatusBarLayout")
            self.status_layout.setContentsMargins(16, 4, 16, 4)
            self.status_layout.setSpacing(0)

            ## The bridge field is clickable when ClickableLabel loaded; otherwise a plain QLabel.
            if ClickableLabel is not None:
                self.lbl_bridge_status = ClickableLabel("ZEROGBRIDGE DISCONNECTED")

                ## A click opens the ZeroGBridge page, same as its nav button.
                self.lbl_bridge_status.clicked.connect(self._on_bridge_status_clicked)
                self.lbl_bridge_status.setToolTip("Open ZeroGBridge")
            else:
                self.lbl_bridge_status = QLabel("ZEROGBRIDGE DISCONNECTED")

            self.lbl_bridge_status.setProperty("state", "offline")
            self.lbl_bridge_status.setProperty("state", "offline")
            self.lbl_server_cpu = QLabel("CPU --")
            self.lbl_server_ram = QLabel("RAM --")
            self.lbl_players = QLabel("PLAYERS --")
            self.lbl_core_version = QLabel("CORE --")

            ## Same object name and stretch for each field, so they share one style and spread evenly.
            for lbl in (
                self.lbl_bridge_status, self.lbl_server_cpu, self.lbl_server_ram,
                self.lbl_players, self.lbl_core_version,
            ):
                lbl.setObjectName("StatusLabel")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.status_layout.addWidget(lbl, stretch=1)
            print("[INFO] MainCockpit: Status bar built")
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to build status bar: {e}")

    # endregion

    # region Header Clock

    def setup_clock_timer(self):
        """Starts a 1 second local timer that keeps the header clock (HH:MM) current."""
        try:

            ## Show the time right away instead of waiting for the first tick.
            self._update_clock()
            self.clock_timer = QTimer(self)
            self.clock_timer.setObjectName("ClockTimer")
            self.clock_timer.timeout.connect(self._update_clock)
            self.clock_timer.start(1000)
            print("[INFO] MainCockpit: Header clock started")
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to start header clock: {e}")

    def _update_clock(self):
        """Writes the local time as HH:MM into the header clock."""
        try:
            if getattr(self, "lbl_clock", None) is not None:
                self.lbl_clock.setText(QTime.currentTime().toString("HH:mm"))
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to update clock: {e}")

    # endregion

    # region Navigation

    def _page_title(self, page_key):
        """Returns the button text for a page key, used as the content title."""

        ## Look the key up in NAV_PAGES. Unknown keys fall back to the key in capitals.
        for key, text in NAV_PAGES:
            if key == page_key:
                return text
        return page_key.upper()

    def _on_nav_clicked(self, page_key):
        """Selects a nav page and updates the content title. Pages load here in a later step."""
        try:
            self.active_page = page_key
            if page_key in self.nav_buttons:
                self.nav_buttons[page_key].setChecked(True)
            if getattr(self, "lbl_content_header", None) is not None:
                self.lbl_content_header.setText(self._page_title(page_key))
            print(f"[INFO] MainCockpit: Page selected: {self._page_title(page_key)}")

            ## Load the clicked page into the content area (or an ErrorCard if it fails).
            self._show_page(page_key)
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to switch page to {page_key}: {e}")

    ## Swaps the content area to the requested page.
    ## The old widget comes out, and the new page (or an ErrorCard) goes in.
    def _show_page(self, page_key):
        try:

            ## Input check: without the page loader, the placeholder stays and nothing breaks.
            if load_page is None:
                print(f"[ERROR] MainCockpit: page_loader missing, cannot show {page_key}")
                return

            ## Ask the loader for the page. It always hands back a widget:
            ## the real page, or an ErrorCard if the page failed.
            new_widget = load_page(page_key)

            ## Find what is on screen now. The first time, that is the
            ## "PAGE LOADS HERE" placeholder; after that, the last page shown.
            old_widget = getattr(self, "current_page_widget", None)
            if old_widget is None:
                old_widget = getattr(self, "lbl_content_placeholder", None)

            ## Take the old widget out of the layout, and let Qt delete it
            ## safely once the current click has finished.
            if old_widget is not None:
                self.content_panel_layout.removeWidget(old_widget)
                old_widget.deleteLater()

            ## Put the new widget in. stretch=1 lets it fill the free space.
            self.content_panel_layout.addWidget(new_widget, stretch=1)
            self.current_page_widget = new_widget

            ## If it is an ErrorCard, wire its Retry button back to this method,
            ## so clicking Retry loads the same page again.
            if ErrorCard is not None and isinstance(new_widget, ErrorCard):
                new_widget.retry_requested.connect(self._show_page)

            print(f"[INFO] MainCockpit: Showing page: {page_key}")
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to show page {page_key}: {e}")

    # endregion

    # region Status Updates
    def update_server_status(self, server_name, is_connected):
        """
        Updates the header server name and status dot.
        Called by the bridge module in a later step; green only on a real connection.
        """
        try:
            self.lbl_server_name.setText(str(server_name).upper())

            ## Remember the latest bridge news so pages can ask for it (e.g. the ZeroGBridge page).
            ## bool() makes sure it is a real True/False, never some other value.
            self.bridge_server_name = str(server_name)
            self.bridge_connected = bool(is_connected)
            state = "online" if is_connected else "offline"
            self.lbl_server_status_dot.setProperty("state", state)

            ## unpolish/polish makes Qt re-read the CSS, so the new dot colour shows.
            ## style() can return None in rare cases, so it is saved and checked before use.
            dot_style = self.lbl_server_status_dot.style()
            if dot_style is not None:
                dot_style.unpolish(self.lbl_server_status_dot)
                dot_style.polish(self.lbl_server_status_dot)

            ## The status bar gets the same news as the header dot, so they always agree.
            self.update_bridge_status(is_connected)

            ## Tell any listening page about the change.
            self.bridge_status_changed.emit(self.bridge_server_name, self.bridge_connected)
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to update server status: {e}")

    def update_bridge_status(self, is_connected):
        """Updates the ZEROGBRIDGE field in the bottom status bar."""
        try:

            ## getattr(..., None) gives None instead of crashing if the status bar failed to build.
            lbl = getattr(self, "lbl_bridge_status", None)
            if lbl is None:
                return

            ## Only a real, logged-in connection says CONNECTED (never fake data in the UI).
            if is_connected:
                lbl.setText("ZEROGBRIDGE CONNECTED")
                lbl.setProperty("state", "online")
            else:
                lbl.setText("ZEROGBRIDGE DISCONNECTED")
                lbl.setProperty("state", "offline")

            ## Same unpolish/polish trick as the dot, so any CSS for "state" re-applies.
            lbl_style = lbl.style()
            if lbl_style is not None:
                lbl_style.unpolish(lbl)
                lbl_style.polish(lbl)
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to update bridge status: {e}")

    def _on_bridge_status_clicked(self):
        """Opens the ZeroGBridge page when the status bar field is clicked."""

        ## Reuses the nav click, so the ZEROGBRIDGE button lights up and the page loads.
        self._on_nav_clicked("zerogbridge")

    def update_alert_badge(self, alert_count):
        """Shows the alert count on the ALERTS & ANTI-CHEAT button; hidden when 0."""
        try:
            count = int(alert_count)

            ## Counts above 99 show as '99+' to keep the badge small.
            self.lbl_alert_badge.setText(str(count) if count < 100 else "99+")
            self.lbl_alert_badge.setVisible(count > 0)
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to update alert badge: {e}")

    # endregion

    # region Bridge Connection

    def setup_bridge(self):
        """Creates the CommandPipe and links its signals to the header. Starts it only if allowed."""
        self.command_pipe = None
        try:
            if CommandPipe is None:
                self.update_server_status("OFFLINE", False)
                return

            ## The saved setting decides. If settings can't load, it stays off (fail closed).
            auto_connect = load_app_settings()["bridge_auto_connect"] if load_app_settings else False
            if not auto_connect:
                print("[INFO] MainCockpit: Bridge auto-connect is off, staying OFFLINE")
                self.update_server_status("OFFLINE", False)
                return

            ## The starting itself now lives in connect_bridge(), so the ZeroGBridge page can use it too.
            self.connect_bridge()
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to set up bridge connection: {e}")
            self.update_server_status("OFFLINE", False)

    def connect_bridge(self):
        """Starts a CommandPipe for the active server. Returns True if it started, False if not."""
        try:
            if CommandPipe is None:
                print("[ERROR] MainCockpit: Bridge module missing, cannot connect")
                self.update_server_status("OFFLINE", False)
                return False

            ## isRunning() is True while the thread is still going. Never start a second pipe.
            command_pipe = getattr(self, "command_pipe", None)
            if command_pipe is not None and command_pipe.isRunning():
                print("[INFO] MainCockpit: Bridge already connected or connecting")
                return False

            ## An old pipe that has already stopped (e.g. a failed login) is thrown away first.
            ## deleteLater() lets Qt free it safely once it is no longer busy.
            if command_pipe is not None:
                command_pipe.deleteLater()

            self.command_pipe = CommandPipe(parent=self)

            ## connect() links a signal to a method. Qt delivers it on the window thread,
            ## so update_server_status can safely change the header widgets.
            self.command_pipe.connection_changed.connect(self.update_server_status)
            self.command_pipe.reply_received.connect(self._on_bridge_reply)

            ## start() launches the thread, and Qt then calls CommandPipe.run() in the background.
            self.command_pipe.start()
            print("[INFO] MainCockpit: Bridge connect started")
            return True
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to connect bridge: {e}")
            self.update_server_status("OFFLINE", False)
            return False

    def disconnect_bridge(self):
        """Stops the CommandPipe (closes the bridge connection). Returns True if one was stopped."""
        try:
            command_pipe = getattr(self, "command_pipe", None)
            if command_pipe is None:
                print("[INFO] MainCockpit: No bridge connection to close")
                return False

            ## stop() waits (up to 3 s) for the thread to close its socket and finish.
            command_pipe.stop()
            self.command_pipe = None

            ## A normal stop sends no signal, so we report the disconnect ourselves.
            ## The server name is kept, so the header still says which server it was.
            self.update_server_status(getattr(self, "bridge_server_name", "OFFLINE"), False)
            print("[INFO] MainCockpit: Bridge disconnected")
            return True
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to disconnect bridge: {e}")
            return False

    def open_zgb_portal(self):
        """Opens the ZeroGBridge Portal window, or brings it to the front if it is already open."""
        try:
            if ZeroGBridgePortal is None:
                print("[ERROR] MainCockpit: ZeroGBridge Portal module missing, cannot open")
                return False

            ## The portal is admin and up; moderators (or no one signed in) can't open it.
            if not self.user_has_role("admin"):
                print("[WARN] MainCockpit: ZeroGBridge Portal is admin and up, not opened")
                return False

            ## Only one portal at a time: if it's already open, just bring it forward.
            zgb_portal = getattr(self, "zgb_portal", None)
            if zgb_portal is not None:
                zgb_portal.raise_()
                zgb_portal.activateWindow()
                return True

            ## parent=self ties the portal to ZAH, so it closes when ZAH closes.
            self.zgb_portal = ZeroGBridgePortal(parent=self)

            ## The portal deletes itself when closed; destroyed tells us to forget it.
            self.zgb_portal.destroyed.connect(self._on_zgb_portal_closed)
            self.zgb_portal.show()
            print("[INFO] MainCockpit: ZeroGBridge Portal opened")
            return True
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to open ZeroGBridge Portal: {e}")
            return False
    def _on_zgb_portal_closed(self):
        """Forgets the portal after its window is closed, so the next open builds a fresh one."""
        self.zgb_portal = None
        print("[INFO] MainCockpit: ZeroGBridge Portal closed")


    def _on_bridge_reply(self, command_str, reply_text):
        """Receives each bridge reply. Pages will use these later; for now it only logs."""
        print(f"[INFO] MainCockpit: Reply received for {command_str.split(':')[0]}")

    # endregion

    # region Painting & Theme

    def paintEvent(self, event):
        """Force background canvas visualization mapping, scaled to cover the window."""
        try:
            painter = QPainter(self)
            if not self.background.isNull():
                scaled_bg = self.background.scaled(
                    self.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )

                ## Center the cover-scaled image so the edges crop evenly
                x = (self.width() - scaled_bg.width()) // 2
                y = (self.height() - scaled_bg.height()) // 2
                painter.drawPixmap(x, y, scaled_bg)
            painter.end()
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to paint background: {e}")

    def apply_theme(self):
        """Loads external CSS stylesheet from assets/ZAH_main.css."""
        try:
            css_path = asset_path("ZAH_main.css")
            with open(css_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
            print(f"[SUCCESS] Main Cockpit applied stylesheet: {css_path}")
        except Exception as e:
            print(f"[ERROR] Could not load stylesheet: {e}")

    def apply_letter_spacing(self):
        """
        Qt stylesheets cannot set letter-spacing, so the wide uppercase look
        is set here on each label and button font instead.
        """
        try:

            ## Object name -> extra space between letters, in pixels.
            spacing_by_name = {
                "AppTitleLabel": 2.0,
                "AppSubtitleLabel": 1.5,
                "ServerNameLabel": 1.5,
                "CtrlKLabel": 1.5,
                "ClockLabel": 2.0,
                "AdminNameLabel": 1.5,
                "NavButton": 1.2,
                "ContentHeaderLabel": 1.5,
                "ContentPlaceholderLabel": 2.0,
                "StatusLabel": 1.5,
            }

            ## Apply the spacing to every child widget whose name is in the table.
            for widget in self.findChildren(QWidget):
                spacing = spacing_by_name.get(widget.objectName())
                if spacing is None:
                    continue
                font = QFont(widget.font())
                font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
                widget.setFont(font)
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to apply letter spacing: {e}")

    # endregion

    # region Shutdown

    def closeEvent(self, event):
        """Logs a clean shutdown when the main window is closed."""
        try:
            if getattr(self, "clock_timer", None) is not None:
                self.clock_timer.stop()
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to stop header clock: {e}")

        try:

            ## Saved to a local name and checked, so Pylance (and Python) know it exists.
            command_pipe = getattr(self, "command_pipe", None)
            if command_pipe is not None:
                command_pipe.stop()
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to stop bridge connection: {e}")

        print("[INFO] MainCockpit: Shutting down main window...")
        event.accept()

    # endregion

# endregion
