"""
Telemetry Worker Thread for Zero-G Admin Helper.
Handles asynchronous TCP streaming on Port 30500 and emits structured PyQt6 signals.
"""

import json
import os
import socket
import time
from typing import Optional
from PyQt6.QtCore import QThread, pyqtSignal

from features.dashboard.telemetry_parser import TelemetryParser


class TelemetryWorker(QThread):
    """
    Dedicated background worker thread that maintains a persistent TCP stream
    connection to the ZeroGBridge mod on Port 30500.
    """

    # Qt Signal Definitions
    metrics_updated = pyqtSignal(dict)
    players_updated = pyqtSignal(list)
    response_received = pyqtSignal(dict)
    connection_status = pyqtSignal(bool, str)

    def __init__(self, host: str = "66.23.236.138", port: int = 30500, password: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port
        self.password = password
        self._is_running = True
        self._socket: Optional[socket.socket] = None

        # Fallback: Load input_pass from data/server_config.json if not explicitly provided
        if not self.password:
            config_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "server_config.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                        self.password = cfg.get("input_pass", "")
                except Exception as err:
                    print(f"[TelemetryWorker] -WARN- Failed to load password from config: {err}")

    def run(self):
        """
        Main worker execution loop. Connects to the server socket and buffers stream lines.
        """
        buffer = ""

        while self._is_running:
            try:
                print(f"[TelemetryWorker] -INFO- Connecting to ZeroGBridge socket at {self.host}:{self.port}...")
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._socket.settimeout(5.0)
                self._socket.connect((self.host, self.port))

                # Step 1: Submit Authentication token to open the socket gate.
                self._send_auth_handshake()

                self.connection_status.emit(True, "Connected")
                print(f"[TelemetryWorker] -STATUS- Successfully connected to Port {self.port}:{self.port}...")

                # Step 2: Request initial player cache to populate the dashboard
                ## self.send_command("plys")

                while self._is_running:
                    try:
                        data = self._socket.recv(4096)
                        if not data:
                            print("[TelemetryWorker] -WARN- Server closed the connection stream.")
                            break

                        buffer += data.decode("utf-8", errors="replace")

                        # Split stream on newline boundary
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            self._process_line(line.strip())

                    except socket.timeout:
                        # Timeout is expected; loop continues to evaluate _is_running
                        continue

            except Exception as err:
                self.connection_status.emit(False, f"Disconnected: {err}")
                print(f"[TelemetryWorker] -ERROR- Socket connection error: {err}")

            finally:
                self._cleanup_socket()

            # Backoff delay before attempting auto-reconnect
            if self._is_running:
                time.sleep(3.0)

    def _send_auth_handshake(self):
        """
        Transmits the authentication payload to unlock the ZeroGBridge telemetry stream.
        """
        auth_token = self.password if self.password else ""
        formatted_auth = f"auth:{auth_token}\r\n"
        if self._socket:
            self._socket.sendall(formatted_auth.encode("utf-8"))
            print("[TelemetryWorker] -STATUS- Transmitted socket auth handshake.")
            time.sleep(0.3)

    def _process_line(self, line: str):
        """
        Parses a single JSON line and emits the appropriate Qt signal.
        """
        if not line:
            return

        payload = TelemetryParser.parse_raw_line(line)
        if not payload:
            return

        pkt_type = payload.get("type")

        # 1. Route METRIC packets
        if pkt_type == "METRIC":
            metric = TelemetryParser.extract_metric(payload)
            if metric:
                self.metrics_updated.emit(metric)
                # If player roster is included, update player cache signal
                if "player_list" in metric:
                    self.players_updated.emit(metric["player_list"])

        # 2. Route PLAYER_CACHE responses
        elif pkt_type == "PLAYER_CACHE":
            cache_data = TelemetryParser.extract_player_cache(payload)
            if cache_data:
                self.players_updated.emit(cache_data.get("player_list", []))

        # 3. Route generic command responses
        elif pkt_type == "RESPONSE":
            self.response_received.emit(payload)

    def send_command(self, command_str: str):
        """
        Sends an outbound command string with Windows-style line terminations.
        """
        if self._socket and self._is_running:
            try:
                # Ensure \r\n line termination matching GTX Gaming calibrations
                formatted_cmd = command_str.strip() + "\r\n"
                self._socket.sendall(formatted_cmd.encode("utf-8"))
                print(f"[TelemetryWorker] -INFO- Transmitted outbound command: {command_str.strip()}")
            except Exception as err:
                print(f"[TelemetryWorker] -ERROR- Failed to transmit command: {err}")

    def stop(self):
        """
        Stops the worker thread and shuts down the active socket connection.
        """
        self._is_running = False
        self._cleanup_socket()
        self.wait(1000)

    def _cleanup_socket(self):
        """
        Closes socket handles safely.
        """
        if self._socket:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None