# Zero-G Admin Helper — Architecture Documentation

Living technical contract for **Zero-G Admin Helper (ZAH)** and the **ZeroGBridge (ZGB)** game mod. This file lists modules, page maps, command names, and class signatures as they exist in the repository. Conceptual explanations live in `ENGINE_CONCEPTS_AND_EXPLANATIONS.md`. Update both files when a module, page, role rule, or bridge command changes.

## Overview

### Purpose

- **ZAH** is a Python desktop program for operating an Empyrion dedicated server: players, chat, factions, structures, playfields, alerts, backups, and game-data editors (items, ECF, PDA).
- **ZeroGBridge** is the all-in-one connector. ZAH talks to the running game through that mod, not through a second file-transfer protocol.
- On-screen wording says **Server**. It never names a specific host or machine, because the same program is meant to work with more than one person's server.

### Languages and runtime

- ZAH is **Python 3.12** with **PyQt6**.
- C# is limited to the **ZeroGBridge** mod.
- Development happens on Linux. ZAH must also run on Windows.
- File paths are built with `os.path.join` (and `pathlib.Path` where used). Slashes are never hard-coded, so the same code works on both systems.
- Assets and `data/` are resolved from the **app root** (the folder that holds `ZAH.py`), never from the current working directory.

### Safety boundaries

- The main window never opens until a login succeeds (fail closed).
- **Bridge auto-connect** is off by default and is stored in `data/app_settings.json`.
- Commands that would change the server (kick, ban, upload, live save, restart, and similar) stay **disabled** in the user interface, with the tooltip `Coming in a later step.`, until they are wired and approved.
- Secrets (auth token, passwords, database URL, developer key, session tokens) are never printed, logged, or committed. Local secrets live under `data/`, which is git-ignored.
- New bridge commands need explicit approval before they are written. A file-send command for downloading server files is **not in the source yet**.

## Folder Layout

| Path | Role |
| --- | --- |
| `ZAH.py` | Program entry point: stylesheet, loading screen, login gate, main window |
| `features/` | One folder per page or shared function |
| `features/shared/` | Page loader, roles, error card, ECF parser, progress bar |
| `features/dashboard/` | `MainCockpit` shell, dashboard page, nav icons |
| `features/bridge/` | Socket login, command queue thread, server profile loading |
| `features/login/` | Login window, password hashing, online and offline sessions |
| `features/settings/` | Settings page and `app_settings.json` helpers |
| `features/library/` | Shared Items and Blueprints library (tiles, stats, ECF loading) |
| `features/ecf_editor/` | ECF Editor page and code view |
| `features/pda_editor/` | PDA Editor page and YAML highlighter |
| `features/users/` | Login-user management page |
| `features/zerogbridge/` | Bridge status page (Connect, Disconnect, Open Portal) |
| `features/zgb_portal/` | ZeroGBridge Portal window (status, hot-reload, alerts) |
| `features/paths.py` | `APP_ROOT`, `DATA_DIR`, `ASSETS_DIR`, and path helpers |
| `login_service/` | HTTP login service and ZAH-DB user store |
| `tools/` | `add_login_user.py`, `set_owner_login.py`, `clear_pycache.py` |
| `assets/ZAH_main.css` | Main stylesheet, organized with CSS region markers |
| `data/` | Runtime files only (settings, sessions, server profiles). Not in git |
| `ZeroGBridge/` | C# mod source: Loader, Core, Network, Logging |
| `ZeroGBridge/bin/`, `ZeroGBridge/obj/` | Build output (not documentation targets) |
| `ZAH_Legacy/` | Previous program, kept for reference, not part of the current app |
| `.instructions/` | AI constraints, Markdown lint readme, and example files |

## Startup Flow

1. `ZAH.py` `main()` creates a `QApplication` and sets the window icon from `assets/branding/`.
2. It loads `assets/ZAH_main.css` and applies it as the application stylesheet.
3. It opens `ApplicationLoader` (the boot screen). Feature imports are each wrapped in `try` / `except`, so a missing module is logged instead of stopping the process.
4. The loader runs staged work, including a **30 percent login gate** and a 60 percent marker reserved for a later network check.
5. At the login gate the loader first tries a saved session:
   - The developer offline remember note, if present (no network).
   - Otherwise an online session token stored in `data/session.json`, checked with the login service.
