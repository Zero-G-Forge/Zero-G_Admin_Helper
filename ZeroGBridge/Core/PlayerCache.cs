// =====================================================================
// MODULE: ZeroGBridge/Core/PlayerCache.cs
// DESCRIPTION: Modern API v2 Ingestion & Dynamic Faction/Structure Resolver
// =====================================================================

using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Collections.Concurrent;
using Newtonsoft.Json;
using Mono.Data.Sqlite;
using Eleon.Modding;

namespace ZeroGBridge
{
    #region Data Models

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

    #endregion

    /// <summary>
    /// Thread-safe in-memory cache managing player records, dynamic faction tags,
    /// and live API v2 telemetry.
    /// </summary>
    public class PlayerCache
    {
        #region Private Fields & Constants

        private readonly ConcurrentDictionary<string, PlayerRecord> _allPlayers = new ConcurrentDictionary<string, PlayerRecord>();
        private readonly ConcurrentDictionary<int, FactionTag> _factionLookup = new ConcurrentDictionary<int, FactionTag>();
        private readonly string _cacheFilePath;
        private readonly string _factionCacheFilePath;
        private readonly object _diskLock = new object();

        #endregion

        #region Lifecycle & Constructor

        public PlayerCache()
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string storageDir = Path.Combine(baseDir, "Logs", "ZeroGBridge");
            if (!Directory.Exists(storageDir))
            {
                Directory.CreateDirectory(storageDir);
            }
            _cacheFilePath = Path.Combine(storageDir, "players.json");
            _factionCacheFilePath = Path.Combine(storageDir, "factions.json");

            // 1. Restore previously discovered factions from disk
            LoadFactionsFromDisk();

            // 2. Discover configuration/scenario factions dynamically
            RegisterServerFactions();

            Console.WriteLine("[ZGB] -DEBUG- PlayerCache initializing (Pure API v2)...");

            // 3. Restore cached players
            LoadFromDisk();
            Console.WriteLine($"[ZGB] -DEBUG- After LoadFromDisk: {_allPlayers.Count} players in memory.");

            // 4. Hydrate offline state and structures from global.db
            SafeScanDatabase(baseDir);
            Console.WriteLine($"[ZGB] -DEBUG- After DatabaseScan: {_allPlayers.Count} players in memory.");
        }

        #endregion

        #region Public Accessors & Query API

        public int TotalCount => _allPlayers.Count;
        public int OnlineCount => _allPlayers.Values.Count(p => p.status == "Online");

        public List<PlayerRecord> GetAllPlayers() => new List<PlayerRecord>(_allPlayers.Values);
        public List<PlayerRecord> GetOnlinePlayers() => _allPlayers.Values.Where(p => p.status == "Online").ToList();

        #endregion

        #region Live Player Telemetry & State Management

        public void AddOrUpdate(string steamId, int entityId, string name, string status = "Online", string playfield = "--", int ping = 0, string role = "Member")
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
            if (!string.IsNullOrEmpty(role) && role != "None") record.role = role;

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

