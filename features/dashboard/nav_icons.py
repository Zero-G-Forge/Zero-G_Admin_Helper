## =====================================================================
## MODULE: features/dashboard/nav_icons.py
## DESCRIPTION: Simple drawn icons for the Main Cockpit nav column and logo.
##              Drawn with QPainter so no image files or pip packages are needed.
## =====================================================================

# region Imports

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

# endregion

# region Icon Settings

## Nav icon colours: idle grey-blue, selected cyan
NAV_ICON_IDLE = "#8fa6b8"
NAV_ICON_ACTIVE = "#33d6ff"
## Icons are drawn on a 64 x 64 canvas, then shrunk to fit the button.
ICON_SIZE = 64

# endregion


# region Drawing Helpers

def _make_pen(color, width=5.0):
    """Builds a round-capped pen used by every drawn icon."""
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen

# endregion


# region Page Icon Drawings

def _draw_dashboard(painter, color):
    ## Four tiles in a grid
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    for x, y in ((8, 8), (36, 8), (8, 36), (36, 36)):
        painter.drawRoundedRect(QRectF(x, y, 20, 20), 3, 3)


def _draw_players(painter, color):
    ## Head and shoulders
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(21, 6, 22, 22))
    path = QPainterPath()
    path.moveTo(8, 58)
    path.cubicTo(8, 36, 56, 36, 56, 58)
    path.closeSubpath()
    painter.drawPath(path)


def _draw_factions(painter, color):
    ## Flag on a pole
    painter.setPen(_make_pen(color, 5))
    painter.drawLine(QPointF(14, 6), QPointF(14, 58))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    flag = QPolygonF([QPointF(16, 8), QPointF(54, 14), QPointF(42, 24), QPointF(54, 34), QPointF(16, 34)])
    painter.drawPolygon(flag)


