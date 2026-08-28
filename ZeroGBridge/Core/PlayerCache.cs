using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;

namespace ZeroGBridge
{
    /// <summary>
    /// Structural representation of a player record supporting online and offline tracking.
    /// </summary>
    public class PlayerRecord
    {
        public int entityId { get; set; }
        public string steamId { get; set; }
        public string name { get; set; }
        public string status { get; set; } = "Offline";
        public string faction { get; set; } = "--";
        public string playfield { get; set; } = "--";
        public int ping { get; set; } = 0;
        public string lastSeen { get; set; }
    }

    /// <summary>
    /// Thread-safe in-memory cache retaining all known server players across sessions.
    /// </summary>
    public class PlayerCache
    {
        private readonly ConcurrentDictionary<string, PlayerRecord> _allPlayers = new ConcurrentDictionary<string, PlayerRecord>();

        /// <summary>
        /// Total count of all known registered players.
        /// </summary>
        public int TotalCount => _allPlayers.Count;

        /// <summary>
        /// Count of currently online players.
        /// </summary>
        public int OnlineCount => _allPlayers.Values.Count(p => p.status == "Online");

        /// <summary>
        /// Marks a player as Online and updates their metadata.
        /// </summary>
        public void AddOrUpdate(string steamId, string name, int entityId, int ping = 0, string faction = "--", string playfield = "--")
        {
            if (string.IsNullOrEmpty(steamId)) return;

            _allPlayers.AddOrUpdate(steamId,
                // If brand new player record:
                new PlayerRecord
                {
                    entityId = entityId,
                    steamId = steamId,
                    name = name,
                    status = "Online",
                    faction = faction,
                    playfield = playfield,
                    ping = ping,
                    lastSeen = DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss")
                },
                // If existing player record:
                (key, existing) =>
                {
                    existing.name = !string.IsNullOrEmpty(name) ? name : existing.name;
                    existing.entityId = entityId != 0 ? entityId : existing.entityId;
                    existing.status = "Online";
                    existing.ping = ping;
                    if (faction != "--") existing.faction = faction;
                    if (playfield != "--") existing.playfield = playfield;
                    existing.lastSeen = DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss");
                    return existing;
                });
        }

        /// <summary>
        /// Marks a player as Offline without deleting their record from the roster.
        /// </summary>
        public bool MarkOffline(string identifier)
        {
            if (string.IsNullOrEmpty(identifier)) return false;

            // 1. Direct SteamID match
            if (_allPlayers.TryGetValue(identifier, out PlayerRecord record))
            {
                record.status = "Offline";
                record.ping = 0;
                record.lastSeen = DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss");
                return true;
            }

            // 2. Fallback match by Name or Entity ID
            var target = _allPlayers.Values.FirstOrDefault(p =>
                string.Equals(p.name, identifier, StringComparison.OrdinalIgnoreCase) ||
                p.entityId.ToString() == identifier);

            if (target != null)
            {
                target.status = "Offline";
                target.ping = 0;
                target.lastSeen = DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss");
                return true;
            }

            return false;
        }

        /// <summary>
        /// Returns all tracked players (both online and offline).
        /// </summary>
        public List<PlayerRecord> GetAllPlayers()
        {
            return new List<PlayerRecord>(_allPlayers.Values);
        }

        /// <summary>
        /// Returns only active online players.
        /// </summary>
        public List<PlayerRecord> GetOnlinePlayers()
        {
            return _allPlayers.Values.Where(p => p.status == "Online").ToList();
        }
    }
}