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

        public LogDiscovery(LogParser logParser)
        {
            _logParser = logParser;
        }

        /// <summary>
        /// Scans root, parent, and subdirectories to locate the active master DedicatedServer.log.
        /// </summary>
        public void ResolveActiveLogPath(string baseDir)
        {
            try
            {
                // 1. Check direct BaseDirectory and Parent Directory for DedicatedServer.log
                string[] directCandidates = new string[]
                {
                    Path.Combine(baseDir, "DedicatedServer.log"),
                    Path.Combine(Directory.GetParent(baseDir)?.FullName ?? baseDir, "DedicatedServer.log")
                };

                foreach (var candidate in directCandidates)
                {
                    if (File.Exists(candidate))
                    {
                        if (_targetLogPath != candidate)
                        {
                            _targetLogPath = candidate;
                            _lastLogFilePosition = 0;
                            Console.WriteLine($"[ZGB] -INFO- Locked log tailer directly to root log: {_targetLogPath}");
                        }
                        return;
                    }
                }

                // 2. Scan Logs/ in BaseDirectory and Parent Directory
                string[] searchRoots = new string[]
                {
                    baseDir,
                    Directory.GetParent(baseDir)?.FullName ?? baseDir
                };

                string newestLog = null;
                DateTime newestTime = DateTime.MinValue;

                foreach (var root in searchRoots)
                {
                    string logsFolder = Path.Combine(root, "Logs");
                    if (Directory.Exists(logsFolder))
                    {
                        var files = Directory.GetFiles(logsFolder, "*.log", SearchOption.AllDirectories);
                        foreach (var file in files)
                        {
                            if (file.IndexOf("ZeroGBridge", StringComparison.OrdinalIgnoreCase) >= 0 ||
                                file.IndexOf("PfServer", StringComparison.OrdinalIgnoreCase) >= 0 ||
                                file.IndexOf("Playfield", StringComparison.OrdinalIgnoreCase) >= 0)
                            {
                                continue;
                            }

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
                }

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
                    if (fs.Length < _lastLogFilePosition)
                    {
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