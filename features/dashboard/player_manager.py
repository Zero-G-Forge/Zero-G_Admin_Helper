# =====================================================================
# MODULE: features/dashboard/player_manager.py
# DESCRIPTION: Local JSON-backed Player Registry Manager
# =====================================================================

import os
import json
from datetime import datetime, timedelta

class PlayerManager:
    """
    Manages persistent local storage and real-time state synchronization
    for all server players using data/player_registry_cache.json.
    """

    def __init__(self, storage_path: str = None):
        if storage_path is None:
            # Step back from features/dashboard/ to project root:
            # __file__ -> features/dashboard/player_manager.py
            # 1 level up: features/dashboard/
            # 2 levels up: features/
            # 3 levels up: Zero-G_Admin_Helper/ (Root Directory)
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            data_dir = os.path.join(root_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            self.storage_path = os.path.join(data_dir, "player_registry_cache.json")
        else:
            self.storage_path = storage_path

        self._players = {}
        self.load_from_disk()

    def load_from_disk(self):
        """Loads existing player records from disk into memory, normalizing schema keys."""
        print(f"[PlayerManager] -DEBUG- Checking for database at: {self.storage_path}")
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    raw_list = data if isinstance(data, list) else list(data.values())

                    for p in raw_list:
                        if not isinstance(p, dict):
                            continue

                        # Extract identifier key across schemas
                        p_name = p.get("player_name") or p.get("name", "Unknown")
                        p_id = str(p.get("private_id") or p.get("entityId", ""))
                        steam_id = str(p.get("steamId", ""))
                        lookup_key = steam_id or p_id or p_name

                        self._players[lookup_key] = {
                            "name": p_name,
                            "entityId": p_id or p.get("entityId", "--"),
                            "steamId": steam_id or p.get("steamId", "--"),
                            "status": p.get("active") or p.get("status", "Offline"),
                            "faction": p.get("faction") or "--",
                            "role": p.get("role", "Member"),
                            "solar_system": p.get("solar_system") or p.get("system", "Unknown"),
                            "playfield": p.get("playfield") or "--",
                            "last_seen": p.get("last_seen") or p.get("lastSeen", ""),
                            "ping": p.get("ping", 0)
                        }

                print(f"[PlayerManager] -SUCCESS- Loaded {len(self._players)} player record(s) from {self.storage_path}")
            except Exception as e:
                print(f"[PlayerManager] -WARN- Failed to load player_registry_cache.json: {e}")
                self._players = {}
        else:
            print(f"[PlayerManager] -WARN- File NOT found at {self.storage_path}")
            self._players = {}

    def save_to_disk(self):
        """Flushes in-memory player records to disk."""
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(list(self._players.values()), f, indent=4)
        except Exception as e:
            print(f"[PlayerManager] -ERROR- Failed to save player_registry_cache.json: {e}")

    def update_from_live_stream(self, online_list: list):
        """
        Ingests the 2-second METRIC player stream from ZeroGBridge.
        Marks connected players as Online and absent players as Offline.
        """
        if not isinstance(online_list, list):
            return

        active_keys = set()
        now_str = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

        # 1. Mark online players
        for p in online_list:
            if not isinstance(p, dict):
                continue

            steam_id = str(p.get("steamId", ""))
            eid = str(p.get("entityId", ""))
            name = p.get("name", "")
            key = steam_id or eid or name

            if not key:
                continue

            active_keys.add(key)
            existing = self._players.get(key, {})

            existing.update({
                "name": name or existing.get("name", "Unknown"),
                "entityId": eid or existing.get("entityId", "--"),
                "steamId": steam_id or existing.get("steamId", "--"),
                "status": "Online",
                "faction": p.get("faction") if p.get("faction") != "--" else existing.get("faction", "--"),
                "role": existing.get("role", "Member"),
                "solar_system": p.get("system") or existing.get("solar_system", "Unknown"),
                "playfield": p.get("playfield") if p.get("playfield") != "--" else existing.get("playfield", "--"),
                "last_seen": now_str,
                "ping": p.get("ping", existing.get("ping", 0))
            })
            self._players[key] = existing

        # 2. Mark absent players as Offline
        for k, p in self._players.items():
            if k not in active_keys and p.get("status") == "Online":
                p["status"] = "Offline"

        self.save_to_disk()

    def update_from_roster_cache(self, roster_list: list):
        """Ingests full player batches returned by 'plys' command."""
        if not isinstance(roster_list, list):
            return

        now_str = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

        for p in roster_list:
            if not isinstance(p, dict):
                continue

            steam_id = str(p.get("steamId", ""))
            eid = str(p.get("entityId", ""))
            name = p.get("name", "")
            key = steam_id or eid or name

            if not key:
                continue

            existing = self._players.get(key, {})
            existing.update({
                "name": name or existing.get("name", "Unknown"),
                "entityId": eid or existing.get("entityId", "--"),
                "steamId": steam_id or existing.get("steamId", "--"),
                "status": p.get("status", existing.get("status", "Offline")),
                "faction": p.get("faction", existing.get("faction", "--")),
                "role": existing.get("role", "Member"),
                "solar_system": p.get("system") or existing.get("solar_system", "Unknown"),
                "playfield": p.get("playfield", existing.get("playfield", "--")),
                "last_seen": p.get("lastSeen") or existing.get("last_seen", now_str),
                "ping": p.get("ping", existing.get("ping", 0))
            })
            self._players[key] = existing

        self.save_to_disk()

    def get_all_players(self) -> list:
        """Returns the full master player roster for Player Registry Popup."""
        return list(self._players.values())

    def get_recent_players(self, days: int = 14) -> list:
        """Returns players active within the past X days for the main cockpit table."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        recent = []

        for p in self._players.values():
            if p.get("status") == "Online":
                recent.append(p)
                continue

            last_seen_str = p.get("last_seen", "")
            try:
                clean_time = last_seen_str.split(".")[0].replace("T", " ")
                last_seen_dt = datetime.strptime(clean_time, "%Y-%m-%d %H:%M:%S")
                if last_seen_dt >= cutoff:
                    recent.append(p)
            except Exception:
                recent.append(p)

        return recent