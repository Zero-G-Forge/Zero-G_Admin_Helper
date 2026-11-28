# data_source.py
"""
Where the ZeroGBridge Portal gets its data.

The portal panels never read files or talk to a server directly. They ask a
PortalDataSource for:
    loader_state()  -> LoaderState   (LOADER tab: versions, port, history)
    scripts()       -> list[Script]  (BRIDGE tab: IronPython scripts)
    cores_dir()     -> Path          (folder the LOADER tab browses for core DLLs)

SampleDataSource reads the example files in <ZAH>/Examples/ZGB_Portal/.
LiveDataSource reads the active ZAH server through ZeroGBridge (hot:status,
plys). Its network calls block, so the panels run them via live_client.run_async.
Reload / rollback are only sent by the panel after the user confirms.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from features.paths import APP_ROOT

TZ = ZoneInfo("America/Chicago")
EXAMPLES_DIR = Path(APP_ROOT) / ".instructions" / "Examples" / "ZGB_Portal"


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
    # Live-only details (blank for Examples)
    connection: str = "Examples"   # Examples | Connecting | Online | Offline | Auth failed
    core_release: str = ""
    core_id: str = ""
    core_domain: str = ""
    pending_drop: str = ""
    server_auto_reload: bool = False
    hot_reload_enabled: bool = True
    reload_in_progress: bool = False


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

        ## Never None here: it was just read, or set to {} above.
        return cast(dict, self._loader_raw)

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


# ---------------------------------------------------------------------------
# Live source (active ZAH server)
# ---------------------------------------------------------------------------

def _parse_utc(text) -> datetime | None:
    if not text:
        return None
    raw = str(text).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    # .NET writes 7 fractional digits; Python accepts at most 6.
    if "." in raw:
        head, _, rest = raw.partition(".")
        frac = ""
        tail = ""
        for i, ch in enumerate(rest):
            if ch.isdigit():
                frac += ch
            else:
                tail = rest[i:]
                break
        raw = f"{head}.{frac[:6]}{tail}" if frac else head + tail
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(TZ)


def short_core_id(core_id) -> str:
    """'1.5.1116.1341_db04e1f8' -> '1.5.1116.1341'. None -> '—'."""
    if not core_id:
        return "—"
    return str(core_id).split("_", 1)[0]


def describe_reload(entry: dict | None) -> tuple[str, bool]:
    """Text for 'Last reload result' plus whether it was OK."""
    if not isinstance(entry, dict) or not entry:
        return "No reload yet", True
    ok = bool(entry.get("ok"))
    action = str(entry.get("action") or "reload")
    parts = [f"{action} {'OK' if ok else 'FAILED'}"]
    if entry.get("durationMs") is not None:
        parts.append(f"{entry.get('durationMs')} ms")
    when = _parse_utc(entry.get("timeUtc"))
    if when:
        parts.append(when.strftime("%I:%M %p CST").lstrip("0"))
    detail = entry.get("error") or entry.get("message")
    if detail:
        parts.append(str(detail))
    return " — ".join(parts), ok


def parse_status(payload: dict, profile: dict | None = None) -> LoaderState:
    """Turns a HOT status reply into the LOADER tab's LoaderState."""
    profile = profile or {}
    payload = payload if isinstance(payload, dict) else {}
    loader = payload.get("loader") or {}
    core = payload.get("core") or {}
    version = core.get("version") or {}
    diag = payload.get("diagnostics") or {}
    view = diag.get("serverView") or {}

    state = LoaderState()
    state.connection = "Online"
    name = str(profile.get("server_name") or "").strip()
    state.server_name = name or str(profile.get("input_ip") or "Unknown server")
    try:
        state.port = int(str(profile.get("bridge_port") or "30500").strip() or 30500)
    except ValueError:
        state.port = 30500
    state.loader_version = str(loader.get("release") or loader.get("assemblyVersion") or "?")
    if loader.get("release") and loader.get("assemblyVersion"):
        state.loader_version = f"{loader['release']}  ({loader['assemblyVersion']})"
    state.core_id = str(version.get("id") or "")
    state.core_release = str(version.get("release") or "")
    state.core_version = short_core_id(state.core_id) if state.core_id else (state.core_release or "?")
    state.core_domain = str(core.get("domain") or "")
    if not core.get("loaded", True):
        state.core_domain = "not loaded"
    loaded = _parse_utc(core.get("loadedUtc")) or _parse_utc(version.get("importedUtc"))
    if loaded:
        state.loaded_since = loaded
    state.last_result, state.last_ok = describe_reload(payload.get("lastReload"))
    online = diag.get("online", view.get("online", 0))
    try:
        state.players_online = int(online or 0)
    except (TypeError, ValueError):
        state.players_online = 0
    pending = payload.get("pendingDrop")
    if pending in (None, False, "", 0):
        state.pending_drop = ""
    elif pending is True:
        state.pending_drop = f"New core waiting in {payload.get('dropFolder') or 'Updates'}/"
    else:
        state.pending_drop = str(pending)
    state.server_auto_reload = bool(payload.get("autoReloadOnDrop"))
    state.hot_reload_enabled = bool(payload.get("hotReloadEnabled", True))
    state.reload_in_progress = bool(payload.get("reloadInProgress"))

    entries = []
    for item in payload.get("history") or []:
        if not isinstance(item, dict):
            continue
        when = _parse_utc(item.get("timeUtc")) or datetime.now(TZ)
        ok = bool(item.get("ok"))
        action = str(item.get("action") or "reload")
        result = "OK" if ok else "Failed"
        if action == "rollback" and ok:
            result = "Rolled back"
        note = f"{action} ({item.get('trigger') or '?'})"
        if item.get("from"):
            note += f" from {short_core_id(item.get('from'))}"
        if item.get("durationMs") is not None:
            note += f" · {item.get('durationMs')} ms"
        detail = item.get("error") or item.get("message")
        if detail:
            note += f" · {detail}"
        entries.append(HistoryEntry(short_core_id(item.get("to")), when, result, note))
    entries.sort(key=lambda e: e.when, reverse=True)
    state.history = entries
    state.pending_dll = state.pending_drop
    return state


