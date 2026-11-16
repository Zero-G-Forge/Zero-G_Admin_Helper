# portal_window.py
"""
ZeroGBridge Portal window opened from View > ZeroGBridge Portal.

Wraps the Loader + Bridge viewer (hot_reload_panel.HotReloadWindow) in its
own top-level window owned by the ZAH main window. Viewer only: simulated
data, no sockets, no commands sent to any game server.
"""

from PyQt6.QtCore import Qt

from .data_source import PortalDataSource
from .hot_reload_panel import HotReloadWindow


class ZeroGBridgePortal(HotReloadWindow):
    """Separate window (not embedded in the cockpit layout) with LOADER and BRIDGE tabs."""

    WINDOW_TITLE = "Zero-G Admin Helper - ZeroGBridge Portal"

    def __init__(self, parent=None, source: PortalDataSource | None = None):
        # source=None -> SampleDataSource (Examples/ZGB_Portal). A live source plugs in here later.
        super().__init__(capture_mode=False, parent=parent, source=source)
        # A parented QWidget would draw inside the cockpit; make it its own window.
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(self.WINDOW_TITLE)
