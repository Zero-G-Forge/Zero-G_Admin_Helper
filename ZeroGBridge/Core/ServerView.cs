// =====================================================================
// MODULE: ZeroGBridge/Core/ServerView.cs
// DESCRIPTION: Players, playfields and structures as seen from the main
//              DedicatedServer process (IApplication lists, GetStructures)
// =====================================================================

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using Eleon.Modding;

namespace ZeroGBridge
{
    /// <summary>
    /// Empyrion runs every playfield in its own PlayfieldServer process, so the DedicatedServer
    /// process (which owns port 30500) never gets OnPlayfieldLoaded / IPlayfield.Players. This
    /// class asks the main server instead:
    ///   - online players:   IApplication.GetPlayerEntityIds() + GetPlayerDataFor()
    ///   - running playfields: IApplication.GetPfServerInfos()
    ///   - structures:       IApplication.GetStructures(playfield, null, null, callback)
    ///                       (the v2 equivalent of ARPfLoader's Request_GlobalStructure_List)
    /// Work runs on the game's main thread via Application.Update (throttled). If Update never
    /// fires, the telemetry thread does the same read-only calls as a fallback.
    /// </summary>
    public class ServerView
    {
        public static readonly TimeSpan PlayerRefreshInterval = TimeSpan.FromSeconds(2);
        public static readonly TimeSpan StructureRefreshInterval = TimeSpan.FromSeconds(30);
        public static readonly TimeSpan UpdateStaleAfter = TimeSpan.FromSeconds(10);

        private readonly IModApi _api;
        private readonly PlayerCache _cache;

        // playfield name -> PlayfieldServer process id
        private volatile Dictionary<string, int> _running = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

        // structure id -> record (from GetStructures)
        public ConcurrentDictionary<int, EntityRecord> Structures { get; } = new ConcurrentDictionary<int, EntityRecord>();

        private readonly object _gate = new object();
        private DateTime _lastPlayerRefresh = DateTime.MinValue;
        private DateTime _lastStructureRequest = DateTime.MinValue;
        private DateTime _lastUpdateSeen = DateTime.MinValue;
        private volatile bool _structureRequestPending;
        private readonly ConcurrentQueue<string> _extraPlayfieldRequests = new ConcurrentQueue<string>();
        private int _outstanding;
        private readonly ManualResetEventSlim _structuresDone = new ManualResetEventSlim(true);
        private bool _loggedGetStructuresUnavailable;
        private bool _loggedFirstRefresh;
        private string _lastErrorLogged;

        public DateTime LastRefreshUtc { get; private set; } = DateTime.MinValue;
        public DateTime LastStructuresUtc { get; private set; } = DateTime.MinValue;
        public string LastDriver { get; private set; } = "none";
        public int OnlineCount { get; private set; }

        public ServerView(IModApi api, PlayerCache cache)
        {
            _api = api;
            _cache = cache;
        }

        /// <summary>Only the DedicatedServer process has the server-wide lists.</summary>
        public bool Enabled
        {
            get
            {
                try { return _api?.Application != null && _api.Application.Mode == ApplicationMode.DedicatedServer; }
                catch { return false; }
            }
        }

        public IReadOnlyDictionary<string, int> RunningPlayfields => _running;
        public int RunningPlayfieldCount => _running.Count;

        private bool UpdateIsDriving => DateTime.UtcNow - _lastUpdateSeen < UpdateStaleAfter;

        /// <summary>Application.Update handler (game main thread, every frame).</summary>
        public void OnUpdate()
        {
            if (!Enabled) return;
            _lastUpdateSeen = DateTime.UtcNow;
            Tick("update");
        }

        /// <summary>Called by the telemetry thread every 2 s; only acts when Update is not firing.</summary>
        public void EnsureFresh()
        {
            if (!Enabled || UpdateIsDriving) return;
            Tick("thread");
        }

