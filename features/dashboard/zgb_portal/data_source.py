# data_source.py
"""
Where the ZeroGBridge Portal gets its data.

The portal panels never read files or talk to a server directly. They ask a
PortalDataSource for:
    loader_state()  -> LoaderState   (LOADER tab: versions, port, history)
    scripts()       -> list[Script]  (BRIDGE tab: IronPython scripts)
    cores_dir()     -> Path          (folder the LOADER tab browses for core DLLs)

SampleDataSource reads the example files in <ZAH>/Examples/ZGB_Portal/.
A LiveDataSource that reads from ZAH's existing ZeroGBridge connection can be
added later with the same three methods and passed to ZeroGBridgePortal(source=...).

Nothing in this module opens a socket or sends a command to a game server.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from features.paths import APP_ROOT

TZ = ZoneInfo("America/Chicago")
EXAMPLES_DIR = Path(APP_ROOT) / "Examples" / "ZGB_Portal"


# ---------------------------------------------------------------------------
# Data models shared by the panels and every source
# ---------------------------------------------------------------------------

@dataclass
class HistoryEntry:
    version: str
    when: datetime
    result: str  # OK | Failed | Rolled back
    note: str = ""


@dataclass
class LoaderState:
    server_name: str = "Unknown server"
    loader_version: str = "?"
    core_version: str = "?"
    loaded_since: datetime = field(default_factory=lambda: datetime.now(TZ))
    last_result: str = "No data"
    last_ok: bool = True
    players_online: int = 0
    port: int = 30500
    auto_reload: bool = False
    busy: bool = False
    pending_dll: str = ""
    history: list[HistoryEntry] = field(default_factory=list)


@dataclass
class Script:
    name: str
    hook: str
    source: str
    enabled: bool = True
    time_limit_ms: int = 50
    live: bool = False


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

class PortalDataSource:
    """Interface every portal data source implements."""

    label = "base"
    is_live = False

    def loader_state(self) -> LoaderState:
        raise NotImplementedError

    def scripts(self) -> list[Script]:
        raise NotImplementedError

    def cores_dir(self) -> Path:
        raise NotImplementedError

    def default_core(self) -> Path | None:
        """Core DLL pre-filled in the LOADER tab (or None)."""
        return None

    def drop_core(self) -> Path | None:
        """Core DLL used by 'Simulate drop' (or None)."""
        return None


def _parse_time(text: str) -> datetime:
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


class SampleDataSource(PortalDataSource):
    """Reads the example files in Examples/ZGB_Portal/. Read-only."""

    label = "Examples"
    is_live = False

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root else EXAMPLES_DIR
        self._loader_raw: dict | None = None

    def _loader_json(self) -> dict:
        if self._loader_raw is None:
            path = self.root / "loader_state.json"
            try:
                self._loader_raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                print(f"[WARNING] ZGB Portal: could not read {path}: {exc}")
                self._loader_raw = {}
        return self._loader_raw

    def loader_state(self) -> LoaderState:
        raw = self._loader_json()
        state = LoaderState()
        for key in ("server_name", "loader_version", "core_version", "last_result"):
            if key in raw:
                setattr(state, key, str(raw[key]))
        if "last_ok" in raw:
            state.last_ok = bool(raw["last_ok"])
        if "players_online" in raw:
            state.players_online = int(raw["players_online"])
        if "port" in raw:
            state.port = int(raw["port"])
        if "loaded_since" in raw:
            state.loaded_since = _parse_time(raw["loaded_since"])
        state.history = [
            HistoryEntry(
                str(h.get("version", "?")),
                _parse_time(h["when"]) if h.get("when") else datetime.now(TZ),
                str(h.get("result", "OK")),
                str(h.get("note", "")),
            )
            for h in raw.get("history", [])
        ]
        default = self.default_core()
        state.pending_dll = str(default) if default else ""
        return state

    def scripts(self) -> list[Script]:
        folder = self.root / "scripts"
        try:
            meta = json.loads((folder / "scripts.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[WARNING] ZGB Portal: could not read {folder / 'scripts.json'}: {exc}")
            return []
        out: list[Script] = []
        for item in meta.get("scripts", []):
            name = item.get("file", "")
            try:
                source = (folder / name).read_text(encoding="utf-8")
            except OSError:
                continue
            out.append(Script(
                name,
                str(item.get("hook", "player_joined")),
                source,
                bool(item.get("enabled", True)),
                int(item.get("time_limit_ms", 50)),
                bool(item.get("live", False)),
            ))
        return out

    def cores_dir(self) -> Path:
        return self.root / "cores"

    def _core(self, key: str) -> Path | None:
        name = self._loader_json().get(key)
        if not name:
            return None
        path = self.cores_dir() / name
        return path if path.exists() else None

    def default_core(self) -> Path | None:
        return self._core("default_core")

    def drop_core(self) -> Path | None:
        return self._core("drop_core")
