## =====================================================================
## MODULE: features/shared/progress_bar.py
## DESCRIPTION: Shared image-layer progress bar (CORE TRANSFER style)
## =====================================================================

## region: Imports

import os
import math
from features.paths import asset_path
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import (
    QPainter, QPixmap, QColor, QFont, QFontMetricsF, QPen, QPolygonF, QLinearGradient, QPainterPath
)

## endregion

## region: Pieces & Colours

## Folder that holds AHB-2's transparent bar pieces
PROGRESS_BAR_FOLDER = ("additional_assets", "progress_bar")

## Valid states and their accent colours (title, tag text, painted fallback)
STATE_COLORS = {
    "normal": "#33d6ff",
    "warning": "#ff9a1f",
    "complete": "#2ee66b",
    "error": "#ff3355",
}

## Painted fallback fill gradients (left colour, right colour) per state
FALLBACK_FILL_COLORS = {
    "normal": ("#22c8ff", "#b46bff"),
    "warning": ("#ff7a00", "#ffc21a"),
    "complete": ("#14b84a", "#6dff9a"),
    "error": ("#b0102a", "#ff4d5e"),
}

## endregion

## region: Piece Layout

## Where the fill track sits inside the frame image, as fractions of the frame
## (measured from the reference frames: track starts about 4% in from each side,
## 29% down from the top and ends 20% up from the bottom)
## Kept for reference only: PIECE_LAYOUTS below now holds the exact pixel
## positions from AHB-2's LAYOUT.md.
TRACK_INSET_LEFT = 0.042
TRACK_INSET_RIGHT = 0.042
TRACK_INSET_TOP = 0.29
TRACK_INSET_BOTTOM = 0.20

## Exact piece positions from assets/additional_assets/progress_bar/LAYOUT.md.
## All numbers are pixels from the frame's top-left corner at 1:1 scale.
## The widget scales every piece by the same factor so these stay true.
##   frame        : frame image size
##   track_x/w    : inner track left edge and width (lead x = track_x + track_w * P / 100)
##   track_y/h    : inner track top and height
##   fill_pos     : where the fill image is placed
##   fill_size    : fill image size (crop width = 2 + track_w * P / 100, full width at 100%)
##   ring_size    : ring image size, placed at (lead_x - ring_w / 2, 0)
##   tag_size     : tag image size, placed at (lead_x - tag_w / 2, tag_y)
##   tag_y        : tag top (negative = above the frame)
##   text_y       : percent text centre line
##   title_height : space above the tag for the bar title (ours, not in LAYOUT.md)
PIECE_LAYOUTS = {
    "main": {
        "frame": (1125, 172),
        "track_x": 47, "track_w": 1031,
        "track_y": 50, "track_h": 88,
        "fill_pos": (45, 47), "fill_size": (1035, 94),
        "ring_size": (60, 172),
        "tag_size": (88, 66), "tag_y": -70, "text_y": -37,
        "title_height": 44,
    },
    "small": {
        "frame": (375, 78),
        "track_x": 16, "track_w": 343,
        "track_y": 23, "track_h": 39,
        "fill_pos": (14, 22), "fill_size": (347, 41),
        "ring_size": (26, 78),
        "tag_size": (60, 45), "tag_y": -47, "text_y": -24,
        "title_height": 22,
    },
}

## endregion

## region: Timing & Font

## Motion timer (ms). 40 ms = 25 updates a second, cheap enough for a splash.
MOTION_TICK_MS = 40

## Font used by the title and percent (Inter on Zorin, DejaVu Sans as a fallback)
CORE_FONT_FAMILIES = ["Inter", "DejaVu Sans"]

## endregion


## region: ProgressBarWidget Class