def offline_state(profile: dict | None, connection: str, message: str = "") -> LoaderState:
    """Placeholder state while connecting or when the server can't be read."""
    profile = profile or {}
    state = LoaderState()
    state.connection = connection
    name = str(profile.get("server_name") or "").strip()
    state.server_name = name or str(profile.get("input_ip") or "No active server")
    try:
        state.port = int(str(profile.get("bridge_port") or "30500").strip() or 30500)
    except ValueError:
        state.port = 30500
    state.loader_version = "—"
    state.core_version = "—"
    state.last_result = message or connection
    state.last_ok = connection in ("Connecting", "Online")
    state.players_online = 0
    return state


def format_players(payload: dict, online_only: bool = False) -> str:
    """Text table for a PLAYER_CACHE reply (BRIDGE tab)."""
    rows = []
    for p in (payload or {}).get("player_list") or []:
        if not isinstance(p, dict):
            continue
        status = str(p.get("status") or "")
        if online_only and status.lower() != "online":
            continue
        rows.append([
            str(p.get("name") or "?"),
            status or "?",
            str(p.get("faction") or ""),
            str(p.get("playfield") or ""),
            str(p.get("last_seen") or ""),
        ])
    headers = ["Name", "Status", "Faction", "Playfield", "Last seen"]
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))
    fmt = lambda r: "  ".join(c.ljust(widths[i]) for i, c in enumerate(r))
    lines = [fmt(headers), "  ".join("-" * w for w in widths)] + [fmt(r) for r in rows]
    return "{0} player(s) shown ({1} in cache)\n\n{2}".format(
        len(rows), (payload or {}).get("players", len(rows)), "\n".join(lines))


def format_status(state: LoaderState) -> str:
    """Text summary of a parsed status (BRIDGE tab 'Get status')."""
    return (
        f"Server:      {state.server_name}\n"
        f"Loader:      {state.loader_version}  (port {state.port})\n"
        f"Core:        {state.core_release or '?'}  ({state.core_id or '—'})\n"
        f"Domain:      {state.core_domain or '—'}\n"
        f"Players:     {state.players_online} online\n"
        f"Last reload: {state.last_result}\n"
        f"Pending:     {state.pending_drop or 'none'}"
    )


class LiveDataSource(PortalDataSource):
    """
    Reads the ACTIVE ZAH server's bridge. profile_provider() returns the ZAH
    profile dict (input_ip, input_pass, bridge_port, server_name); by default
    the active entry in data/server_config.json. The token stays inside the
    profile dict and the socket; it is never displayed or logged.
    """

    label = "Live"
    is_live = True

    def __init__(self, profile_provider=None):
        self._provider = profile_provider

    def profile(self) -> dict:
        prof = None
        if self._provider is not None:
            try:
                prof = self._provider()
            except Exception:
                prof = None
        if not isinstance(prof, dict) or not prof.get("input_ip"):
            from .server_config import get_active_profile
            prof = get_active_profile() or {}
        prof = dict(prof)
        from .server_config import bridge_port_of, list_server_profiles
        prof["bridge_port"] = bridge_port_of(prof)
        if not str(prof.get("server_name") or "").strip():
            # The cockpit's profile may lack the display name; borrow it from the saved list.
            try:
                saved, _ = list_server_profiles()
            except Exception:
                saved = []
            for entry in saved:
                if (str(entry.get("input_ip", "")).strip() == str(prof.get("input_ip", "")).strip()
                        and bridge_port_of(entry) == prof["bridge_port"]
                        and str(entry.get("server_name") or "").strip()):
                    prof["server_name"] = str(entry["server_name"]).strip()
                    break
        return prof

    def server_label(self) -> str:
        prof = self.profile()
        name = str(prof.get("server_name") or "").strip()
        return name or str(prof.get("input_ip") or "No active server")

    # Non-blocking placeholder; panels call fetch_* through run_async.
    def loader_state(self) -> LoaderState:
        return offline_state(self.profile(), "Connecting", "Connecting…")

    def fetch_state(self) -> LoaderState:
        from .live_client import fetch_status
        prof = self.profile()
        return parse_status(fetch_status(prof), prof)

    def fetch_players(self) -> dict:
        from .live_client import fetch_players
        return fetch_players(self.profile())

    def reload(self, force: bool = False) -> dict:
        from .live_client import send_reload
        return send_reload(self.profile(), force=force)

    def rollback(self, core_id: str | None = None) -> dict:
        from .live_client import send_rollback
        return send_rollback(self.profile(), core_id)

    def find_player(self, name_or_id: str) -> dict:
        """Read-only: plys, then pick one player by name / entityId / steamId."""
        from .live_client import fetch_players, resolve_player
        return resolve_player(fetch_players(self.profile()), name_or_id)

    def message_player(self, entity_id, text: str) -> dict:
        """Sends alert:{target:player}. The panel only calls this after a confirm dialog."""
        from .live_client import send_player_alert
        return send_player_alert(self.profile(), entity_id, text)

    # Scripts have no live listing command yet: show the local examples.
    def scripts(self) -> list[Script]:
        return SampleDataSource().scripts()

    def cores_dir(self) -> Path:
        return SampleDataSource().cores_dir()