        private void Tick(string driver)
        {
            DateTime now = DateTime.UtcNow;
            bool doPlayers, doStructures;
            lock (_gate)
            {
                doPlayers = now - _lastPlayerRefresh >= PlayerRefreshInterval;
                doStructures = _structureRequestPending || !_extraPlayfieldRequests.IsEmpty
                               || now - _lastStructureRequest >= StructureRefreshInterval;
                if (doPlayers) _lastPlayerRefresh = now;
                if (doStructures) { _lastStructureRequest = now; _structureRequestPending = false; }
            }

            if (doPlayers) RefreshPlayersAndPlayfields(driver);
            if (doStructures) RequestStructures();
        }

        /// <summary>Reads online players and running playfields from the main server.</summary>
        public void RefreshPlayersAndPlayfields(string driver)
        {
            var app = _api?.Application;
            if (app == null) return;

            try
            {
                var online = new List<PlayerData>();
                var ids = app.GetPlayerEntityIds();
                if (ids != null)
                {
                    foreach (int id in ids)
                    {
                        PlayerData? pd = null;
                        try { pd = app.GetPlayerDataFor(id); } catch { }
                        if (pd.HasValue && pd.Value.IsOnline) online.Add(pd.Value);
                    }
                }

                var running = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
                var infos = app.GetPfServerInfos();
                if (infos != null)
                {
                    foreach (var kv in infos)
                    {
                        if (kv.Value == null) continue;
                        foreach (var name in kv.Value)
                        {
                            if (!string.IsNullOrEmpty(name)) running[name] = kv.Key;
                        }
                    }
                }
                _running = running;

                // Drop structures of playfields that stopped (unless explicitly requested via gents:<pf>)
                foreach (var kv in Structures)
                {
                    if (kv.Value != null && !kv.Value.requested && !running.ContainsKey(kv.Value.playfield ?? ""))
                    {
                        EntityRecord unused;
                        Structures.TryRemove(kv.Key, out unused);
                    }
                }

                _cache?.SyncOnlineFromServer(online);
                OnlineCount = online.Count;
                LastRefreshUtc = DateTime.UtcNow;
                LastDriver = driver;

                if (!_loggedFirstRefresh)
                {
                    _loggedFirstRefresh = true;
                    ZgbLog.Write($"[ZGB] -INFO- Server view active (driver={driver}): {online.Count} online player(s), {running.Count} running playfield(s).");
                }
            }
            catch (Exception ex)
            {
                LogOnce($"[ZGB] -WARN- Server view refresh failed ({driver}): {ex.GetType().Name}: {ex.Message}");
            }
        }

        /// <summary>Asks GetStructures for every running playfield plus any explicitly requested ones.</summary>
        private void RequestStructures()
        {
            var app = _api?.Application;
            if (app == null) { _structuresDone.Set(); return; }

            var names = new HashSet<string>(_running.Keys, StringComparer.OrdinalIgnoreCase);
            var requested = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            string extra;
            while (_extraPlayfieldRequests.TryDequeue(out extra))
            {
                if (!string.IsNullOrWhiteSpace(extra)) { names.Add(extra); requested.Add(extra); }
            }

            if (names.Count == 0)
            {
                // nothing running: no structures to report
                foreach (var kv in Structures) { if (kv.Value != null && !kv.Value.requested) { EntityRecord u; Structures.TryRemove(kv.Key, out u); } }
                LastStructuresUtc = DateTime.UtcNow;
                _structuresDone.Set();
                return;
            }

            Interlocked.Exchange(ref _outstanding, names.Count);
            foreach (var name in names)
            {
                string pf = name;
                bool isRequested = requested.Contains(pf);
                bool accepted = false;
                try
                {
                    accepted = app.GetStructures(pf, null, null, list => OnStructures(pf, isRequested, list));
                }
                catch (Exception ex)
                {
                    LogOnce($"[ZGB] -WARN- GetStructures({pf}) threw {ex.GetType().Name}: {ex.Message}");
                }

                if (!accepted)
                {
                    if (!_loggedGetStructuresUnavailable)
                    {
                        _loggedGetStructuresUnavailable = true;
                        ZgbLog.Write($"[ZGB] -WARN- IApplication.GetStructures returned false for '{pf}' (not available in this process?).");
                    }
                    FinishOne();
                }
            }
        }

