# ZeroGBridge

Server-side Empyrion mod (net48, IMod API v2 + legacy ModInterface) that streams telemetry to
Zero-G Admin Helper and accepts commands on a TCP port (default 30500, set with `Port`). Newline-delimited, UTF-8, one JSON reply per request.

**1.5.0: hot reload.** The mod is now a small loader (`ZeroGBridge.dll`, owns the port and auth) plus a
reloadable core (`Core/ZeroGBridge.Core.dll`, all bridge logic). Drop a new core into `Updates/` and send
`hot:reload`, and it swaps in without a server restart or dropping ZAH connections. A broken core is rolled back
automatically. See [HOTRELOAD.md](HOTRELOAD.md) for the layout, settings and the `hot:` command contract.

**Core 1.5.1 (core-only, hot-swappable on the 1.5.0 loader).** Event_Get_Factions rows are classified by origin
first: NPC groups that the game reports with faction id 0 (Zirax, Talon, ...) now count as `dropped(NPC)` instead of
`skipped(id<=1)`. Only origin 0/1 rows with id <= 1 (the default human group) count as skipped. DEBUG also logs counts
by origin and a sample of dropped/skipped rows. The loader and the `hot:` contract are unchanged.

**Core 1.6.0 (core-only, hot-swappable on the 1.5.0 loader).** Every legacy Eleon request is reachable from ZAH
with `api:`, server console / telnet commands run for real with `con:` (`cmd:` and `exec:` are now aliases),
and `cmds` returns both command lists as JSON so ZAH can build its menus. `loadpf:` now really sends
`Request_Load_Playfield`. The loader, the `auth:` handshake and the `hot:` contract are unchanged. See
[Commands (1.6.0)](#commands-160) below.

Build: `ZeroGBridge.csproj` builds the loader. `CoreProject/ZeroGBridge.Core.csproj` builds the core.
Deploy both the first time (one restart). After that, only the core changes for most patches.

## Configuration: `ZeroGBridge.json` (next to `ZeroGBridge.dll`)

```json
{
  "SaveGameName": "Zero-G Server - Season 4",
  "GlobalDbPath": "",
  "AuthToken": "",
  "Port": 30500,
  "HotReloadEnabled": true,
  "AutoReloadOnDrop": false
}
```

- `HotReloadEnabled`, `AutoReloadOnDrop`, `HotReloadPollMs`, `KeepCoreVersions` and `CoreIsolation` (1.5.0) are described in [HOTRELOAD.md](HOTRELOAD.md).

- `Port` (1.4.2+) is the TCP port the bridge listens on. Missing, empty or invalid (not 1-65535) means 30500.
  It is read once at startup, so restart the server after changing it (a core hot reload does not re-read it). The log shows
  `Bridge port in use: <port> (...)` and `TelemetryServer listening on port <port>`.
  It must not be a port the game already uses (game, query, telnet/RCON).

- `AuthToken` (1.4+) is the shared secret for the `auth:` handshake. Enter it on the server only.
  Never commit it or paste it in chat. The bridge never logs it.
  The file is re-read when it changes, so a new token takes effect on the next login without a restart.
- If `AuthToken` is missing or empty, the bridge falls back to the pre-1.4 built-in password and logs one
  `-WARN- No AuthToken set ...` line. Set a token to close that fallback.

## Handshake

The first line must be `auth:<token>`.

| Reply | Meaning |
|---|---|
| `{"type":"AUTH","status":"Authenticated",...}` | OK, the session stays open |
| `{"type":"AUTH","status":"Denied",...}` | Wrong token, the connection is closed |
| `{"type":"AUTH","status":"Required",...}` | The first line was not `auth:`. The bridge logs ONE WARN with the remote IP and closes the connection (stops port-scanner log spam) |

## In-game alert (1.4+)

Request, one line, after auth:

```
alert:{"req_id":"abc123","target":"all|faction|player","id":"<see below>","text":"Server restart in 10 minutes","prio":0,"duration":10}
```

| Field | Notes |
|---|---|
| `req_id` | Echoed back in the ack. String (numbers are accepted and echoed as strings). |
| `target` | `all`, `faction` or `player`. |
| `id` | Omit for `all`. Faction: numeric faction id or tag/name (`MEC`, `[MEC]`, case-insensitive); player factions only (see below). Player: entity id or Steam id. |
| `text` | Plain text. Control characters are replaced by spaces, then the bridge cuts it to 200 characters. |
| `prio` | Empyrion `IdMsgPrio.prio`: `0` red (**default**), `1` yellow, `2` blue. |
| `duration` | Seconds on screen, default `10`, capped at 300. |

Ack, exactly one line per request:

```
{"type":"ALERT_ACK","req_id":"abc123","status":"sent"}
{"type":"ALERT_ACK","req_id":"abc123","status":"failed","error":"auth|bad_request|unknown_target|api_error|timeout"}
```

- `sent` means the game API accepted the `Game_Request` call (Request_InGameMessage_AllPlayers 59, _Faction 60, _SinglePlayer 58).
- `auth`: an `alert:` line was sent before auth. The connection is then closed.
- `bad_request`: invalid JSON (`req_id` is `null` then), unknown target type, empty text, prio not 0-2, bad duration, missing id.
- `unknown_target`: the player is not in the bridge cache, or the faction is not a player faction with a real player (NPC factions such as Zirax never resolve).
- `api_error`: the game rejected or threw on the call, or the legacy API is not attached in this process.
- `timeout`: the game main thread did not run the call within 5 s, or the rate-limit wait went over 3 s.

Rate limit: at most 5 alerts per second across all clients. Extra alerts wait for a free slot (each still gets its own ack).
Threading: while the game's `Game_Update` is ticking, alert calls run on the game main thread. Otherwise they run directly.

Faction targets (1.4.2): only player factions resolve. That is `FactionInfo.origin` 0 (player clubs)
and 1 (private / one-person factions), and only while at least one real player (a cached player
with a Steam id or entity id) is a member. NPC factions (origin 2 and up, such as Zirax, Talon,
Polaris, traders) and origin 255 are dropped. The list comes from the bridge's built-in clubs plus
the legacy `Request_Get_Factions` (at Game_Start, again about 20 seconds later, then every 5 minutes,
and when a faction changes). The request is always sent on the game thread (Game_Start or
Game_Update); the refresh timer only marks it pending. Other mods' faction replies are merged in.
Each reply is logged at DEBUG with its seqNr and counts, and at INFO when the counts change.

`gents` hides NPC structures by faction group (0 player, 1 private and 5 admin are kept;
NPC groups and 255 are dropped) instead of the old faction-name blacklist.

## Commands (1.6.0)

Every line gets exactly one single-line JSON reply. The line ending is the server's newline
(CRLF on the Windows dedicated server), UTF-8 without BOM. A bad command gets
`{"type":"ERROR","status":"<code>","code":"<code>","message":"..."}`; it never stops the bridge.
A line that contains the AuthToken is refused (`secret_in_command`) and nothing is sent to the game.

### `cmds` - the command catalog

`cmds` (also `help:commands`, `api:list`) returns one `COMMAND_CATALOG` line:

```json
{"type":"COMMAND_CATALOG","release":"1.6.0","eleon_count":41,"console_count":83,"zah_count":4,
 "eleon":[{"name":"Request_Player_Info","cmd_id":17,"short_names":["player_info","playerinfo","pinfo"],
           "param_type":"Id","param_fields":["id"],"required":["id"],"key_aliases":{},
           "replies":["Event_Player_Info"],"wait":"data","changes_server":false,"visible_to_players":false,
           "on_rays_list":true,"description":"...","note":null}, ...],
 "console":[{"name":"debugmenu","aliases":["dm"],"description":"...","permission":"6+","min_permission":6,
             "server_capable":false,"changes_server":false,"safe_without_args":false,
             "blocked":false,"blocked_reason":null,"source":"sheet"}, ...],
 "zah":[{"name":"restart","syntax":"restart:<minutes>","changes_server":true,"status":"implemented"},
        {"name":"restart:cancel","syntax":"restart:cancel","changes_server":true,"status":"implemented"},
        {"name":"save","syntax":"save","status":"not_available"},
        {"name":"backup","syntax":"backup","status":"not_available"}]}
```

- `changes_server: true` means ZAH should put the command behind its CONFIRM step. The bridge itself still
  runs it when asked. In-game messages and dialogs are marked too (`visible_to_players`).
- `safe_without_args: true` (`ticks`, `time`, `saveandexit`, `stoppf`): with no arguments the command only
  shows information, so a `con:` reply for just `ticks` says `changes_server: false`.
- Console rows come from the command sheet (`source: "sheet"`) plus the telnet-only commands from the
  Empyrion wiki (`source: "telnet_wiki"`: `instances`, `plys`, `remoteex`, `saveandexit`, `say`, `servers`, `stoppf`).
  The list lives in `Core/ConsoleCatalogData.cs`.
- `zah` lists the ZAH shortcuts: `restart:<minutes>` / `restart:cancel` (implemented), and `save` / `backup`
  (`status: "not_available"`). These are not telnet commands.


### `api:` - the full Eleon API

```
api:<RequestName or short name> [params]
api:Request_Player_Info {"id":5001}
api:player_info 5001                       (an Id request also takes a plain number)
api:pfstats Akua                           (a PString request also takes plain text)
api:Request_Player_AddItem {"id":5001,"item":{"id":4097,"count":10},"req_id":"z1","timeout_ms":500}
```

- The name is the `CmdId` name (case-insensitive), `Request_` dropped (`player_info`), the same without
  underscores (`playerinfo`), or a short name from the catalog (`credits`, `getinv`, `touch`, `loadpf`, `factions` ...).
- Params are a JSON object using the real field names of the Mif.dll param type (case-insensitive), plus the
  friendly `key_aliases` in the catalog (`text` -> `msg`, `item` -> `itemStack`, `amount` -> `credits` ...).
  Vectors take `{"x":1,"y":2,"z":3}`, `[1,2,3]` or `"1,2,3"`. Items take `{"id":..,"count":..,"slotIdx":..,"ammo":..,"decay":..}`.
  Unknown or missing fields are refused (`bad_params`) before anything is sent.
- `req_id` is echoed back. `timeout_ms` (50-500) sets the wait for the answer.
- `Request_ConsoleCommand` gets the same checks as `con:`.

Reply:

```json
{"type":"API_RESULT","req_id":"z1","request":"Request_Player_Info","cmd_id":17,"seq":40012,"status":"ok",
 "event":"Event_Player_Info","error":null,"data":{...the event object...},"changes_server":false,
 "elapsed_ms":21,"timeout_ms":500,"timestamp":"17-19:28:39"}
```

| `status` | Meaning |
|---|---|
| `ok` | The matching event came back (`event` names it, `data` holds it) |
| `error` | The game answered `Event_Error`; `error` is the `ErrorType` (`PlayerIdNotFound`, `EntityIdNotFound` ...) |
| `accepted` | Dialog / item exchange: shown to the player; their click comes later and is not waited for |
| `timeout` | The game accepted the request but did not answer in time (or `Event_Ok` came without the data). Do not blindly repeat a command that changes something |
| `not_available` | The legacy API is not attached in this process |
| `rejected` / `exception` | `Game_Request` returned false or threw |

Answers are matched by `seq` (40000-65535), so many requests can run at once. `Event_Playfield_Loaded` is also
matched by playfield name. The game thread wait plus the answer wait are kept within the request deadline
(500 ms by default and at most), so a slow answer never holds a ZAH connection or a hot reload for long.

### `con:` - server console / telnet

```
con:<console command line>      cmd:<line> and exec:<line> work the same
con:kick 'Solo A' "bye now"
con:ticks                       read-only form
```

- The first word is looked up in the console catalog (main name or alias, case-insensitive). The whole line is
  sent unchanged as `Request_ConsoleCommand(PString)`.
- Reply: `{"type":"CONSOLE_RESULT","command":"kick","line":"kick ...","seq":40100,"status":"ok","event":"Event_Ok","changes_server":true,...}`.
  The game only answers Ok or Error; what the command prints goes to the server log.
- Refused, nothing sent (`type":"ERROR"`): `client_only` (no `V` in the sheet: only works in the game client
  console), `blocked` (`replaceblocks`: never run on a server; `changemode`: does not work in multiplayer),
  `unknown_command`, `empty`, `bad_text`.

### `files:` - read-only server files (1.6.1)

**Core-only update** (hot-swappable on the 1.5.0 loader). Lets ZAH copy the active scenario's and the current
save game's editable files down. It never writes, renames or deletes anything on the server. The code is
`Network/ServerFiles.cs`; `tests/ServerFilesTest` holds its self-checks (`dotnet run`).

```text
files:info
files:list:{"root":"scenario","offset":0,"limit":1000,"req_id":"a1"}
files:get:{"root":"scenario","items":[{"path":"Content/Configuration/Items.ecf","offset":0}],"req_id":"a2"}
```

Every reply is one `"type":"FILES"` line. A failed request has `"ok":false,"error":"<code>","message":"<text>"`
(codes: `bad_request`, `unknown_root`, `root_unavailable`, `too_many_items`, `unknown_command`, `exception`).

- `files:info` returns `protocol` (1), `readOnly`, `scenario`, `saveName`, `roots` (per root: `available`, `name`,
  `topFolders`, `allowedFolders`), `limits` and `extensions`.
- `files:list` returns `total`, `offset`, `count`, `next` (null on the last page) and `files`: `{path, size, mtime}`.
  Paths are relative to the root and use `/`. The list is sorted by path.
- `files:get` takes up to 50 items. Each result is `{path, size, mtime, offset, length, eof, data}` where `data`
  is base64. One reply carries at most 192 KB of raw file bytes (about 256 KB of text). An item that does not fit
  comes back `{path, deferred:true}`, and a file larger than the budget comes back in pieces (`eof:false`): ZAH asks
  again with `offset` = previous `offset` + `length`. A refused item is `{path, error}` with `bad_path`,
  `not_allowed`, `not_found`, `too_large` or `read_failed`.

Safety, in order:

1. Only two roots exist: `scenario` (the active scenario folder) and `save` (the current save game folder). Both
   are read from the game on the game thread (`IApplication.GetPathFor`), with `dedicated.yaml` as a fallback.
2. Only whitelisted sub-folders (`AllowedFolders` in `ServerFiles.cs`) plus files directly in the root, and only
   `.ecf .yaml .yml .csv .jpg .jpeg .png`. `global.db`, `.json`, `.dll` and everything else is unreachable.
3. A request path is refused when it is empty, absolute, has a drive letter or `:`, has `..` or `.` or an empty
   segment, has control characters or wildcards, a segment ending in a dot or space, or a Windows device name.
4. The resolved full path must stay under the root folder, and no file or folder on the way may be a symlink or junction.
5. Files open with `FileAccess.Read` and `FileShare.ReadWrite` only. Files over 16 MB are refused.
6. The AuthToken is never read here; the `auth:` handshake already happened, and the dispatcher still refuses
   any line that contains the token.

### Older commands

`plys`, `gents[:<playfield>]`, `getplayfields[:all]`, `alert:{...}`, `add_player:`, and the `hot:` commands are unchanged.
`loadpf:<playfield>[|seconds]` now sends `Request_Load_Playfield` (default 60 s) and keeps its reply keys
(`status` is `Loaded`, `Initiated` or `Failed`).

`restart:<minutes>` (integer 0-15) is a real shortcut: it sends `say 'Server restarting in <N> minute(s)'` and then
`saveandexit <N>` on the game thread via `Request_ConsoleCommand`. The reply is one JSON line with
`action:"ServerRestart"`, `minutes`, `executed:true/false`, and the console Ok/Error result for each step.
`restart:cancel` sends `saveandexit cancel` (and a `say` that the restart was cancelled). Bare `restart`, or a
minutes value that is not an integer from 0 to 15, is refused and nothing is sent. `saveandexit` saves and stops
the server; starting it again is the host panel's job. Put this behind ZAH's CONFIRM step and a player check.

`save` and `backup` stay honest and do not run: `executed:false`, `status:"not_available"`. Save replies
`Empyrion has no save-only command; the game autosaves and saveandexit saves before stopping`. Backup replies
`Backups are done by ZAH over sFTP after the server stops, not by the bridge`.

`getcredits:`, `getinv:`, `pfstats:`, `pfents:`, `touch:`, `destroystruct:`, `msg:`, `msgfaction:`, `addcredits:` still only acknowledge;
use their `api:` versions for the real request.
