using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using Newtonsoft.Json;
using Eleon.Modding;

namespace ZeroGBridge
{
    /// <summary>
    /// Background service responsible for serializing telemetry packets and broadcasting them over Port 30500.
    /// </summary>
    public class TelemetryBroadcaster
    {
        private readonly IModApi _modApi;
        private readonly PlayerCache _playerCache;
        private readonly LogDiscovery _logDiscovery;
        private readonly TelemetryServer _telemetryServer;
        private readonly string _logFilePath;

        private Thread _telemetryThread;
        private bool _isRunning;
        private readonly object _fileLock = new object();
        private int _logCounter = 0;

        /// <summary>
        /// Initializes the broadcaster with required engine handles and service references.
        /// </summary>
        public TelemetryBroadcaster(
            IModApi modApi, 
            PlayerCache playerCache, 
            LogDiscovery logDiscovery, 
            TelemetryServer telemetryServer, 
            string logFilePath)
        {
            _modApi = modApi;
            _playerCache = playerCache;
            _logDiscovery = logDiscovery;
            _telemetryServer = telemetryServer;
            _logFilePath = logFilePath;
        }

        /// <summary>
        /// Starts the background telemetry loop worker thread.
        /// </summary>
        public void Start()
        {
            _isRunning = true;
            _telemetryThread = new Thread(TelemetryLoop)
            {
                IsBackground = true,
                Name = "ZeroGBridge_Telemetry_Loop"
            };
            _telemetryThread.Start();
        }

        /// <summary>
        /// Stops the telemetry loop worker thread cleanly.
        /// </summary>
        public void Stop()
        {
            _isRunning = false;
            try
            {
                _telemetryThread?.Join(1000);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -ERROR- Exception stopping TelemetryBroadcaster: {ex.Message}");
            }
        }

        /// <summary>
        /// Worker loop executed every 2000ms.
        /// Samples process CPU usage and physical working set memory.
        /// </summary>
        private void TelemetryLoop()
        {
            var currentProcess = System.Diagnostics.Process.GetCurrentProcess();
            DateTime processStartTime = currentProcess.StartTime;

            // Baseline metrics for differential CPU percentage calculation
            TimeSpan lastCpuTime = currentProcess.TotalProcessorTime;
            DateTime lastSampleTime = DateTime.UtcNow;

            while (_isRunning)
            {
                try
                {
                    // Ingest newly appended server log lines
                    _logDiscovery?.PollActiveLog();

                    var playerList = _playerCache != null ? _playerCache.GetAllPlayers() : new List<PlayerRecord>();
                    int onlineCount = playerList.Count;

                    // Calculate Server Uptime
                    TimeSpan uptimeSpan = DateTime.Now - processStartTime;
                    string uptimeStr = $"{uptimeSpan.Hours:D2}h:{uptimeSpan.Minutes:D2}m";

                    // 1. Calculate Real-Time CPU% across the iteration interval
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

                    // 2. Sample Dedicated Server Physical RAM (WorkingSet64)
                    long ramBytes = currentProcess.WorkingSet64;
                    string ramFormatted = $"{ramBytes / (1024 * 1024)}MB";

                    string preciseTimestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss");
                    string heapStr = (GC.GetTotalMemory(false) / (1024 * 1024)).ToString() + "MB";
                    float fpsVal = 40.0f;
                    int pfsCount = onlineCount;
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

                    // Structure JSON telemetry packet with CPU and RAM keys
                    var telemetryData = new
                    {
                        timestamp = preciseTimestamp,
                        type = "METRIC",
                        status = "Active",
                        uptime = uptimeStr,
                        heap = heapStr,
                        fps = fpsVal.ToString("0.0"),
                        players = onlineCount.ToString(),
                        pfs = pfsCount.ToString(),
                        ticks = tickCount.ToString(),
                        nwqueue = nwQueueVal.ToString(),
                        cpu = cpuPercent,
                        ram = ramFormatted,
                        player_list = playerList,
                        player_data = playerList
                    };

                    string jsonLine = JsonConvert.SerializeObject(telemetryData);

                    // Write live metric cache to disk
                    lock (_fileLock)
                    {
                        File.WriteAllText(_logFilePath, jsonLine + "\n");
                    }

                    // Broadcast JSON packet over TCP socket (Port 30500)
                    if (_telemetryServer != null && _telemetryServer.HasActiveConnections)
                    {
                        _telemetryServer.BroadcastJson(jsonLine);
                    }

                    _logCounter++;
                    if (_logCounter >= 7)
                    {
                        _logCounter = 0;
                        string formattedLog = $"-LOG- INFO: Uptime={uptimeStr} heap={heapStr} fps={fpsVal:0.0} cpu={cpuPercent}% ram={ramFormatted} players={onlineCount} pfs={pfsCount} ticks={tickCount} nwqueue={nwQueueVal}";

                        if (_modApi != null)
                        {
                            _modApi.Log(formattedLog);
                        }
                        else
                        {
                            Console.WriteLine($"{preciseTimestamp} [ZGB] {formattedLog}");
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
                        Console.WriteLine($"[ZGB] -ERROR- Telemetry loop exception: {ex.Message}");
                    }
                }

                Thread.Sleep(2000);
            }
        }
    }
}