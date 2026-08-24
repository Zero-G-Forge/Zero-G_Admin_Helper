using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace ZeroGBridge
{
    /// <summary>
    /// Processes incoming admin instructions received from connected client sockets
    /// and formats JSON response packages.
    /// </summary>
    public class CommandDispatcher
    {
        private readonly PlayerCache _playerCache;

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

                // 1. Handle live player roster query
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
                }

                // 3. Fallback / General Acknowledgment
                return JsonConvert.SerializeObject(new 
                { 
                    type = "RESPONSE", 
                    status = "Acknowledged", 
                    command = cleanCmd 
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