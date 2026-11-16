# test_server_switching.py
"""Close the current ZeroGBridge session, then authenticate to the next one."""

import json
import socket

import pytest

from features.dashboard.telemetry_worker import TelemetryWorker
from features.network.bridge_session import (
    BridgeAuthError,
    close_bridge_socket,
    open_authenticated_socket,
    send_bridge_command,
    switch_authenticated_socket,
)
from tests.mock_bridge import MockBridge


def _read_line(sock):
    pieces = []
    while True:
        chunk = sock.recv(1)
        if not chunk or chunk == b"\n":
            break
        pieces.append(chunk)
    return b"".join(pieces).decode("utf-8").strip()


def test_switch_closes_old_session_then_auths_new():
    left = MockBridge("alpha-token").start()
    right = MockBridge("beta-token").start()
    old = None
    new = None
    try:
        old = open_authenticated_socket("127.0.0.1", left.port, "alpha-token", timeout=2.0)
        assert left.wait_until_authenticated()

        new = switch_authenticated_socket(old, "127.0.0.1", right.port, "beta-token", timeout=2.0)
        old = None

        assert left.wait_until_all_closed()
        assert right.wait_until_authenticated()
        send_bridge_command(new, "plys")
        assert right.wait_for_command("plys")
        send_bridge_command(new, "gents")
        assert right.wait_for_command("gents")
        print("[SUCCESS] Switch closed the old session and authenticated to the new one.")
    finally:
        close_bridge_socket(new)
        close_bridge_socket(old)
        left.stop()
        right.stop()


def test_switch_auth_failure_closes_both_sessions():
    current = MockBridge("good-token").start()
    other = MockBridge("good-token").start()
    old = None
    try:
        old = open_authenticated_socket("127.0.0.1", current.port, "good-token", timeout=2.0)
        assert current.wait_until_authenticated()

        with pytest.raises(BridgeAuthError) as caught:
            switch_authenticated_socket(old, "127.0.0.1", other.port, "wrong-token", timeout=2.0)
        old = None

        assert caught.value.status == "Denied"
        assert current.wait_until_all_closed()
        assert other.wait_until_all_closed()
        assert other.authenticated_count() == 0
        print("[SUCCESS] Failed switch closed the old session and the rejected one.")
    finally:
        close_bridge_socket(old)
        current.stop()
        other.stop()


def test_line_without_auth_is_rejected():
    bridge = MockBridge("good-token").start()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(2.0)
        sock.connect(("127.0.0.1", bridge.port))
        sock.sendall(b"plys\r\n")
        payload = json.loads(_read_line(sock))
        assert payload["type"] == "AUTH"
        assert payload["status"] == "Required"
        assert bridge.wait_until_all_closed()
    finally:
        close_bridge_socket(sock)
        bridge.stop()


def test_worker_stop_closes_session_before_a_new_connection(qapp):
    """The cockpit stops the worker (old session) before the next auth."""
    del qapp
    first = MockBridge("alpha-token").start()
    second = MockBridge("beta-token").start()
    worker = None
    opened = None
    try:
        worker = TelemetryWorker(host="127.0.0.1", port=first.port, password="alpha-token")
        worker.start()
        assert first.wait_until_authenticated()
        assert first.wait_for_command("plys")

        worker.stop()
        worker = None
        assert first.wait_until_all_closed()

        opened = open_authenticated_socket("127.0.0.1", second.port, "beta-token", timeout=2.0)
        send_bridge_command(opened, "plys")
        assert second.wait_until_authenticated()
        assert second.wait_for_command("plys")
        print("[SUCCESS] Worker stop closed the session before the next bridge login.")
    finally:
        if worker is not None:
            worker.stop()
        close_bridge_socket(opened)
        first.stop()
        second.stop()