6. If no saved session is valid, `LoginWindow` appears:
   - The **offline owner login** is checked first (this computer only). A match signs in as **developer**.
   - Everyone else is checked by the **online login service**.
   - **Keep me logged in** can save an offline remember note (developer) or an online session token.
7. If the loader never completed login, `ZAH.py` shows `LoginWindow` again as a backup. Failure still exits; the main window does not open.
8. `MainCockpit` is shown and receives the signed-in user, role, and session token.
9. `MainCockpit.setup_bridge()` creates a `CommandPipe` thread. The thread starts only when **bridge auto-connect** is on. Connect and Disconnect on the ZeroGBridge page can start or stop it later.

## Page Pattern

### File layout

Every feature page lives in its own folder and exposes a factory:

```python
# features/<name>/<name>_page.py
def create_page():
    return SomePage()
```

`page_loader.load_page(page_key)` imports that module, calls `importlib.reload` so a Retry picks up fixes, and calls `create_page()`. If anything raises, the cockpit shows an `ErrorCard` instead, and the rest of ZAH keeps running.

Two nav entries share one widget: **ITEMS** and **BP EDITOR** both build `LibraryPage`, with `start_tab="items"` or `start_tab="blueprints"`.

### Registration

Three tables must stay in sync when a page is added:

| Table | File | Purpose |
| --- | --- | --- |
| `PAGE_MODULES` | `features/shared/page_loader.py` | Maps the page key to the module path |
| `NAV_PAGES` | `features/dashboard/main_cockpit.py` | Maps the page key to the nav label |
| `ICON_DRAWERS` | `features/dashboard/nav_icons.py` | Maps the page key (and group keys) to a drawn icon |

### Navigation groups

`NAV_LAYOUT` is the top-to-bottom order of the nav column. A key found in `NAV_GROUPS` becomes a pop-out menu rather than a single page button.

| Group key | Title | Title also opens | Child pages |
| --- | --- | --- | --- |
| `world` | WORLD | (none) | `structures`, `playfields` |
| `library` | LIBRARY | (none) | `bp_editor`, `items` |
| `settings` | SETTINGS | `settings` | `alerts`, `bans_audit`, `users`, `ecf_editor`, `pda_editor`, `backups` |

The **SERVERS** button is hidden unless two or more servers are connected. If it hides while that page is open, the cockpit returns to **DASHBOARD**.

### Icons

`build_nav_icon(page_key)` draws a 64-pixel pixmap. Idle colour is `#8fa6b8`; the active page uses `#33d6ff`. Group titles use the same drawers (`world`, `library`, and `settings`).

### Failure isolation

- Each feature import in `ZAH.py` is guarded.
- `load_page` catches every exception and returns `ErrorCard(page_key, error_text)`.
- The card's **RETRY** button emits `retry_requested(page_key)`, which `MainCockpit` connects back to `_show_page`.
- One failed page must not close the program.

## Module and Page List

