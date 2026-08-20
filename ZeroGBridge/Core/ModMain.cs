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
    /// Main entry point for ZeroGBridge mod, tuned precisely to Empyrion's dedicated server file layout.
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

        // In-memory thread-safe player cache
        private readonly ConcurrentDictionary<string, object> _activePlayers = new ConcurrentDictionary<string, object>();

        // Exact match regex for Empyrion's "Got player id:" connection line
        private static readonly Regex PlayerGotIdRegex = new Regex(
            @"Got\s+player\s+id:\s*CId=(?<cid>\d+),\s*EId=(?<eid>-?\d+),\s*(?<steam>\d+)/=/'(?<name>[^']+)'", 
            RegexOptions.Compiled | RegexOptions.IgnoreCase);

        // Regex for explicit disconnections
        private static readonly Regex PlayerLeaveRegex = new Regex(
            @"(Player\s+'(?<steam>\d+)/(?<name>[^']*)'\s+disconnected|Player\s+with\s+id\s+(?<eid>\d+)\s+disconnected|disconnected:\s*(?<steam>\d+)|left\s+the\s+game)", 
            RegexOptions.Compiled | RegexOptions.IgnoreCase);

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
            Console.WriteLine("[ZGB] INFO: ZeroGBridge initialized via ModApi framework.");

            // Target the root DedicatedServer.log file explicitly based on server startup arguments
            ResolveDedicatedLogPath(baseDir);

            _telemetryServer = new TelemetryServer(30080, this);
            _telemetryServer.Start();

            _telemetryThread = new Thread(TelemetryLoop)
            {
                IsBackground = true,
                Name = "ZeroGBridge_Telemetry_Loop"
            };
            _telemetryThread.Start();
        }

        private void ResolveDedicatedLogPath(string baseDir)
        {
            // Empyrion stores DedicatedServer.log in the root base directory
            string primaryLog = Path.Combine(baseDir, "DedicatedServer.log");
            if (File.Exists(primaryLog))
            {
                _targetLogPath = primaryLog;
                FileInfo fi = new FileInfo(_targetLogPath);
                _lastLogFilePosition = fi.Length; // Tail from current end
                Console.WriteLine($"[ZGB] INFO: Attached log tailer to {_targetLogPath}");
            }
            else
            {
                // Fallback scan if named differently
                try
                {
                    string logsFolder = Path.Combine(baseDir, "Logs");
                    if (Directory.Exists(logsFolder))
                    {
                        var files = Directory.GetFiles(logsFolder, "*.log");
                        if (files.Length > 0)
                        {
                            Array.Sort(files);
                            _targetLogPath = files[files.Length - 1];
                            FileInfo fi = new FileInfo(_targetLogPath);
                            _lastLogFilePosition = fi.Length;
                        }
                    }
                }
                catch { }
            }
        }

        private void PollDedicatedLogFile()
        {
            if (string.IsNullOrEmpty(_targetLogPath) || !File.Exists(_targetLogPath))
            {
                ResolveDedicatedLogPath(AppDomain.CurrentDomain.BaseDirectory);
                return;
            }

            try
            {
                using (var fs = new FileStream(_targetLogPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                {
                    if (fs.Length < _lastLogFilePosition)
                    {
                        _lastLogFilePosition = 0; // File rotated or reset
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
            catch { }
        }

        private void TelemetryLoop()
        {
            DateTime processStartTime = System.Diagnostics.Process.GetCurrentProcess().StartTime;

            while (_isRunning)
            {
                try
                {
                    // Tail server log for active player events
                    PollDedicatedLogFile();

                    var playerList = new List<object>(_activePlayers.Values);
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

                    lock (_fileLock)
                    {
                        File.WriteAllText(_logFilePath, jsonLine + "\n");
                    }

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
                        Console.WriteLine($"[ZGB] ERROR: Telemetry loop exception: {ex.Message}");
                    }
                }

                Thread.Sleep(2000);
            }
        }

        public void IngestServerLogLine(string logLine)
        {
            if (string.IsNullOrEmpty(logLine)) return;
            // Temporary diagnostic: Print every line hitting the parser
            // Console.WriteLine($"[ZGB-DEBUG] Reading: {logLine}");

            try
            {
                // 1. Check "Got player id:" pattern
                Match gotIdMatch = PlayerGotIdRegex.Match(logLine);
                if (gotIdMatch.Success)
                {
                    string steamId = gotIdMatch.Groups["steam"].Value;
                    string name = gotIdMatch.Groups["name"].Value;
                    int eid = int.TryParse(gotIdMatch.Groups["eid"].Value, out int e) ? e : 0;

                    _activePlayers[steamId] = new
                    {
                        entityId = eid,
                        steamId = steamId,
                        name = name,
                        ping = 0
                    };
                    _modApi.Log($"[ZGB] Player Verified & Cached: {name} (Steam: {steamId}, EId: {eid})");
                    // Console.WriteLine($"[ZGB] Player Verified & Cached: {name} (Steam: {steamId}, EId: {eid})");

                    return;
                }

                // 2. Check disconnect pattern
                Match leaveMatch = PlayerLeaveRegex.Match(logLine);
                if (leaveMatch.Success)
                {
                    string steamId = leaveMatch.Groups["steam"].Value;
                    if (!string.IsNullOrEmpty(steamId) && _activePlayers.ContainsKey(steamId))
                    {
                        _activePlayers.TryRemove(steamId, out _);
                        _modApi.Log($"[ZGB] Player Disconnected: ({steamId})");
                        // Console.WriteLine($"[ZGB] Player Disconnected: ({steamId})");
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] ERROR in IngestServerLogLine: {ex.Message}");
            }
        }

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
                        _activePlayers[steam] = new
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
                    var playerList = new List<object>(_activePlayers.Values);
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
                Console.WriteLine($"[ZGB] ERROR: Shutdown exception: {ex.Message}");
            }
            Console.WriteLine("[ZGB] INFO: ZeroGBridge shut down cleanly.");
        }
    }
}