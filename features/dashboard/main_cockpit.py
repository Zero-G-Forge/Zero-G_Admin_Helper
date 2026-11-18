## =====================================================================
## MODULE: features/dashboard/main_cockpit.py
## DESCRIPTION: Core Main Cockpit Window Shell (Pure Layout & CSS Core)
## =====================================================================

import os
import sys
from features.paths import asset_path
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QButtonGroup, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QTime, QSize
from PyQt6.QtGui import QPainter, QPixmap, QFont

try:
    from features.dashboard.nav_icons import build_nav_icon, build_logo_pixmap
except ImportError as e:
    print(f"[ERROR] MainCockpit: Could not load nav_icons: {e}")
    build_nav_icon = None
    build_logo_pixmap = None


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
]

## Font used by every label (Inter on Zorin, DejaVu Sans as a fallback)
CORE_FONT_FAMILIES = ["Inter", "DejaVu Sans"]


class MainCockpit(QMainWindow):
    """
    Core Main Administration Cockpit Dashboard Shell.
    Maintains clean layout scaffolding and centralized CSS lookups.
    """

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

            ## 2. Central UI Canvas
            self.central_widget = QWidget()
            self.central_widget.setObjectName("CentralWidgetCanvas")
            self.setCentralWidget(self.central_widget)

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

            self.lbl_admin_name = QLabel("ADMIN: RAY")
            self.lbl_admin_name.setObjectName("AdminNameLabel")
            self.header_layout.addWidget(self.lbl_admin_name)
            print("[INFO] MainCockpit: Header bar built")
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to build header bar: {e}")

    def _make_header_divider(self):
        """Returns a thin vertical divider line for the header."""
        divider = QFrame()
        divider.setObjectName("HeaderDivider")
        divider.setFixedSize(1, 30)
        return divider

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

            self.nav_button_group = QButtonGroup(self)
            self.nav_button_group.setExclusive(True)

            for page_key, page_text in NAV_PAGES:
                btn = self._make_nav_button(page_key, page_text)
                if btn is None:
                    continue
                self.nav_buttons[page_key] = btn
                self.nav_button_group.addButton(btn)
                self.left_column.addWidget(btn)

            self.left_column.addStretch()

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

            self.lbl_bridge_status = QLabel("ZEROGBRIDGE DISCONNECTED")
            self.lbl_bridge_status.setProperty("state", "offline")
            self.lbl_server_cpu = QLabel("CPU --")
            self.lbl_server_ram = QLabel("RAM --")
            self.lbl_players = QLabel("PLAYERS --")
            self.lbl_core_version = QLabel("CORE --")

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

    def setup_clock_timer(self):
        """Starts a 1 second local timer that keeps the header clock (HH:MM) current."""
        try:
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

    def _page_title(self, page_key):
        """Returns the button text for a page key, used as the content title."""
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
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to switch page to {page_key}: {e}")

    def update_server_status(self, server_name, is_connected):
        """
        Updates the header server name and status dot.
        Called by the bridge module in a later step; green only on a real connection.
        """
        try:
            self.lbl_server_name.setText(str(server_name).upper())
            state = "online" if is_connected else "offline"
            self.lbl_server_status_dot.setProperty("state", state)
            self.lbl_server_status_dot.style().unpolish(self.lbl_server_status_dot)
            self.lbl_server_status_dot.style().polish(self.lbl_server_status_dot)
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to update server status: {e}")

    def update_alert_badge(self, alert_count):
        """Shows the alert count on the ALERTS & ANTI-CHEAT button; hidden when 0."""
        try:
            count = int(alert_count)
            self.lbl_alert_badge.setText(str(count) if count < 100 else "99+")
            self.lbl_alert_badge.setVisible(count > 0)
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to update alert badge: {e}")

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
            for widget in self.findChildren(QWidget):
                spacing = spacing_by_name.get(widget.objectName())
                if spacing is None:
                    continue
                font = QFont(widget.font())
                font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
                widget.setFont(font)
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to apply letter spacing: {e}")

    def closeEvent(self, event):
        """Logs a clean shutdown when the main window is closed."""
        try:
            if getattr(self, "clock_timer", None) is not None:
                self.clock_timer.stop()
        except Exception as e:
            print(f"[ERROR] MainCockpit: Failed to stop header clock: {e}")
        print("[INFO] MainCockpit: Shutting down main window...")
        event.accept()
