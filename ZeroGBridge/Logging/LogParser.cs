using System;
using System.Text.RegularExpressions;

namespace ZeroGBridge
{
    /// <summary>
    /// Evaluates raw server log lines against pre-compiled regex patterns
    /// and synchronizes player connection and disconnection states.
    /// </summary>
    public class LogParser
    {
        private readonly PlayerCache _playerCache;

        // Regex pattern matching Empyrion "Got player id:" connection lines
        private static readonly Regex PlayerGotIdRegex = new Regex(
            @"Got\s+player\s+id:\s*CId=(?<cid>\d+),\s*EId=(?<eid>-?\d+),\s*(?<steam>\d+)/=/'(?<name>[^']+)'", 
            RegexOptions.Compiled | RegexOptions.IgnoreCase);

        // Regex pattern matching Empyrion "[CM] Player ... disconnected" and fallback disconnect formats
        private static readonly Regex PlayerLeaveRegex = new Regex(
            @"(?:\[CM\]\s+Player\s+CId=(?<cid>\d+),\s*EId=(?<eid>-?\d+),\s*(?<steam>\d+)/=/'(?<name>[^']+)'\s+disconnected|" +
            @"\[PA\]\s+Player\s+'?(?<steam>\d+)?/?(?<name>[^'\s]+)?'?\s+logout|" +
            @"Player\s+'?(?<steam>\d+)?/?(?<name>[^'\s]+)?'?\s+disconnected|" +
            @"Player\s+with\s+id\s+(?<eid>\d+)\s+disconnected|" +
            @"disconnected:\s*(?<steam>\d+)|" +
            @"left\s+the\s+game|" +
            @"Closing\s+connection\s+for\s+CId=(?<cid>\d+))", 
            RegexOptions.Compiled | RegexOptions.IgnoreCase);

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
                    string steam = leaveMatch.Groups["steam"].Value;
                    string name = leaveMatch.Groups["name"].Value;
                    string eid = leaveMatch.Groups["eid"].Value;

                    string targetIdentifier = !string.IsNullOrEmpty(steam) ? steam : (!string.IsNullOrEmpty(name) ? name : eid);

                    if (!string.IsNullOrEmpty(targetIdentifier))
                    {
                        bool updated = _playerCache.MarkOffline(targetIdentifier);
                        if (updated)
                        {
                            Console.WriteLine($"[ZGB] -INFO- Player marked Offline: ({targetIdentifier})");
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