| Key | Nav label | Module | Widget | Current state |
| --- | --- | --- | --- | --- |
| `dashboard` | DASHBOARD | `features.dashboard.dashboard_page` | `DashboardPage` | Layout plus live bridge status, event list, and disabled quick actions |
| `chat` | CHAT | `features.chat.chat_page` | `ChatPage` | Layout; SEND, WARN, and MUTE disabled |
| `players` | PLAYERS | `features.players.players_page` | `PlayersPage` | Layout; player actions and loadouts disabled |
| `factions` | FACTIONS | `features.factions.factions_page` | `FactionsPage` | Layout; SET RELATION and RENAME disabled |
| `structures` | STRUCTURES | `features.structures.structures_page` | `StructuresPage` | Layout; TELEPORT, SET FACTION, and DESTROY disabled |
| `playfields` | PLAYFIELDS | `features.playfields.playfields_page` | `PlayfieldsPage` | Layout; UNLOAD, RESTART PLAYFIELD, and WIPE disabled |
| `scheduler` | SCHEDULER | `features.scheduler.scheduler_page` | `SchedulerPage` | Layout only |
| `zerogbridge` | ZEROGBRIDGE | `features.zerogbridge.zerogbridge_page` | `ZeroGBridgePage` | Live connect and disconnect; portal button for admin and above |
| `settings` | SETTINGS | `features.settings.settings_page` | `SettingsPage` | Auto-connect is live; SERVER FILES and LIVE MODE are layout only |
| `alerts` | ALERTS & ANTI-CHEAT | `features.alerts.alerts_page` | `AlertsPage` | Layout; PREVIEW BAN disabled |
| `bans_audit` | BANS & AUDIT | `features.bans_audit.bans_audit_page` | `BansAuditPage` | Failed-login table is live (owner, or developer with key) |
| `users` | USERS | `features.users.users_page` | `UsersPage` | Live add, edit, and remove through the login service; Live file editing checkbox is layout only |
| `ecf_editor` | ECF EDITOR | `features.ecf_editor.ecf_editor_page` | `EcfEditorPage` | Local folder and code view work; download, upload, validate, and save are disabled |
| `pda_editor` | PDA EDITOR | `features.pda_editor.pda_editor_page` | `PdaEditorPage` | Local folder, chapters, and YAML view work; server buttons are disabled |
| `backups` | BACKUPS | `features.backups.backups_page` | `BackupsPage` | Layout; restore is locked |
| `bp_editor` | BP EDITOR | `features.bp_editor.bp_editor_page` | `LibraryPage` (blueprints tab) | Layout; blueprint data is not loaded yet |
| `items` | ITEMS | `features.items.items_page` | `LibraryPage` (items tab) | Can load items from a Content folder via `load_items_from`; images and server download are not wired |
| `servers` | SERVERS | `features.multi_server.multi_server_page` | `MultiServerPage` | Layout; shown only with two or more connected servers |

Supporting modules (not nav pages):

| Module | Role |
| --- | --- |
| `features/dashboard/main_cockpit.py` | Main window shell: header, nav, content stack, status bar, bridge pipe, logout |
| `features/loading/loading_screen.py` | Boot dialog and login gate |
| `features/bridge/command_pipe.py` | Background thread that logs in and sends queued commands |
| `features/bridge/bridge_connection.py` | Socket helpers and line protocol |
| `features/bridge/server_settings.py` | Reads the active profile from `data/server_config.json` |
| `features/shared/ecf_parser.py` | Read-only ECF parse, Ref merge, and CSV name lookup |
| `features/library/item_library.py` | Builds the item list from `ItemsConfig.ecf` and `Localization.csv` |
| `features/library/item_tiles.py` | Hex tiles and the wrapping tile flow area |
| `features/library/item_stats_dialog.py` | Full stats window for one item |
| `features/zgb_portal/` | Portal window used from the ZeroGBridge page |

## Roles

### Role order

`features/shared/roles.py` holds the only rank list, **lowest first**:

```python
ROLE_ORDER = ("moderator", "admin", "owner", "developer")
```

- `get_role_rank(role)` returns `0` to `3`, or `-1` for a missing or unknown name (fail closed).
- `has_role_at_least(user_role, needed_role)` is true only when the signed-in rank is at least the needed rank. An unknown **needed** role also returns false, so a typo never opens a door.
- `MainCockpit.user_has_role(needed_role)` is the page-level wrapper. Pages ask the cockpit instead of comparing role strings themselves.

The login database allows only `owner`, `admin`, and `moderator`. **developer** is not a database role. It is granted by the offline owner login on this computer (and by the developer key on owner-only service routes).

### What each role can do

| Action | moderator | admin | owner | developer |
| --- | --- | --- | --- | --- |
| Sign in and use the cockpit | yes | yes | yes | yes |
| Open ZeroGBridge Portal | no | yes | yes | yes |
| Portal live Reload and Rollback | no | no | no | yes |
| See Users page and manage users | no (page refuses) | moderators only, own server | own server, any of those three roles | any server, any of those three roles |
| Failed login log on Bans & Audit | no | no | yes (session token) | yes (developer key, fail closed if missing) |
| LIVE MODE toggle (planned) | only with granted permission | only with granted permission | always (when wired) | always (when wired) |
| Grant Live file editing (planned) | no | no | yes | yes |

