# portal_window.py
"""
ZeroGBridge Portal window opened from View > ZeroGBridge Portal.

Wraps the Loader + Bridge view (hot_reload_panel.HotReloadWindow) in its own
top-level window owned by the ZAH main window.

Default data source is Live: the server ZAH is connected to, read through
ZeroGBridge (hot:status, plys) on short-lived worker-thread connections.
Reload / rollback are only sent after a confirmation dialog. The
'Data source' picker switches to Examples (Examples/ZGB_Portal).
"""

from PyQt6.QtCore import Qt

from .data_source import LiveDataSource, PortalDataSource
from .hot_reload_panel import HotReloadWindow


def _cockpit_profile_provider(parent):
    """Uses the cockpit's current server profile when it has one."""

    def provider():
        config = getattr(parent, "config", None)
        if isinstance(config, dict) and config.get("input_ip") and config.get("input_pass"):
            return dict(config)
        return None  # LiveDataSource falls back to the active profile in server_config.json

    return provider


class ZeroGBridgePortal(HotReloadWindow):
    """Separate window (not embedded in the cockpit layout) with LOADER and BRIDGE tabs."""

    WINDOW_TITLE = "Zero-G Admin Helper - ZeroGBridge Portal"

    def __init__(self, parent=None, source: PortalDataSource | None = None, profile_provider=None):
        if profile_provider is None and parent is not None:
            profile_provider = _cockpit_profile_provider(parent)
        if source is None:
            source = LiveDataSource(profile_provider)
        super().__init__(capture_mode=False, parent=parent, source=source, profile_provider=profile_provider)
        # A parented QWidget would draw inside the cockpit; make it its own window.
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(self.WINDOW_TITLE)
