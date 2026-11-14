// =====================================================================
// MODULE: ZeroGBridge/ModMain.cs
// DESCRIPTION: Master API v2 Lifecycle Controller (Pure IMod / IModApi)
// =====================================================================

using System;
using System.IO;
using System.Collections.Generic;
using System.Linq;
using System.Collections.Concurrent;
using System.Threading;
using Eleon.Modding;
using UnityEngine;

namespace ZeroGBridge
{
    /// <summary>
    /// Snapshot of a live structure / vessel taken from a loaded IPlayfield.
    /// Entities are only visible on playfields that are currently loaded.
    /// </summary>
    public class EntityRecord
    {
        public int id { get; set; }
        public string name { get; set; }
        public string type { get; set; }
        public string faction { get; set; }
        public int factionId { get; set; }
        public string playfield { get; set; }
        public string position { get; set; }
        public string pos { get { return position; } }

        // "playfield" = live IPlayfield entity (playfield process), "server" = IApplication.GetStructures
        public string source { get; set; } = "playfield";
        public bool? powered { get; set; }
        public int? blocks { get; set; }
        public int? devices { get; set; }

        // true when fetched by an explicit gents:<playfield> request (kept even if that playfield is not running)
        [Newtonsoft.Json.JsonIgnore]
        public bool requested { get; set; }
    }

    /// <summary>
    /// Master lifecycle controller for ZeroGBridge implementing pure modern IMod.
    /// Hooks API v2 playfield delegates and manages Port 30500 telemetry broadcasts.
    /// </summary>
    public class ModMain : IMod
    {
        public static ModMain Instance { get; private set; }
        public static IModApi ModApiInstance { get; private set; }

        // Modern API v2 structure registry: EntityId -> IStructure
        public static ConcurrentDictionary<int, IStructure> CachedStructures { get; set; } = new ConcurrentDictionary<int, IStructure>();

        // Enriched snapshots used by the gents command (id, name, type, faction, playfield, position)
        public static ConcurrentDictionary<int, EntityRecord> CachedEntityRecords { get; set; } = new ConcurrentDictionary<int, EntityRecord>();

        // Currently loaded IPlayfield instances, keyed by playfield name
        public static ConcurrentDictionary<string, IPlayfield> LoadedPlayfields { get; } = new ConcurrentDictionary<string, IPlayfield>(StringComparer.OrdinalIgnoreCase);

        private IModApi _modApi;
        private PlayerCache _playerCache;
        private ServerView _serverView;
        private CommandDispatcher _commandDispatcher;
        private TelemetryServer _telemetryServer;
        private TelemetryBroadcaster _telemetryBroadcaster;
        private string _logFilePath;

        private readonly ConcurrentDictionary<string, EntityDelegate> _entityLoadedHandlers = new ConcurrentDictionary<string, EntityDelegate>(StringComparer.OrdinalIgnoreCase);
        private readonly ConcurrentDictionary<string, EntityDelegate> _entityUnloadedHandlers = new ConcurrentDictionary<string, EntityDelegate>(StringComparer.OrdinalIgnoreCase);

        public PlayerCache PlayerCache => _playerCache;
        public ServerView ServerView => _serverView;

        #region IMod Lifecycle Handlers

        public void Init(IModApi modApi)
        {
            Instance = this;
            _modApi = modApi;
            ModApiInstance = modApi;

            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string logDir = Path.Combine(baseDir, "Logs", "ZeroGBridge");
            if (!Directory.Exists(logDir))
            {
                Directory.CreateDirectory(logDir);
            }
            _logFilePath = Path.Combine(logDir, "live_telemetry.txt");

            ZgbLog.Write("[ZGB] -INFO- Initializing ZeroGBridge via modern IMod API v2 framework...");
            ZgbLog.Write("[ZGB] -INFO- " + DescribeProcess());

            // 1. Initialize PlayerCache (reads disk cache and hydrates global.db)
            _playerCache = new PlayerCache();
            _serverView = new ServerView(modApi, _playerCache);

            // 2. Wire into pure API v2 playfield lifecycle delegates
            HookApiV2Events();

            // 3. Start Port 30500 Telemetry Server and Dispatcher
            _commandDispatcher = new CommandDispatcher(_playerCache);
            _telemetryServer = new TelemetryServer(30500, _commandDispatcher);
            _telemetryServer.Start();

            // 4. Launch TelemetryBroadcaster (CPU/RAM METRIC). LogDiscovery is left unwired on purpose.
            _telemetryBroadcaster = new TelemetryBroadcaster(
                _modApi,
                _playerCache,
                null,
                _telemetryServer,
                _logFilePath,
                () => { ScanLoadedPlayfields(); _serverView?.EnsureFresh(); });
            _telemetryBroadcaster.Start();

            ZgbLog.Write("[ZGB] -INFO- ZeroGBridge API v2 initialization complete.");
        }

