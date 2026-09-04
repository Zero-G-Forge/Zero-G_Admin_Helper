// =====================================================================
// MODULE: ZeroGBridge/Core/PlayerCache.cs
// DESCRIPTION: Thread-Safe Master Player State & Telemetry Bridge
// =====================================================================

using System;
using System.IO;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json;
using Mono.Data.Sqlite;

namespace ZeroGBridge
{
    #region Data Contract Stubs (Matching Eleon.Modding Schemas)

    public struct PVector3
    {
        public float x;
        public float y;
        public float z;
    }

    public class PlayerInfo
    {
        public int entityId;
        public string steamId;
        public string playerName;
        public string playfield;
        public int factionId;
        public int ping;
        public PVector3 pos;
    }

    public struct FactionInfo
    {
        public int factionId;
        public string name;
        public string abbrev;
        public byte origin;
    }

    public class FactionInfoList
    {
        public List<FactionInfo> factions;
    }

    public struct GlobalStructureInfo
    {
        public int id;
        public string name;
        public int type; // 2=BA, 4=CV, 8=SV, 16=HV
        public int factionId;
        public int playfieldId;
        public PVector3 pos;
    }

    public class GlobalStructureList
    {
        public Dictionary<string, List<GlobalStructureInfo>> globalEntities { get; set; } = new Dictionary<string, List<GlobalStructureInfo>>();
    }

    #endregion

    /// <summary>
    /// Encapsulates the complete modern player schema matching ZAH requirements.
    /// </summary>
    public class PlayerRecord
    {
        public string name { get; set; } = "Unknown";
        public string steamId { get; set; } = "--";
        public string entityId { get; set; } = "--";
        public string status { get; set; } = "Offline";
        public string faction { get; set; } = "--";
        public string role { get; set; } = "Member";
        public string playfield { get; set; } = "--";
        public string solar_system { get; set; } = "Unknown";
        public string coordinates { get; set; } = "-";
        public string cheat { get; set; } = "Off";
        public string cheater { get; set; } = "No";
        public string banned { get; set; } = "No";
        public string auto_ban_protection { get; set; } = "Active";
        public Dictionary<string, object> stats { get; set; } = new Dictionary<string, object>
        {
            { "playtime", "0h" },
            { "bases", 0 },
            { "ships", 0 }
        };
        public Dictionary<string, object> inventory { get; set; } = new Dictionary<string, object>();
        public string last_seen { get; set; } = "";
        public int ping { get; set; } = 0;
    }

    /// <summary>
    /// Thread-safe in-memory cache managing connected and historical player records.
    /// Bridges runtime engine telemetry, savegame crawlers, and TCP Port 30500 broadcasts.
    /// </summary>
    public class PlayerCache
    {
        // Thread-safe dictionary storing all player entities indexed by primary Steam ID
        private readonly ConcurrentDictionary<string, PlayerRecord> _allPlayers = new ConcurrentDictionary<string, PlayerRecord>();
        
        // Faction lookup cache: maps numerical FactionId -> FactionInfo
        private readonly ConcurrentDictionary<int, FactionInfo> _factionLookup = new ConcurrentDictionary<int, FactionInfo>();

        private readonly string _cacheFilePath;
        private readonly object _diskLock = new object();

        public PlayerCache()
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string storageDir = Path.Combine(baseDir, "Logs", "ZeroGBridge");
            if (!Directory.Exists(storageDir))
            {
                Directory.CreateDirectory(storageDir);
            }
            _cacheFilePath = Path.Combine(storageDir, "players.json");

            LoadFromDisk();
            ScanSaveGameDatabase(baseDir);
        }

        public int TotalCount => _allPlayers.Count;
        public int OnlineCount => _allPlayers.Values.Count(p => p.status == "Online");

        // ---------------------------------------------------------------------
        // AddOrUpdate Ingestion Handlers (LogParser & CommandDispatcher compatibility)
        // ---------------------------------------------------------------------
        public void AddOrUpdate(string steamId, int entityId, string name, string status = "Online", string playfield = "--", int ping = 0)
        {
            string key = (!string.IsNullOrEmpty(steamId) && steamId != "--") ? steamId : (!string.IsNullOrEmpty(name) && !name.StartsWith("Player_") ? name : entityId.ToString());

            var record = _allPlayers.GetOrAdd(key, k => new PlayerRecord());

            if (!string.IsNullOrEmpty(name) && !name.StartsWith("Player_")) record.name = name;
            if (!string.IsNullOrEmpty(steamId) && steamId != "--") record.steamId = steamId;
            if (entityId > 0) record.entityId = entityId.ToString();
            if (!string.IsNullOrEmpty(playfield) && playfield != "--") record.playfield = playfield;

            record.status = status;
            record.ping = ping;
            record.last_seen = DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss");

            SaveToDisk();
        }