Owners and admins are limited to their own server on the Users page. The login service enforces the same rules again, so the client cannot be tricked into a higher permission.

## Login Service and User Store

The service is a small HTTP process in `login_service/`. ZAH reaches it through helpers in `features/login/online_login.py`. The service URL comes from the `ZAH_LOGIN_URL` environment variable. Host and bind settings come from environment variables as well; those values are not recorded here.

Passwords are stored as **scrypt** hashes plus salt. Password text, tokens, and the database URL are never logged.

### Routes

| Method | Path | Who | Purpose |
| --- | --- | --- | --- |
| GET | `/health` | anyone | Liveness check |
| POST | `/login` | public, rate limited | Checks username and password; may create a remembered session |
| POST | `/session` | bearer token | Confirms a saved token and returns the current role from the user store |
| POST | `/logout` | bearer token | Ends the token; answers ok even for an unknown token |
| POST | `/failed_logins` | owner token, or developer key | Newest failed login rows |
| POST | `/users` | owner token, or developer key | List of users (no password data) |
| POST | `/users/save` | owner token, or developer key | Add a user or change role / password |
| POST | `/users/delete` | owner token, or developer key | Remove a user |

Rate limiting (`login_service/rate_limiter.py`) uses a 15-minute window: five failures per username, twenty per source address. A lockout returns HTTP 429. ZAH shows `Too many tries, wait 15 minutes`. The login window also stops after five local failed attempts.

### ZAH-DB tables

When a database URL is configured, tables are created on startup. If it is not configured, the service falls back to a local users file and in-memory sessions and logs (for local use only).

The `users` table:

| Column | Notes |
| --- | --- |
| `username` | Primary key, stored lower-case |
| `salt` | Password salt (never returned to the client) |
| `password_hash` | scrypt hash (never returned to the client) |
| `role` | `owner`, `admin`, or `moderator` only (database CHECK) |
| `created_at` | Set on insert |
| `server_name` | Server the user belongs to; blank is shown as UNASSIGNED |
| `server_address` | Address field for that server |
| `display_name` | Name with original capitals, for display only |

There is **no Live file editing column yet**. The Users dialog shows the checkbox in the layout, disabled, until that column is added and approved.

The `sessions` table:

| Column | Notes |
| --- | --- |
| `token_hash` | Primary key; the raw token is never stored |
| `username` | Foreign key to `users`, cascade on delete |
| `expires_at` | Null means unlimited |
| `created_at` | Set on insert |

Remember choices: `8h`, `12h`, `1d`, `7d`, `unlimited`.

The `failed_logins` table:

| Column | Notes |
| --- | --- |
| `id` | Big serial primary key |
| `failed_at` | Timestamp |
| `username` | Attempted name |
| `source` | Request source |
| `reason` | `wrong password` or `locked out` |

Rows are kept for 30 days. List calls cap the count (default 50, hard max 200).

### Client helpers and tools

- `features/login/password_hashing.py` — `hash_password`, `check_password` (offline owner login).
- `features/login/owner_login.py` — reads and checks `data/owner_login.json`.
- `features/login/offline_remember.py` — HMAC-signed remember note for the developer login; the signing key file is git-ignored.
- `features/login/saved_session.py` — writes and clears `data/session.json`.
- `tools/set_owner_login.py` — one-time setup of the offline owner login (hash only).
- `tools/add_login_user.py` — adds an online user (owner, admin, or moderator) and asks which saved server they belong to.
- `tools/clear_pycache.py` — removes `__pycache__` folders.

## Settings

`features/settings/app_settings.py` reads and writes `data/app_settings.json`. Only known keys with the default value's type are kept, so an older file still loads.

| Key | Default | Meaning |
| --- | --- | --- |
| `bridge_auto_connect` | `False` | When true, `MainCockpit` starts `CommandPipe` at launch |

LIVE MODE is **not** a saved setting. The switch always starts off when ZAH opens, and it is not written to the settings file.

The Settings page also has a **SERVER FILES** section (layout only, controls disabled):

- Status lines: `LOCAL COPY` and `LAST PULLED`.
- Button: `DOWNLOAD SERVER FILES (READ-ONLY)`.
- Checkbox: `LIVE MODE: edit files directly on the server`.
- Note: every live save will ask three times (changes preview, online-players warning, then typing the file name), and the bridge will back up the old file first.

