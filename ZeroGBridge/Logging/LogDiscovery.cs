using System;
using System.IO;

namespace ZeroGBridge
{
    /// <summary>
    /// Handles active master dedicated log file discovery and file-stream tailing.
    /// Excludes Playfield child logs and pushes raw lines to the LogParser.
    /// </summary>
    public class LogDiscovery
    {
        private readonly LogParser _logParser;
        private string _targetLogPath = null;
        private long _lastLogFilePosition = 0;

        /// <summary>
        /// Initializes the log discovery engine with a reference to the LogParser.
        /// </summary>
        public LogDiscovery(LogParser logParser)
        {
            _logParser = logParser;
        }

        /// <summary>
        /// Scans directories to locate the active master dedicated server log file.
        /// </summary>
        public void ResolveActiveLogPath(string baseDir)
        {
            try
            {
                string newestLog = null;
                DateTime newestTime = DateTime.MinValue;

                // 1. Check root DedicatedServer.log
                string primaryLog = Path.Combine(baseDir, "DedicatedServer.log");
                if (File.Exists(primaryLog))
                {
                    newestLog = primaryLog;
                    newestTime = File.GetLastWriteTimeUtc(primaryLog);
                }

                // 2. Recursively scan Logs/ hierarchy, targeting Dedicated master logs only
                string logsFolder = Path.Combine(baseDir, "Logs");
                if (Directory.Exists(logsFolder))
                {
                    var files = Directory.GetFiles(logsFolder, "*.log", SearchOption.AllDirectories);
                    foreach (var file in files)
                    {
                        // Exclude mod logs and playfield server child logs
                        if (file.IndexOf("ZeroGBridge", StringComparison.OrdinalIgnoreCase) >= 0 ||
                            file.IndexOf("PfServer", StringComparison.OrdinalIgnoreCase) >= 0 ||
                            file.IndexOf("Playfield", StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            continue;
                        }

                        // Only evaluate logs that represent the master Dedicated server instance
                        if (file.IndexOf("Dedicated", StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            DateTime writeTime = File.GetLastWriteTimeUtc(file);
                            if (writeTime > newestTime)
                            {
                                newestTime = writeTime;
                                newestLog = file;
                            }
                        }
                    }
                }

                // 3. Attach to new active log and force initial seek pointer to byte 0
                if (!string.IsNullOrEmpty(newestLog) && _targetLogPath != newestLog)
                {
                    _targetLogPath = newestLog;
                    _lastLogFilePosition = 0;
                    Console.WriteLine($"[ZGB] -INFO- Locked log tailer to master log from byte 0: {_targetLogPath}");
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
        public void PollActiveLog()
        {
            if (string.IsNullOrEmpty(_targetLogPath) || !File.Exists(_targetLogPath))
            {
                ResolveActiveLogPath(AppDomain.CurrentDomain.BaseDirectory);
                if (string.IsNullOrEmpty(_targetLogPath) || !File.Exists(_targetLogPath))
                {
                    return;
                }
            }

            try
            {
                using (var fs = new FileStream(_targetLogPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                {
                    // Handle log rotation or file reset
                    if (fs.Length < _lastLogFilePosition)
                    {
                        _lastLogFilePosition = 0;
                    }

                    // Read newly appended bytes
                    if (fs.Length > _lastLogFilePosition)
                    {
                        fs.Seek(_lastLogFilePosition, SeekOrigin.Begin);
                        using (var sr = new StreamReader(fs))
                        {
                            string line;
                            while ((line = sr.ReadLine()) != null)
                            {
                                _logParser?.IngestLine(line);
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
    }
}