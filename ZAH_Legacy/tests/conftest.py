# conftest.py

import os

# Headless Qt. Set before any test imports PyQt6.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


# RFC 5737 documentation ranges. They do not route, so a connect times out.
# Live game servers stay refused.
_DOCUMENTATION_HOSTS = ("192.0.2.1", "198.51.100.1", "203.0.113.1")


def _reject_live_host(address):
    """Tests stay on the local mock bridge or an unroutable documentation address."""
    host = address[0] if isinstance(address, tuple) else address
    if str(host) not in ("127.0.0.1", "localhost", "::1", *_DOCUMENTATION_HOSTS):
        raise AssertionError(f"refusing connection to {host}")


@pytest.fixture(autouse=True)
def _block_live_servers(monkeypatch):
    import socket

    real_connect = socket.socket.connect
    real_create = socket.create_connection

    def guarded_connect(self, address):
        _reject_live_host(address)
        return real_connect(self, address)

    def guarded_create(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
        _reject_live_host(address)
        return real_create(address, timeout, source_address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create)


@pytest.fixture(scope="session")
def qapp():
    """One offscreen QApplication for the menu and worker tests."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
