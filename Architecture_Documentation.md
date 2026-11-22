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
- New bridge commands need explicit approval before they are written. The read-only `files:` commands (`files:info`, `files:list`, `files:get`) were approved and added in core 1.6.1. They can read, never write.
- Core 1.6.2 adds the first two **write** commands, approved by Ray on Nov 22, 2026 ("make the changes on your own as long as the server itself doesn't need to be restarted"): `files:put` (replace one existing editable file, backup first) and `coreupload:put` (place a new core in `Updates/`). Both are core-only, so they install with a hot reload and never need a restart. See **Server write commands** below.
- The server files download is **read-only** on both sides: the bridge only opens files with read access, and ZAH never deletes anything on this PC.

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
| `features/server_files/` | Read-only download of the server's editable files (bridge client, worker thread, local folder rules) |
| `tests/` | Python checks, run with `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q`: download (`test_server_files.py`), downloaded-file lookups (`test_local_files.py`), validate/diff/save (`test_edit_tools.py`), and uploads, role gate, LIVE MODE and core upload against the local harness only (`test_server_writes.py`) |
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
| `ZeroGBridge/tests/ServerFilesTest/` | C# self-checks for `Network/ServerFiles.cs` (`dotnet run`), plus a `serve` mode used by the Python tests |
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
| `dashboard` | DASHBOARD | `features.dashboard.dashboard_page` | `DashboardPage` | Live players, uptime, cheat-flag alerts, bridge events; ANNOUNCE through the Safety Flow; SAVE and BACKUP not possible while the server runs |
| `chat` | CHAT | `features.chat.chat_page` | `ChatPage` | Live chat from `chat:recent` (core 1.6.3); SEND and WARN through the Safety Flow; watch words; MUTE and DISCORD not possible |
| `players` | PLAYERS | `features.players.players_page` | `PlayersPage` | Live list, detail and inventory (read-only); MESSAGE, WARP, KICK, BAN, SAVE & APPLY and loadouts through the Safety Flow; GOD MODE not possible from the server |
| `factions` | FACTIONS | `features.factions.factions_page` | `FactionsPage` | Read-only: factions, members, and alliances from the bridge; SET RELATION and RENAME not possible |
| `structures` | STRUCTURES | `features.structures.structures_page` | `StructuresPage` | Live list from `gents` with type filters; TELEPORT TO and DESTROY through the Safety Flow; SET FACTION not possible |
| `playfields` | PLAYFIELDS | `features.playfields.playfields_page` | `PlayfieldsPage` | Live summary and loaded-playfield cards; UNLOAD, RESTART PLAYFIELD, and WIPE on ticked cards (owner, Safety Flow); no star map (no coordinates) |
| `scheduler` | SCHEDULER | `features.scheduler.scheduler_page` | `SchedulerPage` | Layout only |
| `zerogbridge` | ZEROGBRIDGE | `features.zerogbridge.zerogbridge_page` | `ZeroGBridgePage` | Live connect and disconnect; portal button for admin and above |
| `settings` | SETTINGS | `features.settings.settings_page` | `SettingsPage` | Auto-connect is live; the read-only server files download is live, with CANCEL DOWNLOAD; LIVE MODE follows the role gate (see **Server uploads and LIVE MODE**) |
| `alerts` | ALERTS & ANTI-CHEAT | `features.alerts.alerts_page` | `AlertsPage` | Live queue from cheat flags and chat watch-word hits; ACK on this PC; PREVIEW BAN through the Safety Flow |
| `bans_audit` | BANS & AUDIT | `features.bans_audit.bans_audit_page` | `BansAuditPage` | Failed-login table is live (owner, or developer with key) |
| `users` | USERS | `features.users.users_page` | `UsersPage` | Live add, edit, and remove through the login service; Live file editing checkbox for owners and the developer (`/users/live_files`, needs the updated service and the column) |
| `ecf_editor` | ECF EDITOR | `features.ecf_editor.ecf_editor_page` | `EcfEditorPage` | Lists and opens every `.ecf` from the downloaded server files (`load_server_files`); DOWNLOAD FOLDER runs the read-only download and refills the list; empty state when nothing is downloaded |
| `pda_editor` | PDA EDITOR | `features.pda_editor.pda_editor_page` | `PdaEditorPage` | Lists and opens the downloaded PDA `.yaml` / `.csv` files, chapters with English names; DOWNLOAD FOLDER as in the ECF Editor; empty state when nothing is downloaded |
| `backups` | BACKUPS | `features.backups.backups_page` | `BackupsPage` | Layout; PREVIEW and RESTORE locked with the reason (no bridge backup command; a restore needs the server stopped) |
| `bp_editor` | BP EDITOR | `features.bp_editor.bp_editor_page` | `LibraryPage` (blueprints tab) | Layout; blueprint data is not loaded yet |
| `items` | ITEMS | `features.items.items_page` | `LibraryPage` (items tab) | Reads items from the downloaded server files on opening (`load_server_files`), with item pictures; GIVE ITEM to an online player (Safety Flow); ADD TO TEMPLATE on this PC; empty state when nothing is downloaded |
| `servers` | SERVERS | `features.multi_server.multi_server_page` | `MultiServerPage` | Live cards for every saved server (read-only poll), cross-server alerts, BROADCAST and BROADCAST TO ALL SERVERS (Safety Flow), OPEN DASHBOARD; shown when two or more saved servers answer |

Supporting modules (not nav pages):