def _draw_structures(painter, color):
    ## Stacked layers (blocks)
    painter.setPen(_make_pen(color, 4.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    top = QPolygonF([QPointF(32, 6), QPointF(56, 18), QPointF(32, 30), QPointF(8, 18)])
    painter.setBrush(QColor(color))
    painter.drawPolygon(top)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolyline(QPolygonF([QPointF(8, 30), QPointF(32, 42), QPointF(56, 30)]))
    painter.drawPolyline(QPolygonF([QPointF(8, 42), QPointF(32, 54), QPointF(56, 42)]))


def _draw_playfields(painter, color):
    ## Planet with a ring
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(18, 18, 28, 28))
    painter.setPen(_make_pen(color, 4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.save()
    painter.translate(32, 32)
    painter.rotate(-20)
    painter.drawEllipse(QRectF(-28, -9, 56, 18))
    painter.restore()


def _draw_chat(painter, color):
    ## Speech bubble
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(QRectF(6, 10, 52, 34), 8, 8)
    tail = QPolygonF([QPointF(16, 42), QPointF(14, 56), QPointF(30, 42)])
    painter.drawPolygon(tail)


def _draw_alerts(painter, color):
    ## Warning triangle with a cut-out mark
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPolygon(QPolygonF([QPointF(32, 6), QPointF(60, 56), QPointF(4, 56)]))
    painter.setBrush(QColor("#0b1622"))
    painter.drawRoundedRect(QRectF(29, 22, 6, 20), 3, 3)
    painter.drawEllipse(QRectF(29, 45, 6, 6))


def _draw_scheduler(painter, color):
    ## Clock face
    painter.setPen(_make_pen(color, 5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(8, 8, 48, 48))
    painter.drawLine(QPointF(32, 32), QPointF(32, 18))
    painter.drawLine(QPointF(32, 32), QPointF(43, 38))


def _draw_bans_audit(painter, color):
    ## Shield
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    path = QPainterPath()
    path.moveTo(32, 4)
    path.lineTo(56, 12)
    path.cubicTo(56, 38, 46, 52, 32, 60)
    path.cubicTo(18, 52, 8, 38, 8, 12)
    path.closeSubpath()
    painter.drawPath(path)
    painter.setPen(_make_pen("#0b1622", 5))
    painter.drawLine(QPointF(22, 22), QPointF(42, 42))


def _draw_zerogbridge(painter, color):
    ## Two nodes joined by a bridge arc
    painter.setPen(_make_pen(color, 5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(12, 44)
    path.cubicTo(20, 14, 44, 14, 52, 44)
    painter.drawPath(path)
    painter.drawLine(QPointF(6, 46), QPointF(58, 46))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(4, 40, 14, 14))
    painter.drawEllipse(QRectF(46, 40, 14, 14))

def _draw_settings(painter, color):
    ## Gear: eight teeth around a ring, with a hole in the middle
    painter.setPen(_make_pen(color, 7))
    for x1, y1, x2, y2 in ((32, 5, 32, 13), (32, 51, 32, 59), (5, 32, 13, 32), (51, 32, 59, 32),
                           (13, 13, 19, 19), (45, 45, 51, 51), (51, 13, 45, 19), (13, 51, 19, 45)):
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    painter.setPen(_make_pen(color, 6))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(16, 16, 32, 32))

# endregion


# region Icon Lookup Table

## Page key -> drawing function
ICON_DRAWERS = {
    "dashboard": _draw_dashboard,
    "players": _draw_players,
    "factions": _draw_factions,
    "structures": _draw_structures,
    "playfields": _draw_playfields,
    "chat": _draw_chat,
    "alerts": _draw_alerts,
    "scheduler": _draw_scheduler,
    "bans_audit": _draw_bans_audit,
    "zerogbridge": _draw_zerogbridge,
    "settings": _draw_settings,
}

# endregion


# region Public Builders

def _draw_icon_pixmap(page_key, color):
    """Draws one icon onto a transparent pixmap."""
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    ## Transparent background, so only the drawn shape shows.
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        drawer = ICON_DRAWERS.get(page_key)
        if drawer is not None:
            drawer(painter, color)
    ## finally: always runs, so the painter is closed even if drawing fails.
    finally:
        painter.end()
    return pixmap


def build_nav_icon(page_key):
    """
    Returns a QIcon for a nav button: grey when idle, cyan when selected (checked).
    Returns an empty QIcon if drawing fails, so the button still shows its text.
    """
    try:
        icon = QIcon()
        ## Grey picture for the normal state, cyan for the selected (checked) state.
        icon.addPixmap(_draw_icon_pixmap(page_key, NAV_ICON_IDLE), QIcon.Mode.Normal, QIcon.State.Off)
        icon.addPixmap(_draw_icon_pixmap(page_key, NAV_ICON_ACTIVE), QIcon.Mode.Normal, QIcon.State.On)
        icon.addPixmap(_draw_icon_pixmap(page_key, NAV_ICON_ACTIVE), QIcon.Mode.Active, QIcon.State.On)
        return icon
    except Exception as e:
        print(f"[ERROR] NavIcons: Failed to draw icon '{page_key}': {e}")
        return QIcon()


def build_logo_pixmap(size=44):
    """
    Draws the round header logo: an outer cyan ring, a dashed middle ring and a centre dot.
    Returns an empty QPixmap if drawing fails.
    """
    try:
        ## Drawn 4 times larger, then scaled down, so the curved edges come out smooth.
        scale = 4
        full = size * scale
        pixmap = QPixmap(full, full)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            ## Outer ring
            painter.setPen(_make_pen(NAV_ICON_ACTIVE, 3.0 * scale))
            margin = 2.5 * scale
            painter.drawEllipse(QRectF(margin, margin, full - 2 * margin, full - 2 * margin))

            ## Dashed middle ring
            dash_pen = QPen(QColor(NAV_ICON_ACTIVE))
            dash_pen.setWidthF(3.0 * scale)
            dash_pen.setDashPattern([2.0, 1.4])
            dash_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(dash_pen)
            inner = 9 * scale
            painter.drawEllipse(QRectF(inner, inner, full - 2 * inner, full - 2 * inner))

            ## Centre dot
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(NAV_ICON_ACTIVE))
            dot = full * 0.16
            painter.drawEllipse(QRectF(full / 2 - dot / 2, full / 2 - dot / 2, dot, dot))
        finally:
            painter.end()
        return pixmap.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    except Exception as e:
        print(f"[ERROR] NavIcons: Failed to draw header logo: {e}")
        return QPixmap()

# endregion
