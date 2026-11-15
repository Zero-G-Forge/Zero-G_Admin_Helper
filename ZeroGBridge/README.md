# ZeroGBridge

Server-side Empyrion mod (net48, IMod API v2 + legacy ModInterface) that streams telemetry to
Zero-G Admin Helper and accepts commands on TCP port 30500. Newline-delimited, UTF-8, one JSON reply per request.

## Configuration: `ZeroGBridge.json` (next to `ZeroGBridge.dll`)

```json
{
  "SaveGameName": "Zero-G Server - Season 4",
  "GlobalDbPath": "",
  "AuthToken": ""
}
```

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
| `id` | Omit for `all`. Faction: numeric faction id or tag/name (`MEC`, `[MEC]`, case-insensitive). Player: entity id or Steam id. |
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
- `unknown_target`: the faction or player is not in the bridge cache.
- `api_error`: the game rejected or threw on the call, or the legacy API is not attached in this process.
- `timeout`: the game main thread did not run the call within 5 s, or the rate-limit wait went over 3 s.

Rate limit: at most 5 alerts per second across all clients. Extra alerts wait for a free slot (each still gets its own ack).
Threading: while the game's `Game_Update` is ticking, alert calls run on the game main thread. Otherwise they run directly.

Faction targets resolve from the bridge's built-in faction list, plus the factions returned by the legacy
`Request_Get_Factions` at startup.