        public void AddOrUpdate(PlayerRecord record)
        {
            if (record == null) return;
            string key = (!string.IsNullOrEmpty(record.steamId) && record.steamId != "--") ? record.steamId : record.name;
            _allPlayers[key] = record;
            SaveToDisk();
        }

        // ---------------------------------------------------------------------
        // PlayerInfo Ingestion Handler
        // ---------------------------------------------------------------------
        public void UpdateFromPlayerInfo(PlayerInfo info)
        {
            if (info == null) return;

            string steamId = info.steamId ?? "";
            string eidStr = info.entityId.ToString();
            string playerName = info.playerName ?? "";

            PlayerRecord record = null;
            if (!string.IsNullOrEmpty(steamId) && steamId != "--")
            {
                _allPlayers.TryGetValue(steamId, out record);
            }

            if (record == null)
            {
                record = _allPlayers.Values.FirstOrDefault(p => p.entityId == eidStr || p.steamId == steamId);
            }

            if (record == null)
            {
                string key = !string.IsNullOrEmpty(steamId) ? steamId : eidStr;
                record = new PlayerRecord();
                _allPlayers[key] = record;
            }

            if (!string.IsNullOrEmpty(playerName) && !playerName.StartsWith("Player_"))
            {
                record.name = playerName;
            }
            if (!string.IsNullOrEmpty(steamId)) record.steamId = steamId;
            record.entityId = eidStr;
            record.status = "Online";
            record.playfield = !string.IsNullOrEmpty(info.playfield) ? info.playfield : record.playfield;
            record.ping = info.ping;
            record.coordinates = $"{info.pos.x:F0}, {info.pos.y:F0}, {info.pos.z:F0}";
            record.last_seen = DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss");

            if (info.factionId > 0 && _factionLookup.TryGetValue(info.factionId, out FactionInfo fac))
            {
                record.faction = !string.IsNullOrEmpty(fac.abbrev) ? fac.abbrev : fac.name;
            }

            SaveToDisk();
        }

        // ---------------------------------------------------------------------
        // FactionInfoList Ingestion Handler
        // ---------------------------------------------------------------------
        public void UpdateFromFactionList(FactionInfoList factionList)
        {
            if (factionList?.factions == null) return;

            foreach (var fac in factionList.factions)
            {
                _factionLookup[fac.factionId] = fac;

                string facTag = !string.IsNullOrEmpty(fac.abbrev) ? fac.abbrev : fac.name;

                if (fac.origin > 0)
                {
                    var founder = _allPlayers.Values.FirstOrDefault(p => p.entityId == fac.origin.ToString());
                    if (founder != null)
                    {
                        founder.faction = facTag;
                        founder.role = "Founder";
                    }
                }
            }

            SaveToDisk();
        }

        // ---------------------------------------------------------------------
        // GlobalStructureList Ingestion Handler
        // ---------------------------------------------------------------------
        public void UpdateFromGlobalStructures(GlobalStructureList structList)
        {
            if (structList?.globalEntities == null) return;

            var baseCounts = new Dictionary<string, int>();
            var shipCounts = new Dictionary<string, int>();

            foreach (var kvp in structList.globalEntities)
            {
                if (kvp.Value == null) continue;

                foreach (var s in kvp.Value)
                {
                    string ownerId = s.id.ToString();
                    int type = s.type; // 2=BA, 4=CV, 8=SV, 16=HV

                    if (type == 2)
                    {
                        baseCounts[ownerId] = baseCounts.ContainsKey(ownerId) ? baseCounts[ownerId] + 1 : 1;
                    }
                    else if (type == 4 || type == 8 || type == 16)
                    {
                        shipCounts[ownerId] = shipCounts.ContainsKey(ownerId) ? shipCounts[ownerId] + 1 : 1;
                    }
                }
            }

            foreach (var p in _allPlayers.Values)
            {
                int bases = baseCounts.ContainsKey(p.entityId) ? baseCounts[p.entityId] : 0;
                int ships = shipCounts.ContainsKey(p.entityId) ? shipCounts[p.entityId] : 0;

                p.stats["bases"] = bases;
                p.stats["ships"] = ships;
            }

            SaveToDisk();
        }

