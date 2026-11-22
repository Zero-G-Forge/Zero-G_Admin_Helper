## ==========================================
## ZERO-G ADMIN HELPER - LIBRARY TILES
## HexTile: one item drawn as a hex (like the concept mockup), with its short initials inside,
##          the name and ID underneath. The game's item pictures aren't in the server files,
##          so each category gets its own edge colour instead.
##          (Nov 22, 2026: when the downloaded server files have SharedData/Content/Images/<ItemName>.jpg
##          or .png, that picture is drawn inside the hex instead of the initials. No picture = the drawn hex.)
## TileFlowArea: a scrolling grid that re-flows the tiles into as many columns as fit.
## ==========================================

# region Imports

import math

from PyQt6.QtCore import Qt, QPointF, QRectF, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QAbstractButton, QButtonGroup, QFrame, QGridLayout, QScrollArea, QWidget

# endregion


# region Constants

## Edge colour for each filter group, so a weapon tile reads differently from an ore tile at a glance.
GROUP_COLORS = {
    "WEAPONS": "#ff6b6b",
    "ARMOR": "#b48cff",
    "MEDICAL": "#ff4d6d",
    "AMMO": "#ffb454",
    "COMPONENTS": "#33d6ff",
    "ORES": "#ff9e57",
    "DEVICES": "#7ee787",
    "FOOD": "#d7e36b",
    "": "#8fa6b8",
}

TILE_WIDTH = 108
TILE_HEIGHT = 124
TILE_SPACING = 10

## Pictures already read from disk, by (path, size), so scrolling the grid doesn't reload them.
PICTURE_CACHE = {}

# endregion


# region Drawing Helpers

def short_initials(display_name):
    """'Hand Cannon' -> 'HC', 'Flashlight' -> 'FL', '15mm Bullet' -> '1B'. Up to 2 letters."""
    words = [word for word in display_name.replace("-", " ").split() if word]
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    if words:
        return words[0][:2].upper()
    return "?"


def hex_polygon(center_x, center_y, radius):
    """Six points of a pointy-top hexagon around a centre."""
    points = []
    for corner in range(6):
        angle = math.radians(60 * corner - 90)
        points.append(QPointF(center_x + radius * math.cos(angle), center_y + radius * math.sin(angle)))
    return QPolygonF(points)


def draw_hex_badge(painter, center_x, center_y, radius, group, initials, lit):
    """Draws the hex with its category colour and the initials inside. lit = picked tile."""
    edge_color = QColor(GROUP_COLORS.get(group, GROUP_COLORS[""]))
    fill_color = QColor(edge_color)
    fill_color.setAlpha(70 if lit else 28)
    painter.setPen(QPen(edge_color, 3 if lit else 2))
    painter.setBrush(fill_color)
    painter.drawPolygon(hex_polygon(center_x, center_y, radius))
    initials_font = QFont(painter.font())
    initials_font.setPixelSize(int(radius * 0.62))
    initials_font.setBold(True)
    painter.setFont(initials_font)
    painter.setPen(QColor("#ffffff") if lit else edge_color)
    painter.drawText(QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2),
                     Qt.AlignmentFlag.AlignCenter, initials)


def load_picture(image_path, side):
    """The item picture scaled to fill a side x side square, or None if there is none or it can't be read."""
    if not image_path:
        return None
    cache_key = (image_path, int(side))
    if cache_key not in PICTURE_CACHE:
        picture = QPixmap(image_path)
        if picture.isNull():
            print(f"[WARNING] ItemTiles: Could not read picture {image_path}")
            PICTURE_CACHE[cache_key] = None
        else:
            PICTURE_CACHE[cache_key] = picture.scaled(int(side), int(side), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                      Qt.TransformationMode.SmoothTransformation)
    return PICTURE_CACHE[cache_key]