## ZeroGBridge Commands

### Process layout

Empyrion loads `ZeroGBridge.Loader.ZeroGBridgeLoader`, which implements **API v2** `Eleon.Modding.IMod` (`Init`, `Shutdown`) and also the legacy `ModInterface` so the host can load it. The loader is small and stable:

- It owns the TCP listener and authentication (`BridgeListener`, `AuthConfig`).
- It hosts `CoreHost`, which loads the reloadable core (`ZeroGBridge.Core.dll`) in its own AppDomain.
- Game-state work is marshalled onto the **game thread** (`GameThread`, `GameGateway`), never executed on the network thread.
- Loader release is **1.5.0**. A loader change needs a server restart. Core release is **1.6.0** (`Request_*` API, console proxy, command catalog, restart through `saveandexit`). Core changes can be applied with `hot:reload` when that path is used.

The auth token is read from `ZeroGBridge.json` only and is never written into log lines.

### Wire format

- Each command is a **single line** ending in `\r\n`.
- Each reply is a **single JSON line**, also ending in `\r\n`.
- ZAH's `CommandPipe` waits **0.5 seconds** between outgoing commands (`INPUT_DELAY_SEC`).
- Login is `auth:<token>`. A good reply has `"type": "AUTH"` and `"status": "Authenticated"`. The token is sent on the wire and is never printed by ZAH.
- `cmds`, `help:commands`, and `api:list` return a `COMMAND_CATALOG` JSON object: Eleon requests, console commands, and ZAH shortcuts.

### Shorthand commands (core dispatcher)

Handled in `ZeroGBridge/Network/CommandDispatcher.cs` and `ApiCommands.cs` after authentication. Names are case-insensitive.

| Command | Aliases | Effect | Changes the server |
| --- | --- | --- | --- |
| `plys` | | Live player roster | no |
| `add_player:` | | Diagnostic player inject (testing) | no (cache only) |
| `save` | | Not available; the game autosaves | no |
| `backup` | | Not available from the bridge | no |
| `restart:<minutes>` | `restart` | Warns with `say`, then `saveandexit` with minutes `0` to `15` | yes |
| `restart:cancel` | | Cancels a scheduled `saveandexit` | yes |
| `gents` | `structures`, `getentities`, plus a playfield filter suffix | Structure and entity list | no |
| `touchstruct:` | `touch:` | Touch a structure | yes |
| `destroystruct:` | `destroyentity:`, `wipe:` | Destroy an entity | yes |
| `broadcast:` | `say:`, `alert:` | Message to all players | yes (visible) |
| `msg:` | `msgplayer:` | Message to one player | yes (visible) |
| `msgfaction:` | `factionmsg:` | Message to a faction | yes (visible) |
| `getcredits:` | `credits:` | Read a player's credits | no |
| `addcredits:` | `setcredits:` | Change a player's credits | yes |
| `getinv:` | `getinventory:` | Read a player's inventory | no |
| `getplayfields` | `pfs`, `playfields`, plus `:all` | Playfield list | no |
| `pfstats:` | `playfieldstats:` | Playfield stats | no |
| `pfents:` | `playfieldentities:` | Entities on a playfield | no |
| `loadpf:` | `loadplayfield:` | Load a playfield | yes |
| `api:<RequestName>` | short names from the catalog | Eleon request, optional JSON params | depends on the request |
| `con:<line>` | `cmd:`, `exec:` | Dedicated console command | depends on the line |

`save` and `backup` return `status: "not_available"`. The catalog states that backups are a ZAH job after the server has stopped, not a bridge command.

### Eleon `api:` requests

`ZeroGBridge/Core/EleonRequests.cs` registers the requests below. `api:<name>` accepts the full `Request_*` name or a short name from the catalog. Optional JSON follows the name. Every request also accepts control keys `req_id` and `timeout_ms`. Send `cmds` for parameters, replies, and the `changes_server` flag.

Player and inventory:

