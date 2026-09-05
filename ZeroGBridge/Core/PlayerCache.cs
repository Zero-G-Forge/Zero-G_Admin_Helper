// =====================================================================
// MODULE: ZeroGBridge/Core/PlayerCache.cs
// DESCRIPTION: Thread-Safe Master Player State & Telemetry Bridge
// =====================================================================

using System;
using System.IO;
using System.Data;
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

            Console.WriteLine("[ZGB] -DEBUG- PlayerCache initializing...");

            // Step 1: Load disk cache if present
            LoadFromDisk();
            Console.WriteLine($"[ZGB] -DEBUG- After LoadFromDisk: {_allPlayers.Count} players in memory.");

            // Step 2: Trigger safe database scan
            SafeScanDatabase(baseDir);
            Console.WriteLine($"[ZGB] -DEBUG- After DatabaseScan: {_allPlayers.Count} players in memory.");
        }

        public int TotalCount => _allPlayers.Count;
        public int OnlineCount => _allPlayers.Values.Count(p => p.status == "Online");

        // ---------------------------------------------------------------------
        // AddOrUpdate Ingestion Handlers (LogParser & CommandDispatcher compatibility)
        // ---------------------------------------------------------------------
        public void AddOrUpdate(string steamId, int entityId, string name, string status = "Online", string playfield = "--", int ping = 0)
        {
            string key = (!string.IsNullOrEmpty(steamId) && steamId != "--") 
                ? steamId 
                : (!string.IsNullOrEmpty(name) && !name.StartsWith("Player_") ? name : entityId.ToString());

            var record = _allPlayers.GetOrAdd(key, k => new PlayerRecord());

            // Update name only if incoming value is valid and not a generic placeholder
            if (!string.IsNullOrEmpty(name) && !name.StartsWith("Player_"))
            {
                record.name = name;
            }
            else if (string.IsNullOrEmpty(record.name) || record.name == "Unknown")
            {
                record.name = name;
            }

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
        // PlayerInfo Ingestion Handler (Live Engine Telemetry)
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

        #region Database Hydration

        /// <summary>
        /// Safely invokes the SQLite database scanner with full diagnostic logging
        /// and assembly load exception trapping.
        /// </summary>
        private void SafeScanDatabase(string baseDir)
        {
            try
            {
                Console.WriteLine("[ZGB] -INFO- Executing SafeScanDatabase...");
                ScanSaveGameDatabase(baseDir);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -ERROR- SafeScanDatabase critical failure: {ex.GetType().Name} - {ex.Message}");
                if (ex.InnerException != null)
                {
                    Console.WriteLine($"[ZGB] -ERROR- Inner Exception: {ex.InnerException.Message}");
                }
            }
        }

        /// <summary>
        /// Queries the dedicated server global.db to resolve real player names,
        /// Steam IDs, Entity IDs, playfields, coordinates, and playtime metrics.
        /// </summary>
        private void ScanSaveGameDatabase(string baseDir)
        {
            string tempDb = null;
            try
            {
                string currentDir = Directory.GetCurrentDirectory();
                Console.WriteLine($"[ZGB] -DEBUG- BaseDirectory is: {baseDir}");
                Console.WriteLine($"[ZGB] -DEBUG- CurrentDirectory is: {currentDir}");

                string parentBase = Directory.GetParent(baseDir)?.FullName ?? baseDir;
                string parentCur = Directory.GetParent(currentDir)?.FullName ?? currentDir;

                List<string> candidateFiles = new List<string>
                {
                    Path.Combine(parentCur, "Saves", "Games", "Zero-G Server", "global.db"),
                    Path.Combine(currentDir, "Saves", "Games", "Zero-G Server", "global.db"),
                    Path.Combine(parentBase, "Saves", "Games", "Zero-G Server", "global.db"),
                    Path.Combine(baseDir, "Saves", "Games", "Zero-G Server", "global.db"),
                    @"D:\66.23.236.138_30000\Saves\Games\Zero-G Server\global.db"
                };

                string resolvedDb = null;
                foreach (var path in candidateFiles)
                {
                    string fullPath = Path.GetFullPath(path);
                    Console.WriteLine($"[ZGB] -DEBUG- Checking path: {fullPath}");
                    if (File.Exists(fullPath))
                    {
                        resolvedDb = fullPath;
                        Console.WriteLine($"[ZGB] -SUCCESS- Located database at: {resolvedDb}");
                        break;
                    }
                }

                if (string.IsNullOrEmpty(resolvedDb))
                {
                    Console.WriteLine("[ZGB] -WARN- Unable to locate global.db across any candidate paths.");
                    return;
                }

                // 1. Create a local working directory in the server root
                string tempDir = Path.Combine(currentDir, "Logs", "ZeroGBridge");
                if (!Directory.Exists(tempDir))
                {
                    Directory.CreateDirectory(tempDir);
                }

                tempDb = Path.Combine(tempDir, "temp_scan.db");
                if (File.Exists(tempDb))
                {
                    try { File.Delete(tempDb); } catch { }
                }

                // 2. Stream-copy with FileShare.ReadWrite to bypass Empyrion's active file locks
                using (var sourceStream = new FileStream(resolvedDb, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                using (var destStream = new FileStream(tempDb, FileMode.Create, FileAccess.Write, FileShare.None))
                {
                    sourceStream.CopyTo(destStream);
                }

                // 3. Connect using standard SQLite parameters with journaling in memory
                string connString = $"Data Source={tempDb};Version=3;Journal Mode=Memory;Pooling=False;";

                using (var connection = new SqliteConnection(connString))
                {
                    connection.Open();

                    string query = @"
                        SELECT 
                            l.playerid AS steamId,
                            l.entityid AS entityId,
                            l.playername AS playerName,
                            COALESCE(e.facid, 0) AS factionId,
                            COALESCE(pf.name, '--') AS playfield,
                            COALESCE(e.posx, 0.0) AS posx,
                            COALESCE(e.posy, 0.0) AS posy,
                            COALESCE(e.posz, 0.0) AS posz,
                            COALESCE(ps.playtime, 0.0) AS playtime
                        FROM LoginLogoff l
                        INNER JOIN (
                            SELECT playerid, MAX(lid) AS max_lid
                            FROM LoginLogoff
                            WHERE playerid LIKE '7656%'
                            GROUP BY playerid
                        ) latest ON l.playerid = latest.playerid AND l.lid = latest.max_lid
                        LEFT JOIN Entities e ON l.entityid = e.entityid
                        LEFT JOIN Playfields pf ON e.pfid = pf.pfid
                        LEFT JOIN PlayerStatistics ps ON l.entityid = ps.entityid;";

                    using (var cmd = new SqliteCommand(query, connection))
                    using (var reader = cmd.ExecuteReader())
                    {
                        int count = 0;
                        while (reader.Read())
                        {
                            string steamId = reader.IsDBNull(0) ? "" : reader.GetString(0).Trim();
                            int entityId = reader.IsDBNull(1) ? 0 : Convert.ToInt32(reader.GetValue(1));
                            string realName = reader.IsDBNull(2) ? "Unknown" : reader.GetString(2).Trim();
                            int factionId = reader.IsDBNull(3) ? 0 : Convert.ToInt32(reader.GetValue(3));
                            string playfield = reader.IsDBNull(4) ? "--" : reader.GetString(4);

                            float px = reader.IsDBNull(5) ? 0f : Convert.ToSingle(reader.GetValue(5));
                            float py = reader.IsDBNull(6) ? 0f : Convert.ToSingle(reader.GetValue(6));
                            float pz = reader.IsDBNull(7) ? 0f : Convert.ToSingle(reader.GetValue(7));
                            double playtimeSec = reader.IsDBNull(8) ? 0.0 : Convert.ToDouble(reader.GetValue(8));

                            if (!string.IsNullOrEmpty(steamId) && steamId.Length == 17)
                            {
                                string coords = (px != 0f || py != 0f || pz != 0f) ? $"{px:F0}, {py:F0}, {pz:F0}" : "-";
                                int hours = (int)(playtimeSec / 3600.0);
                                string playtimeStr = $"{hours}h";

                                var record = _allPlayers.GetOrAdd(steamId, k => new PlayerRecord());
                                record.steamId = steamId;
                                record.entityId = entityId.ToString();
                                record.name = realName;
                                record.status = "Offline";
                                record.playfield = playfield;
                                record.coordinates = coords;
                                record.stats["playtime"] = playtimeStr;

                                if (factionId > 0 && _factionLookup.TryGetValue(factionId, out FactionInfo fac))
                                {
                                    record.faction = !string.IsNullOrEmpty(fac.abbrev) ? fac.abbrev : fac.name;
                                }

                                count++;
                            }
                        }

                        Console.WriteLine($"[ZGB] -INFO- Successfully hydrated {count} player record(s) from global.db.");
                    }
                }

                SaveToDisk();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -ERROR- Failed to query global.db: {ex.Message}\n{ex.StackTrace}");
            }
            finally
            {
                if (!string.IsNullOrEmpty(tempDb) && File.Exists(tempDb))
                {
                    try { File.Delete(tempDb); } catch { }
                }
            }
        }

        #endregion

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