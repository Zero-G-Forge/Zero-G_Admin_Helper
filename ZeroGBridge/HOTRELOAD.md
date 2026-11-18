# ZeroGBridge 1.5.0 hot reload

ZeroGBridge is split into two DLLs:

| File | What it is | Changing it |
|---|---|---|
| `ZeroGBridge.dll` (loader) | The DLL Empyrion loads. Owns the bridge TCP port, the `auth:` handshake, the `hot:` commands, and the game callbacks. Small and rarely changes. | Needs a server restart |
| `Core/ZeroGBridge.Core.dll` (core) | All bridge logic: commands, factions, players, alerts, server view, telemetry. | Hot reload, no restart |

ZAH connections stay open across a core reload. The connection is held by the loader, so the client
does not need to log in again.

**Core 1.6.0** (`api:`, `con:`, `cmds`, real `loadpf:`) is a core-only update for the 1.5.0 loader
(contract 1 unchanged): drop `ZeroGBridge.Core.dll` into `Updates/` and send `hot:reload`. No restart needed.
Its self-test also checks that both command catalogs load. Commands are described in [README.md](README.md#commands-160).
While an `api:` / `con:` command waits for the game's answer (up to its 500 ms deadline) it counts as in flight, so a
swap waits for it like any other command.

## Mod folder layout

```
Content/Mods/ZeroGBridge/
  ZeroGBridge.dll            loader (Empyrion loads this)
  ZeroGBridge.pdb
  ModInfo.yaml
  ZeroGBridge.json           settings + AuthToken (server only, never commit)
  Core/
    ZeroGBridge.Core.dll     boot core: always the last good core (the loader keeps it updated)
    ZeroGBridge.Core.pdb
    versions/<id>/           immutable copies the loader actually runs (id = <assemblyVersion>_<sha8>)
    hotreload_state.json     current / last good version + the last 50 reload results
  Updates/                   drop folder for a new core
    failed/                  rejected cores are moved here
```

The loader never runs the core from `Core/ZeroGBridge.Core.dll` or `Updates/`. It copies the file to
`Core/versions/<id>/` first and loads that copy. So the files you upload are never locked and can be
overwritten while the server runs.

## Patching the core (no restart)

1. Build `CoreProject/ZeroGBridge.Core.csproj` (Release).
2. Upload `ZeroGBridge.Core.dll` (and `.pdb`) into `Updates/`. If your FTP client can, upload under a
   temporary name and rename it when the upload finishes.
3. Send `hot:reload` from ZAH, or set `"AutoReloadOnDrop": true` so the loader picks the file up by itself
   once it stops changing (it checks every `HotReloadPollMs`, default 2000 ms).

What the loader does:

1. It imports the file into `Core/versions/<id>/`. A file that is not a .NET assembly fails here (`load_failed`).
2. It creates a new AppDomain, loads the core there, and checks the contract version and `SelfTest()`.
   The old core keeps running the whole time. On failure it reports `load_failed`, `contract_mismatch` or `selftest_failed`, and nothing changes.
3. It swaps on the game thread. The old core finishes its in-flight commands, then stops (threads, timers
   and game event handlers are removed). The new core then starts and gets the legacy API. Its faction
   refresh goes out on the next Game_Update. Loaded playfields are replayed to it.
4. It unloads the old AppDomain.
5. If the new core throws while starting (`start_failed`), the previous core is loaded again in a fresh
   AppDomain (`rolledBackTo` in the reply).
6. On success, `Core/ZeroGBridge.Core.dll` is updated to the new core, so a restart boots the same version.
   The drop file is removed from `Updates/`. A rejected drop file moves to `Updates/failed/`.

During the swap, which normally takes 150–300 ms, commands wait. Each one still gets exactly one reply.

## Settings (`ZeroGBridge.json`, all optional)

| Key | Default | Meaning |
|---|---|---|
| `HotReloadEnabled` | `true` | `false` blocks `hot:reload` / `hot:rollback` (`hot:status` and `hot:versions` still work) |
| `AutoReloadOnDrop` | `false` | Reload automatically when a new `Updates/ZeroGBridge.Core.dll` appears |
| `HotReloadPollMs` | `2000` | How often the drop folder is checked (250–60000) |
| `KeepCoreVersions` | `5` | Stored versions kept in `Core/versions/` (the current and last good are always kept) |
| `CoreIsolation` | `"AppDomain"` | `"InProcess"` loads each core into the game's own domain. Use it only if the server cannot create AppDomains: the old core's code then stays in memory until restart. The loader switches to it by itself, with a WARN, if creating an AppDomain fails. |

`Port` and `AuthToken` are unchanged from 1.4.2. Changing `Port` still needs a restart. The listener belongs to the loader.

## `hot:` command contract (for ZAH)

These are sent after `auth:`, one line per command, and each gets exactly one reply line with
`"type":"HOT"`. Before auth, a `hot:` line gets the usual `AUTH Required` reply and the connection closes.

Request forms:

```
hot:status
hot:versions                (aliases: hot:list-versions, hot:list)
hot:reload                  reload from Updates/ZeroGBridge.Core.dll, or Core/ if Updates/ is empty
hot:reload force            reload even if that exact core is already running
hot:rollback                go back to the most recent good version other than the current one
hot:rollback <id>           go to a stored version id (see hot:versions)
hot:{"cmd":"status|versions|reload|rollback","req_id":"abc","force":true,"version":"<id>"}
```

`req_id` is optional and echoed back. A number is echoed as a string.

### Version object (used everywhere below)

```json
{"id":"1.5.1116.1226_dbc4e072","release":"1.5.0","assemblyVersion":"1.5.1116.1226","sha256":"dbc4e072c855",
 "importedUtc":"2026-11-16T17:26:28.526563Z","sizeBytes":151040,"good":true,"lastError":null}
```

All times are UTC (ISO 8601 with `Z`); convert them to local time in the UI. `good` means this version
has run successfully at least once. `lastError` is the error code of its last failed activation.

### hot:reload / hot:rollback

```json
{"type":"HOT","cmd":"reload","req_id":"r1","ok":true,"result":"reloaded",
 "from":{...version...},"to":{...version...},"rolledBackTo":null,"current":{...version...},"durationMs":233}
```

- `result`: `reloaded`, `unchanged` (that core was already running; `ok` is `true`), or `rolled_back` (rollback command).
- On failure, `ok` is `false` and the reply has `error` and `message`:

```json
{"type":"HOT","cmd":"reload","req_id":"r2","ok":false,"error":"start_failed",
 "message":"InvalidOperationException: ...","result":null,"from":{...v2...},"to":{...broken...},
 "rolledBackTo":{...v2...},"current":{...v2...},"durationMs":151}
```

| `error` | Meaning | Running core after it |
|---|---|---|
| `busy` | Another reload or rollback is running | unchanged |
| `disabled` | `HotReloadEnabled` is `false` | unchanged |
| `no_source` | No core file in `Updates/` or `Core/` | unchanged |
| `load_failed` | The file is not a .NET assembly, or the core could not be loaded | unchanged |
| `contract_mismatch` | The core was built for a different loader. Update the loader (restart). | unchanged |
| `selftest_failed` | The new core's self-test failed | unchanged |
| `start_failed` | The new core threw while starting | the previous core, loaded again (`rolledBackTo`) |
| `unknown_version` | `hot:rollback <id>` names a version that is not stored | unchanged |
| `no_previous` | `hot:rollback` with no earlier good version | unchanged |
| `bad_request` | Unknown command or bad JSON | unchanged |

### hot:versions

```json
{"type":"HOT","cmd":"versions","req_id":"v","ok":true,"current":"<id>","lastGood":"<id>",
 "versions":[{...version..., "current":true, "lastGood":true}, ...]}
```

The list is newest first.

### hot:status

```json
{"type":"HOT","cmd":"status","req_id":"st","ok":true,
 "loader":{"release":"1.5.0","assemblyVersion":"1.5.1116.1226","contract":1},
 "core":{"loaded":true,"version":{...},"isolation":"AppDomain","domain":"ZGB-Core-8",
         "loadedUtc":"2026-11-16T17:26:34.085413Z","uptimeSeconds":0,"gatewaySubscriptions":5,"gatewayHandles":5},
 "lastGood":"<id>","reloadInProgress":false,"hotReloadEnabled":true,"autoReloadOnDrop":false,
 "isolationSetting":"AppDomain","appDomainFallback":false,"dropFolder":"Updates","pendingDrop":false,
 "liveCoreDomains":1,"leakedInProcessAssemblies":0,"gameThreadTicking":true,
 "lastReload":{...history entry...},
 "history":[{"timeUtc":"...Z","trigger":"boot|command|auto","action":"boot|reload|rollback|recover",
             "from":"<id>","to":"<id>","ok":true,"error":null,"message":null,"durationMs":224,"isolation":"AppDomain"}, ...],
 "diagnostics":{"release":"1.5.0","domain":"ZGB-Core-8","legacyAttached":true,"updateTicking":true,
                "factionRequestsSent":1,"lastFactionRequestThreadId":3,"playerFactions":1,"players":1,"online":1,
                "serverView":{"enabled":true,"driver":"update","online":1,"runningPlayfields":1},
                "structures":3,"loadedPlayfields":["Akua"],"broadcaster":true,"liveProxies":4}}
```

`core` is `null` when no core is loaded (for example, every core failed at boot). The port stays open, so
ZAH can still use `hot:status`, `hot:versions` and `hot:rollback`. Other commands then reply
`{"type":"ERROR","message":"Bridge core is not loaded. ..."}`. `history` holds the last 20 entries, newest first.

### HOT_EVENT (broadcast to every authenticated client)

```json
{"type":"HOT_EVENT","event":"booted|reloaded|rolled_back|reload_failed","trigger":"boot|command|auto",
 "from":{...},"to":{...},"current":{...},"error":"start_failed: ...","timeUtc":"...Z"}
```

This is sent for every reload, rollback and failure, including auto reloads, so the UI can refresh without polling.

## How it works (for developers)

- net48 cannot unload an assembly, only an AppDomain. Each core gets its own AppDomain
  (`ZGB-Core-<n>`). Resolution of the game's assemblies (ModApi, Mif, Newtonsoft, UnityEngine.CoreModule)
  is set up by `CoreBootstrap`, which probes the folders of the assemblies the game already loaded.
- Live game objects cannot cross domains, and none of the game's data types (PlayerData,
  GlobalStructureInfo, Vector3, IdMsgPrio, FactionInfoList) are serializable. `GameGateway` (loader)
  keeps live objects in a handle table. `GatewayClient` (core) gives the core transparent proxies that
  implement the real Eleon interfaces, so the core code is unchanged. `Wire.cs` copies data types
  field by field. Delegates the core gives the game (event handlers, GetStructures callbacks) become
  callback sinks in the core domain.
- Gateway calls run on the caller's thread. There is no thread hop, so 1.4.2's threading rules hold:
  Request_Get_Factions only from Game_Start / Game_Update, and alerts on the game thread while it ticks.
  The server view still falls back to its telemetry thread when Application.Update does not fire.
- Every game event subscription a core makes is recorded. When that core unloads, anything it left behind is
  removed, so the game never calls into an unloaded domain.
- State is re-seeded rather than handed over. players.json is written on change. Factions are
  re-requested on the next Game_Update. The server view refreshes within 2 s. Loaded playfields are replayed.
- `IBridgeCore` / `IBridgeHost` / `IGameGateway` in `Loader/Contracts.cs` are the contract
  (`HotContract.Version` = 1). Changing them means a new loader (restart). The loader refuses a core
  built for another contract version.
