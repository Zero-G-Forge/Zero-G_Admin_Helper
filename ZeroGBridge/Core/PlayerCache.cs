using System;
using System.IO;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json;

namespace ZeroGBridge
{
    public class PlayerRecord
    {
        public int entityId { get; set; }
        public string steamId { get; set; }
        public string name { get; set; }
        public string status { get; set; } = "Offline";
        public string faction { get; set; } = "--";
        public string playfield { get; set; } = "--";
        public int ping { get; set; }
        public string lastSeen { get; set; }
    }

    public class PlayerCache
    {
        private readonly ConcurrentDictionary<string, PlayerRecord> _allPlayers = new ConcurrentDictionary<string, PlayerRecord>();
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

            // 1. Load any saved JSON database
            LoadFromDisk();

            // 2. Scan Empyrion Savegame directory for all historical .ply / .plr player files
            ScanSaveGamePlayers(baseDir);
        }

        public int TotalCount => _allPlayers.Count;
        public int OnlineCount => _allPlayers.Values.Count(p => p.status == "Online");

        public void AddOrUpdate(string steamId, string name, int entityId, int ping = 0, string faction = "--", string playfield = "--")
        {
            if (string.IsNullOrEmpty(steamId)) return;

            string nowStr = DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss");

            _allPlayers.AddOrUpdate(steamId,
                new PlayerRecord
                {
                    entityId = entityId,
                    steamId = steamId,
                    name = name,
                    status = "Online",
                    faction = faction,
                    playfield = playfield,
                    ping = ping,
                    lastSeen = nowStr
                },
                (key, existing) =>
                {
                    existing.name = string.IsNullOrEmpty(name) ? existing.name : name;
                    existing.entityId = entityId != 0 ? entityId : existing.entityId;
                    existing.status = "Online";
                    if (faction != "--") existing.faction = faction;
                    if (playfield != "--") existing.playfield = playfield;
                    existing.ping = ping;
                    existing.lastSeen = nowStr;
                    return existing;
                });

            SaveToDisk();
        }

        public void MarkOffline(string identifier)
        {
            if (string.IsNullOrEmpty(identifier)) return;

            var target = _allPlayers.Values.FirstOrDefault(p =>
                p.steamId == identifier ||
                string.Equals(p.name, identifier, StringComparison.OrdinalIgnoreCase) ||
                p.entityId.ToString() == identifier);

            if (target != null)
            {
                target.status = "Offline";
                target.lastSeen = DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss");
                SaveToDisk();
            }
        }

        public List<PlayerRecord> GetAllPlayers()
        {
            return new List<PlayerRecord>(_allPlayers.Values);
        }

        public List<PlayerRecord> GetOnlinePlayers()
        {
            return _allPlayers.Values.Where(p => p.status == "Online").ToList();
        }

        private void ScanSaveGamePlayers(string baseDir)
        {
            try
            {
                string savesPath = Path.Combine(baseDir, "Saves", "Games");
                if (!Directory.Exists(savesPath)) return;

                var playerFiles = Directory.GetFiles(savesPath, "*.ply", SearchOption.AllDirectories)
                    .Concat(Directory.GetFiles(savesPath, "*.plr", SearchOption.AllDirectories));

                foreach (var file in playerFiles)
                {
                    string filename = Path.GetFileNameWithoutExtension(file);
                    // Match numeric SteamID or entity files
                    if (filename.Length >= 6 && long.TryParse(filename, out _))
                    {
                        if (!_allPlayers.ContainsKey(filename))
                        {
                            DateTime lastMod = File.GetLastWriteTimeUtc(file);
                            _allPlayers[filename] = new PlayerRecord
                            {
                                entityId = Math.Abs(filename.GetHashCode() % 10000),
                                steamId = filename,
                                name = $"Player_{filename.Substring(Math.Max(0, filename.Length - 4))}",
                                status = "Offline",
                                lastSeen = lastMod.ToString("yyyy-MM-dd HH:mm:ss")
                            };
                        }
                    }
                }
                Console.WriteLine($"[ZGB] -INFO- Total player registry count after savegame scan: {_allPlayers.Count}");
                SaveToDisk();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -WARN- Savegame player scan exception: {ex.Message}");
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
                                _allPlayers[p.steamId] = p;
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