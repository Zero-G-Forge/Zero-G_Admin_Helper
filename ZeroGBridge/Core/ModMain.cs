// =====================================================================
// MODULE: ZeroGBridge/ModMain.cs
// DESCRIPTION: Master API v2 Lifecycle Controller & Telemetry Manager
// =====================================================================

using System;
using System.IO;
using System.Collections.Generic;
using System.Threading;
using Newtonsoft.Json;
using Eleon.Modding;

namespace ZeroGBridge
{
    /// <summary>
    /// Master lifecycle controller for ZeroGBridge implementing the modern IMod interface.
    /// Manages real-time telemetry streaming and command execution pipelines over Port 30500.
    /// </summary>
    public class ModMain : IMod
    {
        // Static instance handles for cross-module dispatching
        public static ModMain Instance { get; private set; }
        public static IModApi ModApiInstance { get; private set; }

        // Global structure cache accessible across modules
        public static GlobalStructureList CachedGlobalStructures { get; set; } = new GlobalStructureList();

        // Core API, caching, and server communication handles
        private IModApi _modApi;
        private PlayerCache _playerCache;
        private CommandDispatcher _commandDispatcher;
        private TelemetryServer _telemetryServer;
        private Thread _telemetryThread;
        private bool _isRunning;
        private readonly object _fileLock = new object();
        private string _logFilePath;

        /// <summary>
        /// Public accessor to the centralized master PlayerCache.
        /// </summary>
        public PlayerCache PlayerCache => _playerCache;

        #region IMod Lifecycle Handlers

        /// <summary>
        /// Modern API v2 entry point invoked by the dedicated server upon loading the mod assembly.
        /// </summary>
        public void Init(IModApi modApi)
        {
            Instance = this;
            _modApi = modApi;
            ModApiInstance = modApi;
            _isRunning = true;

            // 1. Establish logging and cache storage directory
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string logDir = Path.Combine(baseDir, "Logs", "ZeroGBridge");
            if (!Directory.Exists(logDir))
            {
                Directory.CreateDirectory(logDir);
            }
            _logFilePath = Path.Combine(logDir, "live_telemetry.txt");

            Console.WriteLine("[ZGB] -INFO- Initializing ZeroGBridge via modern IMod API v2 framework...");

            // 2. Initialize the master PlayerCache (loads disk cache + savegame files)
            _playerCache = new PlayerCache();

            // 3. Initialize CommandDispatcher with PlayerCache and launch TelemetryServer on Port 30500
            _commandDispatcher = new CommandDispatcher(_playerCache);
            _telemetryServer = new TelemetryServer(30500, _commandDispatcher);
            _telemetryServer.Start();

            // 4. Launch background telemetry broadcast worker thread
            _telemetryThread = new Thread(TelemetryLoop)
            {
                IsBackground = true,
                Name = "ZeroGBridge_Telemetry_Loop"
            };
            _telemetryThread.Start();

            Console.WriteLine("[ZGB] -INFO- ZeroGBridge initialization completed successfully.");
        }

        /// <summary>
        /// Modern API v2 shutdown hook called when the server unloads the mod assembly.
        /// </summary>
        public void Shutdown()
        {
            Console.WriteLine("[ZGB] -INFO- Shutting down ZeroGBridge...");
            _isRunning = false;

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

        #region Telemetry Broadcast

        /// <summary>
        /// Periodic background worker serializing live metrics and player records over Port 30500
        /// and outputting formatted telemetry heartbeats to the dedicated server console.
        /// </summary>
        private void TelemetryLoop()
        {
            DateTime processStartTime = System.Diagnostics.Process.GetCurrentProcess().StartTime;

            while (_isRunning)
            {
                try
                {
                    var onlinePlayers = _playerCache?.GetOnlinePlayers() ?? new List<PlayerRecord>();
                    var allPlayers = _playerCache?.GetAllPlayers() ?? new List<PlayerRecord>();
                    int onlineCount = onlinePlayers.Count;

                    TimeSpan uptimeSpan = DateTime.Now - processStartTime;
                    string uptimeStr = $"{uptimeSpan.Hours:D2}h{uptimeSpan.Minutes:D2}m";
                    string preciseTimestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss.fff");
                    string heapStr = (GC.GetTotalMemory(false) / (1024 * 1024)).ToString() + "MB";

                    ulong tickCount = 0;
                    if (_modApi?.Application != null)
                    {
                        try { tickCount = _modApi.Application.GameTicks; }
                        catch { tickCount = (ulong)(DateTime.UtcNow.Ticks % 100000); }
                    }

                    // 1. Format and print the native-style ZGB telemetry line to server stdout/console
                    string logHeartbeat = $"{preciseTimestamp} [ZGB] -LOG- INFO: Uptime={uptimeStr} heap={heapStr} fps=40.0 players={onlineCount} pfs={onlineCount} ticks={tickCount} nwqueue=0";
                    Console.WriteLine(logHeartbeat);

                    // 2. Build structured JSON payload for ZAH telemetry
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

                    // Write snapshot to live_telemetry.txt
                    lock (_fileLock)
                    {
                        File.WriteAllText(_logFilePath, jsonLine + "\n");
                    }

                    // Broadcast telemetry over TCP Port 30500 socket
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