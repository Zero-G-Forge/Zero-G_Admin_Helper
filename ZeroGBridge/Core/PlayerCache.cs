// =====================================================================
// MODULE: ZeroGBridge/Core/PlayerCache.cs
// DESCRIPTION: Modern API v2 Ingestion & Faction Resolver
// =====================================================================

using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Globalization;
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
        public string role { get; set; } = "--";
        /// <summary>True when <see cref="role"/> was set from IPlayer.FactionRole, not the old default "Member".</summary>
        public bool roleKnown { get; set; } = false;
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

        /// <summary>
        /// 1.4.2: FactionInfo.origin (Empyrion FactionGroup): 0 = player faction (club),
        /// 1 = private / one-person player faction, 2+ = NPC groups, 255 = NoFaction.
        /// Seeded and ECF entries use 0 / OriginUnknown until the game reports the real value.
        /// </summary>
        public byte Origin { get; set; } = 0;

        /// <summary>Where the entry came from: Seed (built-in list), Ecf (config files) or Game (Event_Get_Factions).</summary>
        public FactionSource Source { get; set; } = FactionSource.Game;
    }

    public enum FactionSource { Seed, Ecf, Game }

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

            ZgbLog.Write("[ZGB] -DEBUG- PlayerCache initializing (Pure API v2)...");

            LoadFromDisk();
            ZgbLog.Write($"[ZGB] -DEBUG- After LoadFromDisk: {_allPlayers.Count} players in memory.");

            SafeScanDatabase(baseDir);
            ZgbLog.Write($"[ZGB] -DEBUG- After DatabaseScan: {_allPlayers.Count} players in memory.");
        }

        public int TotalCount => _allPlayers.Count;
        public int OnlineCount => _allPlayers.Values.Count(p => p.status == "Online");

        private void RegisterServerFactions()
        {
            // Seed verified persistent server factions
            // Faction 1 ("Hum", the default human group) is not a real faction: shown as "--".
            _factionLookup[100] = new FactionTag { FactionId = 100, Abbrev = "MEC", Name = "The Mechanics", Source = FactionSource.Seed };
            _factionLookup[101] = new FactionTag { FactionId = 101, Abbrev = "TCS", Name = "Tin Can Sailors", Source = FactionSource.Seed };
            _factionLookup[102] = new FactionTag { FactionId = 102, Abbrev = "=A=", Name = "Ascension Alliance", Source = FactionSource.Seed };
            _factionLookup[103] = new FactionTag { FactionId = 103, Abbrev = "GoG", Name = "Grumpy Old Gits", Source = FactionSource.Seed };
            _factionLookup[104] = new FactionTag { FactionId = 104, Abbrev = "VII", Name = "Legio VII", Source = FactionSource.Seed };
            _factionLookup[105] = new FactionTag { FactionId = 105, Abbrev = "Gru", Name = "GrumpyOldMen", Source = FactionSource.Seed };
            _factionLookup[106] = new FactionTag { FactionId = 106, Abbrev = "KTV", Name = "Knights Templar", Source = FactionSource.Seed };
            _factionLookup[107] = new FactionTag { FactionId = 107, Abbrev = "Den", Name = "Dragon's Den", Source = FactionSource.Seed };
            _factionLookup[108] = new FactionTag { FactionId = 108, Abbrev = "DIG", Name = "DIG DUG", Source = FactionSource.Seed };
            _factionLookup[109] = new FactionTag { FactionId = 109, Abbrev = "GRE", Name = "Gambiarra", Source = FactionSource.Seed };
            _factionLookup[110] = new FactionTag { FactionId = 110, Abbrev = "=$=", Name = "Ascended Adventures", Source = FactionSource.Seed };
            _factionLookup[111] = new FactionTag { FactionId = 111, Abbrev = "DDF", Name = "Dragons Den OG", Source = FactionSource.Seed };
            _factionLookup[112] = new FactionTag { FactionId = 112, Abbrev = "LSW", Name = "Lavro Ship Works", Source = FactionSource.Seed };
            _factionLookup[113] = new FactionTag { FactionId = 113, Abbrev = "BOI", Name = "OS BOIS", Source = FactionSource.Seed };
            _factionLookup[114] = new FactionTag { FactionId = 114, Abbrev = "ISA", Name = "ISA", Source = FactionSource.Seed };
            _factionLookup[115] = new FactionTag { FactionId = 115, Abbrev = "ASS", Name = "Aussie Space Service", Source = FactionSource.Seed };
            _factionLookup[116] = new FactionTag { FactionId = 116, Abbrev = "Clo", Name = "Clodos", Source = FactionSource.Seed };
            _factionLookup[117] = new FactionTag { FactionId = 117, Abbrev = "WoF", Name = "Wings of Fire", Source = FactionSource.Seed };
            _factionLookup[118] = new FactionTag { FactionId = 118, Abbrev = "B&B", Name = "B&B", Source = FactionSource.Seed };
            _factionLookup[119] = new FactionTag { FactionId = 119, Abbrev = "Bad", Name = "Bad Lucky", Source = FactionSource.Seed };
            _factionLookup[120] = new FactionTag { FactionId = 120, Abbrev = "iCF", Name = "iCore Federation", Source = FactionSource.Seed };
            _factionLookup[121] = new FactionTag { FactionId = 121, Abbrev = "FBI", Name = "Fire Began Inside", Source = FactionSource.Seed };

            DiscoverEcfFactions();
        }

        /// <summary>
        /// Adds factions declared in config/scenario *Faction*.ecf files. Additive only:
        /// never overrides the verified server factions seeded above.
        /// </summary>
        private void DiscoverEcfFactions()
        {
            int added = 0;
            try
            {
                string baseDir = AppDomain.CurrentDomain.BaseDirectory;
                string currentDir = Directory.GetCurrentDirectory();
                foreach (var dir in UniquePaths(
                    Path.Combine(currentDir, "Content", "Configuration"),
                    Path.Combine(baseDir, "Content", "Configuration"),
                    Path.Combine(currentDir, "Content", "Scenarios"),
                    Path.Combine(baseDir, "Content", "Scenarios")))
                {
                    if (!Directory.Exists(dir)) continue;
                    foreach (var file in Directory.GetFiles(dir, "*Faction*.ecf", SearchOption.AllDirectories))
                    {
                        added += ParseFactionEcf(file);
                    }
                }
                if (added > 0) ZgbLog.Write($"[ZGB] -INFO- Added {added} faction(s) from ECF files.");
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -WARN- ECF faction scan error: {ex.Message}");
            }
        }

        private int ParseFactionEcf(string filePath)
        {
            int added = 0;
            try
            {
                int currentId = -1;
                string currentAbbrev = "";
                string currentName = "";
                foreach (var rawLine in File.ReadAllLines(filePath))
                {
                    string line = rawLine.Trim();
                    if (string.IsNullOrEmpty(line) || line.StartsWith("#")) continue;

                    if (line.StartsWith("{ Faction") || line.StartsWith("{Faction"))
                    {
                        currentId = -1; currentAbbrev = ""; currentName = "";
                    }
                    else if (line.StartsWith("Id:", StringComparison.OrdinalIgnoreCase))
                    {
                        if (!int.TryParse(line.Substring(3).Trim(), out currentId)) currentId = -1;
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
                        if (currentId > 0 && currentId < 1000 && !string.IsNullOrEmpty(currentAbbrev))
                        {
                            var tag = new FactionTag
                            {
                                FactionId = currentId,
                                Abbrev = currentAbbrev.Trim('[', ']'),
                                Name = !string.IsNullOrEmpty(currentName) ? currentName : currentAbbrev,
                                Origin = OriginUnknown,
                                Source = FactionSource.Ecf
                            };
                            if (_factionLookup.TryAdd(currentId, tag)) added++;
                        }
                        currentId = -1;
                    }
                }
            }
            catch { }
            return added;
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

                        int fId = 0;
                        try { fId = player.Faction.Id; } catch { }

                        string facAbbrev = ResolveFactionAbbrev(fId);
                        if (fId > 0)
                        {
                            foreach (var existing in _allPlayers.Values)
                            {
                                if (existing.factionId == fId && existing.faction != facAbbrev)
                                {
                                    existing.faction = facAbbrev;
                                }
                            }
                        }

                        // Faction role (Owner/Admin/Member) straight from IPlayer
                        string roleStr = null;
                        try { roleStr = player.FactionRole.ToString(); } catch { }

                        AddOrUpdate(steamId, entityId, name, "Online", playfield.Name, player.Ping, fId, facAbbrev, roleStr);
                    }
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -WARN- Exception scanning API v2 playfield: {ex.Message}");
            }
        }

        public void AddOrUpdate(string steamId, int entityId, string name, string status = "Online", string playfield = "--", int ping = 0, int factionId = 0, string faction = null)
            => AddOrUpdate(steamId, entityId, name, status, playfield, ping, factionId, faction, null);

        public void AddOrUpdate(string steamId, int entityId, string name, string status, string playfield, int ping, int factionId, string faction, string role)
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
            if (!string.IsNullOrWhiteSpace(role) && role != "None")
            {
                record.role = role;
                record.roleKnown = true;
            }

            if (factionId > 0)
            {
                record.factionId = factionId;
                record.faction = string.IsNullOrWhiteSpace(faction)
                    ? ResolveFactionAbbrev(factionId)
                    : NormalizeFactionTag(faction);
            }
            else if (!string.IsNullOrWhiteSpace(faction))
            {
                record.faction = NormalizeFactionTag(faction);
            }

            record.status = status;
            record.ping = ping;
            record.last_seen = DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss");

            SaveToDisk();
        }

        /// <summary>
        /// Resolves a FactionData.Id to the single bridge-wide tag format:
        ///   known faction        -> "[ABC]"
        ///   unknown id 1..999    -> "[FAC-123]"
        ///   0 / none / id >= 1000 (private player faction) -> "--"
        /// </summary>
        public string ResolveFactionAbbrev(int factionId)
        {
            if (factionId <= DefaultHumanFactionId) return NoFaction;
            if (_factionLookup.TryGetValue(factionId, out FactionTag fac))
            {
                string abbrev = !string.IsNullOrWhiteSpace(fac.Abbrev) ? fac.Abbrev : fac.Name;
                return NormalizeFactionTag(abbrev);
            }
            if (factionId < 1000) return "[FAC-" + factionId + "]";
            return NoFaction;
        }

        public const string NoFaction = "--";

        /// <summary>Faction id 1 is the default human group every unaligned player belongs to.</summary>
        public const int DefaultHumanFactionId = 1;

        /// <summary>
        /// Normalizes a free-form tag to "[ABC]" (or "--" for none). Handles old cache values
        /// such as "MEC", "[MEC]", "None", "[---] Unaligned".
        /// </summary>
        public static string NormalizeFactionTag(string raw)
        {
            if (string.IsNullOrWhiteSpace(raw)) return NoFaction;
            string t = raw.Trim();
            if (t == "--" || t.Equals("None", StringComparison.OrdinalIgnoreCase)) return NoFaction;

            if (t.StartsWith("["))
            {
                int close = t.IndexOf(']');
                string inner = close > 0 ? t.Substring(1, close - 1).Trim() : t.Trim('[', ']').Trim();
                if (inner.Length == 0 || inner.Trim('-').Length == 0) return NoFaction; // "[---] Unaligned"
                if (inner.Equals("Hum", StringComparison.OrdinalIgnoreCase)) return NoFaction; // 1.2 showed faction 1 as [Hum]
                return "[" + inner + "]";
            }

            if (t.Trim('-').Length == 0) return NoFaction;
            if (t.Equals("Hum", StringComparison.OrdinalIgnoreCase)) return NoFaction;
            return "[" + t + "]";
        }

        /// <summary>
        /// Applies the main server's online list (IApplication.GetPlayerEntityIds/GetPlayerDataFor).
        /// That list is authoritative in the DedicatedServer process: listed players are Online,
        /// everyone else who was Online goes Offline. players.json is written only on changes.
        /// </summary>
        public int SyncOnlineFromServer(IList<PlayerData> online)
        {
            if (online == null) return 0;
            string now = DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss");
            var present = new HashSet<PlayerRecord>();
            bool changed = false;

            foreach (var pd in online)
            {
                string steamId = string.IsNullOrWhiteSpace(pd.SteamId) ? "" : pd.SteamId.Trim();
                string name = pd.PlayerName ?? "";
                PlayerRecord record = null;

                if (steamId.Length > 0 && steamId != "--")
                {
                    record = _allPlayers.GetOrAdd(steamId, k => { changed = true; return new PlayerRecord(); });
                }
                else
                {
                    string eid = pd.EntityId.ToString();
                    record = _allPlayers.Values.FirstOrDefault(p => p.entityId == eid)
                          ?? _allPlayers.GetOrAdd(!string.IsNullOrEmpty(name) ? name : eid, k => { changed = true; return new PlayerRecord(); });
                }

                if (!string.IsNullOrEmpty(name) && !name.StartsWith("Player_") && record.name != name) { record.name = name; changed = true; }
                if (steamId.Length > 0 && record.steamId != steamId) { record.steamId = steamId; changed = true; }
                if (pd.EntityId > 0 && record.entityId != pd.EntityId.ToString()) { record.entityId = pd.EntityId.ToString(); changed = true; }
                if (!string.IsNullOrEmpty(pd.PlayfieldName) && record.playfield != pd.PlayfieldName) { record.playfield = pd.PlayfieldName; changed = true; }
                if (record.status != "Online") { record.status = "Online"; changed = true; }
                record.last_seen = now;
                present.Add(record);
            }

            foreach (var p in _allPlayers.Values)
            {
                if (p.status == "Online" && !present.Contains(p))
                {
                    p.status = "Offline";
                    p.last_seen = now;
                    changed = true;
                }
            }

            if (changed) SaveToDisk();
            return present.Count;
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

        #region Alert target resolution (1.4)

        /// <summary>FactionInfo.origin 0: a player faction (club).</summary>
        public const byte OriginPlayerFaction = 0;
        /// <summary>FactionInfo.origin 1: a private / one-person player faction.</summary>
        public const byte OriginPrivateFaction = 1;
        /// <summary>Marker for ECF entries whose real origin is not known (never treated as a player faction).</summary>
        public const byte OriginUnknown = 254;

        /// <summary>True for origin 0 (player club) and 1 (private faction). NPC groups (2+) and 255 are not player factions.</summary>
        public static bool IsPlayerOrigin(byte origin)
        {
            return origin == OriginPlayerFaction || origin == OriginPrivateFaction;
        }

        /// <summary>
        /// 1.3/1.4 signature, kept for callers that have no origin: treated as a player faction (origin 0).
        /// </summary>
        public void UpsertFaction(int factionId, string abbrev, string name)
        {
            UpsertFaction(factionId, abbrev, name, OriginPlayerFaction);
        }

        /// <summary>How one Event_Get_Factions row was classified (1.5.1).</summary>
        public enum FactionUpsertResult
        {
            /// <summary>Origin 0/1 with an id above the default human group: stored.</summary>
            Stored = 0,
            /// <summary>NPC origin (2+, 255), whatever its id (including the id-0 rows the game sends for NPC groups).</summary>
            DroppedNpc = 1,
            /// <summary>Origin 0/1 with id &lt;= 1 (the default human group): not a faction.</summary>
            SkippedDefaultGroup = 2
        }

        /// <summary>
        /// Adds or refreshes a faction from the legacy API (Event_Get_Factions).
        /// Only origin 0 (player club) and origin 1 (private faction) are stored. NPC origins
        /// (2+, 255) are dropped, and a seeded/game entry with the same id is removed so an NPC
        /// faction can never be an alert target. Ids at or below the default human group (1) are ignored.
        /// Returns true when the faction was stored.
        /// </summary>
        public bool UpsertFaction(int factionId, string abbrev, string name, byte origin)
        {
            return ClassifyAndUpsertFaction(factionId, abbrev, name, origin) == FactionUpsertResult.Stored;
        }

        /// <summary>
        /// 1.5.1: classifies by origin first. A non-player origin is always DroppedNpc, even when
        /// factionId &lt;= 1 (live servers send most NPC groups such as Zirax/Talon with id 0).
        /// Only origin 0/1 rows with id &lt;= 1 count as SkippedDefaultGroup. Rows with id &lt;= 1 are
        /// never stored or used as a lookup key (an id-0 NPC row never removes or overwrites anything).
        /// </summary>
        public FactionUpsertResult ClassifyAndUpsertFaction(int factionId, string abbrev, string name, byte origin)
        {
            if (!IsPlayerOrigin(origin))
            {
                if (factionId > DefaultHumanFactionId
                    && _factionLookup.TryGetValue(factionId, out var existing) && existing != null && existing.Source != FactionSource.Ecf)
                    _factionLookup.TryRemove(factionId, out _);
                return FactionUpsertResult.DroppedNpc;
            }
            if (factionId <= DefaultHumanFactionId) return FactionUpsertResult.SkippedDefaultGroup;
            _factionLookup[factionId] = new FactionTag
            {
                FactionId = factionId,
                Abbrev = string.IsNullOrWhiteSpace(abbrev) ? (name ?? "--") : abbrev.Trim(),
                Name = string.IsNullOrWhiteSpace(name) ? (abbrev ?? "--") : name.Trim(),
                Origin = origin,
                Source = FactionSource.Game
            };
            return FactionUpsertResult.Stored;
        }

        /// <summary>All cached faction entries (player, seeded and ECF). Used for display tags only.</summary>
        public int FactionCount => _factionLookup.Count;

        /// <summary>Player factions (origin 0/1, not ECF) that have at least one real player as a member.</summary>
        public int PlayerFactionCount => PlayerFactions().Count;

        public bool TryGetFaction(int factionId, out FactionTag tag)
        {
            return _factionLookup.TryGetValue(factionId, out tag) && tag != null;
        }

        /// <summary>
        /// A real player: a cached player record with a Steam id or a positive entity id.
        /// Member of a faction when its factionId matches, or (private factions) when the
        /// faction id is the player's own entity id.
        /// </summary>
        public bool HasRealPlayer(FactionTag fac)
        {
            if (fac == null) return false;
            string idStr = fac.FactionId.ToString(CultureInfo.InvariantCulture);
            foreach (var p in _allPlayers.Values)
            {
                if (p == null || !IsRealPlayer(p)) continue;
                if (p.factionId == fac.FactionId) return true;
                if (fac.Origin == OriginPrivateFaction && p.entityId == idStr) return true;
            }
            return false;
        }

        private static bool IsRealPlayer(PlayerRecord p)
        {
            bool hasSteam = !string.IsNullOrWhiteSpace(p.steamId) && p.steamId != "--";
            bool hasEntity = int.TryParse(p.entityId, NumberStyles.Integer, CultureInfo.InvariantCulture, out int eid) && eid > 0;
            return hasSteam || hasEntity;
        }

        /// <summary>
        /// Factions that alerts may target: origin 0 or 1, from the game or the seed list
        /// (never ECF/NPC), with at least one real player member. Evaluated on each call,
        /// so a faction becomes targetable as soon as its players are known.
        /// </summary>
        public List<FactionTag> PlayerFactions()
        {
            var result = new List<FactionTag>();
            foreach (var fac in _factionLookup.Values)
            {
                if (fac == null) continue;
                if (fac.Source == FactionSource.Ecf) continue;
                if (!IsPlayerOrigin(fac.Origin)) continue;
                if (!HasRealPlayer(fac)) continue;
                result.Add(fac);
            }
            return result;
        }

        /// <summary>
        /// Resolves an alert faction target given as a numeric faction id or a tag
        /// ("MEC", "[MEC]") or full name, case-insensitive. 1.4.2: only player factions
        /// (origin 0/1) with a real player resolve; NPC factions such as Zirax never do.
        /// </summary>
        public bool TryResolveFaction(string idOrTag, out int factionId)
        {
            factionId = 0;
            if (string.IsNullOrWhiteSpace(idOrTag)) return false;
            string key = idOrTag.Trim();
            var candidates = PlayerFactions();

            if (int.TryParse(key, NumberStyles.Integer, CultureInfo.InvariantCulture, out int numeric))
            {
                if (numeric > DefaultHumanFactionId && candidates.Any(f => f.FactionId == numeric))
                {
                    factionId = numeric;
                    return true;
                }
                // fall through: a tag can be numeric-looking (unlikely, but harmless)
            }

            string bare = key;
            if (bare.Length >= 2 && bare.StartsWith("[") && bare.EndsWith("]"))
                bare = bare.Substring(1, bare.Length - 2).Trim();
            if (bare.Length == 0) return false;

            foreach (var fac in candidates)
            {
                if (string.Equals(fac.Abbrev, bare, StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(fac.Name, bare, StringComparison.OrdinalIgnoreCase))
                {
                    factionId = fac.FactionId;
                    return true;
                }
            }
            return false;
        }

        /// <summary>
        /// Resolves an alert player target given as an entity id or a Steam id against
        /// the player cache. Returns the entity id the game API expects.
        /// </summary>
        public bool TryResolvePlayer(string entityOrSteamId, out int entityId, out PlayerRecord record)
        {
            entityId = 0;
            record = null;
            if (string.IsNullOrWhiteSpace(entityOrSteamId)) return false;
            string key = entityOrSteamId.Trim();

            foreach (var p in _allPlayers.Values)
            {
                if (p == null) continue;
                bool match = string.Equals(p.entityId, key, StringComparison.Ordinal) ||
                             string.Equals(p.steamId, key, StringComparison.Ordinal);
                if (!match) continue;
                if (int.TryParse(p.entityId, NumberStyles.Integer, CultureInfo.InvariantCulture, out int eid) && eid > 0)
                {
                    entityId = eid;
                    record = p;
                    return true;
                }
            }
            return false;
        }

        #endregion

        /// <summary>
        /// Re-resolves each player's faction tag from the current faction list, and
        /// clears a role that was never taken from IPlayer.FactionRole (the old default
        /// was "Member", which hid missing ranks).
        /// </summary>
        public void RefreshFactionTags()
        {
            foreach (var record in _allPlayers.Values)
            {
                if (record == null) continue;
                if (record.factionId > 0)
                    record.faction = ResolveFactionAbbrev(record.factionId);
                if (!record.roleKnown)
                    record.role = "--";
            }
        }

        public List<PlayerRecord> GetAllPlayers()
        {
            RefreshFactionTags();
            return new List<PlayerRecord>(_allPlayers.Values);
        }

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
                // 1.5.0: the core DLL now lives in Core/versions/<id>/; ZeroGBridge.json stays next to
                // the loader (ZeroGBridge.dll), which is where AuthConfig looks.
                string cfgPath = AuthConfig.ConfigPath;
                if (!string.IsNullOrEmpty(cfgPath))
                {
                    modDir = Path.GetDirectoryName(cfgPath);
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -WARN- Could not read assembly location for ZeroGBridge.json: {ex.Message}");
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
                        ZgbLog.Write($"[ZGB] -SUCCESS- Located database at: {p} (config, GlobalDbPath)");
                        return p;
                    }
                }

                ZgbLog.Write($"[ZGB] -WARN- Configured GlobalDbPath not found: \"{raw}\"");
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
                        ZgbLog.Write($"[ZGB] -SUCCESS- Located database at: {p} (config, SaveGameName=\"{name}\")");
                        return p;
                    }
                }

                ZgbLog.Write($"[ZGB] -WARN- Configured SaveGameName \"{name}\" did not resolve to a global.db; continuing with auto-detect.");
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
                ZgbLog.Write($"[ZGB] -SUCCESS- Located database at: {newest} (auto-detect, newest global.db)");
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
                    ZgbLog.Write($"[ZGB] -SUCCESS- Located database at: {p} (fallback, SaveGameName=\"{fallbackName}\")");
                    return p;
                }
            }

            ZgbLog.Write("[ZGB] -WARN- Unable to locate global.db across candidate paths:");
            if (tried.Count == 0)
            {
                ZgbLog.Write("[ZGB] -WARN-   (no candidate paths were generated)");
            }
            else
            {
                foreach (var p in tried)
                {
                    ZgbLog.Write($"[ZGB] -WARN-   {p}");
                }
            }
            return null;
        }

        private static BridgeConfig LoadBridgeConfig(string modDir)
        {
            if (string.IsNullOrEmpty(modDir))
            {
                ZgbLog.Write("[ZGB] -WARN- Could not determine mod folder for ZeroGBridge.json (assembly location empty).");
                return null;
            }

            string configPath = Path.Combine(modDir, "ZeroGBridge.json");
            if (!File.Exists(configPath))
            {
                ZgbLog.Write($"[ZGB] -INFO- No ZeroGBridge.json at {configPath}; using auto-detect.");
                return null;
            }

            try
            {
                string json = File.ReadAllText(configPath);
                var cfg = JsonConvert.DeserializeObject<BridgeConfig>(json) ?? new BridgeConfig();
                ZgbLog.Write($"[ZGB] -INFO- Loaded config from {configPath} (SaveGameName=\"{cfg.SaveGameName}\", GlobalDbPath=\"{cfg.GlobalDbPath}\")");
                return cfg;
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -WARN- Failed to read {configPath}: {ex.Message}");
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
                ZgbLog.Write("[ZGB] -INFO- Executing SafeScanDatabase...");
                ScanSaveGameDatabase(baseDir);
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -ERROR- SafeScanDatabase failure: {ex.GetType().Name} - {ex.Message}");
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
                                string factionTag = ResolveFactionAbbrev(factionId);

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

                        ZgbLog.Write($"[ZGB] -INFO- Successfully hydrated {count} player record(s) from global.db.");
                    }

                    int enriched = ApplyPlayerDataFromDb(connection);
                    ZgbLog.Write($"[ZGB] -INFO- Position/credits/structure counts filled for {enriched} player(s).");

                    int seenCount = ApplyLastSeenFromDb(connection);
                    ZgbLog.Write($"[ZGB] -INFO- last_seen filled from global.db for {seenCount} player(s).");
                }

                SaveToDisk();
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -ERROR- Failed to query global.db: {ex.Message}\n{ex.StackTrace}");
            }
            finally
            {
                if (!string.IsNullOrEmpty(tempDb) && File.Exists(tempDb))
                {
                    try { File.Delete(tempDb); } catch { }
                }
            }
        }

        /// <summary>
        /// Fills playfield/position (PlayerData), credits, and owned base/ship counts.
        /// </summary>
        private int ApplyPlayerDataFromDb(SqliteConnection connection)
        {
            // Best effort: older/odd saves may lack PlayerData; base hydration already succeeded.
            try
            {
                // etype: 2 = BA, 3 = CV, 4 = SV, 5 = HV (verified against a real global.db)
                const string query = @"
                    SELECT
                        l.playerid,
                        pf.name,
                        pd.posx, pd.posy, pd.posz,
                        COALESCE(pd.credits, 0),
                        (SELECT COUNT(*) FROM Entities b
                          WHERE b.belongstoentityid = l.entityid AND b.etype = 2 AND b.isremoved = 0),
                        (SELECT COUNT(*) FROM Entities s
                          WHERE s.belongstoentityid = l.entityid AND s.etype IN (3, 4, 5) AND s.isremoved = 0)
                    FROM LoginLogoff l
                    INNER JOIN (
                        SELECT playerid, MAX(lid) AS max_lid FROM LoginLogoff
                        WHERE playerid LIKE '7656%' GROUP BY playerid
                    ) latest ON l.playerid = latest.playerid AND l.lid = latest.max_lid
                    LEFT JOIN PlayerData pd ON l.entityid = pd.entityid
                    LEFT JOIN Playfields pf ON pd.pfid = pf.pfid;";

                int count = 0;
                using (var cmd = new SqliteCommand(query, connection))
                using (var reader = cmd.ExecuteReader())
                {
                    while (reader.Read())
                    {
                        string steamId = reader.IsDBNull(0) ? "" : reader.GetString(0).Trim();
                        if (!_allPlayers.TryGetValue(steamId, out var record)) continue;

                        if (!reader.IsDBNull(1)) record.playfield = reader.GetString(1);
                        if (!reader.IsDBNull(2) && !reader.IsDBNull(3) && !reader.IsDBNull(4))
                        {
                            float px = Convert.ToSingle(reader.GetValue(2));
                            float py = Convert.ToSingle(reader.GetValue(3));
                            float pz = Convert.ToSingle(reader.GetValue(4));
                            if (px != 0f || py != 0f || pz != 0f) record.coordinates = $"{px:F0}, {py:F0}, {pz:F0}";
                        }
                        record.stats["credits"] = Convert.ToInt64(reader.GetValue(5));
                        record.stats["bases"] = Convert.ToInt32(reader.GetValue(6));
                        record.stats["ships"] = Convert.ToInt32(reader.GetValue(7));
                        count++;
                    }
                }
                return count;
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -WARN- PlayerData/structure enrichment skipped: {ex.Message}");
                return 0;
            }
        }

        /// <summary>
        /// Fills last_seen from LoginLogoff. Column names are discovered with PRAGMA
        /// table_info (logged once) because they are not documented; game-tick values
        /// are converted to UTC with the ServerStartStop table.
        /// </summary>
        private int ApplyLastSeenFromDb(SqliteConnection connection)
        {
            try
            {
                var cols = GetColumns(connection, "LoginLogoff");
                if (cols.Count == 0) return 0;

                string logoffCol = PickColumn(cols, new[] { "logofftime", "logouttime", "logoff", "logout" }, new[] { "logoff", "logout" }, null);
                string loginCol = PickColumn(cols, new[] { "logintime", "login" }, new[] { "login" }, new[] { "logoff", "logout" });
                ZgbLog.Write($"[ZGB] -INFO- global.db LoginLogoff columns: {string.Join(",", cols)}; last_seen uses logoff={logoffCol ?? "-"} login={loginCol ?? "-"}");
                if (logoffCol == null && loginCol == null) return 0;

                var slices = GlobalDbTime.LoadServerStartStop(connection, GetColumns(connection, "ServerStartStop"));
                DateTime nowUtc = DateTime.UtcNow;
                ulong gameTicks = 0;
                try { gameTicks = ModMain.ModApiInstance?.Application?.GameTicks ?? 0UL; } catch { }
                DateTime? procStart = null;
                try { procStart = System.Diagnostics.Process.GetCurrentProcess().StartTime.ToUniversalTime(); } catch { }
                GlobalDbTime.Calibrate(slices, gameTicks, nowUtc, procStart);
                ZgbLog.Write($"[ZGB] -INFO- global.db time calibration: {GlobalDbTime.CalibrationNote}");
                TimeSpan tz = GlobalDbTime.LatestOffset;
                int future = 0;

                string a = logoffCol != null ? "MAX(\"" + logoffCol + "\")" : "NULL";
                string b = loginCol != null ? "MAX(\"" + loginCol + "\")" : "NULL";
                string sql = $"SELECT playerid, {a}, {b} FROM LoginLogoff WHERE playerid LIKE '7656%' GROUP BY playerid;";

                int filled = 0;
                using (var cmd = new SqliteCommand(sql, connection))
                using (var reader = cmd.ExecuteReader())
                {
                    while (reader.Read())
                    {
                        string steamId = reader.IsDBNull(0) ? "" : Convert.ToString(reader.GetValue(0)).Trim();
                        if (string.IsNullOrEmpty(steamId)) continue;

                        DateTime? off = GlobalDbTime.ToUtc(reader.IsDBNull(1) ? null : reader.GetValue(1), slices, tz);
                        DateTime? on = GlobalDbTime.ToUtc(reader.IsDBNull(2) ? null : reader.GetValue(2), slices, tz);
                        DateTime? best = off.HasValue && on.HasValue ? (off.Value > on.Value ? off : on) : (off ?? on);
                        if (!best.HasValue) continue;
                        if (!GlobalDbTime.NotInFuture(best, nowUtc).HasValue)
                        {
                            // Never report a future last_seen; fall back to the other value if it is sane.
                            DateTime? alt = best == off ? GlobalDbTime.NotInFuture(on, nowUtc) : GlobalDbTime.NotInFuture(off, nowUtc);
                            future++;
                            if (!alt.HasValue) continue;
                            best = alt;
                        }

                        if (!_allPlayers.TryGetValue(steamId, out PlayerRecord rec)) continue;

                        DateTime existing;
                        bool hasExisting = DateTime.TryParseExact(rec.last_seen ?? "", "yyyy-MM-dd HH:mm:ss",
                            CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out existing);
                        if (!hasExisting || best.Value > existing)
                        {
                            rec.last_seen = best.Value.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture);
                            filled++;
                        }
                    }
                }
                if (future > 0) ZgbLog.Write($"[ZGB] -WARN- {future} last_seen value(s) from global.db were in the future and were not used.");
                return filled;
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -WARN- Could not read last_seen from global.db: {ex.Message}");
                return 0;
            }
        }

        private static List<string> GetColumns(SqliteConnection connection, string table)
        {
            var cols = new List<string>();
            try
            {
                using (var cmd = new SqliteCommand($"PRAGMA table_info(\"{table}\");", connection))
                using (var reader = cmd.ExecuteReader())
                {
                    while (reader.Read())
                    {
                        cols.Add(Convert.ToString(reader.GetValue(1)));
                    }
                }
            }
            catch { }
            return cols;
        }

        private static string PickColumn(List<string> cols, string[] exact, string[] contains, string[] exclude)
        {
            foreach (var e in exact)
            {
                var hit = cols.FirstOrDefault(c => string.Equals(c, e, StringComparison.OrdinalIgnoreCase));
                if (hit != null) return hit;
            }
            foreach (var c in cols)
            {
                string lc = c.ToLowerInvariant();
                if (exclude != null && exclude.Any(x => lc.Contains(x))) continue;
                if (contains.Any(x => lc.Contains(x))) return c;
            }
            return null;
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
                                // Older caches mixed "MEC" / "[MEC]" / "None"; normalize on load.
                                p.faction = p.factionId > 0 ? ResolveFactionAbbrev(p.factionId) : NormalizeFactionTag(p.faction);
                                string key = !string.IsNullOrEmpty(p.steamId) && p.steamId != "--" ? p.steamId : p.name;
                                _allPlayers[key] = p;
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -WARN- Could not load players.json: {ex.Message}");
            }
        }

        private void SaveToDisk()
        {
            try
            {
                lock (_diskLock)
                {
                    string json = JsonConvert.SerializeObject(_allPlayers.Values.ToList(), Formatting.Indented);
                    File.WriteAllText(_cacheFilePath, json, new System.Text.UTF8Encoding(false));
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -WARN- Could not write players.json: {ex.Message}");
            }
        }
    }
}