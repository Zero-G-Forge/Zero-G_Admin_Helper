# =====================================================================
# MODULE: features/dashboard/player_manager.py
# DESCRIPTION: Modern Full-Schema Persistent Player Database Manager
# =====================================================================

import os
import json
from datetime import datetime, timedelta, timezone


class PlayerManager:
    """
    Manages persistent local storage and real-time state synchronization
    for all server players using data/player_registry_cache.json.
    Standardized strictly on modern schemas (name, steamId, entityId).
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
        """
        Loads all existing player records from disk into memory, normalizing schema keys
        and enforcing strict primary-key deduplication across Steam ID, Name, and Entity ID.
        """
        print(f"[PlayerManager] -DEBUG- Loading full database from: {self.storage_path}")
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    raw_list = data if isinstance(data, list) else list(data.values())

                    for p in raw_list:
                        if not isinstance(p, dict):
                            continue

                        # Extract identifier candidates strictly using modern schema
                        p_name = str(p.get("name") or p.get("player_name", "Unknown")).strip()
                        p_id = str(p.get("entityId") or p.get("private_id", "")).strip()
                        steam_id = str(p.get("steamId", "")).strip()

                        # Normalize empty stubs
                        if steam_id == "--":
                            steam_id = ""
                        if p_id == "--" or p_id == "0":
                            p_id = ""

                        # -------------------------------------------------------------
                        # Primary Key Resolution: Prefer 17-digit Steam ID (7656...)
                        # -------------------------------------------------------------
                        if steam_id and steam_id.startswith("7656"):
                            lookup_key = steam_id
                        elif p_name and p_name != "Unknown" and not p_name.startswith("Player_"):
                            lookup_key = p_name
                        elif p_id:
                            lookup_key = p_id
                        elif steam_id:
                            lookup_key = steam_id
                        else:
                            continue  # Skip unidentifiable corrupt record stubs

                        # -------------------------------------------------------------
                        # Deduplication Pass: Match against existing records in memory
                        # -------------------------------------------------------------
                        target_key = lookup_key
                        for k, existing in self._players.items():
                            # Match by valid Steam ID
                            if steam_id and existing.get("steamId") == steam_id:
                                target_key = k
                                break
                            # Match by Player Name (case-insensitive)
                            if p_name and p_name != "Unknown" and existing.get("name", "").lower() == p_name.lower():
                                target_key = k
                                break
                            # Match by Entity ID
                            if p_id and str(existing.get("entityId")) == p_id:
                                target_key = k
                                break

                        # Retrieve existing dictionary or initialize from incoming record
                        record = dict(self._players.get(target_key, p))

                        # Standardize baseline fields strictly using modern schema
                        record["name"] = p_name if p_name != "Unknown" else record.get("name", "Unknown")
                        record["steamId"] = steam_id if steam_id else record.get("steamId", "--")
                        record["entityId"] = p_id if p_id else record.get("entityId", "--")
                        record["status"] = p.get("status") or p.get("active", record.get("status", "Offline"))
                        record["faction"] = p.get("faction") or record.get("faction", "--")
                        record["role"] = p.get("role", record.get("role", "Member"))
                        record["solar_system"] = p.get("solar_system") or p.get("system", record.get("solar_system", "Unknown"))
                        record["playfield"] = p.get("playfield") or record.get("playfield", "--")
                        record["coordinates"] = p.get("coordinates", record.get("coordinates", "-"))
                        record["cheat"] = p.get("cheat", record.get("cheat", "Off"))
                        record["cheater"] = p.get("cheater", record.get("cheater", "No"))
                        record["banned"] = p.get("banned", record.get("banned", "No"))
                        record["auto_ban_protection"] = p.get("auto_ban_protection", record.get("auto_ban_protection", "Active"))
                        record["stats"] = p.get("stats", record.get("stats", {"playtime": "0h", "bases": 0, "ships": 0}))
                        record["inventory"] = p.get("inventory", record.get("inventory", {}))
                        record["last_seen"] = p.get("last_seen") or p.get("lastSeen", record.get("last_seen", ""))
                        record["ping"] = p.get("ping", record.get("ping", 0))

                        # Strip legacy artifact keys if present
                        record.pop("player_name", None)
                        record.pop("private_id", None)
                        record.pop("active", None)

                        # Commit deduplicated record to memory
                        self._players[target_key] = record

                print(f"[PlayerManager] -SUCCESS- Loaded {len(self._players)} unique, full-schema player record(s).")
            except Exception as e:
                print(f"[PlayerManager] -WARN- Failed to load player_registry_cache.json: {e}")
                self._players = {}
        else:
            print(f"[PlayerManager] -WARN- File NOT found at {self.storage_path}")
            self._players = {}

    def save_to_disk(self):
        """
        Flushes the complete full-schema database back to disk in JSON format.
        """
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(list(self._players.values()), f, indent=4)
        except Exception as e:
            print(f"[PlayerManager] -ERROR- Failed to save player_registry_cache.json: {e}")

    def update_from_live_stream(self, online_list: list):
        """
        Updates connection state, ping, playfield, and timestamps from the 2-second live stream.
        Uses timezone-aware UTC datetime formatting.
        """
        if not isinstance(online_list, list):
            return

        active_keys = set()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        for p in online_list:
            if not isinstance(p, dict):
                continue

            steam_id = str(p.get("steamId", "")).strip()
            eid = str(p.get("entityId", "")).strip()
            name = str(p.get("name", "")).strip()

            target = self._find_or_create(name, eid, steam_id)
            target_key = target.get("steamId") or target.get("name") or target.get("entityId")
            active_keys.add(target_key)

            # Update live connection attributes
            target["status"] = "Online"
            target["last_seen"] = now_str
            target["ping"] = p.get("ping", 0)

            # Link discovered identifiers
            if steam_id and steam_id != "--" and target.get("steamId") in ("", "--"):
                target["steamId"] = steam_id
            if eid and eid != "--" and eid != "0" and target.get("entityId") in ("", "--"):
                target["entityId"] = eid
            if name and name not in ("", "Unknown") and not name.startswith("Player_"):
                target["name"] = name

            # Update location and faction if provided by live stream
            if p.get("faction") and p.get("faction") not in ("--", "None"):
                target["faction"] = p.get("faction")
            if p.get("playfield") and p.get("playfield") not in ("--", "Unknown"):
                target["playfield"] = p.get("playfield")
            if p.get("solar_system") and p.get("solar_system") not in ("--", "Unknown"):
                target["solar_system"] = p.get("solar_system")

            # Update nested statistics if passed through live packets
            if "stats" in p and isinstance(p["stats"], dict):
                target["stats"].update(p["stats"])
            if "inventory" in p and isinstance(p["inventory"], dict):
                target["inventory"] = p["inventory"]

        # Mark absent records as Offline
        for k, target in self._players.items():
            k_id = target.get("steamId") or target.get("name") or target.get("entityId")
            if k_id not in active_keys and target.get("status") == "Online":
                target["status"] = "Offline"

        self.save_to_disk()

    def update_from_roster_cache(self, roster: list):
        """
        Non-destructively upserts incoming player cache data into the local registry dictionary.
        Prevents duplicate entries across repeated plys query cycles and preserves historical attributes.
        """
        if not isinstance(roster, list):
            return

        for incoming in roster:
            if not isinstance(incoming, dict):
                continue

            steam_id = str(incoming.get("steamId", "")).strip()
            eid = str(incoming.get("entityId", "")).strip()
            name = str(incoming.get("name", "")).strip()

            # Locate existing record or allocate a standardized record
            target = self._find_or_create(name, eid, steam_id)

            # Preserve real names and prevent overwriting with generic Player_XXXX placeholders
            if name and not name.startswith("Player_") and name != "Unknown":
                target["name"] = name
            elif target.get("name") in ("", "Unknown") and name:
                target["name"] = name

            # Standardize primary and secondary identifiers
            if steam_id and steam_id != "--":
                target["steamId"] = steam_id
            if eid and eid not in ("--", "0"):
                target["entityId"] = eid

            # Accept actual last seen from server mod payload if present
            server_last_seen = incoming.get("last_seen") or incoming.get("lastSeen")
            if server_last_seen and server_last_seen not in ("--", ""):
                target["last_seen"] = server_last_seen

            # Update live telemetry attributes if available
            target["status"] = incoming.get("status", target.get("status", "Offline"))
            target["ping"] = incoming.get("ping", target.get("ping", 0))

            if incoming.get("last_seen"):
                target["last_seen"] = incoming.get("last_seen")
            if incoming.get("playfield") and incoming.get("playfield") != "--":
                target["playfield"] = incoming.get("playfield")
            if incoming.get("solar_system") and incoming.get("solar_system") != "Unknown":
                target["solar_system"] = incoming.get("solar_system")
            if incoming.get("faction") and incoming.get("faction") != "--":
                target["faction"] = incoming.get("faction")
            if incoming.get("role") and incoming.get("role") != "--":
                target["role"] = incoming.get("role")

            # Merge nested dictionary collections safely
            if "stats" in incoming and isinstance(incoming["stats"], dict):
                if "stats" not in target or not isinstance(target["stats"], dict):
                    target["stats"] = {}
                target["stats"].update(incoming["stats"])

            if "inventory" in incoming and isinstance(incoming["inventory"], dict):
                target["inventory"] = incoming["inventory"]

        # Commit synchronized registry back to JSON storage
        self.save_to_disk()

    def _find_or_create(self, name: str, eid: str, steam_id: str) -> dict:
        """
        Locates an existing record by Steam ID, Name, or Entity ID, or creates a new full-schema record.
        """
        # 1. Match by Steam ID (Highest Priority)
        if steam_id and steam_id != "--":
            for p in self._players.values():
                if p.get("steamId") == steam_id:
                    return p

        # 2. Match by Player Name (case-insensitive, ignoring generic Player_xxxx stubs)
        if name and not name.startswith("Player_") and name != "Unknown":
            for p in self._players.values():
                if p.get("name", "").lower() == name.lower():
                    return p

        # 3. Match by Entity ID
        if eid and eid != "--" and eid != "0":
            for p in self._players.values():
                if str(p.get("entityId")) == str(eid):
                    return p

        # 4. Fallback: Initialize new record with pure modern schema
        new_key = steam_id if (steam_id and steam_id != "--") else (name if name else eid)
        new_record = {
            "name": name or "Unknown",
            "steamId": steam_id or "--",
            "entityId": eid or "--",
            "status": "Offline",
            "faction": "--",
            "role": "Member",
            "playfield": "--",
            "solar_system": "Unknown",
            "coordinates": "-",
            "cheat": "Off",
            "cheater": "No",
            "banned": "No",
            "auto_ban_protection": "Active",
            "stats": {"playtime": "0h", "bases": 0, "ships": 0},
            "inventory": {},
            "last_seen": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "ping": 0
        }
        self._players[new_key] = new_record
        return new_record

    def get_all_players(self) -> list:
        """
        Returns all registered player records with their full schema.
        """
        return list(self._players.values())

    def get_recent_players(self, days: int = 14) -> list:
        """
        Filters for active or recently seen players within the rolling day window.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        recent = []

        for p in self._players.values():
            if p.get("status") == "Online":
                recent.append(p)
                continue

            last_seen_str = p.get("last_seen", "")
            try:
                clean_time = last_seen_str.split(".")[0].replace("T", " ")
                last_seen_dt = datetime.strptime(clean_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if last_seen_dt >= cutoff:
                    recent.append(p)
            except Exception:
                pass

        if len(recent) < 3 and len(self._players) > 0:
            return list(self._players.values())[:10]

        return recent