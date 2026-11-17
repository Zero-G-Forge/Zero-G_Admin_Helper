# loading_screen.py

import os
import sys
from PyQt6.QtWidgets import QDialog, QApplication
from PyQt6.QtCore import QTimer, Qt, QRectF
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QFont, QPainterPath

try:
    from features.auth.login import LoginWindow
    from features.network.connection import NetworkWizardOverlay, is_network_ready
    from features.auth.persistence import is_session_valid, check_for_persistent_user
except ImportError:
    import sys
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
    from features.auth.login import LoginWindow
    from features.network.connection import NetworkWizardOverlay, is_network_ready
    from features.auth.persistence import is_session_valid, check_for_persistent_user

class ApplicationLoader(QDialog):
    """Screen 1A: Zero-G Advanced Loader - Active Event Pumping Engine"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.login_bypassed = False # Track bypass state for session validation
        self.onboarding_requested = False # State flag to track onboarding request
        print("[DEBUG] Initializing safe loader with active event loop pumping...")

        self.setFixedSize(1000, 750)
        self.setWindowTitle("System Initialization")

        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_dir, "../../"))
        
        bg_path = os.path.join(project_root, "assets/backgrounds/loading_screen.png")
        logo_path = os.path.join(project_root, "assets/branding/ZAH_emblem.png")

        self.bg_pixmap = QPixmap(os.path.normpath(bg_path))
        self.logo_pixmap = QPixmap(os.path.normpath(logo_path))

        self.current_progress = 0       
        self.pulse_offset = 0.0         
        
        self.account_checkpoint_cleared = False
        self.network_checkpoint_cleared = False
        self.is_boot_paused = False

        self.boot_timer = QTimer(self)
        self.boot_timer.timeout.connect(self.advance_loading_cycle)
        self.initialize_circuit_paths()

    def initialize_circuit_paths(self):
        self.circuit_paths = []
        
        p1 = QPainterPath()
        p1.moveTo(50, 350); p1.lineTo(200, 350); p1.lineTo(280, 280); p1.lineTo(350, 280)
        self.circuit_paths.append(p1)

        p2 = QPainterPath()
        p2.moveTo(950, 350); p2.lineTo(800, 350); p2.lineTo(720, 420); p2.lineTo(650, 420)
        self.circuit_paths.append(p2)

        p3 = QPainterPath()
        p3.moveTo(500, 50); p3.lineTo(500, 150); p3.lineTo(450, 200)
        self.circuit_paths.append(p3)

        p4 = QPainterPath()
        p4.moveTo(500, 700); p4.lineTo(500, 600); p4.lineTo(550, 550)
        self.circuit_paths.append(p4)

    def start_boot_sequence(self):
        print("[STATUS] Starting timeline synchronization loop...")
        self.boot_timer.start(30)

    def advance_loading_cycle(self):
        # HARD LOCK: If paused for a modal, exit immediately
        if self.is_boot_paused:
            return
              
        # 1. VISUAL ANIMATION LOGIC (Persisted)
        # Advance vector glow offset across circuit paths
        self.pulse_offset += 5.0
        if self.pulse_offset >= 200.0:
            self.pulse_offset = 0.0

        # 2. STATE-GATED PROGRESSION
        # --- LOGIN GATE (30%) ---
        # Verifies account persistence or launches the modal login dialog
        if self.current_progress == 30 and not self.account_checkpoint_cleared:
            # Force loading progress to stop
            self.boot_timer.stop()
            print("[DEBUG] Milestone 30% Hit: Running Persistence Check...")

            # Scenario A: Persistent session exists, bypass interactive login
            if is_session_valid() or check_for_persistent_user():
                print("[SUCCESS] Active session/persistent user found. Bypassing login.")
                self.account_checkpoint_cleared = True
                self.current_progress = 31 # Advance past checkpoint boundary
                self.boot_timer.start(30)
                return
            else:
                # Scenario B: No persistent session detected, engage modal login dialog
                print("[INFO] No valid session detected. Opening Login Window...")
                self.is_boot_paused = True # Engage lock to prevent background progression
                
                # Instantiate LoginWindow modal
                login_win = LoginWindow(self)
                login_win.setWindowModality(Qt.WindowModality.ApplicationModal)
                
                # Execute modal dialog in blocking loop
                result = login_win.exec()
                
                if result == QDialog.DialogCode.Accepted:
                    print("[SUCCESS] Login verified. Resuming initialization sequence...")
                    self.account_checkpoint_cleared = True
                    self.is_boot_paused = False # Release modal lock
                    self.current_progress = 31 # Advance progress past 30% boundary
                    self.boot_timer.start(30) # Restart timer
                    return
                else:
                    # User canceled or closed login modal, abort boot sequence cleanly
                    print("[STATUS] Login canceled or rejected. Terminating application initialization...")
                    self.boot_timer.stop()
                    self.reject()
                    return # Exit loop until window is closed
            
        # --- NETWORK GATE (60%) ---
        # Validates server configuration profile and verifies port reachability via ping
        elif self.current_progress == 60 and not self.network_checkpoint_cleared:
            self.boot_timer.stop() # 1. Stop timer
            print("[DEBUG] Milestone 60% Hit: Running Network Diagnostics...")

            # Scenario A: Server configuration profile is valid and port probe passes
            if is_network_ready():
                print("[SUCCESS] Network profile verified and ping passed.")
                self.network_checkpoint_cleared = True
                self.current_progress = 61 # Advance past checkpoint boundary
                self.boot_timer.start(30)
                return
            else:
                # Scenario B: Configuration profile is missing, corrupted, or unreachable
                print("[INFO] Server configuration invalid or unreachable. Opening Network Connection Wizard...")
                self.is_boot_paused = True # 2. Set pause flag to prevent further increments
                
                # 3. Use exec() for modal blocking
                network_wizard = NetworkWizardOverlay(self)
                result = network_wizard.exec()
                
                if result == QDialog.DialogCode.Accepted and is_network_ready():
                    print("[SUCCESS] Network configuration saved and verified. Resuming initialization sequence...")
                    self.network_checkpoint_cleared = True
                    self.is_boot_paused = False # Release modal lock
                    self.current_progress = 61 # Advance progress past 60% boundary
                    self.boot_timer.start(30) # Restart timer
                    return
                else:
                    # User canceled or network remained unreachable after wizard
                    print("[STATUS] Network setup canceled or ping failed. Halting progression...")
                    self.boot_timer.stop()
                    self.reject()
                    return 

        # Advance regular progress counter
        self.current_progress += 1

        # 3. TRIGGER REPAINT
        self.update()

        # 4. FINALIZATION
        if self.current_progress >= 100:
            print("[STATUS] Milestone 100% Reached. Committing Handoff.")
            self.boot_timer.stop()
            self.accept() 
            return

    def resume_boot_sequence(self):
        """Callback to resume the timer after a modal is dismissed."""
        print("[STATUS] Gate cleared. Resuming boot sequence...")
        self.boot_timer.start(30)
        self.accept()

    def handle_login_rejected(self):
        print(f"[INFO] Login rejected or canceled. Terminating program.")

        # 1. Close the current loader explicitly
        self.close()

        # 2. Safely stop all processes and exits program
        self.boot_timer.stop()
        QApplication.quit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.bg_pixmap.isNull():
            painter.drawPixmap(0, 0, 1000, 750, self.bg_pixmap)

        underlay_pen = QPen(QColor("#11293a"), 1.5, Qt.PenStyle.SolidLine)
        painter.setPen(underlay_pen)
        for path in self.circuit_paths:
            painter.drawPath(path)

        pulse_glow_pen = QPen(QColor(0, 255, 255, 40), 5.0)  
        pulse_glow_pen.setDashPattern([30, 150]); pulse_glow_pen.setDashOffset(self.pulse_offset)
        pulse_core_pen = QPen(QColor("#00ffff"), 1.8)        
        pulse_core_pen.setDashPattern([30, 150]); pulse_core_pen.setDashOffset(self.pulse_offset)

        painter.setPen(pulse_glow_pen)
        for path in self.circuit_paths:
            painter.drawPath(path)

        painter.setPen(pulse_core_pen)
        for path in self.circuit_paths:
            painter.drawPath(path)

        if not self.logo_pixmap.isNull():
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            
            target_height = 420.0  
            scale_factor = target_height / self.logo_pixmap.height()
            target_width = self.logo_pixmap.width() * scale_factor
            target_x = (1000.0 - target_width) / 2.5
            target_y = 190
            
            logo_rect = QRectF(target_x, target_y, target_width, target_height)
            painter.drawPixmap(logo_rect, self.logo_pixmap, QRectF(self.logo_pixmap.rect()))
            painter.restore()

        text_rect = QRectF(100, 620, 800, 40)
        painter.setPen(QColor("#00ffff"))
        font = QFont("Courier New", 14, QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        painter.setFont(font)
        
        status_msg = f"INITIALIZING SYSTEM ARCHITECTURE... {self.current_progress}%" if self.current_progress < 100 else "ALL MODULES ONLINE"
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, status_msg)