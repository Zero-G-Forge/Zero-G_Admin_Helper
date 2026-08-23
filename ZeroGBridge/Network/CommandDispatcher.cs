using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace ZeroGBridge
{
    /// <summary>
    /// Processes incoming text commands received over the dedicated TCP socket (Port 30500)
    /// and dispatches appropriate state updates to the in-memory PlayerCache.
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
        /// Ingests and processes raw command strings, returning a serialized JSON response.
        /// </summary>
        public string ProcessCommand(string command)
        {
            if (string.IsNullOrEmpty(command))
            {
                return JsonConvert.SerializeObject(new { type = "ERROR", message = "Empty command string received." });
            }

            try
            {
                string cleanCmd = command.Trim().ToLower();

                // 1. Handle manual player injection (format: add_player:SteamID|PlayerName)
                if (cleanCmd.StartsWith("add_player:"))
                {
                    string[] parts = command.Substring(11).Split('|');
                    if (parts.Length >= 2)
                    {
                        string steam = parts[0].Trim();
                        string name = parts[1].Trim();
                        int entityId = steam.GetHashCode();

                        _playerCache?.AddOrUpdate(steam, name, entityId, 0);
                        Console.WriteLine($"[ZGB] -INFO- Manual cache registration: {name} (Steam: {steam})");

                        return JsonConvert.SerializeObject(new 
                        { 
                            type = "RESPONSE", 
                            status = "PlayerAdded", 
                            steamId = steam, 
                            name = name 
                        });
                    }

                    return JsonConvert.SerializeObject(new { type = "ERROR", message = "Invalid add_player format. Expected: add_player:SteamID|Name" });
                }

                // 2. Handle active player cache synchronization request
                if (cleanCmd == "plys")
                {
                    var playerList = _playerCache != null ? _playerCache.GetAllPlayers() : new List<PlayerRecord>();
                    var playerPackage = new
                    {
                        type = "PLAYER_CACHE",
                        status = "Synced",
                        players = playerList.Count.ToString(),
                        player_list = playerList,
                        timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss")
                    };

                    return JsonConvert.SerializeObject(playerPackage);
                }

                // 3. Handle proxied server commands (format: cmd:command_string)
                if (cleanCmd.StartsWith("cmd:"))
                {
                    string innerCommand = command.Substring(4).Trim();
                    Console.WriteLine($"[ZGB] -INFO- Executing proxied command: {innerCommand}");

                    return JsonConvert.SerializeObject(new 
                    { 
                        type = "RESPONSE", 
                        status = "Executed", 
                        command = innerCommand 
                    });
                }

                // Default fallback acknowledgment
                return JsonConvert.SerializeObject(new 
                { 
                    type = "RESPONSE", 
                    status = "Acknowledged", 
                    command = command 
                });
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -ERROR- Exception in CommandDispatcher.ProcessCommand: {ex.Message}");
                return JsonConvert.SerializeObject(new { type = "ERROR", message = ex.Message });
            }
        }
    }
}