        public void MarkOffline(string identifier)
        {
            if (string.IsNullOrEmpty(identifier)) return;

            var target = _allPlayers.Values.FirstOrDefault(p =>
                p.steamId == identifier ||
                string.Equals(p.name, identifier, StringComparison.OrdinalIgnoreCase) ||
                p.entityId == identifier);

            if (target != null)
            {
                target.status = "Offline";
                target.last_seen = DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss");
                SaveToDisk();
            }
        }

        public List<PlayerRecord> GetAllPlayers() => new List<PlayerRecord>(_allPlayers.Values);
        public List<PlayerRecord> GetOnlinePlayers() => _allPlayers.Values.Where(p => p.status == "Online").ToList();

        /// <summary>
        /// Scans the dedicated server savegame SQLite database to resolve real
        /// player names, Steam IDs, Entity IDs, and faction assignments offline.
        /// </summary>
        private void ScanSaveGameDatabase(string baseDir)
        {
            try
            {
                // Locate the active savegame folder
                string[] possibleDbPaths = new string[]
                {
                    Path.Combine(baseDir, "Saves", "Games", "Zero-G Server", "game.db"),
                    Path.Combine(Directory.GetParent(baseDir)?.FullName ?? baseDir, "Saves", "Games", "Zero-G Server", "game.db")
                };

                string dbFile = null;
                foreach (var path in possibleDbPaths)
                {
                    if (File.Exists(path))
                    {
                        dbFile = path;
                        break;
                    }
                }

                if (string.IsNullOrEmpty(dbFile))
                {
                    Console.WriteLine("[ZGB] -WARN- game.db not found for offline player resolution.");
                    return;
                }

                // URI mode with read-only flag prevents file lock conflicts with the running server
                string connString = $"URI=file:{dbFile},version=3,Read Only=True;";

                using (var connection = new SqliteConnection(connString))
                {
                    connection.Open();

                    // Query real player identifiers from the game's internal table
                    string query = "SELECT steamId, entityId, name, factionId FROM Players;";

                    using (var command = new SqliteCommand(query, connection))
                    using (var reader = command.ExecuteReader())
                    {
                        int loadedCount = 0;
                        while (reader.Read())
                        {
                            string steamId = reader.IsDBNull(0) ? "" : reader.GetString(0);
                            int entityId = reader.IsDBNull(1) ? 0 : reader.GetInt32(1);
                            string realName = reader.IsDBNull(2) ? "" : reader.GetString(2);
                            int factionId = reader.IsDBNull(3) ? 0 : reader.GetInt32(3);

                            if (!string.IsNullOrEmpty(steamId) && steamId.Length == 17)
                            {
                                // Ingest without generic Player_XXXX placeholders
                                AddOrUpdate(steamId, entityId, realName, "Offline", "--", 0);
                                loadedCount++;
                            }
                        }

                        Console.WriteLine($"[ZGB] -INFO- Successfully hydrated {loadedCount} player record(s) from game.db.");
                    }
                }

                SaveToDisk();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -WARN- SQLite database scan exception: {ex.Message}");
            }
        }

        private void LoadFromDisk()
        {
            try
            {
                lock (_diskLock)
                {
                    if (File.Exists(_cacheFilePath))
                    {
                        string json = File.ReadAllText(_cacheFilePath);
                        var loaded = JsonConvert.DeserializeObject<List<PlayerRecord>>(json);
                        if (loaded != null)
                        {
                            foreach (var p in loaded)
                            {
                                p.status = "Offline";
                                string key = !string.IsNullOrEmpty(p.steamId) && p.steamId != "--" ? p.steamId : p.name;
                                _allPlayers[key] = p;
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -WARN- Could not load players.json: {ex.Message}");
            }
        }

        private void SaveToDisk()
        {
            try
            {
                lock (_diskLock)
                {
                    string json = JsonConvert.SerializeObject(_allPlayers.Values.ToList(), Formatting.Indented);
                    File.WriteAllText(_cacheFilePath, json);
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -WARN- Could not write players.json: {ex.Message}");
            }
        }
    }
}