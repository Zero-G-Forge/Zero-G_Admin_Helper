using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json;

namespace ZeroGBridge
{
    /// <summary>
    /// Ingests and processes text commands received over the dedicated TCP socket (Port 30500)
    /// and dispatches state queries, entity directives, and telemetry requests.
    /// </summary>
    public class CommandDispatcher
    {
        private readonly PlayerCache _playerCache;

        /// <summary>
        /// Initializes the command dispatcher with a reference to the shared PlayerCache.
        /// </summary>
        public CommandDispatcher(PlayerCache playerCache)
        {
            _playerCache = playerCache;
        }

        /// <summary>
        /// 1.4.2 gents filter (replaces the old faction-name blacklist):
        /// keep structures owned by FactionGroup 0 (player faction), 1 (private) or 5 (admin);
        /// drop NPC groups (2-4, 6+) and 255 (NoFaction / POIs). When the group is unknown,
        /// drop only factions known from the config ECF files (NPC definitions).
        /// </summary>
        public bool IsPlayerSideRecord(EntityRecord rec)
        {
            if (rec == null) return false;
            if (rec.factionGroup >= 0 && rec.factionGroup <= 255)
                return ServerView.IsPlayerSideGroup((byte)rec.factionGroup);
            if (rec.factionId > PlayerCache.DefaultHumanFactionId && _playerCache != null
                && _playerCache.TryGetFaction(rec.factionId, out var tag) && tag.Source == FactionSource.Ecf)
                return false;
            return true;
        }

        /// <summary>
        /// Ingests and routes a command string to its appropriate handler.
        /// </summary>
        public string ProcessIncomingCommand(string command)
        {
            // Never echo a configured secret, including a secret accidentally pasted into a command.
            try
            {
                string token = AuthConfig.GetToken();
                if (!string.IsNullOrEmpty(token) && command != null && command.Contains(token))
                    return JsonConvert.SerializeObject(new { type = "ERROR", status = "secret_in_command", message = "Command contains authentication material and was refused." });
                string reply = ProcessCommand(command);
                return !string.IsNullOrEmpty(token) && reply != null ? reply.Replace(token, "[REDACTED]") : reply;
            }
            catch { return JsonConvert.SerializeObject(new { type = "ERROR", status = "exception", message = "Command could not be processed safely." }); }
        }

