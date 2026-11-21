## =====================================================================
## MODULE: features/loading/loading_screen.py
## DESCRIPTION: Screen 1A: Zero-G Loading Screen (Splash Loader Canvas)
## =====================================================================

# region Imports

import os
from features.paths import asset_path, ensure_data_dir
from PyQt6.QtWidgets import QDialog, QWidget, QLabel, QProgressBar
from PyQt6.QtCore import QTimer, Qt, QRectF
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QFont, QPainterPath, QFontDatabase

# endregion

# region Optional Modules

## Guarded imports: if a piece is missing, the loader falls back to simpler drawing.
try:
    from features.shared.progress_bar import ProgressBarWidget
except ImportError as e:
    print(f"[ERROR] ApplicationLoader: Could not load ProgressBarWidget: {e}")
    ProgressBarWidget = None

try:
    from features.loading.badge_player import BadgePlayer
except ImportError as e:
    print(f"[ERROR] ApplicationLoader: Could not load BadgePlayer: {e}")
    BadgePlayer = None

try:
    from features.login.login_window import LoginWindow
except ImportError as e:
    print(f"[ERROR] ApplicationLoader: Could not load LoginWindow: {e}")
    LoginWindow = None

## Saved-login helpers. If any are missing, the saved login is skipped and the login window shows as normal.
try:
    from features.login.saved_session import load_session_token, clear_session_token
    from features.login.online_login import check_saved_session
except ImportError as e:
    print(f"[ERROR] ApplicationLoader: Could not load saved login helpers: {e}")
    load_session_token = None
    clear_session_token = None
    check_saved_session = None

## Developer offline remember. If it's missing, the developer just signs in as normal.
try:
    from features.login.offline_remember import check_offline_remember
except ImportError as e:
    print(f"[ERROR] ApplicationLoader: Could not load offline remember: {e}")
    check_offline_remember = None

# endregion

# region Loader Settings

## Loader canvas size (same as the legacy loader)
LOADER_WIDTH = 1000
LOADER_HEIGHT = 750

## Timer tick in ms. One tick = 1% progress, so 100 ticks is about 2 seconds.
BOOT_TICK_MS = 55  ## Ray picked the slower preview speed (about 5.5 s), Nov 18

## Milestone markers from the Loading_Screen mockup.
## 30% = login check, 60% = network check. They are drawn on the bar now,
## and become real gates when the login and bridge modules are built.
## They are only drawn with the plain fallback bar; the shared
## ProgressBarWidget has its hex tag in that space.
MILESTONE_MARKERS = [30, 60]

## Font used by every label (Inter on Zorin, DejaVu Sans as a fallback)
CORE_FONT_FAMILIES = ["Inter", "DejaVu Sans"]

# endregion


# region ApplicationLoader Class