        private void OnStructures(string playfield, bool requested, IEnumerable<GlobalStructureInfo> list)
        {
            try
            {
                var fresh = new Dictionary<int, EntityRecord>();
                if (list != null)
                {
                    foreach (var gsi in list)
                    {
                        if (!IsTrackedType(gsi.type)) continue;
                        if (!IsPlayerSideGroup(gsi.factionGroup)) continue;

                        int factionId = gsi.factionId;
                        string faction = _cache != null ? _cache.ResolveFactionAbbrev(factionId) : PlayerCache.NoFaction;
                        fresh[gsi.id] = new EntityRecord
                        {
                            id = gsi.id,
                            name = string.IsNullOrEmpty(gsi.name) ? ((EntityType)gsi.type).ToString() + "_" + gsi.id : gsi.name,
                            type = ((EntityType)gsi.type).ToString(),
                            faction = faction,
                            factionId = factionId,
                            playfield = playfield,
                            position = string.Format(System.Globalization.CultureInfo.InvariantCulture, "{0:F1}, {1:F1}, {2:F1}", gsi.pos.x, gsi.pos.y, gsi.pos.z),
                            source = "server",
                            powered = gsi.powered,
                            blocks = gsi.cntBlocks,
                            devices = gsi.cntDevices,
                            requested = requested
                        };
                    }
                }

                foreach (var kv in Structures)
                {
                    if (kv.Value != null && string.Equals(kv.Value.playfield, playfield, StringComparison.OrdinalIgnoreCase) && !fresh.ContainsKey(kv.Key))
                    {
                        EntityRecord unused;
                        Structures.TryRemove(kv.Key, out unused);
                    }
                }
                foreach (var kv in fresh) Structures[kv.Key] = kv.Value;
                LastStructuresUtc = DateTime.UtcNow;
            }
            catch (Exception ex)
            {
                LogOnce($"[ZGB] -WARN- GetStructures callback for {playfield} failed: {ex.Message}");
            }
            finally
            {
                FinishOne();
            }
        }

        private void FinishOne()
        {
            if (Interlocked.Decrement(ref _outstanding) <= 0) _structuresDone.Set();
        }

        /// <summary>
        /// For gents: refresh structures (optionally for one named playfield, running or not) and
        /// wait up to timeoutMs for the callbacks. Returns false on timeout (data may be stale).
        /// </summary>
        public bool RefreshStructuresAndWait(string playfield, int timeoutMs)
        {
            if (!Enabled) return false;
            _structuresDone.Reset();
            if (!string.IsNullOrWhiteSpace(playfield)) _extraPlayfieldRequests.Enqueue(playfield.Trim());
            _structureRequestPending = true;
            if (!UpdateIsDriving) Tick("thread");
            return _structuresDone.Wait(timeoutMs);
        }

        // 2 = BA, 3 = CV, 4 = SV, 5 = HV, 8 = EscapePod, 24 = TroopTransport
        private static bool IsTrackedType(byte type)
        {
            return type == 2 || type == 3 || type == 4 || type == 5 || type == 8 || type == 24;
        }

        // FactionGroup: 0 = player faction, 1 = private (player), 5 = admin. NPC groups / NoFaction (POIs) are skipped.
        private static bool IsPlayerSideGroup(byte group)
        {
            return group == 0 || group == 1 || group == 5;
        }

        private void LogOnce(string line)
        {
            if (line == _lastErrorLogged) return;
            _lastErrorLogged = line;
            ZgbLog.Write(line);
        }
    }
}