        public void Shutdown()
        {
            ZgbLog.Write("[ZGB] -INFO- Shutting down ZeroGBridge...");

            UnhookApiV2Events();
            UnhookAllPlayfieldEntityEvents();

            try
            {
                _telemetryBroadcaster?.Stop();
                _telemetryServer?.Stop();
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -ERROR- Shutdown exception: {ex.Message}");
            }

            ZgbLog.Write("[ZGB] -INFO- ZeroGBridge shut down cleanly.");
        }

        #endregion

        /// <summary>
        /// Version, process mode and pid. Empyrion loads the mod in the dedicated server
        /// and in every playfield server process, so this tells which one owns port 30500.
        /// </summary>
        public static string DescribeProcess()
        {
            string version = "?";
            try { version = typeof(ModMain).Assembly.GetName().Version.ToString(); } catch { }

            string mode = "unknown";
            try
            {
                if (ModApiInstance?.Application != null)
                {
                    mode = ModApiInstance.Application.Mode.ToString();
                }
            }
            catch (Exception ex)
            {
                mode = "unavailable (" + ex.GetType().Name + ")";
            }

            string proc = "?";
            int pid = 0;
            try
            {
                var p = System.Diagnostics.Process.GetCurrentProcess();
                proc = p.ProcessName;
                pid = p.Id;
            }
            catch { }

            return $"ZeroGBridge v{version} process: mode={mode} name={proc} pid={pid}";
        }

        #region Pure API v2 Event Wiring

