using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Threading;
using Newtonsoft.Json;
using Eleon.Modding;
using ZeroGBridge.Hosting;

namespace ZeroGBridge
{
    /// <summary>
    /// Background service responsible for serializing telemetry packets and broadcasting them over Port 30500.
    /// </summary>
    public class TelemetryBroadcaster
    {
        private static readonly Encoding Utf8NoBom = new UTF8Encoding(false);

        private readonly IModApi _modApi;
        private readonly PlayerCache _playerCache;
        private readonly LogDiscovery _logDiscovery;
        private readonly IClientHub _telemetryServer; // 1.5.0: the loader's listener (or the standalone one)
        private readonly string _logFilePath;
        private readonly Action _onTick;

        private Thread _telemetryThread;
        private readonly ManualResetEventSlim _stopEvent = new ManualResetEventSlim(false);
        private readonly object _fileLock = new object();
        private int _logCounter = 0;

        // 1.6.14: console/server-log of the Uptime line is at most once per 120s.
        // The 14s _logCounter check and the client broadcast are unchanged.
        // 0 = never logged, so the first check after load always prints.
        private long _lastUptimeLogTicks;
        private const long UptimeLogIntervalTicks = 120L * TimeSpan.TicksPerSecond;

        // METRIC roster throttling (see TelemetryLoop)
        public const int RosterResyncTicks = 15; // 15 x 2s = 30s keep-alive resync
        private string _lastRosterSignature = null;
        private int _lastAuthGeneration = 0;
        private int _ticksSinceRoster = 0;
        private int _rosterRevision = 0;

        /// <summary>
        /// Initializes the broadcaster with required engine handles and service references.
        /// LogDiscovery may be null to leave the log watcher unwired.
        /// onTick is an optional periodic callback (used to rescan loaded playfield entities).
        /// </summary>
        public TelemetryBroadcaster(
            IModApi modApi,
            PlayerCache playerCache,
            LogDiscovery logDiscovery,
            IClientHub telemetryServer,
            string logFilePath,
            Action onTick = null)
        {
            _modApi = modApi;
            _playerCache = playerCache;
            _logDiscovery = logDiscovery;
            _telemetryServer = telemetryServer;
            _logFilePath = logFilePath;
            _onTick = onTick;
        }

        /// <summary>
        /// Starts the background telemetry loop worker thread.
        /// </summary>
        public void Start()
        {
            _stopEvent.Reset();
            _telemetryThread = new Thread(TelemetryLoop)
            {
                IsBackground = true,
                Name = "ZeroGBridge_Telemetry_Loop"
            };
            _telemetryThread.Start();
        }

