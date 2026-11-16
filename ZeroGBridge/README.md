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