class ProgressBarWidget(QWidget):
    """
    Shared progress bar built from transparent image pieces:
    frame, fill per state, edge ring and hex tag per state.
    The fill is clipped to the real progress, the ring and tag follow the fill
    edge, and the percent is drawn in the tag. Any missing piece is painted
    with a simple stand-in, so the bar always works.

    bar_size "main" uses progress_bar_<piece>.png,
    bar_size "small" uses progress_bar_<piece>_small.png.
    """

    ## region: Setup

    def __init__(self, title_text="", bar_size="main", parent=None):
        super().__init__(parent)
        self.setObjectName("ProgressBarWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.title_text = title_text
        self.bar_size = bar_size if bar_size in PIECE_LAYOUTS else "main"
        self.layout_spec = PIECE_LAYOUTS[self.bar_size]
        ## Current value, colour state and animation counters.
        self.progress_value = 0
        self.bar_state = "normal"
        self.shimmer_offset = 0.0
        self.motion_phase = 0.0
        ## Loaded images, plus a cache of copies scaled to the current widget size.
        self.pieces = {}
        self.scaled_pieces = {}
        self.scaled_for = None
        ## Set to True after a paint error, so later paints use the plain bar.
        self.paint_failed = False

        try:
            self.load_pieces()
            ## Shimmer timer: a soft light sweep over the filled part
            ## (also drives the fill flicker and the ring pulse)
            self.shimmer_timer = QTimer(self)
            self.shimmer_timer.timeout.connect(self._on_shimmer_tick)
            self.shimmer_timer.start(MOTION_TICK_MS)
        except Exception as e:
            print(f"[ERROR] ProgressBarWidget: Failed to initialize: {e}")

    ## endregion

    ## region: Public Methods

    ## ----------------------------------------------------------------
    ## Public methods
    ## ----------------------------------------------------------------

    def set_progress(self, value):
        """Sets the fill from 0 to 100."""
        try:
            ## Clamp to 0..100 so a bad value cannot draw outside the bar.
            self.progress_value = max(0, min(100, int(value)))
            self.update()
        except Exception as e:
            print(f"[ERROR] ProgressBarWidget: Bad progress value {value!r}: {e}")

    def set_state(self, state):
        """Sets 'normal', 'warning', 'complete' or 'error'."""
        try:
            if state not in STATE_COLORS:
                print(f"[WARNING] ProgressBarWidget: Unknown state '{state}', using normal.")
                state = "normal"
            self.bar_state = state
            self.update()
        except Exception as e:
            print(f"[ERROR] ProgressBarWidget: Failed to set state: {e}")

    def set_title(self, title_text):
        """Sets the title shown above the bar (for example 'LOADING FONTS...')."""
        try:
            self.title_text = str(title_text)
            self.update()
        except Exception as e:
            print(f"[ERROR] ProgressBarWidget: Failed to set title: {e}")

    def load_pieces(self):
        """Loads every image piece that exists. Missing pieces are painted instead."""
        ## Piece names: frame, ring, then one fill and one tag per state.
        piece_names = ["frame", "ring"]
        for state in STATE_COLORS:
            piece_names.append(f"fill_{state}")
            piece_names.append(f"tag_{state}")

        suffix = "_small" if self.bar_size == "small" else ""
        found = 0
        for piece in piece_names:
            try:
                path = asset_path(*PROGRESS_BAR_FOLDER, f"progress_bar_{piece}{suffix}.png")
                pixmap = QPixmap(path) if os.path.exists(path) else QPixmap()
                if not pixmap.isNull():
                    self.pieces[piece] = pixmap
                    found += 1
            except Exception as e:
                print(f"[ERROR] ProgressBarWidget: Failed to load piece '{piece}': {e}")
        if found == len(piece_names):
            print(f"[SUCCESS] ProgressBarWidget: Loaded all {found} bar pieces ({self.bar_size}).")
        else:
            print(f"[INFO] ProgressBarWidget: {found} of {len(piece_names)} bar pieces found ({self.bar_size}). Painting the rest.")

    ## endregion

    ## region: Layout

    ## ----------------------------------------------------------------
    ## Layout
    ## ----------------------------------------------------------------

    def _design_size(self):
        """Full design canvas: title row + tag row + frame, in LAYOUT.md pixels."""
        spec = self.layout_spec
        frame_w, frame_h = spec["frame"]
        return frame_w, spec["title_height"] - spec["tag_y"] + frame_h

    def _scale_and_origin(self):
        """Scale factor that fits the design canvas in the widget, and the frame's top-left."""
        spec = self.layout_spec
        design_w, design_h = self._design_size()
        scale = min(self.width() / design_w, self.height() / design_h)
        left = (self.width() - design_w * scale) / 2.0
        frame_top = (spec["title_height"] - spec["tag_y"]) * scale
        return scale, left, frame_top

    def _layout_rects(self):
        """Works out every piece's rect in widget pixels from the LAYOUT.md numbers."""
        spec = self.layout_spec
        scale, left, frame_top = self._scale_and_origin()

        ## Converts LAYOUT.md pixel numbers into widget pixels.
        def to_widget(x, y, w, h):
            return QRectF(left + x * scale, frame_top + y * scale, w * scale, h * scale)

        frame_w, frame_h = spec["frame"]
        frame_rect = to_widget(0, 0, frame_w, frame_h)
        track_rect = to_widget(spec["track_x"], spec["track_y"], spec["track_w"], spec["track_h"])

        ## Fill end (lead edge) position, used by the ring and the tag.
        lead_design_x = spec["track_x"] + spec["track_w"] * self.progress_value / 100.0
        edge_x = left + lead_design_x * scale

        fill_w, fill_h = spec["fill_size"]
        fill_rect = to_widget(spec["fill_pos"][0], spec["fill_pos"][1], fill_w, fill_h)
        ## Crop width from LAYOUT.md: 2 + track_w * P / 100, the full image at 100%
        if self.progress_value >= 100:
            crop_design_w = fill_w
        else:
            crop_design_w = 2 + spec["track_w"] * self.progress_value / 100.0

        ring_w, ring_h = spec["ring_size"]
        ring_rect = to_widget(lead_design_x - ring_w / 2.0, 0, ring_w, ring_h)

        ## Tag stays centred over the fill end. It is only clamped when it
        ## would stick out past the frame's far left or far right edge.
        tag_w, tag_h = spec["tag_size"]
        tag_design_x = lead_design_x - tag_w / 2.0
        ## Keep the tag inside the widget at 0% and 100%
        tag_design_x = max(0.0, min(frame_w - tag_w, tag_design_x))
        tag_rect = to_widget(tag_design_x, spec["tag_y"], tag_w, tag_h)

        title_rect = QRectF(left, 0, frame_w * scale, spec["title_height"] * scale)
        return {
            "scale": scale, "title": title_rect, "frame": frame_rect, "track": track_rect,
            "fill": fill_rect, "crop_design_w": crop_design_w, "ring": ring_rect,
            "tag": tag_rect, "edge_x": edge_x,
        }

    def _scaled_piece(self, piece, scale):
        """Returns a piece pre-scaled for the current widget size (cached, so it is cheap)."""
        ## Widget size changed: throw away the old scaled copies.
        if self.scaled_for != (self.width(), self.height()):
            self.scaled_pieces = {}
            self.scaled_for = (self.width(), self.height())
        pixmap = self.pieces.get(piece)
        if pixmap is None:
            return None
        if piece not in self.scaled_pieces:
            self.scaled_pieces[piece] = pixmap.scaled(
                max(1, round(pixmap.width() * scale)), max(1, round(pixmap.height() * scale)),
                Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation,
            )
        return self.scaled_pieces[piece]

    ## endregion

    ## region: Painting

    ## ----------------------------------------------------------------
    ## Painting
    ## ----------------------------------------------------------------

    def paintEvent(self, event):
        """Composes the layers. If anything fails, a plain bar is drawn instead."""
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            if self.paint_failed:
                self._paint_plain_bar(painter)
                return
            rects = self._layout_rects()
            ## Drawing order from LAYOUT.md: frame, fill, ring, tag, text
            self._paint_title(painter, rects["title"])
            self._paint_frame(painter, rects)
            self._paint_fill(painter, rects)
            self._paint_ring(painter, rects)
            self._paint_tag(painter, rects)
        except Exception as e:
            print(f"[ERROR] ProgressBarWidget: Layer painting failed, using plain bar: {e}")
            self.paint_failed = True
            try:
                self._paint_plain_bar(painter)
            except Exception as e2:
                print(f"[ERROR] ProgressBarWidget: Plain bar failed too: {e2}")
        finally:
            painter.end()

    ## Returns the accent colour for the current state (normal if unknown).
    def _state_color(self):
        return QColor(STATE_COLORS.get(self.bar_state, STATE_COLORS["normal"]))

    def _paint_title(self, painter, title_rect):
        """Title in the state colour, wide letter spacing."""
        font = QFont(CORE_FONT_FAMILIES[0])
        font.setPixelSize(max(10, int(title_rect.height() * 0.55)))
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.5)
        painter.setFont(font)
        painter.setPen(self._state_color())
        painter.drawText(title_rect.adjusted(title_rect.width() * 0.03, 0, 0, 0),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.title_text)

    def _paint_frame(self, painter, rects):
        """Frame image, or a painted cut-corner double outline."""
        frame_rect = rects["frame"]
        frame_pixmap = self._scaled_piece("frame", rects["scale"])
        if frame_pixmap is not None:
            painter.drawPixmap(frame_rect.topLeft(), frame_pixmap)
            return
        ## No frame image: paint an outer and an inner cut-corner outline instead.
        painter.setBrush(QColor(5, 13, 24, 170))
        painter.setPen(QPen(QColor(40, 120, 255, 200), 1.5))
        painter.drawPolygon(self._cut_corner_polygon(frame_rect.adjusted(1, 1, -1, -1), frame_rect.height() * 0.28))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(51, 214, 255, 170), 1.0))
        painter.drawPolygon(self._cut_corner_polygon(frame_rect.adjusted(8, 8, -8, -8), frame_rect.height() * 0.22))
        ## Inner track outline and tick marks
        track_rect = rects["track"]
        painter.setPen(QPen(QColor(51, 214, 255, 120), 1.0))
        painter.drawRoundedRect(track_rect, 4, 4)
        tick_y = track_rect.bottom() + 5
        painter.setPen(QPen(QColor(51, 214, 255, 70), 1.0))
        for tick in range(0, 101, 2):
            x = track_rect.left() + track_rect.width() * tick / 100.0
            tick_len = 4 if tick % 10 == 0 else 2
            painter.drawLine(QPointF(x, tick_y), QPointF(x, tick_y + tick_len))

    def _paint_fill(self, painter, rects):
        """Fill image for the state, cropped to the progress, plus flicker and a moving shimmer."""
        if self.progress_value <= 0:
            return
        scale = rects["scale"]
        fill_rect = rects["fill"]
        track_rect = rects["track"]
        edge_x = rects["edge_x"]
        fill_pixmap = self._scaled_piece(f"fill_{self.bar_state}", scale)

        painter.save()
        ## Gentle flicker: fill opacity wobbles between about 0.90 and 1.0
        flicker = 0.95 + 0.05 * math.sin(self.motion_phase * 7.0) * math.sin(self.motion_phase * 2.3)
        painter.setOpacity(flicker)
        if fill_pixmap is not None:
            ## Drawn at full track size and clipped, so the texture does not squash
            ## Cropped (not squashed): only the first crop_w pixels of the strip are drawn
            crop_w = max(1, round(rects["crop_design_w"] * scale))
            crop_w = min(crop_w, fill_pixmap.width())
            painter.drawPixmap(fill_rect.topLeft(), fill_pixmap, QRectF(0, 0, crop_w, fill_pixmap.height()))
        else:
            ## No fill image: paint a two-colour gradient up to the fill end.
            left_color, right_color = FALLBACK_FILL_COLORS.get(self.bar_state, FALLBACK_FILL_COLORS["normal"])
            gradient = QLinearGradient(track_rect.left(), 0, track_rect.right(), 0)
            gradient.setColorAt(0.0, QColor(left_color))
            gradient.setColorAt(1.0, QColor(right_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawRoundedRect(QRectF(track_rect.left(), track_rect.top() + 3,
                                           edge_x - track_rect.left(), track_rect.height() - 6), 3, 3)
        painter.setOpacity(1.0)

        ## Shimmer: a soft white band sweeping left to right across the fill
        shine_rect = QRectF(track_rect.left(), track_rect.top() + track_rect.height() * 0.2,
                            edge_x - track_rect.left(), track_rect.height() * 0.6)
        painter.setClipRect(shine_rect)
        band_width = track_rect.width() * 0.12
        band_x = shine_rect.left() + (shine_rect.width() + band_width) * self.shimmer_offset - band_width
        shimmer = QLinearGradient(band_x, 0, band_x + band_width, 0)
        shimmer.setColorAt(0.0, QColor(255, 255, 255, 0))
        shimmer.setColorAt(0.5, QColor(255, 255, 255, 55))
        shimmer.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(shine_rect, shimmer)
        painter.restore()

    def _paint_ring(self, painter, rects):
        """Edge ring image (with a slow pulse), or a painted dashed ellipse in the state colour."""
        ring_rect = rects["ring"]
        ring_pixmap = self._scaled_piece("ring", rects["scale"])
        if ring_pixmap is not None:
            painter.save()
            ## Pulse: the ring breathes a little (opacity and about 3% height)
            pulse = 0.5 + 0.5 * math.sin(self.motion_phase * 3.0)
            painter.setOpacity(0.8 + 0.2 * pulse)
            grow = 1.0 + 0.03 * pulse
            pulsed = QRectF(0, 0, ring_rect.width(), ring_rect.height() * grow)
            pulsed.moveCenter(ring_rect.center())
            painter.drawPixmap(pulsed, ring_pixmap, QRectF(ring_pixmap.rect()))
            painter.restore()
            return
        ## No ring image: paint a dashed ellipse whose dashes creep along with the shimmer.
        ring_color = self._state_color()
        pen = QPen(ring_color, 1.6)
        pen.setDashPattern([4, 3])
        pen.setDashOffset(self.shimmer_offset * 14)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(ring_rect.adjusted(ring_rect.width() * 0.15, 2, -ring_rect.width() * 0.15, -2))
        glow = QColor(ring_color)
        glow.setAlpha(90)
        painter.setPen(QPen(glow, 4.0))
        painter.drawEllipse(ring_rect.adjusted(ring_rect.width() * 0.3, 8, -ring_rect.width() * 0.3, -8))

    def _paint_tag(self, painter, rects):
        """Hex tag image for the state (or a painted hexagon) with the percent inside."""
        tag_rect = rects["tag"]
        frame_rect = rects["frame"]
        edge_x = rects["edge_x"]
        state_color = self._state_color()
        tag_pixmap = self._scaled_piece(f"tag_{self.bar_state}", rects["scale"])
        if tag_pixmap is not None:
            painter.drawPixmap(tag_rect.topLeft(), tag_pixmap)
        else:
            ## Thin leader line from the tag down to the frame
            painter.setPen(QPen(state_color, 1.0))
            painter.drawLine(QPointF(edge_x, tag_rect.bottom()), QPointF(edge_x, frame_rect.top() + 4))
            painter.setBrush(QColor(5, 13, 24, 210))
            painter.setPen(QPen(state_color, 1.6))
            painter.drawPolygon(self._hexagon_polygon(tag_rect.adjusted(2, 4, -2, -4)))

        ## Percent text size follows the tag height.
        font = QFont(CORE_FONT_FAMILIES[0])
        font.setPixelSize(max(9, int(tag_rect.height() * 0.36)))
        font.setWeight(QFont.Weight.DemiBold)
        ## Shrink the text until "100%" fits inside the hexagon's flat middle
        while font.pixelSize() > 7 and QFontMetricsF(font).horizontalAdvance("100%") > tag_rect.width() * 0.6:
            font.setPixelSize(font.pixelSize() - 1)
        painter.setFont(font)
        painter.setPen(QColor("#eef6fb") if self.bar_state == "normal" else state_color)
        ## Text centre from LAYOUT.md (text_y), centred on the tag
        text_center_y = frame_rect.top() + self.layout_spec["text_y"] * rects["scale"]
        text_rect = QRectF(tag_rect.left(), text_center_y - tag_rect.height() / 2, tag_rect.width(), tag_rect.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, f"{self.progress_value}%")

    def _paint_plain_bar(self, painter):
        """Last-resort plain bar: dark track, state-colour fill, percent text."""
        rect = QRectF(self.rect()).adjusted(2, self.height() * 0.4, -2, -self.height() * 0.3)
        painter.setPen(QPen(QColor(40, 170, 215, 140), 1.0))
        painter.setBrush(QColor(5, 13, 24, 200))
        painter.drawRect(rect)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._state_color())
        painter.drawRect(QRectF(rect.left(), rect.top(), rect.width() * self.progress_value / 100.0, rect.height()))
        painter.setPen(QColor("#eef6fb"))
        painter.drawText(QRectF(self.rect()).adjusted(0, 0, 0, -self.height() * 0.6), Qt.AlignmentFlag.AlignCenter, f"{self.title_text}  {self.progress_value}%")

    ## endregion

    ## region: Shape Helpers

    @staticmethod
    def _cut_corner_polygon(rect, cut):
        """Eight-point frame with angled corners."""
        return QPolygonF([
            QPointF(rect.left() + cut, rect.top()), QPointF(rect.right() - cut, rect.top()),
            QPointF(rect.right(), rect.top() + cut), QPointF(rect.right(), rect.bottom() - cut),
            QPointF(rect.right() - cut, rect.bottom()), QPointF(rect.left() + cut, rect.bottom()),
            QPointF(rect.left(), rect.bottom() - cut), QPointF(rect.left(), rect.top() + cut),
        ])

    @staticmethod
    def _hexagon_polygon(rect):
        """Flat-sided hexagon that fills the tag rect."""
        ## inset: how far the angled sides cut in from the left and right.
        inset = rect.width() * 0.22
        return QPolygonF([
            QPointF(rect.left() + inset, rect.top()), QPointF(rect.right() - inset, rect.top()),
            QPointF(rect.right(), rect.center().y()), QPointF(rect.right() - inset, rect.bottom()),
            QPointF(rect.left() + inset, rect.bottom()), QPointF(rect.left(), rect.center().y()),
        ])

    ## endregion

    ## region: Motion & Visibility

    def _on_shimmer_tick(self):
        """Moves the shimmer band, flicker and ring pulse, then repaints."""
        try:
            ## Shimmer position runs from 0.0 to 1.0, then starts over.
            self.shimmer_offset += 0.03
            if self.shimmer_offset > 1.0:
                self.shimmer_offset = 0.0
            self.motion_phase += MOTION_TICK_MS / 1000.0
            ## Repaint only while visible, to save work.
            if self.isVisible():
                self.update()
        except Exception as e:
            print(f"[ERROR] ProgressBarWidget: Shimmer tick failed: {e}")
            self.shimmer_timer.stop()

    def hideEvent(self, event):
        """Stops the shimmer while hidden."""
        try:
            self.shimmer_timer.stop()
        except Exception as e:
            print(f"[ERROR] ProgressBarWidget: Failed to stop shimmer: {e}")
        super().hideEvent(event)

    def showEvent(self, event):
        """Restarts the shimmer when shown."""
        try:
            self.shimmer_timer.start(MOTION_TICK_MS)
        except Exception as e:
            print(f"[ERROR] ProgressBarWidget: Failed to start shimmer: {e}")
        super().showEvent(event)

    ## endregion

## endregion