class ApplicationLoader(QDialog):
    """
    Screen 1A: Zero-G Loading Screen.
    Shows the badge on the plating background, steps through the real
    startup stages, then hands the built MainCockpit back to ZAH.py.
    """

    # region Setup

    def __init__(self, build_main_window=None, parent=None):
        super().__init__(parent)

        ## Callback from ZAH.py that builds (but does not show) the main window
        self.build_main_window = build_main_window
        self.main_window = None

        ## Progress state and drawing resources, filled in during setup.
        self.current_progress = 0
        self.pulse_offset = 0.0
        self.status_text = "STARTING UP"
        self.transfer_bar = None
        self.stage_failed = False
        self.bg_pixmap = QPixmap()
        self.logo_pixmap = QPixmap()
        self.badge_player = None
        self.circuit_paths = []

        ## Login state. ZAH.py only opens the main window if login_passed is True.
        self.login_passed = False
        self.signed_in_user = None
        self.signed_in_role = None

        ## Startup stages: (progress %, status text, stage function)
        self.boot_stages = [
            (5, "CHECKING ASSETS", self._stage_check_assets),
            (25, "PREPARING DATA FOLDER", self._stage_prepare_data),
            (30, "USER LOGIN CHECK", self._stage_login_gate),
            (45, "LOADING FONTS", self._stage_load_fonts),
            (70, "BUILDING MAIN WINDOW", self._stage_build_main_window),
        ]

        try:
            print("[INFO] ApplicationLoader: Initializing loading screen...")
            self.setObjectName("ApplicationLoaderCanvas")
            self.setFixedSize(LOADER_WIDTH, LOADER_HEIGHT)
            self.setWindowTitle("Zero-G Admin Helper")

            self._load_images()
            self.setup_badge_player()
            self.initialize_circuit_paths()
            self.setup_widgets()
            self.apply_theme()
            self.apply_letter_spacing()
            self._update_status_label()

            ## Timer that drives the loading cycle. start_boot_sequence() starts it.
            self.boot_timer = QTimer(self)
            self.boot_timer.timeout.connect(self.advance_loading_cycle)
            print("[SUCCESS] ApplicationLoader: Loading screen initialized.")
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Failed to initialize the loading screen: {e}")
            raise

    # endregion

    # region Images & Animation

    def _load_images(self):
        """Loads the plating background and the Admin Helper badge."""
        try:
            bg_path = asset_path("new_backgrounds", "plating.jpg")
            self.bg_pixmap = QPixmap(bg_path)
            if self.bg_pixmap.isNull():
                print(f"[WARNING] ApplicationLoader: Background missing or unreadable: {bg_path}")
            else:
                print(f"[SUCCESS] ApplicationLoader: Background loaded: {bg_path}")
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Failed to load background: {e}")

        try:
            ## The 512 px copy is plenty for the splash. Fall back to the full-size badge.
            logo_path = asset_path("branding", "ZAH_badge_512.png")
            if not os.path.exists(logo_path):
                logo_path = asset_path("branding", "ZAH_badge.png")
            self.logo_pixmap = QPixmap(logo_path)
            if self.logo_pixmap.isNull():
                print(f"[WARNING] ApplicationLoader: Badge missing or unreadable: {logo_path}")
            else:
                print(f"[SUCCESS] ApplicationLoader: Badge loaded: {logo_path}")
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Failed to load badge: {e}")

    def setup_badge_player(self):
        """Starts the looping badge animation. The still badge is used if it fails."""
        try:
            if BadgePlayer is None:
                return
            player = BadgePlayer(self)
            if player.is_ready():
                player.frame_changed.connect(self.update)
                player.start()
                self.badge_player = player
            else:
                print("[WARNING] ApplicationLoader: Badge animation unavailable. Using still badge.")
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Failed to start badge animation: {e}. Using still badge.")
            self.badge_player = None

    def initialize_circuit_paths(self):
        """Circuit lines with the travelling cyan pulse (kept from the legacy loader)."""
        try:
            self.circuit_paths = []

            ## Each path is a line of points: moveTo starts the line, lineTo adds the next corner.
            p1 = QPainterPath()
            p1.moveTo(50, 300); p1.lineTo(200, 300); p1.lineTo(260, 240); p1.lineTo(330, 240)
            self.circuit_paths.append(p1)

            p2 = QPainterPath()
            p2.moveTo(950, 300); p2.lineTo(800, 300); p2.lineTo(740, 360); p2.lineTo(670, 360)
            self.circuit_paths.append(p2)

            p3 = QPainterPath()
            p3.moveTo(500, 20); p3.lineTo(500, 70); p3.lineTo(470, 100)
            self.circuit_paths.append(p3)
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Failed to build circuit paths: {e}")
            self.circuit_paths = []

    # endregion

    # region Widgets & Theme

    def setup_widgets(self):
        """Builds the title label, the progress bar and the status line."""
        try:
            ## Large title under the badge, placed at a fixed pixel position.
            self.lbl_app_title = QLabel("ZERO-G ADMIN HELPER", self)
            self.lbl_app_title.setObjectName("LoaderTitleLabel")
            self.lbl_app_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lbl_app_title.setGeometry(100, 438, 800, 48)
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Failed to build title labels: {e}")

        ## Shared CORE TRANSFER bar. The plain QProgressBar below is only
        ## built if the shared bar cannot be loaded.
        try:
            if ProgressBarWidget is not None:
                self.transfer_bar = ProgressBarWidget("STARTING UP...", "main", self)
                self.transfer_bar.setGeometry(90, 500, 820, 215)
                return
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Failed to build ProgressBarWidget: {e}. Using plain bar.")
            self.transfer_bar = None

        ## Fallback: plain progress bar plus a status text line.
        try:
            self.progress_bar = QProgressBar(self)
            self.progress_bar.setObjectName("LoaderProgressBar")
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_bar.setTextVisible(False)
            self.progress_bar.setGeometry(120, 640, 760, 12)

            self.lbl_status = QLabel("", self)
            self.lbl_status.setObjectName("LoaderStatusLabel")
            self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lbl_status.setGeometry(120, 664, 760, 26)
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Failed to build progress bar: {e}")

    def apply_theme(self):
        """Loads external CSS stylesheet from assets/ZAH_main.css."""
        try:
            css_path = asset_path("ZAH_main.css")
            with open(css_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
            print(f"[SUCCESS] ApplicationLoader applied stylesheet: {css_path}")
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Could not load stylesheet: {e}")

    def apply_letter_spacing(self):
        """
        Qt stylesheets cannot set letter-spacing, so the wide uppercase look
        is set here on each label font instead.
        """
        try:
            ## Object name -> extra space between letters, in pixels.
            spacing_by_name = {
                "LoaderTitleLabel": 6.0,
                "LoaderStatusLabel": 2.5,
            }
            for widget in self.findChildren(QWidget):
                spacing = spacing_by_name.get(widget.objectName())
                if spacing is None:
                    continue
                font = QFont(widget.font())
                font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
                widget.setFont(font)
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Failed to apply letter spacing: {e}")

    # endregion

    # region Boot Sequence

    def start_boot_sequence(self):
        """Starts the progress timer."""
        try:
            print("[INFO] ApplicationLoader: Starting boot sequence...")
            self.boot_timer.start(BOOT_TICK_MS)
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Failed to start boot timer: {e}")
            self.accept()

    def advance_loading_cycle(self):
        """One timer tick: move the pulse, run any stage due now, and step the bar."""
        try:
            ## 1. VISUAL ANIMATION LOGIC
            self.pulse_offset += 5.0
            if self.pulse_offset >= 200.0:
                self.pulse_offset = 0.0

            ## 2. STAGES: run each stage when the bar reaches its milestone
            for stage_progress, stage_text, stage_function in self.boot_stages:
                if self.current_progress == stage_progress:
                    self._run_stage(stage_text, stage_function)

            ## 3. Advance regular progress counter
            self.current_progress += 1
            if self.current_progress >= 100:
                self.current_progress = 100
                self.status_text = "ALL MODULES ONLINE"
            self._update_status_label()
            self.update()

            ## 4. FINALIZATION
            if self.current_progress >= 100:
                print("[INFO] ApplicationLoader: 100% reached. Handing off to MainCockpit.")
                self.boot_timer.stop()
                ## Short pause so "ALL MODULES ONLINE" can be read
                QTimer.singleShot(250, self.accept)
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Boot cycle failed: {e}")
            self.boot_timer.stop()
            self.accept()

    def _run_stage(self, stage_text, stage_function):
        """Shows the stage text, then runs the stage. A failed stage is logged and skipped."""
        self.status_text = stage_text
        self._update_status_label()
        ## repaint() draws right away, so the stage text shows before the stage runs.
        self.repaint()
        try:
            print(f"[INFO] ApplicationLoader: {stage_text.title()}...")
            stage_function()
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Stage '{stage_text.title()}' failed: {e}")
            self.stage_failed = True

    # endregion

    # region Startup Stages

    def _stage_check_assets(self):
        """Checks the files the main window needs are on disk."""
        needed_assets = [
            ("ZAH_main.css",),
            ("new_backgrounds", "hexgrid.jpg"),
            ("branding", "ZG_AdminHelper.png"),
        ]
        for parts in needed_assets:
            path = asset_path(*parts)
            if os.path.exists(path):
                print(f"[SUCCESS] ApplicationLoader: Found {'/'.join(parts)}")
            else:
                print(f"[WARNING] ApplicationLoader: Missing {'/'.join(parts)}")

    def _stage_prepare_data(self):
        """Makes sure data/ exists under the app root."""
        data_dir = ensure_data_dir()
        print(f"[SUCCESS] ApplicationLoader: Data folder ready: {data_dir}")

    def _try_saved_session(self):
        """Checks a saved "Keep me logged in" token. Returns {"username", "role"} or None."""
        
        ## Fail closed: any missing piece or problem returns None, and the login window shows.
        try:

            ## The developer's offline note is checked first; it needs no internet.
            if check_offline_remember is not None:
                developer_name = check_offline_remember()
                if developer_name is not None:
                    return {"username": developer_name, "role": "developer"}
            if load_session_token is None or check_saved_session is None:
                return None
            session_token = load_session_token()
            if session_token is None:
                return None
            session_result, session_details = check_saved_session(session_token)
            if session_result == "ok" and session_details is not None:
                return session_details
            
            ## "denied" means the token is dead for good, so the file is removed. "offline" keeps it for next time.
            if session_result == "denied" and clear_session_token is not None:
                clear_session_token()
            return None
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Saved login check failed: {e}")
            return None
    
    def _stage_login_gate(self):
        """30% gate: pauses the loader and shows the login window. Fails closed."""
        ## Unlike other stages, this one never "logs and skips": any problem quits ZAH.
        try:
            ## The timer is stopped first; otherwise it keeps ticking behind the open login window.
            self.boot_timer.stop()

            ## A saved "Keep me logged in" token is tried first. Only an "ok" from the service skips the login window.
            saved_login = self._try_saved_session()
            if saved_login is not None:
                self.login_passed = True
                self.signed_in_user = saved_login["username"]
                self.signed_in_role = saved_login["role"]
                print("[SUCCESS] ApplicationLoader: Saved login verified. Resuming startup...")
                self.boot_timer.start(BOOT_TICK_MS)
                return
            if LoginWindow is None:
                print("[ERROR] ApplicationLoader: Login window missing. Stopping for safety.")
                self.reject()
                return

            login_window = LoginWindow(self)
            ## exec() shows the window and waits here until it is accepted or rejected.
            login_result = login_window.exec()

            if login_result == QDialog.DialogCode.Accepted:
                self.login_passed = True
                self.signed_in_user = login_window.signed_in_user
                self.signed_in_role = login_window.signed_in_role
                print("[SUCCESS] ApplicationLoader: Login verified. Resuming startup...")
                self.boot_timer.start(BOOT_TICK_MS)
            else:
                print("[STATUS] ApplicationLoader: Login cancelled. Shutting down.")
                self.reject()
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Login gate failed: {e}. Stopping for safety.")
            self.login_passed = False
            self.reject()

    def _stage_load_fonts(self):
        """Checks the Inter font is installed (DejaVu Sans is used if it is not)."""
        ## List of every font family installed on this computer.
        families = QFontDatabase.families()
        if "Inter" in families:
            print("[SUCCESS] ApplicationLoader: Inter font found.")
        else:
            print("[WARNING] ApplicationLoader: Inter font not installed. Using DejaVu Sans.")

    def _stage_build_main_window(self):
        """Builds the MainCockpit (hidden) through the callback from ZAH.py."""
        if self.build_main_window is None:
            print("[WARNING] ApplicationLoader: No main window builder given.")
            return
        self.main_window = self.build_main_window()
        print("[SUCCESS] ApplicationLoader: MainCockpit built.")

    # endregion

    # region Status Line

    def _update_status_label(self):
        """Writes the status line, e.g. 'CHECKING ASSETS... 12%'."""
        try:
            ## Shared bar: progress value, title text and colour state.
            if self.transfer_bar is not None:
                self.transfer_bar.set_progress(self.current_progress)
                if self.current_progress < 100:
                    self.transfer_bar.set_title(f"{self.status_text}...")
                    self.transfer_bar.set_state("error" if self.stage_failed else "normal")
                elif self.stage_failed:
                    self.transfer_bar.set_title("STARTED WITH ERRORS")
                    self.transfer_bar.set_state("error")
                else:
                    self.transfer_bar.set_title("ALL MODULES ONLINE")
                    self.transfer_bar.set_state("complete")
                return
            ## Plain fallback bar and its status text.
            self.progress_bar.setValue(self.current_progress)
            if self.current_progress < 100:
                self.lbl_status.setText(f"{self.status_text}... {self.current_progress}%")
            else:
                self.lbl_status.setText("ALL MODULES ONLINE")
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Failed to update status line: {e}")

    # endregion

    # region Painting

    def paintEvent(self, event):
        """Paints the plating background, circuit pulse, badge and glass panel."""
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            self._paint_background(painter)
            self._paint_circuits(painter)
            self._paint_badge(painter)
            if self.transfer_bar is None:
                self._paint_progress_panel(painter)
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Failed to paint loading screen: {e}")
        finally:
            painter.end()

    def _paint_background(self, painter):
        """Plating image scaled to cover the window, darkened so the text reads."""
        painter.fillRect(self.rect(), QColor("#050b14"))
        if not self.bg_pixmap.isNull():
            scaled_bg = self.bg_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            ## Center the cover-scaled image so the edges crop evenly
            x = (self.width() - scaled_bg.width()) // 2
            y = (self.height() - scaled_bg.height()) // 2
            painter.drawPixmap(x, y, scaled_bg)
        painter.fillRect(self.rect(), QColor(5, 11, 20, 120))

    def _paint_circuits(self, painter):
        """Dark circuit lines with a moving cyan pulse."""
        ## Dark base lines first, then a soft glow pen and a bright core pen for the pulse.
        painter.setPen(QPen(QColor("#11293a"), 1.5, Qt.PenStyle.SolidLine))
        for path in self.circuit_paths:
            painter.drawPath(path)

        ## Dash pattern [30, 150]: 30 px of light, then a 150 px gap. The offset slides the dash along the line.
        pulse_glow_pen = QPen(QColor(51, 214, 255, 40), 5.0)
        pulse_glow_pen.setDashPattern([30, 150]); pulse_glow_pen.setDashOffset(self.pulse_offset)
        pulse_core_pen = QPen(QColor("#33d6ff"), 1.8)
        pulse_core_pen.setDashPattern([30, 150]); pulse_core_pen.setDashOffset(self.pulse_offset)

        painter.setPen(pulse_glow_pen)
        for path in self.circuit_paths:
            painter.drawPath(path)
        painter.setPen(pulse_core_pen)
        for path in self.circuit_paths:
            painter.drawPath(path)

    def _paint_badge(self, painter):
        """Badge centred above the title: animation frame, else the still badge, else nothing."""
        badge_pixmap = self.logo_pixmap
        if self.badge_player is not None and not self.badge_player.current_pixmap.isNull():
            badge_pixmap = self.badge_player.current_pixmap
        if badge_pixmap.isNull():
            return
        ## Badge is drawn 380 px square, centred left to right, 48 px from the top.
        target_size = 380.0
        target_x = (LOADER_WIDTH - target_size) / 2
        target_y = 48.0
        logo_rect = QRectF(target_x, target_y, target_size, target_size)
        painter.drawPixmap(logo_rect, badge_pixmap, QRectF(badge_pixmap.rect()))

    def _paint_progress_panel(self, painter):
        """Navy glass panel behind the bar, with the 30% and 60% milestone markers."""
        panel_rect = QRectF(90, 604, 820, 100)
        painter.setPen(QPen(QColor(40, 170, 215, 110), 1.0))
        painter.setBrush(QColor(8, 20, 34, 205))
        painter.drawRoundedRect(panel_rect, 10, 10)

        ## Numbered circles at each milestone. They turn cyan once the bar has passed them.
        bar_x = 120.0
        bar_width = 760.0
        marker_font = QFont(CORE_FONT_FAMILIES[0], 8, QFont.Weight.DemiBold)
        marker_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        painter.setFont(marker_font)
        for marker_number, marker_progress in enumerate(MILESTONE_MARKERS, start=1):
            marker_x = bar_x + bar_width * marker_progress / 100.0
            reached = self.current_progress >= marker_progress
            marker_color = QColor("#33d6ff") if reached else QColor(185, 202, 216, 120)
            painter.setPen(QPen(marker_color, 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(marker_x - 7, 618, 14, 14))
            painter.drawText(QRectF(marker_x - 7, 618, 14, 14), Qt.AlignmentFlag.AlignCenter, str(marker_number))

    # endregion

    # region Shutdown

    def done(self, result):
        """Stops the badge animation when the loading screen finishes."""
        try:
            if self.badge_player is not None:
                self.badge_player.stop()
            if self.transfer_bar is not None:
                self.transfer_bar.shimmer_timer.stop()
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Failed to stop badge animation: {e}")
        super().done(result)

    def closeEvent(self, event):
        """Stops the timers if the loading screen is closed early."""
        try:
            self.boot_timer.stop()
            if self.badge_player is not None:
                self.badge_player.stop()
        except Exception as e:
            print(f"[ERROR] ApplicationLoader: Failed to stop boot timer: {e}")
        print("[INFO] ApplicationLoader: Loading screen closed.")
        event.accept()

    # endregion

# endregion