        private void HookApiV2Events()
        {
            try
            {
                if (_modApi?.Application != null)
                {
                    _modApi.Application.OnPlayfieldLoaded += OnPlayfieldLoaded;
                    _modApi.Application.OnPlayfieldUnloading += OnPlayfieldUnloading;
                    _modApi.Application.Update += OnApplicationUpdate;
                    ZgbLog.Write("[ZGB] -SUCCESS- Registered API v2 OnPlayfieldLoaded, OnPlayfieldUnloading and Update delegates.");
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -WARN- Could not register playfield delegates: {ex.Message}");
            }
        }

        private void UnhookApiV2Events()
        {
            try
            {
                if (_modApi?.Application != null)
                {
                    _modApi.Application.OnPlayfieldLoaded -= OnPlayfieldLoaded;
                    _modApi.Application.OnPlayfieldUnloading -= OnPlayfieldUnloading;
                    _modApi.Application.Update -= OnApplicationUpdate;
                }
            }
            catch { }
        }

        private void OnApplicationUpdate()
        {
            try { _serverView?.OnUpdate(); }
            catch { /* never let the frame loop see an exception */ }
        }

        private void OnPlayfieldLoaded(IPlayfield playfield)
        {
            if (playfield == null) return;

            try
            {
                ZgbLog.Write($"[ZGB] -INFO- API v2 Playfield Loaded: {playfield.Name}");
                if (!string.IsNullOrEmpty(playfield.Name))
                {
                    LoadedPlayfields[playfield.Name] = playfield;
                }
                HookPlayfieldEntityEvents(playfield);
                _playerCache?.ScanPlayfieldEntities(playfield);
                ScanPlayfieldStructures(playfield);
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -ERROR- Error handling OnPlayfieldLoaded: {ex.Message}");
            }
        }

        private void OnPlayfieldUnloading(IPlayfield playfield)
        {
            if (playfield == null) return;
            ZgbLog.Write($"[ZGB] -INFO- API v2 Playfield Unloading: {playfield.Name}");

            UnhookPlayfieldEntityEvents(playfield);

            IPlayfield removed;
            if (!string.IsNullOrEmpty(playfield.Name))
            {
                LoadedPlayfields.TryRemove(playfield.Name, out removed);
            }

            RemoveEntitiesFromPlayfield(playfield.Name);
        }

        private void HookPlayfieldEntityEvents(IPlayfield playfield)
        {
            if (playfield == null || string.IsNullOrEmpty(playfield.Name)) return;

            UnhookPlayfieldEntityEvents(playfield);

            EntityDelegate loaded = entity =>
            {
                try
                {
                    if (entity == null) return;
                    if (entity.Type == EntityType.Player)
                    {
                        _playerCache?.ScanPlayfieldEntities(playfield);
                    }
                    else
                    {
                        UpdateEntityRecord(playfield, entity);
                    }
                }
                catch (Exception ex)
                {
                    ZgbLog.Write($"[ZGB] -WARN- OnEntityLoaded handler: {ex.Message}");
                }
            };

            EntityDelegate unloaded = entity =>
            {
                try
                {
                    if (entity == null) return;
                    RemoveEntityRecord(entity.Id);
                }
                catch { }
            };

            _entityLoadedHandlers[playfield.Name] = loaded;
            _entityUnloadedHandlers[playfield.Name] = unloaded;
            playfield.OnEntityLoaded += loaded;
            playfield.OnEntityUnloaded += unloaded;
        }

        private void UnhookPlayfieldEntityEvents(IPlayfield playfield)
        {
            if (playfield == null || string.IsNullOrEmpty(playfield.Name)) return;

            EntityDelegate loaded;
            if (_entityLoadedHandlers.TryRemove(playfield.Name, out loaded))
            {
                try { playfield.OnEntityLoaded -= loaded; } catch { }
            }

            EntityDelegate unloaded;
            if (_entityUnloadedHandlers.TryRemove(playfield.Name, out unloaded))
            {
                try { playfield.OnEntityUnloaded -= unloaded; } catch { }
            }
        }

        private void UnhookAllPlayfieldEntityEvents()
        {
            foreach (var kvp in LoadedPlayfields)
            {
                try { UnhookPlayfieldEntityEvents(kvp.Value); } catch { }
            }
            _entityLoadedHandlers.Clear();
            _entityUnloadedHandlers.Clear();
        }

        #endregion

        #region Structure / Entity Scanning

        /// <summary>
        /// Periodic and event-driven rescan of every currently loaded playfield.
        /// Entity lists are only available for loaded playfields (IPlayfield.Entities).
        /// </summary>
        public void ScanLoadedPlayfields()
        {
            foreach (var kvp in LoadedPlayfields)
            {
                var playfield = kvp.Value;
                if (playfield == null) continue;
                try
                {
                    ScanPlayfieldStructures(playfield);
                }
                catch (Exception ex)
                {
                    ZgbLog.Write($"[ZGB] -WARN- Periodic structure scan failed for {playfield.Name}: {ex.Message}");
                }
            }
        }

        public void ScanPlayfieldStructures(IPlayfield playfield)
        {
            if (playfield?.Entities == null) return;

            foreach (var kvp in playfield.Entities)
            {
                UpdateEntityRecord(playfield, kvp.Value);
            }
        }

        private void UpdateEntityRecord(IPlayfield playfield, IEntity entity)
        {
            if (entity == null || playfield == null) return;
            if (entity.Type == EntityType.Player) return;
            if (!IsTrackedEntity(entity)) return;

            try
            {
                if (entity.Structure != null)
                {
                    CachedStructures[entity.Id] = entity.Structure;
                }

                int factionId = 0;
                try { factionId = entity.Faction.Id; } catch { }

                string faction = _playerCache != null
                    ? _playerCache.ResolveFactionAbbrev(factionId)
                    : (factionId > 0 && factionId < 1000 ? "[FAC-" + factionId + "]" : PlayerCache.NoFaction);

                string entityName = entity.Name;
                if (string.IsNullOrEmpty(entityName))
                {
                    entityName = entity.Type.ToString() + "_" + entity.Id;
                }

                var record = new EntityRecord
                {
                    id = entity.Id,
                    name = entityName,
                    type = entity.Type.ToString(),
                    faction = faction,
                    factionId = factionId,
                    playfield = playfield.Name ?? "--",
                    position = FormatPosition(entity.Position)
                };

                CachedEntityRecords[entity.Id] = record;
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -WARN- Failed to cache entity {entity.Id}: {ex.Message}");
            }
        }

        private static bool IsTrackedEntity(IEntity entity)
        {
            if (entity == null) return false;

            switch (entity.Type)
            {
                case EntityType.BA:
                case EntityType.CV:
                case EntityType.SV:
                case EntityType.HV:
                case EntityType.EscapePod:
                case EntityType.TroopTransport:
                    return true;
                case EntityType.Player:
                case EntityType.Animal:
                case EntityType.Item:
                case EntityType.PlayerBackpack:
                case EntityType.DropContainer:
                case EntityType.PlayerDrone:
                case EntityType.EnemyDrone:
                case EntityType.Unknown:
                    return false;
                default:
                    return entity.Structure != null;
            }
        }

        private void RemoveEntityRecord(int entityId)
        {
            EntityRecord unusedRecord;
            IStructure unusedStructure;
            CachedEntityRecords.TryRemove(entityId, out unusedRecord);
            CachedStructures.TryRemove(entityId, out unusedStructure);
        }

        private void RemoveEntitiesFromPlayfield(string playfieldName)
        {
            if (string.IsNullOrEmpty(playfieldName)) return;

            foreach (var kvp in CachedEntityRecords)
            {
                if (kvp.Value != null && string.Equals(kvp.Value.playfield, playfieldName, StringComparison.OrdinalIgnoreCase))
                {
                    RemoveEntityRecord(kvp.Key);
                }
            }
        }

        private static string FormatPosition(Vector3 position)
        {
            try
            {
                return string.Format("{0:F1}, {1:F1}, {2:F1}", position.x, position.y, position.z);
            }
            catch
            {
                return "--";
            }
        }

        /// <summary>
        /// Builds the getplayfields payload: loaded IPlayfield objects plus known names
        /// from IApplication.GetAllPlayfields() and GetPfServerInfos().
        /// Only loaded playfields expose live entity lists.
        /// </summary>
        public static List<object> BuildPlayfieldList(bool includeAll = false)
        {
            var results = new List<object>();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            foreach (var kvp in LoadedPlayfields)
            {
                var pf = kvp.Value;
                if (pf == null || string.IsNullOrEmpty(pf.Name)) continue;
                if (!seen.Add(pf.Name)) continue;

                results.Add(new
                {
                    name = pf.Name,
                    playfieldType = pf.PlayfieldType,
                    solarSystem = pf.SolarSystemName,
                    isPvP = pf.IsPvP,
                    loaded = true
                });
            }

            // Playfields running in PlayfieldServer processes, as reported to the main server.
            var view = Instance?._serverView;
            if (view != null)
            {
                var online = Instance?._playerCache?.GetOnlinePlayers() ?? new List<PlayerRecord>();
                foreach (var kv in view.RunningPlayfields)
                {
                    if (!seen.Add(kv.Key)) continue;
                    string pfName = kv.Key;
                    results.Add(new
                    {
                        name = pfName,
                        pfServer = kv.Value,
                        players = online.Count(p => string.Equals(p.playfield, pfName, StringComparison.OrdinalIgnoreCase)),
                        loaded = true,
                        source = "server"
                    });
                }
            }

            // Default: loaded playfields only (the full known list is ~1,750 entries / ~150 KB).
            if (!includeAll)
            {
                return results;
            }

            try
            {
                var all = ModApiInstance?.Application?.GetAllPlayfields();
                if (all != null)
                {
                    foreach (var descr in all)
                    {
                        if (descr == null || string.IsNullOrEmpty(descr.PlayfieldName)) continue;
                        if (!seen.Add(descr.PlayfieldName)) continue;

                        results.Add(new
                        {
                            name = descr.PlayfieldName,
                            playfieldType = descr.PlayfieldType.ToString(),
                            isInstance = descr.IsInstance,
                            loaded = LoadedPlayfields.ContainsKey(descr.PlayfieldName)
                        });
                    }
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -WARN- GetAllPlayfields failed: {ex.Message}");
            }

            try
            {
                var infos = ModApiInstance?.Application?.GetPfServerInfos();
                if (infos != null)
                {
                    foreach (var entry in infos)
                    {
                        if (entry.Value == null) continue;
                        foreach (var name in entry.Value)
                        {
                            if (string.IsNullOrEmpty(name) || !seen.Add(name)) continue;
                            results.Add(new
                            {
                                name = name,
                                playfieldType = "Unknown",
                                loaded = LoadedPlayfields.ContainsKey(name)
                            });
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -WARN- GetPfServerInfos failed: {ex.Message}");
            }

            return results;
        }

        #endregion
    }
}