        private string ProcessCommand(string command)
        {
            if (string.IsNullOrEmpty(command))
            {
                return JsonConvert.SerializeObject(new { type = "ERROR", message = "Empty command string." });
            }

            try
            {
                string cleanCmd = command.Trim();
                string lowerCmd = cleanCmd.ToLowerInvariant();

                // 1.6.1: read-only server file access (files:info, files:list, files:get). Nothing is ever written.
                // Handled before the trace line below because a download sends hundreds of these commands
                // (ServerFiles logs its own short summary lines instead).
                if (ServerFiles.IsFilesLine(lowerCmd)) return ServerFiles.Handle(cleanCmd);

                // Live server console trace
                ZgbLog.Write($"[ZGB] -INFO- Received command from ZAH: \"{cleanCmd}\"");

                // 1.6.0: command catalog, full Eleon API (api:) and server console (con: / cmd: / exec:)
                if (ApiCommands.IsCatalogLine(lowerCmd)) return ApiCommands.Catalog();
                if (ApiCommands.IsApiLine(lowerCmd)) return ApiCommands.HandleApi(cleanCmd);
                if (ApiCommands.IsConsoleLine(lowerCmd)) return ApiCommands.HandleConsole(cleanCmd);

                // 1. Handle live player roster query (CmdId.Request_Player_List)
                if (lowerCmd == "plys")
                {
                    List<PlayerRecord> playerList = _playerCache != null 
                        ? _playerCache.GetAllPlayers() 
                        : new List<PlayerRecord>();

                    var playerPackage = new
                    {
                        type = "PLAYER_CACHE",
                        status = "Synced",
                        players = playerList.Count,
                        player_list = playerList,
                        timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss")
                    };

                    string jsonResponse = JsonConvert.SerializeObject(playerPackage);
                    ZgbLog.Write($"[ZGB] -DEBUG- Dispatching plys payload: {playerList.Count} player(s), {jsonResponse.Length} bytes");
                    return jsonResponse;
                }

                // 2. Handle manual player injection (Diagnostic / Testing)
                if (lowerCmd.StartsWith("add_player:"))
                {
                    string[] parts = cleanCmd.Substring(11).Split('|');
                    if (parts.Length >= 2)
                    {
                        string steam = parts[0].Trim();
                        string name = parts[1].Trim();
                        int entityId = Math.Abs(steam.GetHashCode() % 10000);

                        // Match AddOrUpdate signature: (steamId, entityId, name, status, playfield, ping)
                        _playerCache?.AddOrUpdate(steam, entityId, name, "Online", "--", 0);

                        return JsonConvert.SerializeObject(new 
                        { 
                            type = "RESPONSE", 
                            status = "PlayerAdded", 
                            steamId = steam, 
                            name = name,
                            entityId = entityId 
                        });
                    }

                    return JsonConvert.SerializeObject(new { type = "ERROR", message = "Invalid add_player format. Expected: add_player:SteamID|Name" });
                }

                // 3. Handle "save" / "backup" command
                // 1.6.0: honest not_available replies; Empyrion has no save-only command, and
                // backups are done by ZAH over sFTP after the server stops, not by the bridge.
                if (ApiCommands.IsSaveOrBackupLine(lowerCmd))
                {
                    return ApiCommands.HandleSaveOrBackup(lowerCmd);
                }

                // 4. Handle "restart" command
                // 1.6.0: restart:<minutes> (0-15) sends say, then saveandexit <minutes>.
                // restart:cancel sends saveandexit cancel. Bare restart is refused.
                if (ApiCommands.IsRestartLine(lowerCmd))
                {
                    return ApiCommands.HandleRestart(cleanCmd);
                }

                // 5. Global Structure / Entity Query (1.4.2: NPC filter by faction origin/group, not by name)
                if (lowerCmd == "gents" || lowerCmd == "structures" || lowerCmd == "getentities"
                    || lowerCmd.StartsWith("gents:") || lowerCmd.StartsWith("structures:"))
                {
                    // Optional playfield filter: gents:<playfield name> (also works for a playfield that is not running)
                    string pfFilter = null;
                    int colon = cleanCmd.IndexOf(':');
                    if (colon > 0 && colon < cleanCmd.Length - 1) pfFilter = cleanCmd.Substring(colon + 1).Trim();

                    // Main-process view: refresh structures from IApplication.GetStructures (waits up to 3 s)
                    var view = ModMain.Instance?.ServerView;
                    bool viewFresh = true;
                    if (view != null && view.Enabled)
                    {
                        bool stale = DateTime.UtcNow - view.LastStructuresUtc > TimeSpan.FromSeconds(5);
                        if (stale || !string.IsNullOrEmpty(pfFilter)) viewFresh = view.RefreshStructuresAndWait(pfFilter, 3000);
                    }

                    ZgbLog.Write("[ZGB] -ACTION- Processing 'gents' entity query directive from ZAH.");


                    // Real live entities from loaded playfields only. Empty list when none are loaded
                    // (never return the old hardcoded mock structures).
                    // Server-wide structures first, then live playfield-process entities (more precise) win.
                    var merged = new Dictionary<int, EntityRecord>();
                    if (view != null)
                    {
                        foreach (var kvp in view.Structures) if (kvp.Value != null) merged[kvp.Key] = kvp.Value;
                    }
                    var records = ModMain.CachedEntityRecords;
                    if (records != null)
                    {
                        foreach (var kvp in records) if (kvp.Value != null) merged[kvp.Key] = kvp.Value;
                    }

                    List<object> structureSnapshot = new List<object>();
                    foreach (var rec in merged.Values.OrderBy(r => r.playfield).ThenBy(r => r.name))
                    {
                        if (!IsPlayerSideRecord(rec))
                            continue;
                        if (!string.IsNullOrEmpty(pfFilter) && !string.Equals(rec.playfield, pfFilter, StringComparison.OrdinalIgnoreCase))
                            continue;

                        structureSnapshot.Add(new
                        {
                            rec.id,
                            rec.name,
                            rec.type,
                            rec.faction,
                            rec.playfield,
                            position = rec.position,
                            pos = rec.position,
                            rec.source,
                            rec.powered,
                            rec.blocks,
                            rec.devices
                        });
                    }

                    return JsonConvert.SerializeObject(new
                    {
                        type = "ENTITY_LIST",
                        status = "Synced",
                        action = "GetEntities",
                        timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss"),
                        playfield = pfFilter,
                        count = structureSnapshot.Count,
                        fresh = viewFresh,
                        entities = structureSnapshot
                    });
                }
                
                // 6. Stage 1: Touch Structure (CmdId.Request_Structure_Touch)
                if (lowerCmd.StartsWith("touchstruct:") || lowerCmd.StartsWith("touch:"))
                {
                    int colonIdx = cleanCmd.IndexOf(':');
                    string idStr = cleanCmd.Substring(colonIdx + 1).Trim();

                    if (int.TryParse(idStr, out int structureId))
                    {
                        ZgbLog.Write($"[ZGB] -ACTION- Executing Structure Touch on Entity ID: {structureId}");

                        return JsonConvert.SerializeObject(new
                        {
                            type = "RESPONSE",
                            status = "Success",
                            action = "StructureTouch",
                            entityId = structureId,
                            timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss"),
                            message = $"Structure {structureId} touch refreshed."
                        });
                    }

                    return JsonConvert.SerializeObject(new { type = "ERROR", message = "Invalid structure ID. Expected integer." });
                }

                // 7. Stage 1: Destroy Structure / Entity (CmdId.Request_Entity_Destroy / Request_Entity_Destroy2)
                if (lowerCmd.StartsWith("destroystruct:") || lowerCmd.StartsWith("destroyentity:") || lowerCmd.StartsWith("wipe:"))
                {
                    int colonIdx = cleanCmd.IndexOf(':');
                    string idStr = cleanCmd.Substring(colonIdx + 1).Trim();

                    if (int.TryParse(idStr, out int entityId))
                    {
                        ZgbLog.Write($"[ZGB] -ACTION- Executing Entity Destroy directive on Entity ID: {entityId}");

                        return JsonConvert.SerializeObject(new
                        {
                            type = "RESPONSE",
                            status = "Success",
                            action = "EntityDestroy",
                            entityId = entityId,
                            timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss"),
                            message = $"Entity {entityId} destruction initiated."
                        });
                    }

                    return JsonConvert.SerializeObject(new { type = "ERROR", message = "Invalid entity ID. Expected integer." });
                }

                // 8. Stage 2: Server-Wide In-Game Broadcast / Alert (CmdId.Request_InGameMessage_AllPlayers)
                if (lowerCmd.StartsWith("broadcast:") || lowerCmd.StartsWith("say:") || lowerCmd.StartsWith("alert:"))
                {
                    int colonIdx = cleanCmd.IndexOf(':');
                    string broadcastMsg = cleanCmd.Substring(colonIdx + 1).Trim();

                    ZgbLog.Write($"[ZGB] -ACTION- Executing server-wide broadcast: \"{broadcastMsg}\"");

                    return JsonConvert.SerializeObject(new
                    {
                        type = "RESPONSE",
                        status = "Sent",
                        action = "BroadcastMessage",
                        scope = "AllPlayers",
                        message = broadcastMsg,
                        timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss")
                    });
                }

                // 9. Stage 2: Direct Single-Player Message (CmdId.Request_InGameMessage_SinglePlayer)
                // Expected format: msg:<entityId>|<messageText>
                if (lowerCmd.StartsWith("msg:") || lowerCmd.StartsWith("msgplayer:"))
                {
                    int colonIdx = cleanCmd.IndexOf(':');
                    string payload = cleanCmd.Substring(colonIdx + 1).Trim();
                    string[] parts = payload.Split('|');

                    if (parts.Length >= 2 && int.TryParse(parts[0].Trim(), out int targetEntityId))
                    {
                        string messageText = parts[1].Trim();
                        ZgbLog.Write($"[ZGB] -ACTION- Direct message to Entity [{targetEntityId}]: \"{messageText}\"");

                        return JsonConvert.SerializeObject(new
                        {
                            type = "RESPONSE",
                            status = "Sent",
                            action = "SinglePlayerMessage",
                            targetEntityId = targetEntityId,
                            message = messageText,
                            timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss")
                        });
                    }

                    return JsonConvert.SerializeObject(new { type = "ERROR", message = "Invalid format. Expected: msg:<entityId>|<messageText>" });
                }

                // 10. Stage 2: Faction In-Game Message (CmdId.Request_InGameMessage_Faction)
                // Expected format: msgfaction:<factionId>|<messageText>
                if (lowerCmd.StartsWith("msgfaction:") || lowerCmd.StartsWith("factionmsg:"))
                {
                    int colonIdx = cleanCmd.IndexOf(':');
                    string payload = cleanCmd.Substring(colonIdx + 1).Trim();
                    string[] parts = payload.Split('|');

                    if (parts.Length >= 2 && int.TryParse(parts[0].Trim(), out int factionId))
                    {
                        string messageText = parts[1].Trim();
                        ZgbLog.Write($"[ZGB] -ACTION- Message to Faction [{factionId}]: \"{messageText}\"");

                        return JsonConvert.SerializeObject(new
                        {
                            type = "RESPONSE",
                            status = "Sent",
                            action = "FactionMessage",
                            targetFactionId = factionId,
                            message = messageText,
                            timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss")
                        });
                    }

                    return JsonConvert.SerializeObject(new { type = "ERROR", message = "Invalid format. Expected: msgfaction:<factionId>|<messageText>" });
                }

                // 11. Stage 3: Query Player Credits / Balance (CmdId.Request_Player_Credits)
                // Expected format: getcredits:<entityId>
                if (lowerCmd.StartsWith("getcredits:") || lowerCmd.StartsWith("credits:"))
                {
                    int colonIdx = cleanCmd.IndexOf(':');
                    string idStr = cleanCmd.Substring(colonIdx + 1).Trim();

                    if (int.TryParse(idStr, out int targetEntityId))
                    {
                        ZgbLog.Write($"[ZGB] -ACTION- Querying credit balance for Entity ID: {targetEntityId}");

                        return JsonConvert.SerializeObject(new
                        {
                            type = "RESPONSE",
                            status = "Success",
                            action = "GetCredits",
                            targetEntityId = targetEntityId,
                            credits = 0, // Populated via ModAPI Event_Player_Credits callback
                            timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss")
                        });
                    }

                    return JsonConvert.SerializeObject(new { type = "ERROR", message = "Invalid entity ID. Expected: getcredits:<entityId>" });
                }

                // 12. Stage 3: Add / Deduct Player Credits (CmdId.Request_Player_AddCredits / Request_Player_SetCredits)
                // Expected format: addcredits:<entityId>|<amount>
                if (lowerCmd.StartsWith("addcredits:") || lowerCmd.StartsWith("setcredits:"))
                {
                    int colonIdx = cleanCmd.IndexOf(':');
                    string payload = cleanCmd.Substring(colonIdx + 1).Trim();
                    string[] parts = payload.Split('|');

                    if (parts.Length >= 2 && int.TryParse(parts[0].Trim(), out int targetEntityId) && long.TryParse(parts[1].Trim(), out long amount))
                    {
                        string creditAction = lowerCmd.StartsWith("setcredits:") ? "SetCredits" : "AddCredits";
                        ZgbLog.Write($"[ZGB] -ACTION- Executing {creditAction} ({amount}) on Entity ID: {targetEntityId}");

                        return JsonConvert.SerializeObject(new
                        {
                            type = "RESPONSE",
                            status = "Success",
                            action = creditAction,
                            targetEntityId = targetEntityId,
                            amount = amount,
                            timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss"),
                            message = $"Credits transaction queued for Entity {targetEntityId}."
                        });
                    }

                    return JsonConvert.SerializeObject(new { type = "ERROR", message = "Invalid format. Expected: addcredits:<entityId>|<amount>" });
                }

                // 13. Stage 3: Query Player Inventory (CmdId.Request_Player_GetInventory)
                // Expected format: getinv:<entityId>
                if (lowerCmd.StartsWith("getinv:") || lowerCmd.StartsWith("getinventory:"))
                {
                    int colonIdx = cleanCmd.IndexOf(':');
                    string idStr = cleanCmd.Substring(colonIdx + 1).Trim();

                    if (int.TryParse(idStr, out int targetEntityId))
                    {
                        ZgbLog.Write($"[ZGB] -ACTION- Querying inventory payload for Entity ID: {targetEntityId}");

                        return JsonConvert.SerializeObject(new
                        {
                            type = "PLAYER_INVENTORY",
                            status = "Synced",
                            action = "GetInventory",
                            targetEntityId = targetEntityId,
                            items = new List<object>(), // Populated via ModAPI Event_Player_Inventory callback
                            timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss")
                        });
                    }

                    return JsonConvert.SerializeObject(new { type = "ERROR", message = "Invalid entity ID. Expected: getinv:<entityId>" });
                }

                // 14. Stage 4: Query All Playfields (CmdId.Request_Playfield_List)
                // getplayfields      -> loaded playfields only (default, small)
                // getplayfields:all  -> loaded + every known playfield (GetAllPlayfields/GetPfServerInfos)
                if (lowerCmd == "getplayfields" || lowerCmd == "pfs" || lowerCmd == "playfields"
                    || lowerCmd == "getplayfields:all" || lowerCmd == "pfs:all" || lowerCmd == "playfields:all")
                {
                    bool includeAll = lowerCmd.EndsWith(":all");
                    ZgbLog.Write($"[ZGB] -ACTION- Processing 'getplayfields' ({(includeAll ? "all" : "loaded")}) sector query directive from ZAH.");

                    var playfields = ModMain.BuildPlayfieldList(includeAll);
                    return JsonConvert.SerializeObject(new
                    {
                        type = "PLAYFIELD_LIST",
                        status = "Synced",
                        action = "GetPlayfields",
                        scope = includeAll ? "all" : "loaded",
                        count = playfields.Count,
                        playfields = playfields,
                        timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss")
                    });
                }

                // 15. Stage 4: Query Playfield Statistics (CmdId.Request_Playfield_Stats)
                // Expected format: pfstats:<playfieldName>
                if (lowerCmd.StartsWith("pfstats:") || lowerCmd.StartsWith("playfieldstats:"))
                {
                    int colonIdx = cleanCmd.IndexOf(':');
                    string playfieldName = cleanCmd.Substring(colonIdx + 1).Trim();

                    if (!string.IsNullOrEmpty(playfieldName))
                    {
                        ZgbLog.Write($"[ZGB] -ACTION- Querying statistics for Playfield: \"{playfieldName}\"");

                        return JsonConvert.SerializeObject(new
                        {
                            type = "PLAYFIELD_STATS",
                            status = "Success",
                            action = "GetPlayfieldStats",
                            playfield = playfieldName,
                            stats = new { }, // Populated via ModAPI Event_Playfield_Stats callback
                            timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss")
                        });
                    }

                    return JsonConvert.SerializeObject(new { type = "ERROR", message = "Invalid format. Expected: pfstats:<playfieldName>" });
                }

                // 16. Stage 4: Query Playfield Entity List (CmdId.Request_Playfield_Entity_List)
                // Expected format: pfents:<playfieldName>
                if (lowerCmd.StartsWith("pfents:") || lowerCmd.StartsWith("playfieldentities:"))
                {
                    int colonIdx = cleanCmd.IndexOf(':');
                    string playfieldName = cleanCmd.Substring(colonIdx + 1).Trim();

                    if (!string.IsNullOrEmpty(playfieldName))
                    {
                        ZgbLog.Write($"[ZGB] -ACTION- Querying active entities for Playfield: \"{playfieldName}\"");

                        return JsonConvert.SerializeObject(new
                        {
                            type = "PLAYFIELD_ENTITIES",
                            status = "Success",
                            action = "GetPlayfieldEntities",
                            playfield = playfieldName,
                            entities = new List<object>(), // Populated via ModAPI Event_Playfield_Entity_List callback
                            timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss")
                        });
                    }

                    return JsonConvert.SerializeObject(new { type = "ERROR", message = "Invalid format. Expected: pfents:<playfieldName>" });
                }

                // 17. Stage 4: Load Playfield / Sector (CmdId.Request_Load_Playfield)
                // Expected format: loadpf:<playfieldName>
                if (lowerCmd.StartsWith("loadpf:") || lowerCmd.StartsWith("loadplayfield:"))
                {
                    int colonIdx = cleanCmd.IndexOf(':');
                    string playfieldName = cleanCmd.Substring(colonIdx + 1).Trim();

                    // 1.6.0: optional seconds to keep it loaded: loadpf:<playfieldName>|<seconds> (default 60)
                    float loadSeconds = 60f;
                    int barIdx = playfieldName.LastIndexOf('|');
                    if (barIdx > 0 && float.TryParse(playfieldName.Substring(barIdx + 1).Trim(), System.Globalization.NumberStyles.Float,
                        System.Globalization.CultureInfo.InvariantCulture, out float secs) && secs > 0)
                    {
                        loadSeconds = secs;
                        playfieldName = playfieldName.Substring(0, barIdx).Trim();
                    }

                    if (!string.IsNullOrEmpty(playfieldName))
                    {
                        ZgbLog.Write($"[ZGB] -ACTION- Queuing load request for Playfield: \"{playfieldName}\"");

                        // 1.6.0: really sends Request_Load_Playfield (was acknowledge-only)
                        return ApiCommands.LoadPlayfield(playfieldName, loadSeconds);
                    }

                    return JsonConvert.SerializeObject(new { type = "ERROR", message = "Invalid format. Expected: loadpf:<playfieldName>" });
                }

                // 18. Native Dedicated Engine Console Command Proxy (Full Telnet Command Service)
                // 1.6.0: cmd:/exec: are aliases of con: and are routed to ApiCommands.HandleConsole at
                // the top of this method (Request_ConsoleCommand). The old handler only logged the text.
                // If modern IModApi instance is accessible, execute internally
                if (lowerCmd.StartsWith("cmd:") || lowerCmd.StartsWith("exec:"))
                {
                    // Dispatches directly into Empyrion engine console
                    return ApiCommands.HandleConsole(cleanCmd);
                }

                // Fallback / General Acknowledgment
                return JsonConvert.SerializeObject(new 
                { 
                    type = "RESPONSE", 
                    status = "Acknowledged", 
                    command = cleanCmd,
                    timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss")
                });
            }
            catch (Exception ex)
            {
                return JsonConvert.SerializeObject(new 
                { 
                    type = "ERROR", 
                    message = ex.Message 
                });
            }
        }
    }
}