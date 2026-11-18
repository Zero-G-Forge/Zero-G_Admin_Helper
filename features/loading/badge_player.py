## =====================================================================
## MODULE: features/loading/badge_player.py
## DESCRIPTION: Looping badge animation for the loading screen
## =====================================================================

import os
import glob
from features.paths import asset_path
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap

## Frame folder made from assets/branding/ZAH_badge_anim.webm
## (400 px PNG frames, real alpha from the webm, no audio, loop already blended)
## The older mp4 version is kept at assets/branding/ZAH_badge_anim.mp4
BADGE_ANIM_FOLDER = ("branding", "ZAH_badge_anim")

## The source video runs at 24 fps
BADGE_ANIM_FPS = 24


class BadgePlayer(QObject):
    """
    Plays the badge frame sequence on a loop with a QTimer.
    Frames are read from disk one at a time, so memory use stays small.
    If no frames are found, is_ready() returns False and the loader
    falls back to the still badge.
    """

    frame_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame_paths = []
        self.frame_index = 0
        self.current_pixmap = QPixmap()

        try:
            folder = asset_path(*BADGE_ANIM_FOLDER)
            self.frame_paths = sorted(glob.glob(os.path.join(folder, "ZAH_badge_anim_*.png")))
            if self.frame_paths:
                self.current_pixmap = QPixmap(self.frame_paths[0])
            if self.current_pixmap.isNull():
                print(f"[WARNING] BadgePlayer: No badge animation frames found in: {folder}")
                self.frame_paths = []
            else:
                print(f"[SUCCESS] BadgePlayer: Loaded badge animation, {len(self.frame_paths)} frames")

            self.frame_timer = QTimer(self)
            self.frame_timer.timeout.connect(self._on_frame_tick)
        except Exception as e:
            print(f"[ERROR] BadgePlayer: Failed to set up badge animation: {e}")
            self.frame_paths = []
            self.current_pixmap = QPixmap()

    def is_ready(self):
        """True when at least one frame loaded."""
        return bool(self.frame_paths) and not self.current_pixmap.isNull()

    def start(self):
        """Starts the loop."""
        try:
            if self.is_ready():
                self.frame_timer.start(int(1000 / BADGE_ANIM_FPS))
        except Exception as e:
            print(f"[ERROR] BadgePlayer: Failed to start badge animation: {e}")

    def stop(self):
        """Stops the loop."""
        try:
            self.frame_timer.stop()
        except Exception as e:
            print(f"[ERROR] BadgePlayer: Failed to stop badge animation: {e}")

    def _on_frame_tick(self):
        """Shows the next frame, wrapping back to the first one."""
        try:
            self.frame_index = (self.frame_index + 1) % len(self.frame_paths)
            next_pixmap = QPixmap(self.frame_paths[self.frame_index])
            ## A bad frame is skipped; the last good frame stays on screen
            if not next_pixmap.isNull():
                self.current_pixmap = next_pixmap
            self.frame_changed.emit()
        except Exception as e:
            print(f"[ERROR] BadgePlayer: Failed to show badge frame: {e}")
            self.stop()
