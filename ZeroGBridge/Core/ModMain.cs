using System;
using System.IO;
using System.Collections.Generic;
using Eleon.Modding;

namespace ZeroGBridge
{
    /// <summary>
    /// Master lifecycle entry point for ZeroGBridge.
    /// Orchestrates service instantiation and teardown for Port 30500 telemetry operations.
    /// </summary>
    public class ModMain : IMod
    {
        private IModApi _modApi;
        // Modern ModAPI handle
        public static IModApi ModApiInstance;
        private PlayerCache _playerCache;
        private LogParser _logParser;
        private LogDiscovery _logDiscovery;
        private CommandDispatcher _commandDispatcher;
        // Static thread-safe list of active structures cached for CommandDispatcher
        public static readonly List<object> CachedGlobalStructures = new List<object>();
        private TelemetryServer _telemetryServer;
        private TelemetryBroadcaster _telemetryBroadcaster;

        #region IMod Lifecycle Handlers

        /// <summary>
        /// Entry point invoked by the dedicated server engine upon mod loading.
        /// </summary>
        public void Init(IModApi modApi)
        {
            _modApi = modApi;
            ModApiInstance = modApi;

            // Resolve log output directory for disk caching
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string logDir = Path.Combine(baseDir, "Logs", "ZeroGBridge");
            if (!Directory.Exists(logDir))
            {
                Directory.CreateDirectory(logDir);
            }
            string logFilePath = Path.Combine(logDir, "live_telemetry.txt");

            Console.WriteLine("[ZGB] -INFO- Initializing ZeroGBridge modular architecture...");

            // 1. Initialize core state cache and parser
            _playerCache = new PlayerCache();
            _logParser = new LogParser(_playerCache);
            _logDiscovery = new LogDiscovery(_logParser);
            _commandDispatcher = new CommandDispatcher(_playerCache);

            // 2. Initial discovery attachment starting from byte 0
            _logDiscovery.ResolveActiveLogPath(baseDir);

            // 3. Initialize TCP socket server bound to Port 30500
            _telemetryServer = new TelemetryServer(30500, _commandDispatcher);
            _telemetryServer.Start();

            // 4. Initialize background 2-second telemetry broadcaster
            _telemetryBroadcaster = new TelemetryBroadcaster(
                _modApi, 
                _playerCache, 
                _logDiscovery, 
                _telemetryServer, 
                logFilePath
            );
            _telemetryBroadcaster.Start();

            Console.WriteLine("[ZGB] -INFO- ZeroGBridge initialized successfully on Port 30500.");
        }

        

        /// <summary>
        /// Terminates background worker threads and socket listeners cleanly upon server shutdown.
        /// </summary>
        public void Shutdown()
        {
            Console.WriteLine("[ZGB] -INFO- Shutting down ZeroGBridge services...");
            try
            {
                _telemetryBroadcaster?.Stop();
                _telemetryServer?.Stop();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -ERROR- Exception during shutdown: {ex.Message}");
            }
            Console.WriteLine("[ZGB] -INFO- ZeroGBridge shut down cleanly.");
        }

        #endregion
    }
}