| Module | Role |
| --- | --- |
| `features/dashboard/main_cockpit.py` | Main window shell: header, nav, content stack, status bar, bridge pipe, auto-reconnect, keepalive, server monitor, logout |
| `features/loading/loading_screen.py` | Boot dialog and login gate |
| `features/bridge/command_pipe.py` | Background thread that logs in and sends queued commands |
| `features/bridge/bridge_connection.py` | Socket helpers and line protocol |
| `features/bridge/server_settings.py` | Reads the active profile from `data/server_config.json`; `set_active_index` switches the active server (only `active_index` changes) |
| `features/shared/ecf_parser.py` | Read-only ECF parse, Ref merge, and CSV name lookup |
| `features/shared/server_actions.py` | Read-only bridge reads, the ZAH Safety Flow, the action role table, and the audit log |
| `features/shared/loadouts.py` | Loadout templates in `data/loadout_templates.json` |
| `features/library/item_library.py` | Builds the item list from `ItemsConfig.ecf` and `Localization.csv` |
| `features/library/item_tiles.py` | Hex tiles and the wrapping tile flow area |
| `features/library/item_stats_dialog.py` | Full stats window for one item |
| `features/zgb_portal/` | Portal window used from the ZeroGBridge page |
| `features/server_files/file_client.py` | Own short bridge session and the `files:` request helper (`ServerFilesSession`) |
| `features/server_files/download_worker.py` | `ServerFileDownloadWorker` thread: list, compare, download, verify |
| `features/server_files/file_store.py` | Local folder layout, safe local paths, manifest, time text |
| `features/server_files/local_files.py` | Finds the downloaded scenario folder, files in it (save copy wins), and item pictures |
| `features/server_files/edit_store.py` | Edited copies, backups, line endings, and upload base hashes |
| `features/shared/edit_tools.py` | Validation and diffs |
| `features/shared/editor_actions.py` | Shared VALIDATE, CHANGES PREVIEW, SAVE, and UPLOAD TO SERVER actions |
| `features/server_files/upload_flow.py` | The three upload confirmations, the role gate helpers, and the online-player count |
| `features/server_files/write_worker.py` | `files:put`, `coreupload:put`, and single-file `files:get` steps, run in `ServerWriteWorker` |
| `features/multi_server/server_monitor.py` | `ServerMonitor`: read-only poll of every saved server every 30 s (`hot:status`, `plys`, `api:Request_Dedi_Stats`) |
| `features/chat/chat_store.py` | Chat history in memory (from `chat:recent`) and watch words in `data/chat_watch_words.json`; shared by Chat and Alerts |

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
| Portal live Browse (core upload) | no | no | no | yes |
| UPLOAD TO SERVER in the editors | only with granted permission | only with granted permission | yes | yes |
| See Users page and manage users | no (page refuses) | moderators only, own server | own server, any of those three roles | any server, any of those three roles |
| Failed login log on Bans & Audit | no | no | yes (session token) | yes (developer key, fail closed if missing) |
| LIVE MODE toggle | only with granted permission | only with granted permission | always | always |
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
| POST | `/users/live_files` | owner token (own server's users), or developer key; admins 403 | Turn Live file editing on or off: `{"username", "enabled": true/false}`. 404 unknown user, 400 when `enabled` is not true/false, 409 when the column is missing (nothing changed) |

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

(Nov 22, 2026: the checkbox is wired for owners and the developer. It sends `/users/live_files` after the user is saved, only when the box changed. `user_store.set_live_file_editing` looks the column up in `information_schema.columns` first and saves nothing when it is missing, so the route answers 409 and ZAH shows "Not changed". `/users` adds each user's `live_file_editing` flag for owners and the developer. Admins see the box greyed out. Ray deploys the updated login service and adds the column with the SQL below.)

The login service already reads it, fail closed: `user_store.get_live_file_editing(username)` returns True only when the `live_file_editing` column exists and is TRUE for that user. A missing column, no database, or any error gives False. `/login` and `/session` send it back as `live_file_editing`. The column itself is added by Ray (ZAH never changes the database):

```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS live_file_editing BOOLEAN NOT NULL DEFAULT FALSE;
```

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

## Downloaded Server Files as the Data Source

The Library and both editors read only `data/server_files/<scenario>/`, the folder the Settings download made. They never read the local base game.

- **Which scenario:** `local_files.current_scenario_folder()` uses `server_files_local_folder` from `app_settings` when it is a folder directly inside `data/server_files` with a manifest. Otherwise it takes the newest such folder. No folder means the empty state. The scenario name is whatever `files:info` reported, so nothing is hard-coded.
- **Which copy:** a path that exists in both `save/` and `scenario/` is read from `save/`, because the running game uses the save's copy. `ItemsConfig.ecf` and `Localization.csv` are looked up separately, so one can come from the save and the other from the scenario.
- **Empty state:** every page shows `No server files yet. Use Settings > DOWNLOAD SERVER FILES.`

### Editor validation and local saves

The ECF and PDA editors use `features/shared/editor_actions.py`. VALIDATE checks the current text and reports line numbers. ECF validation catches unclosed blocks, unexpected closing braces, unclosed quotes, and lines outside blocks. YAML validation catches tab indents and parse errors. CSV validation checks parsing and extra columns.

CHANGES PREVIEW is a unified diff from the downloaded copy to the editor text. SAVE writes only `data/server_files/<scenario>/_edits/<root>/<path>`. Before overwriting an edit, it creates a timestamped backup under `_backups/`. The first save backs up the downloaded copy. Writes use a `.part` file and `os.replace`. The downloaded copy is kept for diffing. Line endings follow the downloaded file. `_edits/_bases.json` stores the hash of the downloaded copy an edit started from, for the later upload check.

### Server uploads and LIVE MODE

UPLOAD TO SERVER (ECF and PDA editors) is on only when all of these are true: a downloaded server file is open, the cockpit says the bridge is connected, and `MainCockpit.can_edit_live_files()` says yes. That is `roles.can_edit_live_files(role, flag)`: owner and developer always; admin and moderator only when the login reply had `live_file_editing` exactly True. Otherwise the button is off and its tooltip says why. The same checks run again right before the send.

The upload refuses text that VALIDATE finds errors in, and text with no changes. Then it asks three times (`upload_flow.py`), and any No stops it with nothing sent:

1. **Changes**: the diff, with Continue (Cancel is the default).
2. **Players**: a fresh read-only `plys` count. Any online player gives a warning with their names. If the count cannot be read, the upload stops.
3. **Type the name**: the exact file name must be typed.

After that the edit is saved locally (backup first), and `ServerWriteWorker` sends `files:put` in 120 KB pieces with `base_sha256` from `_bases.json`. On success `edit_store.record_upload` backs up the old downloaded copy, replaces it with the uploaded bytes, updates the base, and marks the manifest so the next download fetches it again. On `changed_on_server` nothing is replaced and the editor says to download again.

LIVE MODE (Settings) is a tick on the cockpit (`MainCockpit.live_mode`). It is never saved and is reset at every sign-in. It is enabled only for the same role gate with the bridge connected, and turning it on asks first (No is the default). While it is on, opening a file reads the server's current copy with `files:get` (a newer one replaces the download, backup first), the bottom line says `LIVE MODE - SAVE also uploads to the server`, and SAVE is followed by the same three-step upload.

The portal's Browse button on live data uploads a new core (developer only, bridge online). It takes only a file named `ZeroGBridge.Core.dll` that starts with `MZ`, shows size, sha256 and the players line in a confirmation, sends the `.pdb` next to it first and then the dll with `coreupload:put`, and then opens the normal Reload now confirmation. Nothing loads until that is confirmed.

## Settings

`features/settings/app_settings.py` reads and writes `data/app_settings.json`. Only known keys with the default value's type are kept, so an older file still loads.

| Key | Default | Meaning |
| --- | --- | --- |
| `bridge_auto_connect` | `False` | When true, `MainCockpit` starts `CommandPipe` at launch |
| `server_files_last_pulled` | `""` | When the last complete download finished (ISO text with time zone). Empty means never |
| `server_files_local_folder` | `""` | Local folder of the last download. Empty means none yet |

LIVE MODE is **not** a saved setting. The switch always starts off when ZAH opens, and it is not written to the settings file.

The Settings page also has a **SERVER FILES** section:

- Status lines: `LOCAL COPY` and `LAST PULLED`. Both start from the two saved keys above.
- Button: `DOWNLOAD SERVER FILES (READ-ONLY)`. See **Server files download** below. It is enabled only while `MainCockpit.bridge_connected` is true. The page listens to `bridge_status_changed` (connected in `showEvent`), so the button follows the connection live. With no news from the cockpit it stays disabled (fail closed).
- While a download runs: the button reads `DOWNLOADING` and is disabled, a thin progress bar (`SettingsProgressBar`) and a status line show `Downloading 412 of 906 files`.
- Checkbox: `LIVE MODE: edit files directly on the server`. Layout only: always off and disabled, tooltip `Coming in a later step.`
- Note: every live save will ask three times (changes preview, online-players warning, then typing the file name), and the bridge will back up the old file first.

### Server files download

Flow, run by `ServerFileDownloadWorker` (a `QThread`, so the window never freezes):

1. Open a **separate** short bridge session with the active server profile (`ServerFilesSession`). It is not the dashboard's telemetry socket, so replies never get mixed up.
2. `files:info`. The reply must have `protocol` 1 and a `scenario` name. An old bridge answers with its generic `RESPONSE` or an `ERROR` line, and ZAH stops with: `This server's ZeroGBridge does not have the file commands yet. Ask the owner to update the bridge.` Nothing is written locally in that case.
3. `files:list` for each available root (`scenario`, `save`), page by page.
4. Compare with the local manifest. A file is skipped when its size and modified time match the manifest and the local file still has that size.
5. `files:get` in batches of 40 items. Files that do not fit the reply come back `deferred` and are asked for again. A big file arrives in chunks; ZAH asks for the next chunk with the next `offset`.
6. Every chunk is appended to `<name>.part`. At `eof`, the byte count must equal the reported size, then the file is moved into place with `os.replace`. A file that changes on the server mid-copy is restarted (at most 2 times).
7. The manifest is saved, even after a failure, so a retry only fetches what is missing.

Local folder (under `data/server_files/`, which is git-ignored):

| Path | Content |
| --- | --- |
| `data/server_files/<scenario>/scenario/<server path>` | Files from the active scenario, same relative paths as on the server |
| `data/server_files/<scenario>/save/<server path>` | Files from the current save game |
| `data/server_files/<scenario>/_manifest.json` | `files` map of `"<root>/<path>"` to `{size, mtime}` |

Local safety rules (`file_store.local_target_path`): the scenario name is cleaned into a safe folder name (`safe_folder_name`). A server path is refused when it is empty, absolute, has a drive letter or `:`, has `..`, `.` or an empty part, has control characters, or would land outside the download folder. Only ZAH's own `.part` files are ever removed. Old local copies of files that no longer exist on the server are left alone.

After a run: `LOCAL COPY` is always updated; `LAST PULLED` is updated only when no file failed. A run with failures says so in the status line and lists the files in the terminal.

Message table:

| Situation | Text shown |
| --- | --- |
| Old bridge (no `files:`) | `Download failed: This server's ZeroGBridge does not have the file commands yet. Ask the owner to update the bridge.` |
| Wrong bridge password | `Download failed: The server rejected the bridge login.` |
| Server not reachable | `Download failed: Could not reach the server (<error type>).` |
| No server profile saved | `Download failed: No active server is saved in ZAH.` |
| Scenario or save folder not known yet | `Download failed: The server has not reported its active scenario yet. Try again in a minute.` |
| Some files refused | `Finished, but the server would not send N file(s). LAST PULLED was not updated. Details are in the terminal.` |

The bridge password is only written to the socket. It is never printed, logged, or included in any message.

## ZeroGBridge Commands

### Process layout

Empyrion loads `ZeroGBridge.Loader.ZeroGBridgeLoader`, which implements **API v2** `Eleon.Modding.IMod` (`Init`, `Shutdown`) and also the legacy `ModInterface` so the host can load it. The loader is small and stable:

- It owns the TCP listener and authentication (`BridgeListener`, `AuthConfig`).
- It hosts `CoreHost`, which loads the reloadable core (`ZeroGBridge.Core.dll`) in its own AppDomain.
- Game-state work is marshalled onto the **game thread** (`GameThread`, `GameGateway`), never executed on the network thread.
- Loader release is **1.5.0**. A loader change needs a server restart. Core release is **1.6.3** (`Request_*` API, console proxy, command catalog, restart through `saveandexit`, read-only `files:` commands, the 1.6.2 write commands `files:put` and `coreupload:`, and the 1.6.3 read-only chat history `chat:recent`). Core changes are installed with `coreupload:put` and `hot:reload`, never a restart.

The auth token is read from `ZeroGBridge.json` only and is never written into log lines.

### Wire format

- Each command is a **single line** ending in `\r\n`.
- Each reply is a **single JSON line**, also ending in `\r\n`.
- ZAH's `CommandPipe` waits **0.5 seconds** between outgoing commands (`INPUT_DELAY_SEC`).
- Login is `auth:<token>`. A good reply has `"type": "AUTH"` and `"status": "Authenticated"`. The token is sent on the wire and is never printed by ZAH.
- `cmds`, `help:commands`, and `api:list` return a `COMMAND_CATALOG` JSON object: Eleon requests, console commands, and ZAH shortcuts.
- File content is sent as **base64 text** inside the JSON line, so a reply is still one line with no embedded newlines and no byte-order mark.

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
| `touchstruct:` | `touch:` | Log line only: replies `Success` but sends nothing to the game | no (stub) |
| `destroystruct:` | `destroyentity:`, `wipe:` | Log line only: replies `Success` but destroys nothing | no (stub) |
| `broadcast:` | `say:`, `alert:` | Log line only: replies `Sent` but shows nothing in game | no (stub) |
| `msg:` | `msgplayer:` | Log line only: replies `Sent` but shows nothing in game | no (stub) |
| `msgfaction:` | `factionmsg:` | Log line only: replies `Sent` but shows nothing in game | no (stub) |
| `getcredits:` | `credits:` | Stub: always replies `credits: 0` | no (stub) |
| `addcredits:` | `setcredits:` | Log line only: replies `Success` but changes nothing | no (stub) |
| `getinv:` | `getinventory:` | Stub: always an empty `items` list (use `api:Request_Player_GetInventory`) | no (stub) |
| `getplayfields` | `pfs`, `playfields`, plus `:all` | Playfield list | no |
| `pfstats:` | `playfieldstats:` | Stub: always an empty `stats` box (use `api:Request_Playfield_Stats`) | no (stub) |
| `pfents:` | `playfieldentities:` | Stub: always an empty `entities` list (use `gents:<playfield>` or `api:Request_Playfield_Entity_List`) | no (stub) |
| `loadpf:` | `loadplayfield:` | Load a playfield | yes |
| `api:<RequestName>` | short names from the catalog | Eleon request, optional JSON params | depends on the request |
| `con:<line>` | `cmd:`, `exec:` | Dedicated console command | depends on the line |
| `files:info` | | Read-only: which roots exist, scenario and save names, limits | no |
| `files:list:<json>` | | Read-only: paths, sizes and times of the editable files in a root | no |
| `files:get:<json>` | | Read-only: file bytes as base64, in chunks | no |
| `files:put:<json>` | | 1.6.2: replace one existing editable file, backup first, in chunks | yes |
| `coreupload:status` | | 1.6.2: what core files wait in `Updates/` (size, sha256) | no |
| `coreupload:put:<json>` | | 1.6.2: place a new `ZeroGBridge.Core.dll` / `.pdb` in `Updates/`, in chunks | yes (loads only on `hot:reload`) |
| `chat:recent` | `chat:recent:{"since":N,"max":M}` | 1.6.3: read-only chat history kept in memory (see **Chat history** below) | no |

The stub rows are left from early bridge stages. ZAH never uses them: it sends the real Eleon requests instead (`api:Request_InGameMessage_SinglePlayer`, `_Faction`, `_AllPlayers`, `api:Request_Entity_Destroy`, `api:Request_Structure_Touch`), through `server_actions.api_command`.

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

### Server file commands (`files:`)

Core 1.6.1, `ZeroGBridge/Network/ServerFiles.cs`. Core-only: it needs a hot reload, not a loader change or a server restart. Handled at the top of `CommandDispatcher.ProcessCommand`, before the trace log line, because a download sends many commands. They are read-only and only reachable after `auth:`, like every command. Reply type is always `FILES`.

Requests (one line each, JSON after the second colon):

```text
files:info
files:list:{"root":"scenario","offset":0,"limit":1000,"req_id":"a1"}
files:get:{"root":"scenario","items":[{"path":"Content/Configuration/Items.ecf","offset":0}],"req_id":"a2"}
```

| Field | Meaning |
| --- | --- |
| `root` | `scenario` (the active scenario folder) or `save` (the current save game folder) |
| `offset`, `limit` (list) | Paging. `limit` is 1 to 2000, default 1000 |
| `items` (get) | 1 to 50 objects, each with `path` and an optional `offset` (byte position, default 0) |
| `req_id` | Optional. A string or number, echoed back as a string |

Replies:

| Command | Success reply fields |
| --- | --- |
| `files:info` | `ok`, `protocol` (1), `readOnly`, `source`, `scenario`, `saveName`, `roots` (per root: `root`, `available`, `name`, `topFolders`, `allowedFolders`), `limits`, `extensions` |
| `files:list` | `ok`, `root`, `total`, `offset`, `count`, `next` (number, or null on the last page), `files` (each `{path, size, mtime}`, sorted by path, `mtime` is ISO 8601 UTC) |
| `files:get` | `ok`, `root`, `files`. Each entry is `{path, size, mtime, offset, length, eof, data}` (base64), or `{path, deferred: true}`, or `{path, error}` |

Failure reply: `{"type":"FILES","cmd":"<name>","ok":false,"error":"<code>","message":"<text>"}` with codes `bad_request`, `unknown_root`, `root_unavailable`, `too_many_items`, `unknown_command`, `exception`. A per-item `error` is one of `bad_path`, `not_allowed`, `not_found`, `too_large`, `read_failed`.

Limits: one `files:get` reply carries at most **192 KB** of raw bytes (about 256 KB of text). Items past that budget come back `deferred`. A single file over the budget arrives in pieces. A file over **16 MB** is refused. A list scan stops at 50,000 files per root and 12 folder levels. The first list page (`offset` 0) always rescans the folders; later pages reuse that scan for up to 60 seconds so paging stays consistent.

Where the roots come from: `IApplication.GetPathFor(AppFolder.ActiveScenario)` and `AppFolder.SaveGame`, read on the **game thread** from `ModMain.OnApplicationUpdate` (at most every 30 seconds) and kept in memory. If the game gives no folder, `dedicated.yaml` in the server's working folder is used: only `CustomScenario` and `GameName` are read, and only plain folder names are accepted. Command handlers only read the saved values.

Safety checks, in order (`NormalizeRelativePath`, `ResolveUnderRoot`):

1. Root name must be `scenario` or `save`.
2. The path text is refused when empty, longer than 260, absolute, has a drive letter or `:` (this also blocks NTFS streams), `*`, `?`, quotes, `<`, `>`, `|`, control characters, an empty or `.` or `..` segment, a segment starting or ending with a space or ending with a dot, or a Windows device name (`CON`, `NUL`, `COM1` and similar).
3. File type must be on the list: `.ecf .yaml .yml .csv .jpg .jpeg .png`. Databases, `.json`, `.dll`, `.key` and everything else are unreachable.
4. The first folder must be on the root's whitelist (whole folder names only), or the file must sit directly in the root. Scenario: `Content`, `SharedData/Content`. Save: `Content`, `Shared/Content`, `SharedData/Content`. The lists are the `AllowedFolders` table in `ServerFiles.cs`.
5. The resolved full path must still start with the root folder.
6. Neither the file nor any folder on the way may be a symlink or junction. The folder scan skips them too.
7. Files open with `FileAccess.Read` and `FileShare.ReadWrite` only, so the running game is never blocked and nothing can be written.
8. The auth token is never read in this code. The dispatcher still refuses any command line that contains the token, and removes it from any reply.

Checks: `ZeroGBridge/tests/ServerFilesTest` (run `dotnet run` in that folder) compiles the real `ServerFiles.cs` and runs 65 checks: listing, paging, chunk reassembly byte for byte, the batch budget, every refused path shape, symlinks, and reading while another handle has the file open for writing.

### Server write commands (`files:put`, `coreupload:`)

Core 1.6.2, `ZeroGBridge/Network/ServerFileWrites.cs`. Core-only (hot reload, no restart). `files:put` is routed from `ServerFiles.Handle`; `coreupload:` is routed in `CommandDispatcher.ProcessCommand` right after `files:`, before the trace line, because an upload is several large lines. The loader owns every `hot:` line, so a `hot:upload` name would need a loader change and a restart; the core uses its own `coreupload:` prefix instead.

```text
files:put:{"root":"scenario","path":"Content/Configuration/ItemsConfig.ecf","offset":0,"total":525000,"sha256":"<new file>","base_sha256":"<downloaded copy>","data":"<base64>","req_id":"w1"}
coreupload:status
coreupload:put:{"file":"pdb","offset":0,"total":49660,"sha256":"<file>","data":"<base64>","req_id":"c1"}
coreupload:put:{"file":"dll","offset":0,"total":290304,"sha256":"<file>","data":"<base64>","req_id":"c2"}
```

How a chunked upload works:

1. `offset` 0 starts (or restarts) the upload. Each next chunk must start where the last one ended; otherwise the reply is `bad_offset` with `expected_offset`.
2. A chunk holds at most **128 KB** of raw bytes. A file is at most **16 MB** (`files:put`) or **8 MB** (`coreupload:`).
3. Chunks go into the bridge's own `Uploads/` folder (next to `ZeroGBridge.json`), never into a game folder.
4. When `total` bytes have arrived, the staged file must match `sha256`, or nothing is replaced (`hash_mismatch`).
5. The old file is copied to `Backups/files/<root>/<path>.<yyyyMMdd-HHmmss>.bak` (or `Backups/core/`) **before** anything is replaced. The bridge never deletes a backup.
6. The new file is copied next to the target as `<name>.zgbput.tmp` and swapped in with `File.Replace` in one step, so the game never sees a half-written file.

Reply while chunks are arriving: `{"type":"FILES","cmd":"put","ok":true,"done":false,"received":N,"total":T,"next_offset":N}`. Final reply: `done:true`, `size`, `sha256`, `backup` (path relative to the mod folder). `coreupload` also returns `assemblyVersion` and `pendingDrop`.

Extra rules for `files:put`:

- Same path checks as `files:get` (roots, whitelisted folders, no `..`, no symlinks, must stay under the root).
- Only `.ecf .yaml .yml .csv`. No pictures, and never `.json`, `.dll`, `.key`, `.db` or the token file.
- Only an **existing** file can be replaced; new files are refused (`not_found`).
- `base_sha256` must equal the hash of the file on the server now (checked at the first chunk and again just before the swap). If someone changed it since the download, the reply is `changed_on_server` with `current_sha256`, and nothing is written.

Extra rules for `coreupload:`:

- Only two fixed names can be written: `Updates/ZeroGBridge.Core.dll` and `Updates/ZeroGBridge.Core.pdb`.
- The DLL must start with `MZ` and read as a .NET assembly named `ZeroGBridge.Core` (read with `AssemblyName.GetAssemblyName`, never loaded), or the reply is `bad_core`.
- Send the `.pdb` first, then the `.dll`. The loader takes the pdb next to the dll when it imports it.
- Nothing loads until `hot:reload` (unless `AutoReloadOnDrop` is turned on in `ZeroGBridge.json`; it is off). The loader still runs its own start-up check and keeps the old core if the new one fails.

Kill switch: `"FileWritesEnabled": false` in `ZeroGBridge.json` turns both commands off at once (`writes_disabled`). It is read on every call, so it works without a restart. Missing means on. `files:info` now also returns `writeProtocol` (1) and `canWrite`.

Error codes: `writes_disabled`, `not_ready` (mod folder unknown), `bad_request`, `unknown_root`, `root_unavailable`, `bad_path`, `not_allowed`, `not_found`, `too_large`, `bad_offset`, `hash_mismatch`, `changed_on_server`, `bad_core`, `write_failed`, `exception`.

Checks: the same `ServerFilesTest` program also compiles `ServerFileWrites.cs` (103 checks in total): kill switch, not-ready, a chunked put with its backup, a second put keeping both backups, stale base hash, hash mismatch, new file, `.png`, `.json`, traversal, symlink, out-of-order chunk, size caps, the save root, a non-DLL and a wrong DLL refused, and the real Release core uploaded byte for byte with its version read back. The `serve` mode answers `coreupload:` too; set `ZGB_TEST_MODDIR` to a test folder for the write commands.

### Chat history (`chat:recent`)

Core 1.6.3, `ZeroGBridge/Network/ChatLog.cs`. Core-only (hot reload, no restart). `ModMain` hooks API v2 `Application.ChatMessageSent` and passes each `MessageData` to `ChatLog.Add`. The log is memory only: the newest 500 lines (`MaxKept`), lost on a reload. Routed in `CommandDispatcher.ProcessCommand` after `coreupload:`, before the trace line, because ZAH polls it every few seconds.

- `chat:recent` returns the newest 200 (`DefaultMax`). `chat:recent:{"since":N,"max":M}` returns lines with `seq` above N, at most M.
- Reply: `{"type":"CHAT_LOG","ok":true,"count":C,"last_seq":S,"kept":500,"messages":[{"seq","time","channel","senderType","senderId","senderName","senderFactionId","recipientId","recipientFactionId","text"}]}`. `time` is UTC; `channel` is `Global`, `Faction`, `Alliance`, `SinglePlayer`, or `Server`.
- Any other `chat:` word returns `ERROR` `unknown_command`; bad JSON returns `bad_json`.
- `seq` restarts at 1 after a reload. ZAH notices a `last_seq` below its own and starts over.
- Sending chat does not use this command. It uses the existing `con:say`, `api:Request_InGameMessage_Faction` and `api:Request_InGameMessage_SinglePlayer`.
- Harness only: `harness:chat|<channel>|<senderId>|<text>` adds a line in the test harness serve mode.

### Bridge auto-reconnect and multi-server

- **Auto-reconnect** (`MainCockpit`): when a connection that was up drops on its own, the cockpit tries again after 5, 10, 20, 40, then every 60 seconds. The status bar says `ZEROGBRIDGE RECONNECTING IN Ns`. A disconnect asked for by the user (ZeroGBridge page, server switch, logout, closing ZAH) sets `bridge_user_stopped` and is never retried. A successful login resets the count.
- **Keepalive**: every 30 s while connected, the cockpit queues one read-only `plys` when the pipe is idle. A dead connection then shows up as a drop within about 30 s. Keepalive replies are not logged.
- **Server monitor**: while the main bridge is connected, `ServerMonitor` reads every saved server in `data/server_config.json` every 30 s on its own short connections: `hot:status` (core release), `plys` (players, cheat flags), and `api:Request_Dedi_Stats` (fps, memory, uptime). All read-only. The SERVERS nav button shows when two or more answer.
- **OPEN DASHBOARD** calls `switch_server`: `set_active_index` writes only `active_index` in `data/server_config.json` (a local file on the PC, not a server change), then the cockpit disconnects and connects to that server.
- **BROADCAST TO ALL SERVERS**: one Safety Flow, then `api:Request_InGameMessage_AllPlayers` to each answering server in turn (`run_server_action(..., profiles=[...])`). Each server gets its own audit line; one failing does not stop the others. A server on an older core without that request answers `ERROR`, which is shown as failed.

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
def set_active_index(server_index)              # True when saved; .part file then os.replace

class CommandPipe(QThread):
    connection_changed = pyqtSignal(str, bool)
    reply_received = pyqtSignal(str, str)
    command_dispatched = pyqtSignal(str)
    queue_empty = pyqtSignal()
    def __init__(self, input_delay_sec=INPUT_DELAY_SEC, parent=None)
    def enqueue_command(self, command_str)
    def stop(self)
    def run(self)

# features/dashboard/main_cockpit.py (Auto-Reconnect and Server Monitor region)
RECONNECT_DELAYS_SEC = [5, 10, 20, 40, 60]       # the last value repeats
KEEPALIVE_SEC = 30
def _after_status_change(self, is_connected)
def _schedule_reconnect(self)
def _cancel_reconnect(self)
def _try_reconnect(self)
def _send_keepalive(self)                       # queues one read-only plys
def _start_server_monitor(self)
def _on_servers_updated(self, results)          # SERVERS nav shows at 2+ answering servers
def switch_server(self, server_index)           # OPEN DASHBOARD

# features/multi_server/server_monitor.py
POLL_SEC = 30
def poll_server(profile) -> dict                # name, profile, online, core, players_online, players_total, fps, mem, uptime, flagged
def poll_all() -> list
class ServerMonitor(QObject):
    servers_updated = pyqtSignal(list)
    def start(self)
    def stop(self)
    def poll_now(self)
    def online_count(self)
```

Profile fields used from `data/server_config.json` include the display name, the host address, and the bridge port. The auth token is read from the same profile and is never printed. `active_index` selects the current profile. A blank bridge port uses the built-in default from `server_settings.py`.

### Server files

```python
## features/server_files/file_client.py
class ServerFilesError(Exception):
    kind   # config, offline, auth, timeout, closed, unsupported, protocol, refused
class ServerFilesSession:
    def __init__(self, profile)
    def request(self, sub_command, payload=None, prefix="files")   # returns the FILES reply dictionary
    # ServerFilesError.code holds the bridge error, e.g. changed_on_server
    def open(self)
    def close(self)

## features/server_files/download_worker.py
class ServerFileDownloadWorker(QThread):
    progress = pyqtSignal(int, int, str)     # done, total, status text
    finished_ok = pyqtSignal(dict)           # scenario, save, folder, listed, downloaded, skipped, failed, bytes
    failed = pyqtSignal(str)                 # one plain message
    def __init__(self, profile_provider=None, parent=None)
    def request_stop(self)
    def run(self)

## features/server_files/file_store.py
def safe_folder_name(name)
def scenario_folder(scenario_name)
def local_target_path(base_folder, relative_path)   # None when unsafe
def load_manifest(folder)
def save_manifest(folder, manifest)
def now_iso()
def format_last_pulled(iso_text)

## features/server_files/local_files.py
NO_FILES_TEXT = "No server files yet. Use Settings > DOWNLOAD SERVER FILES."
def current_scenario_folder()                   # None when nothing is downloaded
def scenario_label(folder)
def find_file(folder, parts)                    # (root, full path), save first, or (None, None)
def list_files(folder, extensions, under=None)  # [{root, path, full, label}]
def build_image_index(folder)                   # {lower item name: picture path}
def find_item_image(folder, item_name, image_index=None)

## features/server_files/write_worker.py
CHUNK_BYTES = 120 * 1024
def put_file(session, root, path, data, base_sha256, report=None)   # final files:put reply
def upload_core(session, dll_path, report=None)                     # pdb first, then dll
def fetch_file(session, root, path)                                 # bytes
class ServerWriteWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str, str, str)       # kind, bridge code, message
    def __init__(self, job, profile_provider=None, parent=None)
def start_write_worker(worker)

## features/server_files/upload_flow.py
def user_can_write_server_files(widget)   # cockpit can_edit_live_files(), False when not found
def bridge_is_connected(widget)
def live_mode_on(widget)
def count_online(players_payload)         # (count, names) or (None, [])
def fetch_players_for_upload()
def ask_changes(parent, file_name, diff_lines)
def ask_players(parent, online_count, names)
def ask_type_name(parent, file_name)
```

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
def set_live_files(session_token, username, enabled, dev_key=None)   # /users/live_files

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
def get_live_file_editing(username)            # False unless the column exists and is TRUE
def set_live_file_editing(username, enabled)   # True saved, False no user, None not possible (no DB / no column)
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

public static class ServerFiles
{
    public const string Prefix = "files:";
    public const int ProtocolVersion = 1;
    public const long MaxFileBytes = 16L * 1024 * 1024;
    public const int ReplyBudgetBytes = 192 * 1024;
    public const int MaxItemsPerGet = 50;
    public static bool IsFilesLine(string lower);
    public static string Handle(string line);                 // files:info, files:list, files:get
    public static void RefreshRoots(IModApi api);             // game thread, throttled
    public static string NormalizeRelativePath(string rootName, string requested, out string error);
    public static string ResolveUnderRoot(string rootFull, string normalizedRelative, out string error);
    internal static string RootFolderForWrite(string rootName);   // 1.6.2, used by ServerFileWrites
}

public static class ServerFileWrites                          // 1.6.2
{
    public const string CoreUploadPrefix = "coreupload:";
    public const int WriteProtocolVersion = 1;
    public const int MaxChunkBytes = 128 * 1024;
    public const long MaxCoreBytes = 8L * 1024 * 1024;
    public const string CoreFileName = "ZeroGBridge.Core.dll";
    public static string ModDirectory;                        // set by CoreEntry.Start
    public static bool WritesEnabled { get; }                 // ZeroGBridge.json FileWritesEnabled, default true
    public static bool IsCoreUploadLine(string lower);
    public static string HandlePut(JObject request, string reqId);     // files:put
    public static string HandleCoreUpload(string line);                // coreupload:status, coreupload:put
    public static string HashFile(string path);                        // sha256, lower-case hex
}

public static class ChatLog                                     // 1.6.3
{
    public const string Prefix = "chat:";
    public const int MaxKept = 500;
    public const int DefaultMax = 200;
    public static bool IsChatLine(string lowerCmd);
    public static void Add(string channel, string senderType, int senderId, string senderName, int senderFactionId, int recipientId, int recipientFactionId, string text);
    public static string Handle(string cleanCmd);                       // chat:recent[:json] -> CHAT_LOG
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

## Live Pages and the Safety Flow

Pages talk to the bridge through `features/shared/server_actions.py`, one short session per command (`live_client.bridge_request`, which now also accepts a tuple of reply types so an `ERROR` comes back at once).

- **Read-only** (`read_bridge`): lists, stats and inventories. No confirmation. Runs on Qt's thread pool.
- **Server-changing** (`run_server_action`): the ZAH Safety Flow.
  1. Role check from `ACTION_ROLES` (an action missing from the table is refused) and a connected bridge.
  2. Command preview: the exact line that will be sent.
  3. `CONFIRM` typed by hand.
  4. A 15 second countdown (`SAFETY_DELAY_SEC`) with CANCEL.
  5. The role is checked again, the command is sent, and one line is added to `data/audit/server_actions.jsonl` (time, user, role, server, action, command, ok, detail). A cancel is audited too.
- A list of commands (a loadout, or several playfields) is sent one by one, `gap_sec` apart (0.5 s by default, 20 s for RESTART PLAYFIELD); the first refusal stops the rest.
- Tests replace `SEND_FUNCTION` and `ask_safety_flow`, so no test reaches a server.

Action roles:

| Action | Lowest role |
| --- | --- |
| Private message, kick, chat send, chat warn, announce | moderator |
| Ban, unban, warp, inventory, loadout, give item, structure teleport, structure destroy, broadcast to all servers, ban from an alert | admin |
| Playfield unload, restart, wipe | owner |

Page wiring:

| Page | Control | Bridge command | Changes the server |
| --- | --- | --- | --- |
| Players | PLAYER LIST | `plys` (every 15 s while open) | no |
| Players | PLAYER DETAIL bars | `api:Request_Player_Info {"id":N}` | no |
| Players | INVENTORY | `api:Request_Player_GetInventory {"id":N}` | no |
| Players | MESSAGE | `api:Request_InGameMessage_SinglePlayer {"id":N,"msg":"..."}` | yes |
| Players | WARP | `api:Request_Entity_Teleport` (same playfield) or `api:Request_Entity_ChangePlayfield` | yes |
| Players | KICK | `con:kick <entityId> '<reason>'` | yes |
| Players | BAN | `con:ban <entityId> <1h\|1d\|7d\|30d\|1y>` | yes |
| Players | SAVE & APPLY | `api:Request_Player_SetInventory` (counts edited in the table; 0 removes a stack) | yes |
| Players | RESET | none (puts the read counts back) | no |
| Players | STARTER / EXPLORER / BUILDER | one `api:Request_Player_AddItem` per template item | yes |
| Players | GOD MODE | none: the game's `godmode` only works in a player's own console | stays disabled |
| Dashboard | PLAYERS, ONLINE PLAYERS | `plys` (every 15 s while open) | no |
| Dashboard | UPTIME | `api:Request_Dedi_Stats` (`data.uptime`, seconds) | no |
| Dashboard | ACTIVE ALERTS, NEEDS ATTENTION, SETTINGS badge | `plys` fields `cheat` and `cheater` | no |
| Dashboard | ANNOUNCE | `api:Request_InGameMessage_AllPlayers {"msg":"..."}` (HUD message to everyone) | yes |
| Dashboard | SAVE | none: Empyrion has no save-only command; `saveandexit` stops the server | stays disabled |
| Dashboard | BACKUP | none: a consistent backup needs the server stopped | stays disabled |
| Chat | GLOBAL / FACTION / PRIVATE lists | `chat:recent:{"since":N}` (every 5 s while open), names from `plys` | no |
| Chat | SEND on GLOBAL | `con:say '<text>'` | yes |
| Chat | SEND on FACTION | `api:Request_InGameMessage_Faction {"id":factionId,"msg":"..."}` (faction of the picked message) | yes |
| Chat | SEND on PRIVATE | `api:Request_InGameMessage_SinglePlayer` (sender of the picked message) | yes |
| Chat | WATCH WORDS, RECENT HITS | none (saved on this PC, matched against the history) | no |
| Chat | WARN | `api:Request_InGameMessage_SinglePlayer` to the player of the picked hit | yes |
| Chat | MUTE | none: the server console has no mute command | stays disabled |
| Chat | DISCORD tab | none: ZAH has no Discord bot or webhook | stays disabled |
| Factions | FACTION LIST, ORIGIN | `api:Request_Get_Factions {"id":1}` (`factionId`, `name`, `abbrev`, `origin`) | no |
| Factions | MEMBERS | `plys` (`factionId`, `role`, `status`) | no |
| Factions | RELATIONS | `api:Request_AlliancesAll` (each pair packed as `(first << 16) \| second`) | no |
| Factions | FOUNDED | none: the game does not report it | shows `--` |
| Factions | SET RELATION | none: `alliances` is a player-console command; no mod API request | stays disabled |
| Factions | RENAME | none: no console command or mod API request | stays disabled |
| Structures | STRUCTURES table, count, detail | `gents` (every 30 s while open; loaded playfields only), filtered on this PC | no |
| Structures | TELEPORT TO | `plys` to pick an online player, then `api:Request_Entity_Teleport` or `api:Request_Entity_ChangePlayfield` to 15 m above the structure | yes |
| Structures | DESTROY | `api:Request_Entity_Destroy {"id":N}` (the playfield must be loaded) | yes |
| Structures | SET FACTION | none: no mod API request changes a structure's faction | stays disabled |
| Playfields | Summary (known, loaded, with players) | `getplayfields:all` and `plys` | no |
| Playfields | Cards (type, players, structures) | `getplayfields:all`, `plys`, `api:Request_Playfield_Stats {"pstr":name}` (up to 12 cards) | no |
| Playfields | UNLOAD | `con:stoppf <name>` per ticked card (names with spaces in double quotes) | yes |
| Playfields | RESTART PLAYFIELD | `con:stoppf <name>`, 20 s wait, `loadpf:<name>\|600` | yes |
| Playfields | WIPE | `con:wipe <name> <deposit\|poi\|terrain\|player\|all>`; the game applies it at the next server restart | yes |
| Playfields | Star map | none: the bridge sends no sector coordinates | summary text only |
| Alerts | ALERT QUEUE (CRITICAL) | `plys` fields `cheat` and `cheater` (every 15 s while open) | no |
| Alerts | ALERT QUEUE (WARNING) | `chat:recent` plus the watch words saved on this PC | no |
| Alerts | Details, EVIDENCE TIMELINE | the same reads (current flags only, so BEFORE and DELTA show `--`) | no |
| Alerts | ACK | none: hides the alert on this PC while ZAH runs | no |
| Alerts | COMMAND PREVIEW, PREVIEW BAN | `con:ban <entityId> <1h\|1d\|7d\|30d\|1y>` | yes |
| Backups | SNAPSHOTS, BACKUP SCHEDULE, DISK USAGE | none: the bridge has no snapshot or backup listing (`backup` answers `not_available`) | panels say why |
| Backups | PREVIEW, RESTORE SELECTED | none: restoring a save needs the server stopped, which is a restart | stays disabled |
| Servers | Cards (status, players, RAM, TICK RATE, core, uptime) | `ServerMonitor`: `hot:status`, `plys`, `api:Request_Dedi_Stats` per saved server, every 30 s | no |
| Servers | CPU ring | none: the game does not report CPU use | shows `--` |
| Servers | CROSS-SERVER ALERTS | the same poll (a server not answering, cheat flags) | no |
| Servers | OPEN DASHBOARD | none on the server: changes `active_index` on this PC and reconnects | no |
| Servers | BROADCAST (one server) | `api:Request_InGameMessage_AllPlayers` to that server | yes |
| Servers | BROADCAST TO ALL SERVERS | `api:Request_InGameMessage_AllPlayers` to every answering server | yes |
| Items (Library) | PLAYER list | `plys` (online players with an entity id), read when the page shows | no |
| Items (Library) | GIVE ITEM (was ADD TO PENDING EDITS) | `api:Request_Player_AddItem {"id":N,"item":{"id":X,"count":Q}}` | yes |
| Items (Library) | ADD TO TEMPLATE | none: adds the item and quantity to STARTER / EXPLORER / BUILDER in `data/loadout_templates.json` | no |
| BP Editor (Library) | BLUEPRINTS tab | none: no blueprint data source yet | empty state |
| ECF / PDA Editor | DOWNLOAD FOLDER FROM SERVER (READ-ONLY) | the `files:` download (`ServerFileDownloadWorker`), then `load_server_files` | no |
| Settings | CANCEL DOWNLOAD | none on the server: `request_stop` on the download thread | no |
| Users | Live file editing checkbox | none on the game server: login service `/users/live_files` (owner or developer key) | no (login service only) |

## Planned / Not Yet Wired

These items have UI placeholders, agreed behaviour, or both. They are **not** implemented end-to-end. Server-changing steps stay disabled until they are approved.

### SERVER FILES download: what is left

Done: the read-only `files:` bridge commands (core 1.6.1) and the working Settings download button. See **Server files download** and **Server file commands** above.

Still to do:

- Done: the live server runs core 1.6.2 (it has `files:`), so the old "Ray deploys the 1.6.1 core" step is finished.
- Check the real scenario's folder layout with `files:info` (`topFolders`) and adjust the `AllowedFolders` table in `ServerFiles.cs` if the real folders differ. The save game folders in particular are guesses until seen on the live server.
- Done (Nov 22, 2026): Items, ECF Editor, and PDA Editor read from `data/server_files/<scenario>/`, **never** from local base-game Content files.
- Done (Nov 22, 2026): CANCEL DOWNLOAD on the Settings page calls the worker's `request_stop`; the worker stops between two requests and reports `Download stopped.` Half-finished `.part` files are removed.
- Done (Nov 22, 2026): the editors' DOWNLOAD FOLDER button runs the same read-only download. Only one download runs at a time across ZAH (`settings_page.RUNNING_DOWNLOADS`).

### Item images

- Image files are named after each item's internal `Name`, for example `<ItemName>.jpg`.
- Lookup path, once the scenario is downloaded: `Scenarios/<scenario>/SharedData/Content/Images/<ItemName>.jpg`.
- An item with no image falls back to the drawn hex tile.
- Files in that folder that do not match an item name (for example PDA pictures) are skipped.
- Done (Nov 22, 2026): `local_files.build_image_index` reads `SharedData/Content/Images` in the downloaded save and scenario folders (save first, `.jpg` before `.png`, names compared without case). The tile, the detail card and the stats window draw the picture cut to the hex shape (`item_tiles.draw_hex_picture`), with the category colour as the edge. Pictures are cached by path and size (`PICTURE_CACHE`).
- The live server currently reports the scenario **Default Multiplayer**, which has no Images folder, so every item shows the drawn hex there until the real scenario is confirmed.

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
- Bridge side done (core 1.6.2): `files:put` gives the backup-first, hash-checked replace that LIVE MODE and UPLOAD will use. The ZAH side (popups, role gate, sending) is the next step.
- Done (Nov 22, 2026): the ZAH side is wired (see **Server uploads and LIVE MODE**). Tested only against the local harness. The Users page checkbox and the `/users/live_files` route are done too (Nov 22, 2026). Still open on Ray's side: deploy the updated login service and add the column.

### ECF and PDA editor follow-through

Still to wire, all against **downloaded server files** (or LIVE MODE once approved):

- **VALIDATE**
- A real diff in **Changes Preview**
- **SAVE** to the local copy, with a backup of the previous file
- **UPLOAD TO SERVER** through ZeroGBridge, only with explicit approval (done Nov 22, 2026, see **Server uploads and LIVE MODE**)

(Nov 22, 2026: every toolbar button is wired; none says `Coming in a later step.` any more.) The ECF and PDA pages can already open a local folder for layout and editor testing. That path is not the long-term data source.

Done (Nov 22, 2026): both editors fill their file dropdown from the downloaded server files on opening (`load_server_files`). Each row is shown as `<file name>  (scenario)` or `(save)`, carries its whole entry (`root`, server `path`, local `full` path), and has the server path as its tooltip. The PDA list only takes `.yaml` and `.csv` under `SharedData/Content/Extras/PDA` or `Content/Extras/PDA`. With nothing downloaded the dropdown is disabled and the editor says `No server files yet. Use Settings > DOWNLOAD SERVER FILES.` `load_local_folder` stays for tests.

### Other agreed follow-ups

- Done (Nov 22, 2026): multi-server connections and bridge auto-reconnect (see **Bridge auto-reconnect and multi-server** below).
- Done (Nov 22, 2026): players, chat, factions, structures, playfields, alerts, and backups are wired or locked with a reason (see **Live Pages and the Safety Flow**).
- Optional restyle of Bans & Audit and Users, only if requested.
