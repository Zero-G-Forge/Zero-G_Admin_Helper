// =====================================================================
// MODULE: ZeroGBridge/Core/LegacyApi.cs
// DESCRIPTION: Legacy ModInterface (Mif.dll) bridge used for in-game alerts
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
    /// Holds the legacy ModGameAPI handed to ModMain.Game_Start and runs Game_Request calls.
    ///
    /// Empyrion's mod loader instantiates ONE object for a class that implements both IMod and
    /// ModInterface and assigns it to both slots, so Game_Start and Init arrive on the same instance.
    /// The legacy API only exists in the DedicatedServer process (the one that owns port 30500).
    ///
    /// Threading: when Game_Update is ticking (game main thread), requests are queued and executed
    /// from Game_Update. If Game_Update has not ticked in the last second, requests are executed
    /// directly on the caller's thread (same as most legacy mods do).
    ///
    /// 1.4.2: Request_Get_Factions is only ever issued on the game thread: from Game_Start
    /// (the game calls it on its main thread) or from Game_Update. The refresh timer, Init and
    /// Event_Faction_Changed only mark a refresh as pending; the next Game_Update sends it.
    /// (1.4.1 called Game_Request from the System.Threading.Timer worker, which the game
    /// appears to ignore, so the cache never grew past the seeded clubs.)
    /// </summary>
    public static class LegacyApi
    {
        public enum RequestResult { Accepted, Rejected, NotAvailable, Timeout, Exception }

        private sealed class Pending
        {
            public CmdId Cmd;
            public ushort Seq;
            public object Data;
            public RequestResult Result = RequestResult.Timeout;
            public string Error;
            public readonly ManualResetEventSlim Done = new ManualResetEventSlim(false);
            public int Claimed; // 0 = waiting, 1 = taken by executor or abandoned by caller
        }

        private static volatile ModGameAPI _api;
        private static readonly ConcurrentQueue<Pending> Queue = new ConcurrentQueue<Pending>();
        private static long _lastUpdateTicks; // DateTime.UtcNow.Ticks of the last Game_Update
        private static int _seq = 40000;
        private static int _unavailableWarned;
        private static PlayerCache _playerCache;

        // Faction list refresh: an immediate Id(1) request at start can return only a handful
        // of factions before the world is loaded. Re-request once after 20 s, then every 5 min.
        public const int DefaultInitialFactionRefreshDelayMs = 20000;
        public const int DefaultFactionRefreshIntervalMs = 5 * 60 * 1000;
        public static int InitialFactionRefreshDelayMs = DefaultInitialFactionRefreshDelayMs;
        public static int FactionRefreshIntervalMs = DefaultFactionRefreshIntervalMs;

        private static readonly object RefreshLock = new object();
        private static Timer _refreshTimer;
        private static int _loggedFactionCount = -1; // -1 = never logged
        private static long _lastFactionRequestTicks;
        private const int FactionChangedDebounceMs = 2000;

        // 1.4.2: game-thread faction requests
        private static int _factionRequestPending;      // 1 = send Request_Get_Factions on the next Game_Update
        private static long _factionPendingSinceTicks;
        private static int _pendingWaitWarned;
        private static int _lastFactionSeq = -1;         // seq of the last Request_Get_Factions we sent
        private static int _factionRequestsSent;
        private static string _lastFactionLogKey;
        public static int LastFactionRequestThreadId { get; private set; }
        public static int GameStartThreadId { get; private set; }
        public static int FactionRequestsSent => Volatile.Read(ref _factionRequestsSent);
        public static bool FactionRequestPending => Volatile.Read(ref _factionRequestPending) == 1;
        public static int LastFactionSeq => Volatile.Read(ref _lastFactionSeq);

        public static bool IsAvailable => _api != null;
        public static int MainThreadId { get; private set; }
        public static int LastExecThreadId { get; private set; }

        public static bool UpdateIsTicking
        {
            get
            {
                long last = Interlocked.Read(ref _lastUpdateTicks);
                return last != 0 && (DateTime.UtcNow.Ticks - last) < TimeSpan.TicksPerSecond;
            }
        }

        public static void AttachPlayerCache(PlayerCache cache) { _playerCache = cache; }

        public static void OnGameStart(ModGameAPI api)
        {
            _api = api;
            GameStartThreadId = Thread.CurrentThread.ManagedThreadId;
            Interlocked.Exchange(ref _unavailableWarned, 0);
            ZgbLog.Write("[ZGB] -SUCCESS- Legacy ModInterface attached (Game_Start); in-game alerts available.");
            // Game_Start runs on the game's main thread, so the first request can go out right here.
            SendFactionRequestNow("Game_Start");
            StartFactionRefresh();
        }

        /// <summary>
        /// 1.5.0 hot reload: a freshly loaded core gets the ModGameAPI the game handed the loader at
        /// Game_Start. This may run off the game thread, so the faction request is only marked
        /// pending; the next Game_Update sends it.
        /// </summary>
        public static void AttachAfterReload(ModGameAPI api)
        {
            _api = api;
            Interlocked.Exchange(ref _unavailableWarned, 0);
            ZgbLog.Write("[ZGB] -SUCCESS- Legacy ModInterface re-attached after core load; faction refresh queued for the next Game_Update.");
            RequestFactions();
            StartFactionRefresh();
        }

        public static void OnGameExit()
        {
            StopFactionRefresh();
            _api = null;
            Interlocked.Exchange(ref _lastUpdateTicks, 0);
            Interlocked.Exchange(ref _factionRequestPending, 0);
            // Fail anything still queued
            while (Queue.TryDequeue(out var p))
            {
                if (Interlocked.CompareExchange(ref p.Claimed, 1, 0) == 0)
                {
                    p.Result = RequestResult.NotAvailable;
                    p.Done.Set();
                }
            }
        }

        /// <summary>Called from ModMain.Game_Update on the game main thread.</summary>
        public static void OnGameUpdate()
        {
            MainThreadId = Thread.CurrentThread.ManagedThreadId;
            Interlocked.Exchange(ref _lastUpdateTicks, DateTime.UtcNow.Ticks);
            if (Interlocked.Exchange(ref _factionRequestPending, 0) == 1)
            {
                Interlocked.Exchange(ref _pendingWaitWarned, 0);
                SendFactionRequestNow("Game_Update");
            }
            int budget = 20;
            while (budget-- > 0 && Queue.TryDequeue(out var p))
            {
                if (Interlocked.CompareExchange(ref p.Claimed, 1, 0) != 0) continue; // caller timed out
                Execute(p);
                p.Done.Set();
            }
        }

        public static void OnGameEvent(CmdId eventId, ushort seqNr, object data)
        {
            try
            {
                switch (eventId)
                {
                    case CmdId.Event_Get_Factions:
                        HandleFactionList(seqNr, data as FactionInfoList);
                        break;
                    case CmdId.Event_Faction_Changed:
                        RequestFactionsDebounced();
                        break;
                    case CmdId.Event_Error:
                        var err = data as ErrorInfo;
                        if (seqNr >= 40000)
                        {
                            ZgbLog.Write($"[ZGB] -WARN- Game reported Event_Error for bridge request seq {seqNr}: {(err != null ? err.errorType.ToString() : "unknown")}");
                        }
                        break;
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -WARN- Legacy Game_Event handler: {ex.Message}");
            }
        }

        /// <summary>
        /// Merges one Event_Get_Factions reply (ours or another mod's). Stores origin 0/1 only;
        /// NPC origins are dropped (1.5.1: classified by origin first, so id-0 NPC rows count as
        /// dropped, not skipped). Logs the incoming count and seqNr (DEBUG every time, plus counts
        /// by origin and a sample of dropped/skipped rows; INFO when the numbers change).
        /// </summary>
        internal static void HandleFactionList(ushort seqNr, FactionInfoList list)
        {
            int received = list?.factions?.Count ?? 0;
            string whose = seqNr == Volatile.Read(ref _lastFactionSeq) ? "ours" : "other";
            if (list?.factions == null || _playerCache == null)
            {
                ZgbLog.Write($"[ZGB] -DEBUG- Event_Get_Factions seqNr={seqNr} ({whose}): received={received}, nothing cached (list or cache missing).");
                return;
            }

            // 1.5.1: classify by origin first. NPC origins count as dropped(NPC) even with id 0/1
            // (live servers report most NPC groups with factionId 0); only origin 0/1 rows with
            // id <= 1 (the default human group) count as skipped(id<=1).
            int stored = 0, npc = 0, skipped = 0;
            var byOrigin = new SortedDictionary<int, int>();
            var skippedSample = new List<string>();
            var droppedSample = new List<string>();
            foreach (var f in list.factions)
            {
                byOrigin.TryGetValue(f.origin, out int oc);
                byOrigin[f.origin] = oc + 1;
                switch (_playerCache.ClassifyAndUpsertFaction(f.factionId, f.abbrev, f.name, f.origin))
                {
                    case PlayerCache.FactionUpsertResult.Stored:
                        stored++;
                        break;
                    case PlayerCache.FactionUpsertResult.DroppedNpc:
                        npc++;
                        if (droppedSample.Count < FactionLogSampleSize) droppedSample.Add(DescribeFactionRow(f));
                        break;
                    default:
                        skipped++;
                        if (skippedSample.Count < FactionLogSampleSize) skippedSample.Add(DescribeFactionRow(f));
                        break;
                }
            }
            int playerFactions = _playerCache.PlayerFactionCount;
            ZgbLog.Write($"[ZGB] -DEBUG- Event_Get_Factions seqNr={seqNr} ({whose}): received={received} stored(origin 0/1)={stored} dropped(NPC)={npc} skipped(id<=1)={skipped} player factions with a real player={playerFactions}");
            ZgbLog.Write($"[ZGB] -DEBUG- Event_Get_Factions detail seqNr={seqNr} by origin: {string.Join(", ", byOrigin.Select(kv => kv.Key + "=" + kv.Value))}");
            if (droppedSample.Count > 0)
                ZgbLog.Write($"[ZGB] -DEBUG- Event_Get_Factions detail seqNr={seqNr} dropped(NPC) sample ({droppedSample.Count} of {npc}): {string.Join("; ", droppedSample)}");
            if (skippedSample.Count > 0)
                ZgbLog.Write($"[ZGB] -DEBUG- Event_Get_Factions detail seqNr={seqNr} skipped(id<=1) sample ({skippedSample.Count} of {skipped}): {string.Join("; ", skippedSample)}");

            string key = received + "/" + stored + "/" + npc + "/" + playerFactions;
            string prevKey = Interlocked.Exchange(ref _lastFactionLogKey, key);
            Interlocked.Exchange(ref _loggedFactionCount, playerFactions);
            if (prevKey != key)
                ZgbLog.Write($"[ZGB] -INFO- Legacy Event_Get_Factions (seqNr {seqNr}, {whose}): {received} received, {stored} player faction(s) stored, {npc} NPC dropped; {playerFactions} with a real player available for alert targeting.");
        }

        /// <summary>Max rows per DEBUG sample line for dropped/skipped faction rows.</summary>
        internal const int FactionLogSampleSize = 8;

        private static string DescribeFactionRow(FactionInfo f)
        {
            return $"id={f.factionId} origin={f.origin} abbrev={f.abbrev ?? "-"} name={f.name ?? "-"}";
        }

        public static ushort NextSeq()
        {
            // 40000..65535 so bridge requests are recognizable in Event_Error
            int v = Interlocked.Increment(ref _seq);
            if (v > 65535)
            {
                Interlocked.CompareExchange(ref _seq, 40000, v);
                v = Interlocked.Increment(ref _seq);
            }
            return (ushort)v;
        }

        /// <summary>
        /// Asks for a faction list refresh. Safe from any thread: it only marks the request as
        /// pending; the next Game_Update (game main thread) sends Request_Get_Factions.
        /// </summary>
        public static void RequestFactions()
        {
            if (_api == null) return;
            Interlocked.Exchange(ref _lastFactionRequestTicks, DateTime.UtcNow.Ticks);
            if (Interlocked.Exchange(ref _factionRequestPending, 1) == 0)
                Interlocked.Exchange(ref _factionPendingSinceTicks, DateTime.UtcNow.Ticks);
        }

        /// <summary>Sends Request_Get_Factions on the current thread. Only call from Game_Start or Game_Update.</summary>
        private static void SendFactionRequestNow(string from)
        {
            var api = _api;
            if (api == null) return;
            Interlocked.Exchange(ref _lastFactionRequestTicks, DateTime.UtcNow.Ticks);
            ushort seq = NextSeq();
            Interlocked.Exchange(ref _lastFactionSeq, seq);
            LastFactionRequestThreadId = Thread.CurrentThread.ManagedThreadId;
            try
            {
                bool ok = api.Game_Request(CmdId.Request_Get_Factions, seq, new Id(1));
                Interlocked.Increment(ref _factionRequestsSent);
                ZgbLog.Write($"[ZGB] -DEBUG- Request_Get_Factions sent from {from} (thread {LastFactionRequestThreadId}) seqNr={seq} accepted={ok}");
            }
            catch (Exception ex) { ZgbLog.Write($"[ZGB] -WARN- Request_Get_Factions failed: {ex.Message}"); }
        }

        /// <summary>
        /// Starts (or restarts) the delayed faction refresh timer using the current
        /// InitialFactionRefreshDelayMs / FactionRefreshIntervalMs values.
        /// A delay of Timeout.Infinite or a negative value disables the timer.
        /// </summary>
        public static void StartFactionRefresh()
        {
            StopFactionRefresh();
            if (_api == null) return;
            int due = InitialFactionRefreshDelayMs;
            int period = FactionRefreshIntervalMs;
            if (due < 0 || due == Timeout.Infinite) return;
            if (period <= 0 || period == Timeout.Infinite)
                period = Timeout.Infinite;
            lock (RefreshLock)
            {
                _refreshTimer = new Timer(OnFactionRefreshTick, null, due, period);
            }
        }

        public static void StopFactionRefresh()
        {
            lock (RefreshLock)
            {
                var t = _refreshTimer;
                _refreshTimer = null;
                if (t != null)
                {
                    try { t.Dispose(); } catch { }
                }
            }
        }

        // Timer worker thread: never call the game from here, just mark the refresh pending.
        private static void OnFactionRefreshTick(object _)
        {
            try
            {
                RequestFactions();
                long since = Interlocked.Read(ref _factionPendingSinceTicks);
                if (FactionRequestPending && since != 0 && !UpdateIsTicking
                    && DateTime.UtcNow.Ticks - since > TimeSpan.TicksPerMinute
                    && Interlocked.Exchange(ref _pendingWaitWarned, 1) == 0)
                {
                    ZgbLog.Write("[ZGB] -WARN- Faction refresh is waiting for Game_Update (game thread), which has not ticked for over a minute.");
                }
            }
            catch { /* never throw from a timer */ }
        }

        private static void RequestFactionsDebounced()
        {
            long last = Interlocked.Read(ref _lastFactionRequestTicks);
            if (last != 0 && (DateTime.UtcNow.Ticks - last) < TimeSpan.FromMilliseconds(FactionChangedDebounceMs).Ticks)
                return;
            RequestFactions();
        }

        /// <summary>
        /// Runs one Game_Request and reports whether the game accepted it.
        /// </summary>
        public static RequestResult Request(CmdId cmd, object data, int timeoutMs, out string error)
        {
            error = null;
            if (_api == null)
            {
                if (Interlocked.Exchange(ref _unavailableWarned, 1) == 0)
                {
                    ZgbLog.Write("[ZGB] -WARN- In-game alert requested but the legacy ModGameAPI is not attached (Game_Start not called in this process).");
                }
                error = "legacy API not attached";
                return RequestResult.NotAvailable;
            }

            var p = new Pending { Cmd = cmd, Seq = NextSeq(), Data = data };

            if (!UpdateIsTicking)
            {
                p.Claimed = 1;
                Execute(p);
                error = p.Error;
                return p.Result;
            }

            Queue.Enqueue(p);
            if (!p.Done.Wait(timeoutMs))
            {
                if (Interlocked.CompareExchange(ref p.Claimed, 1, 0) == 0)
                {
                    error = "main thread did not run the request in time";
                    return RequestResult.Timeout;
                }
                // executor claimed it just now; wait for it to finish
                p.Done.Wait(2000);
            }
            error = p.Error;
            return p.Result;
        }

        private static void Execute(Pending p)
        {
            var api = _api;
            LastExecThreadId = Thread.CurrentThread.ManagedThreadId;
            if (api == null)
            {
                p.Result = RequestResult.NotAvailable;
                p.Error = "legacy API not attached";
                return;
            }
            try
            {
                bool ok = api.Game_Request(p.Cmd, p.Seq, p.Data);
                p.Result = ok ? RequestResult.Accepted : RequestResult.Rejected;
                if (!ok) p.Error = "Game_Request returned false";
            }
            catch (Exception ex)
            {
                p.Result = RequestResult.Exception;
                p.Error = ex.GetType().Name + ": " + ex.Message;
            }
        }
    }
}