- `Request_Player_List`
- `Request_Player_Info`
- `Request_Player_SetPlayerInfo`
- `Request_Player_GetInventory`
- `Request_Player_SetInventory`
- `Request_Player_AddItem`
- `Request_Player_ItemExchange`
- `Request_Player_GetAndRemoveInventory`
- `Request_Player_Credits`
- `Request_Player_SetCredits`
- `Request_Player_AddCredits`
- `Request_Player_ChangePlayerfield`

Entities, structures, and playfields:

- `Request_NewEntityId`
- `Request_Entity_Teleport`
- `Request_Entity_ChangePlayfield`
- `Request_Entity_Destroy`
- `Request_Entity_Destroy2`
- `Request_Entity_PosAndRot`
- `Request_Entity_Spawn`
- `Request_Entity_SetName`
- `Request_Entity_Export`
- `Request_Blueprint_Finish`
- `Request_Blueprint_Resources`
- `Request_Playfield_List`
- `Request_Playfield_Stats`
- `Request_Playfield_Entity_List`
- `Request_Load_Playfield`
- `Request_GlobalStructure_List`
- `Request_GlobalStructure_Update`
- `Request_Structure_Touch`
- `Request_Structure_BlockStatistics`
- `Request_Dedi_Stats`

Factions and messages:

- `Request_Get_Factions`
- `Request_AlliancesAll`
- `Request_AlliancesFaction`
- `Request_GetBannedPlayers`
- `Request_InGameMessage_SinglePlayer`
- `Request_InGameMessage_AllPlayers`
- `Request_InGameMessage_Faction`
- `Request_ShowDialog_SinglePlayer`
- `Request_ConsoleCommand`

### Loader `hot:` commands

Handled by the loader, not the core, so they still work while a core is missing or reloading. The ZeroGBridge Portal exposes Reload and Rollback to the **developer** role only.

| Command | Effect |
| --- | --- |
| `hot:status` | Current core, reload state, and version info |
| `hot:versions` | Stored core versions |
| `hot:reload` | Load a new core (optional `force`) |
| `hot:rollback` | Return to a stored core (optional version id) |

The same commands also accept a JSON body after `hot:` with keys `cmd`, `req_id`, `force`, and `version`.

There is **no file-list or file-send command** in the current source.

## Class and Method Signatures

### Entry, shell, and loader

```python
def main()

class ApplicationLoader(QDialog):
    def __init__(self, build_main_window=None, parent=None)
    def start_boot_sequence(self)
    def _stage_check_assets(self)
    def _stage_prepare_data(self)
    def _try_saved_session(self)
    def _stage_login_gate(self)
    def _stage_load_fonts(self)
    def _stage_build_main_window(self)

class MainCockpit(QMainWindow):
    def __init__(self, parent=None)
    def set_signed_in_user(self, username, role, session_token=None)
    def user_has_role(self, needed_role)
    def _on_logout_clicked(self)
    def _show_page(self, page_key)
    def update_server_status(self, server_name, is_connected)
    def update_bridge_status(self, is_connected)
    def update_multi_server_nav(self, connected_count)
    def update_alert_badge(self, alert_count)
    def setup_bridge(self)
    def connect_bridge(self)
    def disconnect_bridge(self)
    def open_zgb_portal(self)
```

### Shared helpers

```python
PAGE_MODULES: dict[str, str]
def load_page(page_key)

ROLE_ORDER = ("moderator", "admin", "owner", "developer")
def get_role_rank(role)
def has_role_at_least(user_role, needed_role)

class ErrorCard(QFrame):
    retry_requested = pyqtSignal(str)
    def __init__(self, page_name, error_text, parent=None)

class ProgressBarWidget(QWidget)

def parse_ecf_blocks(file_text)
def resolve_refs(blocks)
def read_english_names(csv_path)

def spread_letters(widget, spacing_px)
def make_card(title_text="")

def data_path(*parts: str) -> str
def asset_path(*parts: str) -> str
```

`make_card(title)` returns `(QFrame #DashCard, layout)`. The title label is `QLabel #DashCardTitle`.

### Bridge client

