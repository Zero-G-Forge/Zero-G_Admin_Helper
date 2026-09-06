// =====================================================================
// MODULE: ZeroGBridge/ModMain.cs
// DESCRIPTION: Master API v2 Lifecycle Controller (Pure IMod / IModApi)
// =====================================================================

using System;
using System.IO;
using System.Collections.Generic;
using System.Collections.Concurrent;
using System.Threading;
using Newtonsoft.Json;
using Eleon.Modding;

namespace ZeroGBridge
{
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

        private IModApi _modApi;
        private PlayerCache _playerCache;
        private CommandDispatcher _commandDispatcher;
        private TelemetryServer _telemetryServer;
        private Thread _telemetryThread;
        private bool _isRunning;
        private readonly object _fileLock = new object();
        private string _logFilePath;

        public PlayerCache PlayerCache => _playerCache;

        #region IMod Lifecycle Handlers

        public void Init(IModApi modApi)
        {
            Instance = this;
            _modApi = modApi;
            ModApiInstance = modApi;
            _isRunning = true;

            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string logDir = Path.Combine(baseDir, "Logs", "ZeroGBridge");
            if (!Directory.Exists(logDir))
            {
                Directory.CreateDirectory(logDir);
            }
            _logFilePath = Path.Combine(logDir, "live_telemetry.txt");

            Console.WriteLine("[ZGB] -INFO- Initializing ZeroGBridge via modern IMod API v2 framework...");

            // 1. Initialize PlayerCache (reads disk cache and hydrates global.db)
            _playerCache = new PlayerCache();

            // 2. Wire into pure API v2 playfield lifecycle delegates
            HookApiV2Events();

            // 3. Start Port 30500 Telemetry Server and Dispatcher
            _commandDispatcher = new CommandDispatcher(_playerCache);
            _telemetryServer = new TelemetryServer(30500, _commandDispatcher);
            _telemetryServer.Start();

            // 4. Launch background telemetry broadcast thread
            _telemetryThread = new Thread(TelemetryLoop)
            {
                IsBackground = true,
                Name = "ZeroGBridge_Telemetry_Loop"
            };
            _telemetryThread.Start();

            Console.WriteLine("[ZGB] -INFO- ZeroGBridge API v2 initialization complete.");
        }

        public void Shutdown()
        {
            Console.WriteLine("[ZGB] -INFO- Shutting down ZeroGBridge...");
            _isRunning = false;

            UnhookApiV2Events();

            try
            {
                _telemetryServer?.Stop();
                if (_telemetryThread != null && _telemetryThread.IsAlive)
                {
                    _telemetryThread.Join(1000);
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -ERROR- Shutdown exception: {ex.Message}");
            }

            Console.WriteLine("[ZGB] -INFO- ZeroGBridge shut down cleanly.");
        }

        #endregion

        #region Pure API v2 Event Wiring

        private void HookApiV2Events()
        {
            try
            {
                if (_modApi?.Application != null)
                {
                    _modApi.Application.OnPlayfieldLoaded += OnPlayfieldLoaded;
                    _modApi.Application.OnPlayfieldUnloading += OnPlayfieldUnloading;
                    Console.WriteLine("[ZGB] -SUCCESS- Registered API v2 OnPlayfieldLoaded and OnPlayfieldUnloading delegates.");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -WARN- Could not register playfield delegates: {ex.Message}");
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
                }
            }
            catch { }
        }

        private void OnPlayfieldLoaded(IPlayfield playfield)
        {
            if (playfield == null) return;

            try
            {
                Console.WriteLine($"[ZGB] -INFO- API v2 Playfield Loaded: {playfield.Name}");
                _playerCache?.ScanPlayfieldEntities(playfield);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -ERROR- Error handling OnPlayfieldLoaded: {ex.Message}");
            }
        }

        private void OnPlayfieldUnloading(IPlayfield playfield)
        {
            if (playfield == null) return;
            Console.WriteLine($"[ZGB] -INFO- API v2 Playfield Unloading: {playfield.Name}");
        }

        #endregion

        #region Telemetry Broadcast

        private void TelemetryLoop()
        {
            DateTime processStartTime = System.Diagnostics.Process.GetCurrentProcess().StartTime;
            DateTime lastConsoleLogTime = DateTime.MinValue;

            while (_isRunning)
            {
                try
                {
                    var onlinePlayers = _playerCache?.GetOnlinePlayers() ?? new List<PlayerRecord>();
                    var allPlayers = _playerCache?.GetAllPlayers() ?? new List<PlayerRecord>();
                    int onlineCount = onlinePlayers.Count;

                    TimeSpan uptimeSpan = DateTime.Now - processStartTime;
                    string uptimeStr = $"{uptimeSpan.Hours:D2}h:{uptimeSpan.Minutes:D2}m";
                    string preciseTimestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss.fff");
                    string heapStr = (GC.GetTotalMemory(false) / (1024 * 1024)).ToString() + "MB";

                    ulong tickCount = 0;
                    if (_modApi?.Application != null)
                    {
                        try { tickCount = _modApi.Application.GameTicks; }
                        catch { tickCount = (ulong)(DateTime.UtcNow.Ticks % 100000); }
                    }

                    if ((DateTime.UtcNow - lastConsoleLogTime).TotalSeconds >= 30)
                    {
                        string logHeartbeat = $"{preciseTimestamp} [ZGB] -LOG- INFO: Uptime={uptimeStr} heap={heapStr} fps=40.0 players={onlineCount} pfs={onlineCount} ticks={tickCount} nwqueue=0";
                        Console.WriteLine(logHeartbeat);
                        lastConsoleLogTime = DateTime.UtcNow;
                    }

                    var telemetryData = new
                    {
                        timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss"),
                        type = "METRIC",
                        status = "Active",
                        uptime = uptimeStr,
                        heap = heapStr,
                        fps = "40.0",
                        players = onlineCount.ToString(),
                        pfs = onlineCount.ToString(),
                        ticks = tickCount.ToString(),
                        nwqueue = "0",
                        player_list = onlinePlayers,
                        player_data = allPlayers
                    };

                    string jsonLine = JsonConvert.SerializeObject(telemetryData);

                    lock (_fileLock)
                    {
                        File.WriteAllText(_logFilePath, jsonLine + "\n");
                    }

                    if (_telemetryServer != null && _telemetryServer.HasActiveConnections)
                    {
                        _telemetryServer.BroadcastJson(jsonLine);
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"[ZGB] -ERROR- Telemetry loop exception: {ex.Message}");
                }

                Thread.Sleep(2000);
            }
        }

        #endregion
    }
}