        /// <summary>
        /// Stops the telemetry loop worker thread cleanly, signalling the wait handle so
        /// the thread wakes immediately instead of finishing a 2s sleep.
        /// </summary>
        public void Stop()
        {
            _stopEvent.Set();
            try
            {
                if (_telemetryThread != null && _telemetryThread.IsAlive)
                {
                    _telemetryThread.Join(5000);
                    if (_telemetryThread.IsAlive)
                    {
                        ZgbLog.Write("[ZGB] -WARN- TelemetryBroadcaster thread did not exit within 5s.");
                    }
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -ERROR- Exception stopping TelemetryBroadcaster: {ex.Message}");
            }
        }

        public bool IsThreadAlive
        {
            get { return _telemetryThread != null && _telemetryThread.IsAlive; }
        }

        /// <summary>
        /// Background worker loop executed every 2000ms.
        /// Samples host CPU, physical RAM (WorkingSet64), engine ticks, and active online players,
        /// serializing and broadcasting the METRIC packet over Port 30500.
        /// </summary>
        private void TelemetryLoop()
        {
            var currentProcess = System.Diagnostics.Process.GetCurrentProcess();
            DateTime processStartTime = currentProcess.StartTime;

            // Baseline values for differential CPU percentage calculation
            TimeSpan lastCpuTime = currentProcess.TotalProcessorTime;
            DateTime lastSampleTime = DateTime.UtcNow;

            while (!_stopEvent.IsSet)
            {
                try
                {
                    // Optional periodic work (entity rescan). LogDiscovery is only used if the caller wired it.
                    _onTick?.Invoke();
                    _logDiscovery?.PollActiveLog();

                    // Fetch ONLY active online players. METRIC carries counts every tick; the
                    // (slim) online roster is attached only when it changed, when a new client
                    // authenticated, or every RosterResyncTicks as a resync. The full offline
                    // roster is available via the plys command, never via METRIC.
                    var onlinePlayers = _playerCache != null
                        ? _playerCache.GetOnlinePlayers()
                        : new List<PlayerRecord>();
                    int onlineCount = onlinePlayers.Count;

                    var slimRoster = BuildSlimRoster(onlinePlayers);
                    string rosterSignature = BuildRosterSignature(slimRoster);
                    int authGen = _telemetryServer != null ? _telemetryServer.AuthGeneration : 0;

                    bool rosterChanged = !string.Equals(rosterSignature, _lastRosterSignature, StringComparison.Ordinal);
                    bool newClient = authGen != _lastAuthGeneration;
                    _ticksSinceRoster++;
                    bool includeRoster = rosterChanged || newClient || _ticksSinceRoster >= RosterResyncTicks;

                    if (rosterChanged)
                    {
                        _rosterRevision++;
                        _lastRosterSignature = rosterSignature;
                    }
                    if (includeRoster)
                    {
                        _ticksSinceRoster = 0;
                        _lastAuthGeneration = authGen;
                    }

                    TimeSpan uptimeSpan = DateTime.Now - processStartTime;
                    string uptimeStr = $"{uptimeSpan.Hours:D2}h:{uptimeSpan.Minutes:D2}m";

                    DateTime currentSampleTime = DateTime.UtcNow;
                    currentProcess.Refresh();
                    TimeSpan currentCpuTime = currentProcess.TotalProcessorTime;

                    double elapsedMs = (currentSampleTime - lastSampleTime).TotalMilliseconds;
                    double cpuUsedMs = (currentCpuTime - lastCpuTime).TotalMilliseconds;

                    double cpuPercent = 0.0;
                    if (elapsedMs > 0)
                    {
                        cpuPercent = (cpuUsedMs / (elapsedMs * Environment.ProcessorCount)) * 100.0;
                        cpuPercent = Math.Round(Math.Max(0.0, Math.Min(100.0, cpuPercent)), 1);
                    }

                    lastCpuTime = currentCpuTime;
                    lastSampleTime = currentSampleTime;

                    // WorkingSet64 reads 0 on the live Empyrion runtime; see RamSampler.
                    RamSample ram = RamSampler.Sample(currentProcess);
                    string ramFormatted = RamSampler.FormatMb(ram.Bytes);

                    string preciseTimestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss");
                    string heapStr = (GC.GetTotalMemory(false) / (1024 * 1024)).ToString() + "MB";
                    float fpsVal = 40.0f;
                    // Playfields loaded in this process plus those the main server reports as running
                    var pfNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                    if (ModMain.LoadedPlayfields != null) foreach (var k in ModMain.LoadedPlayfields.Keys) pfNames.Add(k);
                    var view = ModMain.Instance?.ServerView;
                    if (view != null) foreach (var k in view.RunningPlayfields.Keys) pfNames.Add(k);
                    int pfsCount = pfNames.Count;
                    int nwQueueVal = 0;

                    ulong tickCount = 0;
                    if (_modApi?.Application != null)
                    {
                        try
                        {
                            tickCount = _modApi.Application.GameTicks;
                        }
                        catch
                        {
                            tickCount = (ulong)(DateTime.UtcNow.Ticks % 100000);
                        }
                    }
                    else
                    {
                        tickCount = (ulong)(DateTime.UtcNow.Ticks % 100000);
                    }

                    var telemetryData = new Dictionary<string, object>
                    {
                        { "timestamp", preciseTimestamp },
                        { "type", "METRIC" },
                        { "status", "Active" },
                        { "uptime", uptimeStr },
                        { "heap", heapStr },
                        { "fps", fpsVal.ToString("0.0") },
                        { "players", onlineCount.ToString() },
                        { "pfs", pfsCount.ToString() },
                        { "ticks", tickCount.ToString() },
                        { "nwqueue", nwQueueVal.ToString() },
                        { "cpu", cpuPercent },
                        { "ram", ramFormatted },
                        { "ram_src", ram.Source },
                        { "roster_rev", _rosterRevision }
                    };
                    if (includeRoster)
                    {
                        telemetryData["player_list"] = slimRoster;
                    }

                    string jsonLine = JsonConvert.SerializeObject(telemetryData);

                    if (!string.IsNullOrEmpty(_logFilePath))
                    {
                        lock (_fileLock)
                        {
                            File.WriteAllText(_logFilePath, jsonLine + "\n", Utf8NoBom);
                        }
                    }

                    if (_telemetryServer != null && _telemetryServer.HasActiveConnections)
                    {
                        _telemetryServer.BroadcastJson(jsonLine, null);
                    }

                    _logCounter++;
                    if (_logCounter >= 7)
                    {
                        _logCounter = 0;
                        long nowTicks = DateTime.UtcNow.Ticks;
                        long last = Interlocked.Read(ref _lastUptimeLogTicks);
                        if (last == 0 || nowTicks - last >= UptimeLogIntervalTicks)
                        {
                            Interlocked.Exchange(ref _lastUptimeLogTicks, nowTicks);
                            string formattedLog = $"-LOG- INFO: Uptime={uptimeStr} heap={heapStr} fps={fpsVal:0.0} cpu={cpuPercent}% ram={ramFormatted} ({ram.Source}) players={onlineCount} pfs={pfsCount} ticks={tickCount} nwqueue={nwQueueVal}";

                            if (_modApi != null)
                            {
                                _modApi.Log(formattedLog);
                            }
                            else
                            {
                                ZgbLog.Write($"{preciseTimestamp} [ZGB] {formattedLog}");
                            }
                        }
                    }
                }
                catch (Exception ex)
                {
                    if (_modApi != null)
                    {
                        _modApi.LogError($"Telemetry loop exception: {ex.Message}");
                    }
                    else
                    {
                        ZgbLog.Write($"[ZGB] -ERROR- Telemetry loop exception: {ex.Message}");
                    }
                }

                _stopEvent.Wait(2000);
            }
        }

        /// <summary>
        /// Lightweight per-player view for METRIC (no stats / inventory / ban fields).
        /// Field names match what Admin Helper's PlayerManager.update_from_live_stream reads.
        /// </summary>
        private static List<Dictionary<string, object>> BuildSlimRoster(List<PlayerRecord> online)
        {
            var list = new List<Dictionary<string, object>>(online.Count);
            foreach (var p in online)
            {
                if (p == null) continue;
                list.Add(new Dictionary<string, object>
                {
                    { "name", p.name },
                    { "steamId", p.steamId },
                    { "entityId", p.entityId },
                    { "status", p.status },
                    { "faction", p.faction },
                    { "factionId", p.factionId },
                    { "playfield", p.playfield },
                    { "solar_system", p.solar_system },
                    { "ping", p.ping }
                });
            }
            list.Sort((a, b) => string.CompareOrdinal(Convert.ToString(a["steamId"]) + Convert.ToString(a["name"]),
                                                      Convert.ToString(b["steamId"]) + Convert.ToString(b["name"])));
            return list;
        }

        /// <summary>
        /// Signature of who is online and where. Ping is excluded on purpose so jitter
        /// does not force the roster onto every tick; ping refreshes on the periodic resync.
        /// </summary>
        private static string BuildRosterSignature(List<Dictionary<string, object>> roster)
        {
            var sb = new StringBuilder();
            foreach (var p in roster)
            {
                sb.Append(p["steamId"]).Append('|').Append(p["entityId"]).Append('|').Append(p["name"]).Append('|')
                  .Append(p["faction"]).Append('|').Append(p["playfield"]).Append(';');
            }
            return sb.ToString();
        }
    }
}