```python
LINE_END = "\r\n"
def open_authenticated_socket(host, port, token, timeout=BRIDGE_LOGIN_TIMEOUT)
def send_bridge_command(bridge_socket, command_text)
def read_bridge_line(bridge_socket, max_bytes=65536)
def close_bridge_socket(bridge_socket)
def get_active_profile()

class CommandPipe(QThread):
    connection_changed = pyqtSignal(str, bool)
    reply_received = pyqtSignal(str, str)
    command_dispatched = pyqtSignal(str)
    queue_empty = pyqtSignal()
    def __init__(self, input_delay_sec=INPUT_DELAY_SEC, parent=None)
    def enqueue_command(self, command_str)
    def stop(self)
    def run(self)
```

Profile fields used from `data/server_config.json` include the display name, the host address, and the bridge port. The auth token is read from the same profile and is never printed. `active_index` selects the current profile. A blank bridge port uses the built-in default from `server_settings.py`.

### Login, users, and settings

```python
class LoginWindow(QDialog):
    def _on_login_clicked(self)

def check_owner_login(username, password_text)
def check_online_login(username, password_text, remember=None)
def check_saved_session(session_token)
def end_online_session(session_token)
def fetch_failed_logins(session_token, limit=50, dev_key=None)
def fetch_users(session_token, dev_key=None)
def save_user(session_token, username, role, password="", dev_key=None, server_name="", server_address="")
def remove_user(session_token, username, dev_key=None)

class UsersPage(QWidget)
class UserEditDialog(QDialog)
class UserTaskRunner(QThread)
class BansAuditPage(QWidget)
class FailedLoginFetcher(QThread)

def load_app_settings()
def save_app_setting(key, value)
```

### Library and editors

```python
def load_items(content_folder)

class LibraryPage(QWidget):
    def __init__(self, start_tab="items", parent=None)
    def load_items_from(self, content_folder)
    def _apply_filters(self, *args)
    def _on_tile_picked(self, item)
    def _show_item_stats(self)

class HexTile(QAbstractButton)
class TileFlowArea(QScrollArea):
    def set_items(self, items)
    def show_only(self, tiles_to_show)

class ItemStatsDialog(QDialog):
    def __init__(self, item, own_keys=None, parent=None)

class EcfEditorPage(QWidget):
    def load_local_folder(self, folder_path)

class EcfCodeEditor(QPlainTextEdit)
class EcfHighlighter(QSyntaxHighlighter)

class PdaEditorPage(QWidget):
    def load_local_folder(self, folder_path)

class PdaYamlHighlighter(QSyntaxHighlighter)
```

Item filter groups, in button order: `WEAPONS`, `ARMOR`, `MEDICAL`, `AMMO`, `COMPONENTS`, `ORES`, `DEVICES`, `FOOD`. Items with `ShowUser: No` are omitted. Display names come from `Localization.csv`.

`ItemStatsDialog` sections: **GENERAL**, one **MODE n** section per child block, **OTHER**, and collapsed **FILE DETAILS**. Inherited Ref values are marked. Units are appended from the property `formatter` (`Kilogram` to `kg`, `Liter` to `L`, `ROF` to `s`, `WattHour` to `Wh`).

### Login service

```python
class LoginRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self)
    def do_POST(self)

def add_user(username, password_text, role, server_name="", server_address="")
def check_user(username, password_text)
def list_users()
def delete_user(username)
def set_user_role(username, role, server_name="", server_address="")
def create_session(username, remember)
def check_session(session_token)
def delete_session(session_token)
def log_failed_login(username, source, reason)
def list_failed_logins(limit=50)
def is_locked_out(username, source)
```

### ZeroGBridge (C#)

```C#
public class ZeroGBridgeLoader : IMod, ModInterface
{
    public void Init(IModApi modApi);
    public void Shutdown();
}

public class CommandDispatcher
{
    public CommandDispatcher(PlayerCache playerCache);
    public string ProcessIncomingCommand(string command);
}

public static class ApiCommands
{
    public const string ApiPrefix = "api:";
    public static string Catalog();
    public static string HandleApi(string line);
    public static string HandleConsole(string line);
    public static string HandleSaveOrBackup(string lowerCmd);
    public static string HandleRestart(string cleanCmd);
    public static string LoadPlayfield(string playfieldName, float seconds);
}
```

## CSS Conventions

The live stylesheet is `assets/ZAH_main.css`. Sections use CSS region markers so they fold in an editor:

```CSS
/* region: Palette */
/* endregion */
```