        public void ScanPlayfieldEntities(IPlayfield playfield)
        {
            if (playfield == null) return;

            try
            {
                if (playfield.Players != null)
                {
                    foreach (var kvp in playfield.Players)
                    {
                        var player = kvp.Value;
                        if (player == null) continue;

                        string steamId = player.SteamId ?? "";
                        int entityId = player.Id;
                        string name = player.Name ?? "Unknown";

                        // 1. Dynamic Faction Registration
                        int fId = player.Faction.Id;
                        if (fId > 0)
                        {
                            if (!_factionLookup.ContainsKey(fId))
                            {
                                string tag = $"FAC-{fId}";
                                try
                                {
                                    tag = player.Faction.Group.ToString();
                                }
                                catch { }

                                _factionLookup[fId] = new FactionTag
                                {
                                    FactionId = fId,
                                    Abbrev = tag,
                                    Name = tag
                                };
                                SaveFactionsToDisk();
                            }

                            // Propagate newly resolved tag to all records matching this faction
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

                        // 2. Dynamic Faction Role from IPlayer
                        string roleStr = "Member";
                        try
                        {
                            roleStr = player.FactionRole.ToString();
                        }
                        catch { }

                        // 3. Update player record
                        AddOrUpdate(steamId, entityId, name, "Online", playfield.Name, player.Ping, roleStr);
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -WARN- Exception scanning API v2 playfield: {ex.Message}");
            }
        }

        #endregion

        #region Faction Discovery & Extraction

        private void RegisterServerFactions()
        {
            try
            {
                string baseDir = AppDomain.CurrentDomain.BaseDirectory;
                string currentDir = Directory.GetCurrentDirectory();

                // 1. Locate and dynamically parse game.dat for player factions (100+)
                List<string> candidateGameDats = new List<string>
                {
                    Path.Combine(currentDir, "Saves", "Games", "Zero-G Server", "game.dat"),
                    Path.Combine(baseDir, "Saves", "Games", "Zero-G Server", "game.dat"),
                    Path.Combine(Directory.GetParent(currentDir)?.FullName ?? currentDir, "Saves", "Games", "Zero-G Server", "game.dat"),
                    Path.Combine(Directory.GetParent(baseDir)?.FullName ?? baseDir, "Saves", "Games", "Zero-G Server", "game.dat"),
                    @"D:\66.23.236.138_30000\Saves\Games\Zero-G Server\game.dat"
                };

                string resolvedGameDat = candidateGameDats.FirstOrDefault(File.Exists);
                if (!string.IsNullOrEmpty(resolvedGameDat))
                {
                    Console.WriteLine($"[ZGB] -INFO- Parsing player factions from: {resolvedGameDat}");
                    ScanGameDatForFactions(resolvedGameDat);
                }
                else
                {
                    Console.WriteLine("[ZGB] -WARN- game.dat not found for dynamic faction extraction.");
                }

                // 2. Discover scenario / configuration NPC factions from ECF files
                List<string> candidateDirs = new List<string>
                {
                    Path.Combine(currentDir, "Content", "Configuration"),
                    Path.Combine(baseDir, "Content", "Configuration"),
                    Path.Combine(currentDir, "Scenarios"),
                    Path.Combine(baseDir, "Scenarios")
                };

                foreach (var dir in candidateDirs)
                {
                    if (!Directory.Exists(dir)) continue;

                    var ecfFiles = Directory.GetFiles(dir, "*Faction*.ecf", SearchOption.AllDirectories);
                    foreach (var file in ecfFiles)
                    {
                        ParseFactionEcf(file);
                    }
                }

                SaveFactionsToDisk();
                Console.WriteLine($"[ZGB] -SUCCESS- Discovered {_factionLookup.Count} total factions from game.dat and ECFs.");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -WARN- Dynamic faction scan error: {ex.Message}");
            }
        }

        private void ScanGameDatForFactions(string gameDatPath)
        {
            try
            {
                byte[] data;
                using (var fs = new FileStream(gameDatPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                {
                    data = new byte[fs.Length];
                    fs.Read(data, 0, (int)fs.Length);
                }

                // Scan byte by byte for sequential faction blocks (IDs 100 to 999)
                for (int i = 0; i < data.Length - 10; i++)
                {
                    ushort potentialId = BitConverter.ToUInt16(data, i);

                    if (potentialId >= 100 && potentialId <= 999)
                    {
                        int nameLen = data[i + 2];
                        // Validate reasonable length for a faction name
                        if (nameLen >= 3 && nameLen <= 32 && (i + 3 + nameLen) < data.Length)
                        {
                            string name = System.Text.Encoding.UTF8.GetString(data, i + 3, nameLen);

                            // Check that the name consists of valid printable ASCII characters
                            if (name.All(c => c >= 32 && c <= 126))
                            {
                                int tagOffset = i + 3 + nameLen;
                                int tagLen = data[tagOffset];

                                // Faction tags are typically 2 to 6 characters (e.g., MEC, TCS, =A=)
                                if (tagLen >= 2 && tagLen <= 6 && (tagOffset + 1 + tagLen) <= data.Length)
                                {
                                    string tag = System.Text.Encoding.UTF8.GetString(data, tagOffset + 1, tagLen);

                                    if (tag.All(c => c >= 33 && c <= 126))
                                    {
                                        _factionLookup[potentialId] = new FactionTag
                                        {
                                            FactionId = potentialId,
                                            Name = name,
                                            Abbrev = tag
                                        };

                                        // Skip forward past this discovered faction block
                                        i = tagOffset + tagLen;
                                    }
                                }
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -WARN- Could not parse game.dat: {ex.Message}");
            }
        }

        private void ParseFactionEcf(string filePath)
        {
            try
            {
                string[] lines = File.ReadAllLines(filePath);
                int currentId = -1;
                string currentAbbrev = "";
                string currentName = "";

                foreach (var rawLine in lines)
                {
                    string line = rawLine.Trim();
                    if (string.IsNullOrEmpty(line) || line.StartsWith("#")) continue;

                    if (line.StartsWith("{ Faction") || line.StartsWith("{Faction"))
                    {
                        currentId = -1;
                        currentAbbrev = "";
                        currentName = "";
                    }
                    else if (line.StartsWith("Id:", StringComparison.OrdinalIgnoreCase))
                    {
                        int.TryParse(line.Substring(3).Trim(), out currentId);
                    }
                    else if (line.StartsWith("Abbrev:", StringComparison.OrdinalIgnoreCase))
                    {
                        currentAbbrev = line.Substring(7).Trim().Trim('"');
                    }
                    else if (line.StartsWith("Name:", StringComparison.OrdinalIgnoreCase))
                    {
                        currentName = line.Substring(5).Trim().Trim('"');
                    }
                    else if (line.StartsWith("}"))
                    {
                        if (currentId >= 0 && !string.IsNullOrEmpty(currentAbbrev))
                        {
                            _factionLookup[currentId] = new FactionTag
                            {
                                FactionId = currentId,
                                Abbrev = currentAbbrev,
                                Name = !string.IsNullOrEmpty(currentName) ? currentName : currentAbbrev
                            };
                        }
                    }
                }
            }
            catch { }
        }

        #endregion

        #region Database Hydration (global.db)

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

                string resolvedDb = candidateFiles.FirstOrDefault(File.Exists);

                if (string.IsNullOrEmpty(resolvedDb))
                {
                    Console.WriteLine("[ZGB] -WARN- Unable to locate global.db across candidate paths.");
                    return;
                }

                Console.WriteLine($"[ZGB] -SUCCESS- Located database at: {resolvedDb}");

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

                // Copy with FileShare.ReadWrite to avoid dedicated server locks
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
                            CASE e.facid
                                WHEN 0 THEN '[---] None'
                                WHEN 100 THEN '[MEC]'
                                WHEN 101 THEN '[TCS]'
                                WHEN 102 THEN '[=A=]'
                                WHEN 103 THEN '[GoG]'
                                WHEN 105 THEN '[Gru]'
                                WHEN 106 THEN '[KTV]'
                                WHEN 107 THEN '[Den]'
                                WHEN 108 THEN '[DIG]'
                                WHEN 109 THEN '[GRE]'
                                WHEN 111 THEN '[DDF]'
                                WHEN 112 THEN '[LSW]'
                                WHEN 113 THEN '[BOI]'
                                WHEN 114 THEN '[ISA]'
                                WHEN 115 THEN '[ASS]'
                                WHEN 116 THEN '[Clo]'
                                WHEN 117 THEN '[WoF]'
                                WHEN 118 THEN '[MOO]'
                                WHEN 119 THEN '[Bad]'
                                WHEN 120 THEN '[iCF]'
                                WHEN 121 THEN '[FBI]'
                                ELSE 
                                    CASE 
                                        WHEN e.facid = e.entityid THEN '[---] Unaligned'
                                        WHEN e.facid > 0 THEN '[ID:' || CAST(e.facid AS TEXT) || ']'
                                        ELSE '--'
                                    END
                            END AS factionTag,
                            COALESCE(pf.name, '--') AS playfield,
                            ROUND(COALESCE(pd.posx, e.posx, 0.0), 1) AS posx,
                            ROUND(COALESCE(pd.posy, e.posy, 0.0), 1) AS posy,
                            ROUND(COALESCE(pd.posz, e.posz, 0.0), 1) AS posz,
                            COALESCE(ps.playtime, 0.0) AS playtime,
                            COALESCE(pd.credits, 0) AS credits,
                            (SELECT COUNT(*) FROM Entities b 
                             WHERE b.belongstoentityid = l.entityid 
                               AND b.etype = 2 
                               AND b.isremoved = 0) AS baseCount,
                            (SELECT COUNT(*) FROM Entities s 
                             WHERE s.belongstoentityid = l.entityid 
                               AND s.etype IN (4, 8, 16) 
                               AND s.isremoved = 0) AS shipCount,
                            COALESCE(NULLIF(l.logoffticks, 0), l.loginticks, 0) AS lastSessionTicks
                        FROM LoginLogoff l
                        INNER JOIN (
                            SELECT playerid, MAX(lid) AS max_lid
                            FROM LoginLogoff
                            WHERE playerid LIKE '7656%'
                            GROUP BY playerid
                        ) latest ON l.playerid = latest.playerid AND l.lid = latest.max_lid
                        LEFT JOIN Entities e ON l.entityid = e.entityid
                        LEFT JOIN PlayerData pd ON l.entityid = pd.entityid
                        LEFT JOIN Playfields pf ON COALESCE(pd.pfid, e.pfid) = pf.pfid
                        LEFT JOIN PlayerStatistics ps ON l.entityid = ps.entityid
                        ORDER BY l.playername ASC;";
                    using (var cmd = new SqliteCommand(query, connection))
                    using (var reader = cmd.ExecuteReader())
                    {
                        int count = 0;
                        while (reader.Read())
                        {
                            string steamId = reader.IsDBNull(0) ? "" : reader.GetString(0).Trim();
                            int entityId = reader.IsDBNull(1) ? 0 : Convert.ToInt32(reader.GetValue(1));
                            string realName = reader.IsDBNull(2) ? "Unknown" : reader.GetString(2).Trim();
                            string factionTag = reader.IsDBNull(3) ? "--" : reader.GetString(3);
                            string playfield = reader.IsDBNull(4) ? "--" : reader.GetString(4);

                            double px = reader.IsDBNull(5) ? 0.0 : Convert.ToDouble(reader.GetValue(5));
                            double py = reader.IsDBNull(6) ? 0.0 : Convert.ToDouble(reader.GetValue(6));
                            double pz = reader.IsDBNull(7) ? 0.0 : Convert.ToDouble(reader.GetValue(7));
                            double playtimeSec = reader.IsDBNull(8) ? 0.0 : Convert.ToDouble(reader.GetValue(8));
                            long credits = reader.IsDBNull(9) ? 0 : Convert.ToInt64(reader.GetValue(9));
                            int baseCount = reader.IsDBNull(10) ? 0 : Convert.ToInt32(reader.GetValue(10));
                            int shipCount = reader.IsDBNull(11) ? 0 : Convert.ToInt32(reader.GetValue(11));

                            if (!string.IsNullOrEmpty(steamId) && steamId.Length == 17)
                            {
                                string coords = (px != 0.0 || py != 0.0 || pz != 0.0) 
                                    ? $"{px:F1}, {py:F1}, {pz:F1}" 
                                    : "-";
                                int hours = (int)(playtimeSec / 3600.0);
                                string playtimeStr = $"{hours}h";

                                // Read tick timestamp from LoginLogoff
                                long sessionTicks = reader.IsDBNull(12) ? 0 : reader.GetInt64(12);
                                string resolvedLastSeen = "";

                                if (sessionTicks > 0)
                                {
                                    try
                                    {
                                        // Handle standard .NET DateTime ticks
                                        if (sessionTicks > 621355968000000000L) // After year 1970
                                        {
                                            resolvedLastSeen = new DateTime(sessionTicks, DateTimeKind.Utc).ToString("yyyy-MM-dd HH:mm:ss");
                                        }
                                        // Handle Unix Epoch (Seconds or Milliseconds)
                                        else if (sessionTicks > 1000000000000L) // Milliseconds epoch
                                        {
                                            resolvedLastSeen = DateTimeOffset.FromUnixTimeMilliseconds(sessionTicks).UtcDateTime.ToString("yyyy-MM-dd HH:mm:ss");
                                        }
                                        else if (sessionTicks > 1000000000L) // Seconds epoch
                                        {
                                            resolvedLastSeen = DateTimeOffset.FromUnixTimeSeconds(sessionTicks).UtcDateTime.ToString("yyyy-MM-dd HH:mm:ss");
                                        }
                                    }
                                    catch
                                    {
                                        resolvedLastSeen = "";
                                    }
                                }

                                var record = _allPlayers.GetOrAdd(steamId, k => new PlayerRecord());
                                record.steamId = steamId;
                                record.entityId = entityId.ToString();
                                record.name = realName;
                                record.status = "Offline";
                                record.faction = factionTag;
                                record.playfield = playfield;
                                record.coordinates = coords;
                                record.stats["playtime"] = playtimeStr;
                                record.stats["credits"] = credits;
                                record.stats["bases"] = baseCount;
                                record.stats["ships"] = shipCount;

                                if (string.IsNullOrEmpty(record.role) || record.role == "None")
                                {
                                    record.role = "Member";
                                }

                                // Assign actual historical last seen from database only if valid
                                if (!string.IsNullOrEmpty(resolvedLastSeen))
                                {
                                    record.last_seen = resolvedLastSeen;
                                }

                                count++;
                            }
                        }

                        Console.WriteLine($"[ZGB] -INFO- Successfully hydrated {count} player record(s) with structures and credits from global.db.");
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

        #region Disk Persistence (players.json & factions.json)

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

        private void LoadFactionsFromDisk()
        {
            try
            {
                lock (_diskLock)
                {
                    if (File.Exists(_factionCacheFilePath))
                    {
                        string json = File.ReadAllText(_factionCacheFilePath);
                        var loaded = JsonConvert.DeserializeObject<List<FactionTag>>(json);
                        if (loaded != null)
                        {
                            foreach (var f in loaded)
                            {
                                if (f.FactionId >= 0)
                                {
                                    _factionLookup[f.FactionId] = f;
                                }
                            }
                            Console.WriteLine($"[ZGB] -INFO- Restored {_factionLookup.Count} faction(s) from factions.json cache.");
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -WARN- Could not load factions.json: {ex.Message}");
            }
        }

        private void SaveFactionsToDisk()
        {
            try
            {
                lock (_diskLock)
                {
                    string json = JsonConvert.SerializeObject(_factionLookup.Values.ToList(), Formatting.Indented);
                    File.WriteAllText(_factionCacheFilePath, json);
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -WARN- Could not write factions.json: {ex.Message}");
            }
        }

        #endregion
    }
}