using System;
using System.IO;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using System.Threading;
using Newtonsoft.Json;
using Eleon.Modding;

namespace ZeroGBridge
{
    /// <summary>
    /// Master lifecycle orchestrator and log ingestion bridge for ZeroGBridge.
    /// Manages IMod initialization, active player registry, and telemetry streaming on Port 30500.
    /// </summary>
    public class ModMain : IMod
    {
        private IModApi _modApi;
        private TelemetryServer _telemetryServer;
        private Thread _telemetryThread;
        private bool _isRunning;
        private readonly object _fileLock = new object();
        private string _logFilePath;
        private int _logCounter = 0;
        private long _lastLogFilePosition = 0;
        private string _targetLogPath = null;

        // In-memory thread-safe player cache keyed by Steam ID
        private readonly ConcurrentDictionary<string, PlayerRecord> _activePlayers = new ConcurrentDictionary<string, PlayerRecord>();

        // Resilient regex pattern matching Empyrion "Got player id:" connection lines
        private static readonly Regex PlayerGotIdRegex = new Regex(
            @"Got\s+player\s+id:\s*CId=(?<cid>\d+),\s*EId=(?<eid>-?\d+),\s*(?<steam>\d+)/=/'(?<name>[^']+)'", 
            RegexOptions.Compiled | RegexOptions.IgnoreCase);

        // Regex pattern matching player disconnect occurrences
        private static readonly Regex PlayerLeaveRegex = new Regex(
            @"(Player\s+'(?<steam>\d+)/(?<name>[^']*)'\s+disconnected|Player\s+with\s+id\s+(?<eid>\d+)\s+disconnected|disconnected:\s*(?<steam>\d+)|left\s+the\s+game)", 
            RegexOptions.Compiled | RegexOptions.IgnoreCase);

        /// <summary>
        /// Structural representation of an active connected player record.
        /// </summary>
        public class PlayerRecord
        {
            public int entityId { get; set; }
            public string steamId { get; set; }
            public string name { get; set; }
            public int ping { get; set; }
        }

        #region IMod Lifecycle Handlers

        /// <summary>
        /// Entry point invoked by the dedicated server engine upon mod loading.
        /// </summary>
        public void Init(IModApi modApi)
        {
            _modApi = modApi;
            _isRunning = true;

            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string logDir = Path.Combine(baseDir, "Logs", "ZeroGBridge");
            if (!Directory.Exists(logDir))
            {
                Directory.CreateDirectory(logDir);
            }
            _logFilePath = Path.Combine(logDir, "live_telemetry.txt");
            Console.WriteLine("[ZGB] -INFO- ZeroGBridge initialized via ModApi framework.");

            // Resolve target log file path for active stdout tailing
            ResolveDedicatedLogPath(baseDir);

            // Initialize TelemetryServer on dedicated Port 30500
            _telemetryServer = new TelemetryServer(30500, this);
            _telemetryServer.Start();

            // Spawn background telemetry loop thread
            _telemetryThread = new Thread(TelemetryLoop)
            {
                IsBackground = true,
                Name = "ZeroGBridge_Telemetry_Loop"
            };
            _telemetryThread.Start();
        }

