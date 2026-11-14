// =====================================================================
// MODULE: ZeroGBridge/Core/PlayerCache.cs
// DESCRIPTION: Modern API v2 Ingestion & Faction Resolver
// =====================================================================

using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Collections.Generic;
using System.Collections.Concurrent;
using Newtonsoft.Json;
using Mono.Data.Sqlite;
using Eleon.Modding;

namespace ZeroGBridge
{
    public class PlayerRecord
    {
        public string name { get; set; } = "Unknown";
        public string steamId { get; set; } = "--";
        public string entityId { get; set; } = "--";
        public int factionId { get; set; } = 0;
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

    public class FactionTag
    {
        public int FactionId { get; set; }
        public string Abbrev { get; set; } = "--";
        public string Name { get; set; } = "--";
    }

    /// <summary>
    /// Thread-safe in-memory cache managing player records and resolving dynamic faction tags.
    /// </summary>
    public class PlayerCache
    {
        private readonly ConcurrentDictionary<string, PlayerRecord> _allPlayers = new ConcurrentDictionary<string, PlayerRecord>();
        private readonly ConcurrentDictionary<int, FactionTag> _factionLookup = new ConcurrentDictionary<int, FactionTag>();
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

            // Seed primary persistent factions
            RegisterServerFactions();

            Console.WriteLine("[ZGB] -DEBUG- PlayerCache initializing (Pure API v2)...");

            LoadFromDisk();
            Console.WriteLine($"[ZGB] -DEBUG- After LoadFromDisk: {_allPlayers.Count} players in memory.");

            SafeScanDatabase(baseDir);
            Console.WriteLine($"[ZGB] -DEBUG- After DatabaseScan: {_allPlayers.Count} players in memory.");
        }

        public int TotalCount => _allPlayers.Count;
        public int OnlineCount => _allPlayers.Values.Count(p => p.status == "Online");

