# Zero-G Admin Helper (ZAH): Master Operational Registry

This Master Operational Registry sets the ground rules for the Zero-G Admin Helper (ZAH) project.
Last updated: Nov 17, 2026 (new PDA layout and styling, ZeroGBridge 1.5 hot-reload, multi-server, fresh-start plan).
AI rules for anyone (human or AI) working on ZAH: `.instructions/AI_INSTRUCTIONS.md`.

## ✍️ Coding Rules (Ray's syntax)
- **Language:** Python 3.12 for everything we can. C# is used **only** for the ZeroGBridge mod.
- **Plain names:** files, classes, functions and variables use clear, easy-to-read names that say what they do
  (for example `send_player_alert`, `PlayerListPage`, `bridge_is_connected`). No cryptic abbreviations.
- **Ray must be able to change it himself:** short functions, one job per file, comments that explain *why*,
  and no "clever" tricks.
- **No secrets in code or docs:** passwords and tokens live only in `data/` config files (git-ignored), never in
  this README, source code, or commits.
- **Comments:** Python uses `##` comments (C# uses `//`). Old single `#` comments are switched to `##` when that
  file is next edited, wording kept. Existing code and comments are never stripped out when code is changed.
- **Debug switch:** one central `DEBUG_MODE` flag controls debug prints; log lines carry a tag like `[ZAH.Players]`.
- **Every page is its own module** with its own error handling (see Modular Pages).
- **No server changes without Ray's direct OK.** Approval to commit or push code never covers a server change.

## 🏗️ Technical Stack & Framework
- **Primary language:** Python 3.12
- **GUI framework:** PyQt6, with scoped enum namespaces (`Qt.AlignmentFlag`, `Qt.Orientation`, etc.).
- **Root workspace path:** `/mnt/Zero-G_Files/Zero-G_Forge/Zero-G_Admin_Helper`
- **GitHub:** Zero-G-Forge/Zero-G_Admin_Helper
- **Line terminations:** all outbound server commands use `\r\n` with a 500 ms input buffer delay
  (GTX Gaming hardware calibration).

## 🌌 Look & Feel (New PDA Layout)
ZAH looks like an Empyrion PDA / starship computer: dark navy panels, thin glowing cyan borders, angled panel
corners, a faint starfield/scanline background, and monospace caps headers. All styling lives in `ZAH.css`
so every window matches by default.

**Color palette (set once in `ZAH.css`):**
| Use | Color |
|---|---|
| Active / selected / glow | Cyan `#00FFFF` |
| Panel borders & headers | Sky blue `#00D4FF` |
| Secondary borders, idle buttons | Deep teal `#005577` |
| Panels | Navy `#0F1923` |
| Background | Void `#0A0F19` |
| Body text | `#E0E0E0` (white for emphasis) |
| Critical / destructive only | Red `#FF0000` |
| WARNING pill | Amber |
| ONLINE pill | Green |

**Font:** Courier New (monospace). Headers, tabs and pill labels in CAPS.

**Shared building blocks** (built once, reused on every screen):
- Panel with title bar
- Status pill (ONLINE / WARNING / CRITICAL / PENDING / OFFLINE / STALE)
- Gauge and stat bars
- Data table with search, sort, total count, and a **right-click menu** (risky items in red at the bottom)
- Card grid and action tiles
- **Confirm dialog** (see Safety Flow)
- Console footer

**Window size:** the main window starts at 1000x750 (minimum). The AccountOnboardingWizard stays fixed at 512x512.
**Textures:** QSS `border-image` keeps corner brackets and glow textures from stretching on any monitor size.

## 🖥️ App Frame (every screen)
- **Top ribbon:** logo, server dropdown (each server with its status dot), Connect / Disconnect, Force Backup,
  Save Game, search (Ctrl+K), clock, admin name, game and ZGB core version.
- **Left nav:** one full list, the same on every screen (see Screens). Only the current page lights up.
  Alerts shows a red count badge.
- **Middle:** the current page.
- **Console footer (like EAH):** latest server log line with yellow/red flags, toggles for Auto-scroll, Debug,
  Warn, Errors, plus bridge status, CPU, RAM, players online and core version.
- **Menu bar:** File, and **View > ZeroGBridge Portal** (built).
- **Bridge offline:** a banner reads "ZeroGBridge disconnected - reconnecting", and live numbers gray out with a
  STALE time stamp until the link is back.

## 🛡️ Safety Flow (every action that changes the server)
1. **Command preview:** shows the exact bridge/console command ZAH will send.
2. **Type CONFIRM** for anything destructive (wipe, ban, kill playfield, etc.).
3. **15-second send delay** with a Cancel button (no "Send Now" skip).
4. **Audit log:** every action is recorded (OK, Failed, or Cancelled).
- Inventory and profile edits stay **pending** until Save & Apply; Discard throws them away.

## 🗂️ Screens
Status: ✅ built, 🛠️ planned (bridge already has the data), 🔌 planned (needs a new bridge command, Ray's OK first).

| # | Screen | What it does | Status |
|---|---|---|---|
| 1 | Dashboard | Needs Attention (click-through), server health, online players, next tasks, quick actions | 🛠️ |
| 2 | Players | EAH roster: name, Steam/EGS ID, faction, playfield, status, playtime, last seen, ping (amber >250 ms); message, warp, kick, ban, inventory editor, loadouts | 🛠️ / 🔌 inventory, kick, ban, warp |
| 3 | Factions | Faction list, members, structures by class | 🛠️ / 🔌 diplomacy, leader changes |
| 4 | Structures | CV/SV/HV/BA filters, entity ID, owner, blocks (red over limit), position, fuel; reassign, export blueprint, wipe | 🛠️ / 🔌 actions |
| 5 | Playfields & Map | Galaxy map, loaded/unloaded state, players, structures, starter flag; unload, scheduled wipes | 🛠️ / 🔌 unload, wipes |
| 6 | Chat | Global / Faction / Server-Bot / Private tabs, blacklist words, freeze auto-scroll, mute 15m/1h/1d/Forever, say/whisper line | 🔌 |
| 7 | Alerts & Anti-Cheat | Alert queue with ACK, auto-ban rules, combat-log monitor, chat-bot triggers | 🛠️ / 🔌 inventory checks |
| 8 | Scheduler | EAH timetable (interval, command, on/off, last/next run, Run Now) plus chained tasks (warn > save > backup > restart) | 🛠️ |
| 9 | Bans & Audit | Ban list with Unban, full audit log, CSV export | 🛠️ / 🔌 ban list |
| 10 | ZeroGBridge Portal | Loader/core versions, hot status, reload, rollback, link health, command traffic | ✅ (restyle 🛠️) |
| 11 | Confirm dialog | Shared Safety Flow dialog | 🛠️ |
| 12 | Config & Setup | Servers, Paths, Remote/FTP, Feature toggles | 🛠️ |
| 13 | Backups & Restore | Snapshots; restore one player, structure or playfield with preview | 🔌 |
| 14 | Item & Blueprint Library | Searchable items/blueprints feeding Give Item and loadouts | 🔌 |
| 15 | Multi-Server Overview | All servers side by side, combined alerts, broadcast to all | 🛠️ |

To check before promising (may need file/console access instead of the game API): RAM per playfield,
terrain voxel reset, structure "touch", single-structure restore.

Concept images for every screen: `/workspace/zah_suite/v3/` on the bot computer (example data only).

## 📡 Servers
| Server | Host | Game port | Bridge port |
|---|---|---|---|
| GTX (primary) | GTX Gaming, 66.23.236.138 | - | 30500 |
| Ascension | HostHavoc, 104.192.227.34 | 30004 | 30500 |

Server profiles live in `data/server_config.json` (`servers[]` with `input_ip`, `input_port`, `input_pass`,
`bridge_port`, optional `server_name`, and `active_index`). The bridge AuthToken is stored there and in each
server's `ZeroGBridge.json`, **never in this README**.

sFTP connection: needed for `.log` files to be read and parsed (credentials in `data/mirror_config.json`).

## 🌉 ZeroGBridge (ZGB) - C# Server Mod
ZeroGBridge is a custom C# server-side mod in the Empyrion Dedicated Server (`Content/Mods/ZeroGBridge/`).
It is the backend link and telemetry pipeline for ZAH.

- **Runtime:** C# (.NET Framework 4.8) using Eleon's IMod / ModApi lifecycle.
- **Version 1.5 hot-reload layout:**
  - `ZeroGBridge.dll` = the **loader**. Owns port 30500 and authentication. Never needs swapping for normal updates.
  - `Core/ZeroGBridge.Core.dll` = the **core** with all features, running in its own AppDomain (`ZGB-Core-N`).
  - `Updates/` = drop a new core here, then hot-reload it with **no server restart** (players stay connected).
  - Rollback to the previous core is available.
- **Network:** async TcpListener on port 30500, lines end in `\r\n`.
- **Authentication:** `auth:<token>` before anything else; reply is AUTH Authenticated. Token = `AuthToken` in
  `ZeroGBridge.json`.
- **Telemetry:** METRIC JSON packets every 2 seconds (tick/FPS, heap, CPU %, RAM, uptime, player cache).

**Commands:**
| Command | Reply | What it does |
|---|---|---|
| `plys` | PLAYER_CACHE | Live player list |
| `gents` | ENTITY_LIST | Global structure/entity list |
| `alert:{json}` | ALERT_ACK | In-game message to all / a faction / one player (sent, or failed: auth, bad_request, unknown_target, api_error, timeout) |
| `hot:{"cmd":"status"}` | HOT status | Loader and core state |
| `hot:{"cmd":"reload"}` | HOT result | Load a new core from `Updates/` (`"force":true` to reload the same core) |
| `hot:{"cmd":"rollback"}` | HOT result | Go back to the previous core |
| `save` / `backup` | - | Flush world state to disk |
| `restart` | - | Graceful restart notice and shutdown |
| `cmd:<command>` | - | Run a dedicated-server console command |

Note: `msg:`, `broadcast:` and `msgfaction:` are placeholders that only log; use `alert:` for messages.
Full contract: `ZeroGBridge/README.md`.

## 🧱 Modular Pages (one failure never takes down ZAH)
Unlike EAH, where one broken part can crash the whole program, every ZAH page and feature is its own module.
- **One folder per page:** `features/<page_name>/` (for example `features/players/players_page.py`).
  Pages never import each other; they share only the building blocks and the bridge client.
- **Page loader:** the app frame loads each page inside a `try/except`. If a page fails to load or crashes,
  only that page is replaced by an error card ("Players page failed to load - View Log / Retry").
  The nav, the other pages and the bridge link keep running.
- **Safe buttons and timers:** every button click, timer and bridge reply handler is wrapped so an error is
  logged and shown on that page instead of closing the app.
- **Background workers:** each page's workers run on their own thread, catch their own errors, and stop
  cleanly. A stuck worker times out instead of freezing the window.
- **Bridge calls:** every call has a timeout and a clear error message; a dropped link only shows the STALE state.
- **Last line of defense:** a global error hook (`sys.excepthook`) writes any missed error to `logs/` and keeps
  ZAH open.
- **Turn pages on/off:** Config > Features can disable a misbehaving page without touching the code.
- **Tests:** each page has its own tests, including one that forces the page to fail and checks the rest of ZAH
  still works.

## 🏗️ Architecture & File Rules
- **Feature-first:** all logic lives in `/features/<feature>/`. Features don't import from each other.
- **Fixed entry points:** `ZAH.py` (starts the app and boot sequence) and `startup.py` (discovery).
- **State separation:** `/data`, `/logs`, `__pycache__` and secrets are git-ignored.
- **Threads:** heavy work (log parsing, bridge traffic, chat) runs on background threads so the UI never freezes.
- **Branches:** one branch and pull request per screen or feature, tested against the fake bridge, then merged to main.

## 📦 Directory Layout
`/mnt/Zero-G_Files/Zero-G_Forge/Zero-G_Admin_Helper/`
- `ZAH_Legacy/` - the old program (tag `legacy-v1`): `ZAH.py`, `features/`, `launch_zah.sh`, milestone checks. Kept for reference.
- `.instructions/` - `AI_INSTRUCTIONS.md` (AI and coding rules), README
- `.gitignore`, `LICENSE`, `Zero-G Admin Helper.code-workspace`
- `tools/` - helper scripts, e.g. `clear_pycache.py` (clears all `__pycache__` folders).
- GitHub token lives outside the project at `~/.config/zah/git_token.txt` (never in the repo).
- `assets/` - `branding/`, `backgrounds/`, `buttons/`
- `additional_assets/ZAH.css` - the theme for the whole app.
- `.instructions/Examples/ZGB_Portal/` - sample data for the portal (`README.md`, `loader_state.json`, `cores/`, `scripts/`).
  Live data is the default; samples are for testing and demos only.
- `data/` (git-ignored) - `users.json`, `player_profiles.json`, `server_config.json`, `mirror_config.json` (FTP
  login), `telemetry_cache.json`, `player_registry_cache.json`, `player_registry.py`, `playfield_registry.py`,
  `secret.key`, `server_mirror.log`
- `features/`
  - `auth/` - `inspect_users.py`, `login.py`, `onboarding.py`, `persistence.py` (Remember Me)
  - `dashboard/` - `main_cockpit.py` (main window, menu bar with View menu), `resource_worker.py`,
    `telemetry_parser.py`, `telemetry_worker.py`
    - `zgb_portal/` - `portal_window.py`, `hot_reload_panel.py`, `bridge_panel.py`, `data_source.py`
      (sample or live data, find player, message player), `live_client.py` (short authenticated bridge calls)
  - `loading/` - `loading_screen.py`
  - `network/` - `connection.py`
  - `security/` - `security_module.py`
- `ZAH_Legacy/tests/` - `test_zgb_portal.py`, `test_zgb_portal_live.py`, `fake_zgb_hot_bridge.py`, `test_telemetry.py`,
  `sFTP.py`, `migrate_users.py`
- `ZeroGBridge/` (C# mod source)
  - `Core/ModMain.cs` (Init and Shutdown), `Core/LegacyApi.cs`
  - `Handlers/CommandDispatcher.cs` (routes commands like `plys`)
  - `Network/TelemetryServer.cs` (sockets + auth on 30500), `Network/TelemetryBroadcaster.cs` (METRIC loop),
    `Network/AlertService.cs` (`alert:`)
  - `logging/LogParser.cs`, `logging/LogDiscovery.cs`
  - `lib/` (EGS modding DLLs), `bin/`, `obj/`, `Properties/AssemblyInfo.cs`

## 🆕 Fresh Start (Legacy Move)
The new ZAH is built as a clean program next to the old one, instead of rewriting the old code in place.
1. **Save everything first:** push open branches (including `feature/zgb-portal-view`), then tag the current
   `main` as `legacy-v1`.
2. **Move, don't delete:** the current program goes into a `legacy/` folder and stays runnable until the new app
   matches it screen for screen. Git history keeps every line.
3. **Clean app folder:** the new app frame (nav, ribbon, console footer), page loader, theme and fake bridge start
   from a blank slate.
4. **Bring over what works, one module at a time:** bridge client, reply parsers, ZGB Portal logic, login and
   onboarding. Each piece is renamed and re-commented to the new rules as it moves.
5. **Keep saved data working:** the new app reads the same `data/` files (`server_config.json`, `users.json`,
   Remember Me via `persistence.py`), so admin logins and server profiles carry straight over. The login flow stays
   the same: admin login, game port check, then the bridge connects on its own.
6. **Carry tests over:** existing tests (`test_server_switching`, `test_log_into_server`, `test_logout`,
   `test_zgb_portal*`, `test_telemetry`) move into the new app as the check that nothing broke.

Status: plan only. Nothing moves until Ray says go.

## 🧭 Build Plan for the New Layout
1. Clean base: push open branches, tag `legacy-v1`, move the old program to `legacy/` (see Fresh Start).
2. Theme and shared building blocks in `ZAH.css` and reusable widgets.
3. New app frame (nav, ribbon, footer); today's dashboard becomes the first page.
4. Screens the bridge already supports.
5. ZAH-only screens (Bans & Audit, Scheduler, Config, Alerts rules).
6. New bridge commands, each only with Ray's OK, shipped as a hot-swap with no restart.

🔄 Automated Lifecycle & Sequential Flows
1. Boot Diagnostics & Key Milestone Logic Recap
At 30% Progress: The loader's timing loop pauses and checks if there are accounts with "keep me logged in", if there are login screen is bypassed if no then the Login Screen Overlay is activated, Progress bar is kept frozen until successful user login or account creation has been verified.

At 60% Progress: The progression bar halts a second time to check if a server configuration profile available, conditionally intercepting the initialization of the Network Connection Wizard. If there are available network configurations then network wizard is bypassed. If there are no configuration profiles available then the network wizard opens for network login data. Progress bar is kept frozen until successful configuration profile is found/created.

Ping is run to verify network configuration. If unable to verify then network wizard is re-initialized with ping error and request to re-enter network login info.

At 100% Progress: Upon successfully navigating both state gates, the orchestrator closes the loading phase and hands control off over to the main_window cockpit dashboard interface.

[ Boot: ZAH.py ] ──> UI Thread Draws 1000x750 Canvas │ ▼ [ Increment to 30% ] │ Gated Check: "Keep Me Logged In"? ├── Yes ──► Bypass Login └── No ──► [ HALT Progress ] ──► Open Login Screen │ Verified Account Login/Creation │ ┌───────────────────────────┘ ▼ [ Progress Resumes ] │ ▼ [ Increment to 60% ] │ Gated Check: Server Config Profiles? ├── Yes ──► Bypass Network Wizard ────────────────────────────────────────► [Network Ping] ◃───┒ └── No ──► [ HALT Progress ] ──► Open Network Connection Wizard | | │ | | Config Created | | │ | | | | | ▼ | | ┌───────────────────[Validated Ping]<──────────────────────────────────┘ | | | | ▼ ▼ | (Yes) (NO) | ▼ └────► Re-launch Network Connection Wizard ──────────────┘ [ Progress Resumes ] │ ▼ [ Milestone 100% ] ──► Hand off to Main Workspace
