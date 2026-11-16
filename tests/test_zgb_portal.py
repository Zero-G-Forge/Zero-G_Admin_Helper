# test_zgb_portal.py
"""View > ZeroGBridge Portal sits next to File and opens the portal offscreen."""

import os

from PyQt6.QtWidgets import QApplication

from features.dashboard.main_cockpit import MainCockpit
from features.dashboard.telemetry_worker import TelemetryWorker
from features.dashboard.zgb_portal import ZeroGBridgePortal
from features.dashboard.zgb_portal import hot_reload_panel
from features.dashboard.zgb_portal.data_source import EXAMPLES_DIR, SampleDataSource
from features.paths import APP_ROOT, DATA_DIR


def _visible(text):
    return text.replace("&", "")


def _build_window(monkeypatch):
    monkeypatch.setattr(TelemetryWorker, "start", lambda self: None)
    monkeypatch.setattr(
        "features.dashboard.main_cockpit.registry_cache_for",
        lambda profile, config_path=None: os.path.join(DATA_DIR, "player_registry_cache.json"),
    )
    return MainCockpit({
        "input_ip": "127.0.0.1",
        "input_port": "9",
        "input_pass": "portal-test-token",
    })


def test_portal_code_and_examples_live_inside_zah():
    root = os.path.abspath(APP_ROOT)
    assert os.path.abspath(hot_reload_panel.HERE).startswith(root)
    assert os.path.abspath(str(hot_reload_panel.ZAH_CSS)) == os.path.join(root, "assets", "ZAH.css")
    assert os.path.abspath(str(EXAMPLES_DIR)) == os.path.join(root, "Examples", "ZGB_Portal")


def test_sample_source_reads_examples():
    src = SampleDataSource()
    assert not src.is_live
    state = src.loader_state()
    assert state.core_version == "1.4.2"
    assert state.port == 30500
    assert len(state.history) == 4
    assert state.pending_dll.endswith("ZeroGBridge.Core.1.4.3.dll")
    assert src.drop_core().name == "ZeroGBridge.Core.1.4.4.dll"
    names = [s.name for s in src.scripts()]
    assert names == ["greet_on_join.py", "death_notice.py", "starter_kit.py"]
    assert all(s.source.strip() for s in src.scripts())


def test_view_menu_opens_zgb_portal(qapp, monkeypatch):
    del qapp
    window = _build_window(monkeypatch)
    try:
        top = [_visible(a.text()) for a in window.menuBar().actions()]
        assert "View" in top
        assert top.index("View") == top.index("File") + 1

        view_menu = window.menuBar().actions()[top.index("View")].menu()
        portal_actions = [a for a in view_menu.actions() if _visible(a.text()) == "ZeroGBridge Portal"]
        assert len(portal_actions) == 1

        portal_actions[0].trigger()
        QApplication.processEvents()
        portal = window.zgb_portal
        assert isinstance(portal, ZeroGBridgePortal)
        assert portal.isVisible()
        assert portal.isWindow()
        assert portal.windowTitle() == "Zero-G Admin Helper - ZeroGBridge Portal"
        assert portal.tabs.count() == 2
        assert isinstance(portal.source, SampleDataSource)
        assert len(portal.bridge.scripts) == 3

        # Single instance: triggering again raises the same window.
        portal_actions[0].trigger()
        QApplication.processEvents()
        assert window.zgb_portal is portal

        grab_path = os.environ.get("ZAH_PORTAL_GRAB")
        if grab_path:
            assert portal.grab().save(grab_path, "PNG")
            portal.tabs.setCurrentIndex(1)
            QApplication.processEvents()
            assert portal.grab().save(grab_path.replace(".png", "_bridge.png"), "PNG")
            portal.tabs.setCurrentIndex(0)

        portal.close()
        QApplication.processEvents()
        QApplication.sendPostedEvents(None, 0)
        QApplication.processEvents()
        assert window.zgb_portal is None
    finally:
        window.close()