Python regions use `# region Name` / `# endregion`. C# uses `#region` / `#endregion`. Instructional comments in Python use `##` and stay in neutral third person.

Current CSS regions, in file order:

| Region | Covers |
| --- | --- |
| Palette | Shared colours |
| Global Container & Base Labels | Window and default text |
| Shell Panels | Main chrome |
| Header Bar | Top bar |
| Nav Column | Nav buttons, groups, and badge |
| Content Panel | Page stack |
| Status Bar | Bottom bar |
| Loading Screen | Boot dialog |
| Error Card | Failed-page card and Retry |
| Dashboard Page | Stat cards, tables, quick actions |
| Alerts Page | Queue and evidence |
| Chat Page | Tabs and message list |
| Players Page | List, bars, and action buttons |
| Factions Page | List and relations |
| Structures Page | Filters and table |
| Scheduler Page | Tasks and chain editor |
| ECF Editor Page | Shared with the PDA Editor (same layout) |
| Backups Page | Snapshots and restore |
| Library Page | Tiles, filters, detail, and stats dialog |
| Settings Page | Sections, checkbox, and notes |
| Multi-Server Page | Server cards and rings |

Widgets are targeted by `objectName` (`SettingsPage`, `DashCard`, `DashCardTitle`, `LibraryTileArea`, `ItemStatsDialog`, and others). Prefer adding a name and a rule in the matching region rather than a one-off style in Python.

## Planned / Not Yet Wired

These items have UI placeholders, agreed behaviour, or both. They are **not** implemented end-to-end. Server-changing steps stay disabled until they are approved.

### SERVER FILES download through ZeroGBridge

- Settings button: `DOWNLOAD SERVER FILES (READ-ONLY)`.
- The download must go through **ZeroGBridge**, not a second connector.
- The bridge will need a new **read-only** command that lists and sends files from fixed folders only, so it cannot be pointed at arbitrary paths. That command is not in the source and still needs approval before it is written.
- Folders to copy from the active scenario and save, into a local folder for the current server:
  - `Content/Configuration` (ECF files)
  - `Extras/PDA`
  - `SharedData/Content/Images`
  - the save-game files
- The Settings card should show the local copy path and the last-pulled time.
- Items, ECF Editor, and PDA Editor must then read from that downloaded folder, **never** from local base-game Content files.

### Item images

- Image files are named after each item's internal `Name`, for example `<ItemName>.jpg`.
- Lookup path, once the scenario is downloaded: `Scenarios/<scenario>/SharedData/Content/Images/<ItemName>.jpg`.
- An item with no image falls back to the drawn hex tile.
- Files in that folder that do not match an item name (for example PDA pictures) are skipped.

### LIVE MODE

- Settings switch: `LIVE MODE: edit files directly on the server`.
- **Off by default** and **never saved**. It turns itself back off whenever ZAH starts.
- With it off, editors use the downloaded copies.
- With it on, editors read and write through the bridge, and the page shows a red **LIVE** banner.
- Every live save goes through three popups, in order:
  1. Changes preview.
  2. Online-player check and warning.
  3. The operator types the file name to confirm.
- The bridge backs up the old file before writing the new one.
- **Developers and owners** always have the toggle (once it is wired).
- An owner or developer may grant **Live file editing** to an individual admin or moderator on the Users page. The checkbox is already in `UserEditDialog`, hidden when the role is Owner, and disabled until a new ZAH-DB column is added (a database change that must be applied with approval).
- Live writes are server changes. The control stays disabled until that work is approved.

### ECF and PDA editor follow-through

Still to wire, all against **downloaded server files** (or LIVE MODE once approved):

- **VALIDATE**
- A real diff in **Changes Preview**
- **SAVE** to the local copy, with a backup of the previous file
- **UPLOAD TO SERVER** through ZeroGBridge, only with explicit approval

Until then, the toolbar buttons stay disabled with `Coming in a later step.` The ECF and PDA pages can already open a local folder for layout and editor testing. That path is not the long-term data source.

### Other agreed follow-ups

- Multi-server connections and bridge auto-reconnect.
- Wiring play, chat, faction, structure, playfield, alert, and backup actions that still have disabled buttons.
- Optional restyle of Bans & Audit and Users, only if requested.