def draw_hex_picture(painter, center_x, center_y, radius, group, picture, lit):
    """Draws the picture cut to the hex shape, then the category-coloured hex edge on top."""
    hex_shape = hex_polygon(center_x, center_y, radius)
    painter.save()

    ## A clip path is a stencil: only the part of the picture inside the hex gets painted.
    clip_path = QPainterPath()
    clip_path.addPolygon(hex_shape)
    painter.setClipPath(clip_path)
    painter.drawPixmap(int(center_x - picture.width() / 2), int(center_y - picture.height() / 2), picture)
    painter.restore()
    edge_color = QColor(GROUP_COLORS.get(group, GROUP_COLORS[""]))
    painter.setPen(QPen(QColor("#ffffff") if lit else edge_color, 3 if lit else 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolygon(hex_shape)


def make_hex_pixmap(size, group, display_name, image_path=None):
    """A square picture of the hex badge, used by the detail card and the stats window."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        ## The item's own picture when the server files have one, otherwise the initials badge.
        picture = load_picture(image_path, size)
        if picture is not None:
            draw_hex_picture(painter, size / 2, size / 2, size / 2 - 3, group, picture, True)
        else:
            draw_hex_badge(painter, size / 2, size / 2, size / 2 - 3, group, short_initials(display_name), True)

    ## finally: always runs, so the painter is closed even if drawing fails.
    finally:
        painter.end()
    return pixmap

# endregion


# region HexTile Class

class HexTile(QAbstractButton):
    """One clickable item tile. Checkable, so the picked tile stays lit."""

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = item
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(TILE_WIDTH, TILE_HEIGHT)
        self.setToolTip(item["display_name"] + "\n" + item["name"] + "  (ID " + item["id"] + ")")

    def sizeHint(self):
        return QSize(TILE_WIDTH, TILE_HEIGHT)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            lit = self.isChecked() or self.underMouse()

            ## The item's own picture when the server files have one, otherwise the initials badge.
            picture = load_picture(self.item.get("image_path"), 68)
            if picture is not None:
                draw_hex_picture(painter, TILE_WIDTH / 2, 38, 34, self.item["filter_group"], picture, lit)
            else:
                draw_hex_badge(painter, TILE_WIDTH / 2, 38, 34, self.item["filter_group"],
                               short_initials(self.item["display_name"]), lit)

            ## Name (cut with … if too long) and ID under the hex.
            name_font = QFont(self.font())
            name_font.setPixelSize(12)
            name_font.setBold(True)
            painter.setFont(name_font)
            painter.setPen(QColor("#e6f3fb"))
            name_text = painter.fontMetrics().elidedText(self.item["display_name"], Qt.TextElideMode.ElideRight, TILE_WIDTH - 6)
            painter.drawText(QRectF(0, 78, TILE_WIDTH, 18), Qt.AlignmentFlag.AlignCenter, name_text)
            id_font = QFont(self.font())
            id_font.setPixelSize(11)
            painter.setFont(id_font)
            painter.setPen(QColor("#8fa6b8"))
            painter.drawText(QRectF(0, 96, TILE_WIDTH, 16), Qt.AlignmentFlag.AlignCenter, "ID: " + self.item["id"])
        finally:
            painter.end()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

# endregion


# region TileFlowArea Class

class TileFlowArea(QScrollArea):
    """Scrolling grid of HexTiles. Emits tile_picked(item) when one is clicked."""

    tile_picked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LibraryTileArea")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inner = QWidget()
        self.inner.setObjectName("LibraryTileInner")
        self.tile_grid = QGridLayout(self.inner)
        self.tile_grid.setContentsMargins(0, 0, 0, 0)
        self.tile_grid.setSpacing(TILE_SPACING)
        self.tile_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setWidget(self.inner)

        ## Only one tile can be picked at a time.
        self.tile_group = QButtonGroup(self)
        self.tile_group.setExclusive(True)
        self.tiles = []
        self.visible_tiles = []
        self.column_count = 0

    def set_items(self, items):
        """Replaces every tile with one per item."""
        for old_tile in self.tiles:
            self.tile_group.removeButton(old_tile)
            old_tile.setParent(None)
            old_tile.deleteLater()
        self.tiles = []
        for item in items:
            tile = HexTile(item, self.inner)

            ## The lambda passes this tile's item to the tile_picked signal.
            tile.clicked.connect(lambda checked, picked=item: self.tile_picked.emit(picked))
            self.tile_group.addButton(tile)
            self.tiles.append(tile)
        self.show_only(self.tiles)

    def show_only(self, tiles_to_show):
        """Shows just these tiles (search and filters), packed from the top-left."""
        self.visible_tiles = list(tiles_to_show)
        shown = set(id(tile) for tile in self.visible_tiles)
        for tile in self.tiles:
            tile.setVisible(id(tile) in shown)
        self.column_count = 0
        self._reflow()

    def _reflow(self):
        """Places the visible tiles in as many columns as fit the current width."""
        usable_width = self.viewport().width()
        column_count = max(1, (usable_width + TILE_SPACING) // (TILE_WIDTH + TILE_SPACING))
        if column_count == self.column_count:
            return
        self.column_count = column_count
        while self.tile_grid.count() > 0:
            self.tile_grid.takeAt(0)
        for index, tile in enumerate(self.visible_tiles):
            self.tile_grid.addWidget(tile, index // column_count, index % column_count)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

# endregion