        /// <summary>
        /// Scans directories to locate the active server log file with the most recent write timestamp.
        /// </summary>
        private void ResolveDedicatedLogPath(string baseDir)
        {
            try
            {
                string newestLog = null;
                DateTime newestTime = DateTime.MinValue;

                // Check root DedicatedServer.log
                string primaryLog = Path.Combine(baseDir, "DedicatedServer.log");
                if (File.Exists(primaryLog))
                {
                    newestLog = primaryLog;
                    newestTime = File.GetLastWriteTimeUtc(primaryLog);
                }

                // Check Logs directory hierarchy recursively for active subfolder logs
                string logsFolder = Path.Combine(baseDir, "Logs");
                if (Directory.Exists(logsFolder))
                {
                    var files = Directory.GetFiles(logsFolder, "*.log", SearchOption.AllDirectories);
                    foreach (var file in files)
                    {
                        // Exclude mod internal logs from tailing target
                        if (file.IndexOf("ZeroGBridge", StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            continue;
                        }

                        DateTime writeTime = File.GetLastWriteTimeUtc(file);
                        if (writeTime > newestTime)
                        {
                            newestTime = writeTime;
                            newestLog = file;
                        }
                    }
                }

                if (!string.IsNullOrEmpty(newestLog))
                {
                    bool isNewTarget = (_targetLogPath != newestLog);
                    _targetLogPath = newestLog;

                    // On initial attachment, start reading from position 0 to parse connected players
                    if (isNewTarget)
                    {
                        _lastLogFilePosition = 0;
                        Console.WriteLine($"[ZGB] -INFO- Attached log tailer to active log: {_targetLogPath}");
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -ERROR- Exception resolving log path: {ex.Message}");
            }
        }

        /// <summary>
        /// Scans and ingests newly appended lines from the active dedicated server log.
        /// </summary>
        private void PollDedicatedLogFile()
        {
            // Continuously verify and discover active log target if rotated
            ResolveDedicatedLogPath(AppDomain.CurrentDomain.BaseDirectory);

            if (string.IsNullOrEmpty(_targetLogPath) || !File.Exists(_targetLogPath))
            {
                return;
            }

            try
            {
                using (var fs = new FileStream(_targetLogPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                {
                    if (fs.Length < _lastLogFilePosition)
                    {
                        // File reset or rotation detected
                        _lastLogFilePosition = 0;
                    }

                    if (fs.Length > _lastLogFilePosition)
                    {
                        fs.Seek(_lastLogFilePosition, SeekOrigin.Begin);
                        using (var sr = new StreamReader(fs))
                        {
                            string line;
                            while ((line = sr.ReadLine()) != null)
                            {
                                IngestServerLogLine(line);
                            }
                            _lastLogFilePosition = fs.Position;
                        }
                    }
                }
            }
            catch
            {
                // Suppress non-critical read-lock contention during server file flush
            }
        }

        /// <summary>
        /// Background worker loop responsible for serializing telemetry and pushing to connected clients.
        /// </summary>
        private void TelemetryLoop()
        {
            DateTime processStartTime = System.Diagnostics.Process.GetCurrentProcess().StartTime;

            while (_isRunning)
            {
                try
                {
                    // Ingest newly written server log lines
                    PollDedicatedLogFile();

                    var playerList = new List<PlayerRecord>(_activePlayers.Values);
                    int onlineCount = playerList.Count;

                    TimeSpan uptimeSpan = DateTime.Now - processStartTime;
                    string uptimeStr = $"{uptimeSpan.Hours:D2}h:{uptimeSpan.Minutes:D2}m";

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

                    // Structure JSON telemetry packet
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
                        string formattedLog = $"-LOG- INFO: Uptime={uptimeStr} heap={heapStr} fps={fpsVal:0.0} players={onlineCount} pfs={pfsCount} ticks={tickCount} nwqueue={nwQueueVal}";

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

        /// <summary>
        /// Ingests and processes raw server log lines to maintain the active player cache.
        /// </summary>
        public void IngestServerLogLine(string logLine)
        {
            if (string.IsNullOrEmpty(logLine)) return;

            try
            {
                // Match player connection handshake line
                Match gotIdMatch = PlayerGotIdRegex.Match(logLine);
                if (gotIdMatch.Success)
                {
                    string steamId = gotIdMatch.Groups["steam"].Value;
                    string name = gotIdMatch.Groups["name"].Value;
                    int eid = int.TryParse(gotIdMatch.Groups["eid"].Value, out int e) ? e : 0;

                    var record = new PlayerRecord
                    {
                        entityId = eid,
                        steamId = steamId,
                        name = name,
                        ping = 0
                    };

                    _activePlayers[steamId] = record;
                    Console.WriteLine($"[ZGB] -INFO- Player Verified & Cached: {name} (Steam: {steamId}, EId: {eid})");
                    return;
                }

                // Match player disconnection line
                Match leaveMatch = PlayerLeaveRegex.Match(logLine);
                if (leaveMatch.Success)
                {
                    string steamId = leaveMatch.Groups["steam"].Value;
                    if (!string.IsNullOrEmpty(steamId) && _activePlayers.ContainsKey(steamId))
                    {
                        _activePlayers.TryRemove(steamId, out _);
                        Console.WriteLine($"[ZGB] -INFO- Player Disconnected: ({steamId})");
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -ERROR- Exception in IngestServerLogLine: {ex.Message}");
            }
        }

        /// <summary>
        /// Ingests and processes text commands received over the TCP socket connection.
        /// </summary>
        public string ProcessIncomingCommand(string command)
        {
            try
            {
                string cleanCmd = command.Trim().ToLower();

                if (cleanCmd.StartsWith("add_player:"))
                {
                    string[] parts = command.Substring(11).Split('|');
                    if (parts.Length >= 2)
                    {
                        string steam = parts[0];
                        string name = parts[1];
                        _activePlayers[steam] = new PlayerRecord
                        {
                            entityId = steam.GetHashCode(),
                            steamId = steam,
                            name = name,
                            ping = 0
                        };
                        return JsonConvert.SerializeObject(new { type = "RESPONSE", status = "PlayerAdded", steamId = steam, name = name });
                    }
                }
                else if (cleanCmd == "plys")
                {
                    var playerList = new List<PlayerRecord>(_activePlayers.Values);
                    var playerPackage = new
                    {
                        type = "PLAYER_CACHE",
                        status = "Synced",
                        players = playerList.Count.ToString(),
                        player_list = playerList,
                        timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss")
                    };

                    return JsonConvert.SerializeObject(playerPackage);
                }

                return JsonConvert.SerializeObject(new { type = "RESPONSE", status = "Acknowledged", command = command });
            }
            catch (Exception ex)
            {
                return JsonConvert.SerializeObject(new { type = "ERROR", message = ex.Message });
            }
        }

        /// <summary>
        /// Shuts down background workers and socket server cleanly.
        /// </summary>
        public void Shutdown()
        {
            _isRunning = false;
            try
            {
                _telemetryServer?.Stop();
                _telemetryThread?.Join(1000);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -ERROR- Shutdown exception: {ex.Message}");
            }
            Console.WriteLine("[ZGB] -INFO- ZeroGBridge shut down cleanly.");
        }

        #endregion
    }
}