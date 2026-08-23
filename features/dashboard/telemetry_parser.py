"""
Telemetry Parser Engine for Zero-G Admin Helper.
Ingests, validates, and transforms JSON stream packets received from ZeroGBridge.
"""

import json
from typing import Any, Dict, Optional


class TelemetryParser:
    """
    Parses and sanitizes incoming JSON strings from the ZeroGBridge TCP stream (Port 30500).
    """

    @staticmethod
    def parse_raw_line(line: str) -> Optional[Dict[str, Any]]:
        """
        Parses a raw line string into a structured dictionary.
        Returns None if the line is empty or malformed.
        """
        if not line or not line.strip():
            return None

        clean_line = line.strip()

        try:
            payload = json.loads(clean_line)
            if not isinstance(payload, dict):
                return None
            return payload
        except json.JSONDecodeError:
            # Handles split chunks or non-JSON log noise safely
            return None

    @classmethod
    def extract_metric(cls, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extracts and normalizes live server metrics from a METRIC packet.
        """
        if data.get("type") != "METRIC":
            return None

        try:
            return {
                "timestamp": data.get("timestamp", ""),
                "status": data.get("status", "Active"),
                "uptime": data.get("uptime", "00h:00m"),
                "heap": data.get("heap", "0MB"),
                "fps": float(data.get("fps", 0.0)),
                "players": int(data.get("players", 0)),
                "pfs": int(data.get("pfs", 0)),
                "ticks": int(data.get("ticks", 0)),
                "nwqueue": int(data.get("nwqueue", 0)),
                "player_list": data.get("player_list", []),
            }
        except (ValueError, TypeError) as err:
            print(f"[TelemetryParser] -ERROR- Failed to normalize METRIC packet: {err}")
            return None

    @classmethod
    def extract_player_cache(cls, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extracts active player list from a PLAYER_CACHE packet.
        """
        if data.get("type") != "PLAYER_CACHE":
            return None

        return {
            "status": data.get("status", "Synced"),
            "players": int(data.get("players", 0)),
            "player_list": data.get("player_list", []),
            "timestamp": data.get("timestamp", ""),
        }