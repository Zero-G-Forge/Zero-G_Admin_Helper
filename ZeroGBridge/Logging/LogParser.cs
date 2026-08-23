using System;
using System.Text.RegularExpressions;

namespace ZeroGBridge
{
    /// <summary>
    /// Evaluates raw server log lines against pre-compiled regex patterns
    /// and synchronizes player states into the PlayerCache.
    /// </summary>
    public class LogParser
    {
        private readonly PlayerCache _playerCache;

        // Regex pattern matching Empyrion "Got player id:" connection lines
        private static readonly Regex PlayerGotIdRegex = new Regex(
            @"Got\s+player\s+id:\s*CId=(?<cid>\d+),\s*EId=(?<eid>-?\d+),\s*(?<steam>\d+)/=/'(?<name>[^']+)'", 
            RegexOptions.Compiled | RegexOptions.IgnoreCase);

        // Regex pattern matching player disconnect occurrences
        private static readonly Regex PlayerLeaveRegex = new Regex(
            @"(Player\s+'(?<steam>\d+)/(?<name>[^']*)'\s+disconnected|Player\s+with\s+id\s+(?<eid>\d+)\s+disconnected|disconnected:\s*(?<steam>\d+)|left\s+the\s+game)", 
            RegexOptions.Compiled | RegexOptions.IgnoreCase);

        /// <summary>
        /// Initializes the log parser with a shared PlayerCache reference.
        /// </summary>
        public LogParser(PlayerCache playerCache)
        {
            _playerCache = playerCache;
        }

        /// <summary>
        /// Ingests and processes a single log line to update active player records.
        /// </summary>
        public void IngestLine(string logLine)
        {
            if (string.IsNullOrEmpty(logLine) || _playerCache == null) return;

            try
            {
                // 1. Match player connection handshake line
                Match gotIdMatch = PlayerGotIdRegex.Match(logLine);
                if (gotIdMatch.Success)
                {
                    string steamId = gotIdMatch.Groups["steam"].Value;
                    string name = gotIdMatch.Groups["name"].Value;
                    int eid = int.TryParse(gotIdMatch.Groups["eid"].Value, out int e) ? e : 0;

                    _playerCache.AddOrUpdate(steamId, name, eid, 0);
                    Console.WriteLine($"[ZGB] -INFO- Player Verified & Cached: {name} (Steam: {steamId}, EId: {eid})");
                    return;
                }

                // 2. Match player disconnection line
                Match leaveMatch = PlayerLeaveRegex.Match(logLine);
                if (leaveMatch.Success)
                {
                    string steamId = leaveMatch.Groups["steam"].Value;
                    if (!string.IsNullOrEmpty(steamId))
                    {
                        bool removed = _playerCache.Remove(steamId);
                        if (removed)
                        {
                            Console.WriteLine($"[ZGB] -INFO- Player Disconnected: ({steamId})");
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -ERROR- Exception in LogParser.IngestLine: {ex.Message}");
            }
        }
    }
}