        private void RegisterServerFactions()
        {
            // Seed verified persistent server factions
            _factionLookup[1]   = new FactionTag { FactionId = 1,   Abbrev = "Hum", Name = "Human" };
            _factionLookup[100] = new FactionTag { FactionId = 100, Abbrev = "MEC", Name = "The Mechanics" };
            _factionLookup[101] = new FactionTag { FactionId = 101, Abbrev = "TCS", Name = "Tin Can Sailors" };
            _factionLookup[102] = new FactionTag { FactionId = 102, Abbrev = "=A=", Name = "Ascension Alliance" };
            _factionLookup[103] = new FactionTag { FactionId = 103, Abbrev = "GoG", Name = "Grumpy Old Gits" };
            _factionLookup[104] = new FactionTag { FactionId = 104, Abbrev = "VII", Name = "Legio VII" };
            _factionLookup[105] = new FactionTag { FactionId = 105, Abbrev = "Gru", Name = "GrumpyOldMen" };
            _factionLookup[106] = new FactionTag { FactionId = 106, Abbrev = "KTV", Name = "Knights Templar" };
            _factionLookup[107] = new FactionTag { FactionId = 107, Abbrev = "Den", Name = "Dragon's Den" };
            _factionLookup[108] = new FactionTag { FactionId = 108, Abbrev = "DIG", Name = "DIG DUG" };
            _factionLookup[109] = new FactionTag { FactionId = 109, Abbrev = "GRE", Name = "Gambiarra" };
            _factionLookup[110] = new FactionTag { FactionId = 110, Abbrev = "=$=", Name = "Ascended Adventures" };
            _factionLookup[111] = new FactionTag { FactionId = 111, Abbrev = "DDF", Name = "Dragons Den OG" };
            _factionLookup[112] = new FactionTag { FactionId = 112, Abbrev = "LSW", Name = "Lavro Ship Works" };
            _factionLookup[113] = new FactionTag { FactionId = 113, Abbrev = "BOI", Name = "OS BOIS" };
            _factionLookup[114] = new FactionTag { FactionId = 114, Abbrev = "ISA", Name = "ISA" };
            _factionLookup[115] = new FactionTag { FactionId = 115, Abbrev = "ASS", Name = "Aussie Space Service" };
            _factionLookup[116] = new FactionTag { FactionId = 116, Abbrev = "Clo", Name = "Clodos" };
            _factionLookup[117] = new FactionTag { FactionId = 117, Abbrev = "WoF", Name = "Wings of Fire" };
            _factionLookup[118] = new FactionTag { FactionId = 118, Abbrev = "B&B", Name = "B&B" };
            _factionLookup[119] = new FactionTag { FactionId = 119, Abbrev = "Bad", Name = "Bad Lucky" };
            _factionLookup[120] = new FactionTag { FactionId = 120, Abbrev = "iCF", Name = "iCore Federation" };
            _factionLookup[121] = new FactionTag { FactionId = 121, Abbrev = "FBI", Name = "Fire Began Inside" };
        }
        // ---------------------------------------------------------------------
        // Modern API v2 Object Scanner (IPlayfield -> Players / Entities)
        // ---------------------------------------------------------------------
        public void ScanPlayfieldEntities(IPlayfield playfield)
        {
            if (playfield == null) return;

            try
            {
                // In API v2, playfield.Players provides live connected IPlayer objects
                if (playfield.Players != null)
                {
                    foreach (var kvp in playfield.Players)
                    {
                        var player = kvp.Value;
                        if (player == null) continue;

                        string steamId = player.SteamId ?? "";
                        int entityId = player.Id; // IPlayer uses .Id, not .EntityId
                        string name = player.Name ?? "Unknown";

                        // FactionData is a struct; check id > 0
                        int fId = player.Faction.Id;
                        if (fId > 0)
                        {
                            // If this factionId exists in our lookup, sync any player records matching it
                            if (_factionLookup.TryGetValue(fId, out FactionTag fac))
                            {
                                foreach (var p in _allPlayers.Values)
                                {
                                    if (p.factionId == fId)
                                    {
                                        p.faction = fac.Abbrev;
                                    }
                                }
                            }
                        }

                        AddOrUpdate(steamId, entityId, name, "Online", playfield.Name, player.Ping);
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -WARN- Exception scanning API v2 playfield: {ex.Message}");
            }
        }

        public void AddOrUpdate(string steamId, int entityId, string name, string status = "Online", string playfield = "--", int ping = 0)
        {
            string key = (!string.IsNullOrEmpty(steamId) && steamId != "--") 
                ? steamId 
                : (!string.IsNullOrEmpty(name) && !name.StartsWith("Player_") ? name : entityId.ToString());

            var record = _allPlayers.GetOrAdd(key, k => new PlayerRecord());

            if (!string.IsNullOrEmpty(name) && !name.StartsWith("Player_"))
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

        private class BridgeConfig
        {
            public string SaveGameName { get; set; }
            public string GlobalDbPath { get; set; }
        }

        /// <summary>
        /// Resolves global.db from ZeroGBridge.json (mod folder), then the newest
        /// Saves/Games/*/global.db under the process directory or its parent, then
        /// the legacy "Zero-G Server" folder name.
        /// </summary>
        private static string ResolveGlobalDbPath(string baseDir, string currentDir)
        {
            var tried = new List<string>();
            string parentCur = Directory.GetParent(currentDir)?.FullName ?? currentDir;
            string parentBase = Directory.GetParent(baseDir)?.FullName ?? baseDir;

            string[] serverRoots = UniquePaths(currentDir, parentCur, baseDir, parentBase);
            string[] autoRoots = UniquePaths(currentDir, parentCur);

            string modDir = null;
            try
            {
                string assemblyPath = Assembly.GetExecutingAssembly().Location;
                if (!string.IsNullOrEmpty(assemblyPath))
                {
                    modDir = Path.GetDirectoryName(assemblyPath);
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -WARN- Could not read assembly location for ZeroGBridge.json: {ex.Message}");
            }

            BridgeConfig cfg = LoadBridgeConfig(modDir);

            if (cfg != null && !string.IsNullOrWhiteSpace(cfg.GlobalDbPath))
            {
                string raw = cfg.GlobalDbPath.Trim();
                var pathCandidates = new List<string>();
                if (Path.IsPathRooted(raw))
                {
                    pathCandidates.Add(raw);
                }
                else
                {
                    foreach (var root in serverRoots)
                    {
                        pathCandidates.Add(Path.GetFullPath(Path.Combine(root, raw)));
                    }
                    if (!string.IsNullOrEmpty(modDir))
                    {
                        pathCandidates.Add(Path.GetFullPath(Path.Combine(modDir, raw)));
                    }
                }

                foreach (var p in UniquePaths(pathCandidates.ToArray()))
                {
                    tried.Add(p);
                    if (File.Exists(p))
                    {
                        Console.WriteLine($"[ZGB] -SUCCESS- Located database at: {p} (config, GlobalDbPath)");
                        return p;
                    }
                }

                Console.WriteLine($"[ZGB] -WARN- Configured GlobalDbPath not found: \"{raw}\"");
            }

            if (cfg != null && !string.IsNullOrWhiteSpace(cfg.SaveGameName))
            {
                string name = cfg.SaveGameName.Trim();
                foreach (var root in serverRoots)
                {
                    string p = Path.Combine(root, "Saves", "Games", name, "global.db");
                    tried.Add(p);
                    if (File.Exists(p))
                    {
                        Console.WriteLine($"[ZGB] -SUCCESS- Located database at: {p} (config, SaveGameName=\"{name}\")");
                        return p;
                    }
                }

                Console.WriteLine($"[ZGB] -WARN- Configured SaveGameName \"{name}\" did not resolve to a global.db; continuing with auto-detect.");
            }

            string newest = null;
            DateTime newestTime = DateTime.MinValue;
            foreach (var root in autoRoots)
            {
                string gamesDir = Path.Combine(root, "Saves", "Games");
                if (!Directory.Exists(gamesDir))
                {
                    continue;
                }

                string[] files;
                try
                {
                    files = Directory.GetFiles(gamesDir, "global.db", SearchOption.AllDirectories);
                }
                catch
                {
                    continue;
                }

                foreach (var p in files)
                {
                    tried.Add(p);
                    DateTime writeTime;
                    try
                    {
                        writeTime = File.GetLastWriteTimeUtc(p);
                    }
                    catch
                    {
                        continue;
                    }

                    if (newest == null || writeTime >= newestTime)
                    {
                        newestTime = writeTime;
                        newest = p;
                    }
                }
            }

            if (!string.IsNullOrEmpty(newest))
            {
                Console.WriteLine($"[ZGB] -SUCCESS- Located database at: {newest} (auto-detect, newest global.db)");
                return newest;
            }

            const string fallbackName = "Zero-G Server";
            foreach (var root in serverRoots)
            {
                string p = Path.Combine(root, "Saves", "Games", fallbackName, "global.db");
                if (!tried.Any(x => string.Equals(x, p, StringComparison.OrdinalIgnoreCase)))
                {
                    tried.Add(p);
                }
                if (File.Exists(p))
                {
                    Console.WriteLine($"[ZGB] -SUCCESS- Located database at: {p} (fallback, SaveGameName=\"{fallbackName}\")");
                    return p;
                }
            }

            Console.WriteLine("[ZGB] -WARN- Unable to locate global.db across candidate paths:");
            if (tried.Count == 0)
            {
                Console.WriteLine("[ZGB] -WARN-   (no candidate paths were generated)");
            }
            else
            {
                foreach (var p in tried)
                {
                    Console.WriteLine($"[ZGB] -WARN-   {p}");
                }
            }
            return null;
        }

        private static BridgeConfig LoadBridgeConfig(string modDir)
        {
            if (string.IsNullOrEmpty(modDir))
            {
                Console.WriteLine("[ZGB] -WARN- Could not determine mod folder for ZeroGBridge.json (assembly location empty).");
                return null;
            }

            string configPath = Path.Combine(modDir, "ZeroGBridge.json");
            if (!File.Exists(configPath))
            {
                Console.WriteLine($"[ZGB] -INFO- No ZeroGBridge.json at {configPath}; using auto-detect.");
                return null;
            }

            try
            {
                string json = File.ReadAllText(configPath);
                var cfg = JsonConvert.DeserializeObject<BridgeConfig>(json) ?? new BridgeConfig();
                Console.WriteLine($"[ZGB] -INFO- Loaded config from {configPath} (SaveGameName=\"{cfg.SaveGameName}\", GlobalDbPath=\"{cfg.GlobalDbPath}\")");
                return cfg;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -WARN- Failed to read {configPath}: {ex.Message}");
                return null;
            }
        }

        private static string[] UniquePaths(params string[] paths)
        {
            var list = new List<string>();
            foreach (var p in paths)
            {
                if (string.IsNullOrEmpty(p))
                {
                    continue;
                }
                if (!list.Any(x => string.Equals(x, p, StringComparison.OrdinalIgnoreCase)))
                {
                    list.Add(p);
                }
            }
            return list.ToArray();
        }

        private void SafeScanDatabase(string baseDir)
        {
            try
            {
                Console.WriteLine("[ZGB] -INFO- Executing SafeScanDatabase...");
                ScanSaveGameDatabase(baseDir);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -ERROR- SafeScanDatabase failure: {ex.GetType().Name} - {ex.Message}");
            }
        }

        private void ScanSaveGameDatabase(string baseDir)
        {
            string tempDb = null;
            try
            {
                string currentDir = Directory.GetCurrentDirectory();
                string resolvedDb = ResolveGlobalDbPath(baseDir, currentDir);

                if (string.IsNullOrEmpty(resolvedDb))
                {
                    return;
                }


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

                // Stream copy with FileShare.ReadWrite to avoid dedicated server locks
                using (var sourceStream = new FileStream(resolvedDb, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                using (var destStream = new FileStream(tempDb, FileMode.Create, FileAccess.Write, FileShare.None))
                {
                    sourceStream.CopyTo(destStream);
                }

                string connString = $"Data Source={tempDb};Version=3;Journal Mode=Memory;Pooling=False;";

                using (var connection = new SqliteConnection(connString))
                {
                    connection.Open();

                    string query = @"
                        SELECT 
                            l.playerid AS steamId,
                            l.entityid AS entityId,
                            l.playername AS playerName,
                            COALESCE(
                                NULLIF(e.facid, 0),
                                (SELECT sh.facid 
                                 FROM StructuresHistory sh 
                                 WHERE sh.touchedentityid = l.entityid AND sh.facid > 0 
                                 ORDER BY sh.gametime DESC LIMIT 1),
                                (SELECT sh2.facid 
                                 FROM StructuresHistory sh2 
                                 WHERE sh2.entityid = l.entityid AND sh2.facid > 0 
                                 ORDER BY sh2.gametime DESC LIMIT 1),
                                0
                            ) AS factionId,
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

                                // Resolve faction name/abbreviation from cache
                                string factionTag = "--";
                                if (factionId > 0 && _factionLookup.TryGetValue(factionId, out FactionTag fac))
                                {
                                    factionTag = !string.IsNullOrEmpty(fac.Abbrev) ? fac.Abbrev : fac.Name;
                                }
                                else if (factionId > 1 && factionId < 1000)
                                {
                                    factionTag = $"FAC-{factionId}";
                                }

                                var record = _allPlayers.GetOrAdd(steamId, k => new PlayerRecord());
                                record.steamId = steamId;
                                record.entityId = entityId.ToString();
                                record.name = realName;
                                record.factionId = factionId;
                                record.status = "Offline";
                                record.faction = factionTag; // Unconditionally updates in-memory record
                                record.playfield = playfield;
                                record.coordinates = coords;
                                record.stats["playtime"] = playtimeStr;

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