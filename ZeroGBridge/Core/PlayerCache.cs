using System.Collections.Concurrent;
using System.Collections.Generic;

namespace ZeroGBridge
{
    /// <summary>
    /// Encapsulates the structural representation of an active connected player.
    /// </summary>
    public class PlayerRecord
    {
        public int entityId { get; set; }
        public string steamId { get; set; }
        public string name { get; set; }
        public int ping { get; set; }
    }

    /// <summary>
    /// Thread-safe in-memory cache managing connected player records.
    /// Isolated from file streams and network sockets.
    /// </summary>
    public class PlayerCache
    {
        private readonly ConcurrentDictionary<string, PlayerRecord> _activePlayers = new ConcurrentDictionary<string, PlayerRecord>();

        /// <summary>
        /// Gets the current count of online players.
        /// </summary>
        public int Count => _activePlayers.Count;

        /// <summary>
        /// Adds a new player or updates an existing player record in memory.
        /// </summary>
        public void AddOrUpdate(string steamId, string name, int entityId, int ping = 0)
        {
            if (string.IsNullOrEmpty(steamId)) return;

            var record = new PlayerRecord
            {
                entityId = entityId,
                steamId = steamId,
                name = name,
                ping = ping
            };

            _activePlayers[steamId] = record;
        }

        /// <summary>
        /// Removes a player record from memory by SteamID.
        /// </summary>
        public bool Remove(string steamId)
        {
            if (string.IsNullOrEmpty(steamId)) return false;
            return _activePlayers.TryRemove(steamId, out _);
        }

        /// <summary>
        /// Returns a snapshot copy of all active player records for telemetry serialization.
        /// </summary>
        public List<PlayerRecord> GetAllPlayers()
        {
            return new List<PlayerRecord>(_activePlayers.Values);
        }

        /// <summary>
        /// Clears all active player records from memory.
        /// </summary>
        public void Clear()
        {
            _activePlayers.Clear();
        }
    }
}