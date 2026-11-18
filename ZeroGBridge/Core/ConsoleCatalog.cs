// =====================================================================
// MODULE: ZeroGBridge/Core/ConsoleCatalog.cs
// DESCRIPTION: 1.6.0 console / telnet command catalog (names, aliases, permission, flags).
//              The rows live in ConsoleCatalogData.cs (from Ray's command sheet).
// =====================================================================

using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace ZeroGBridge
{
    // One row of the command sheet, as written in ConsoleCatalogData.cs
    internal sealed class ConsoleCommandInfoRow
    {
        public readonly string SheetName;     // e.g. "debugmenu or dm"
        public readonly string Description;
        public readonly bool ServerCapable;   // sheet column "Is telnet?" = V
        public readonly string Permission;    // sheet text, e.g. "6+ ?"
        public readonly bool ChangesServer;
        public readonly bool SafeWithoutArgs; // e.g. "ticks" only reads, "ticks set .." changes
        public readonly string BlockedReason; // null = not blocked
        public readonly string Source;        // "sheet" or "telnet_wiki"

        public ConsoleCommandInfoRow(string sheetName, string description, bool serverCapable, string permission,
            bool changesServer, bool safeWithoutArgs, string blockedReason, string source)
        {
            SheetName = sheetName; Description = description; ServerCapable = serverCapable; Permission = permission;
            ChangesServer = changesServer; SafeWithoutArgs = safeWithoutArgs; BlockedReason = blockedReason; Source = source;
        }
    }

    // A console command ZAH can show in its menus
    public sealed class ConsoleCommand
    {
        public string Name;            // main name, lower case ("debugmenu", "ds reload")
        public string Keyword;         // first word typed for it ("debugmenu", "ds")
        public string[] Aliases;       // short names ("dm")
        public string Description;
        public string Permission;      // as written in the sheet
        public int MinPermission;      // number from the sheet, -1 when unknown
        public bool ServerCapable;     // can run over telnet / the server console
        public bool ChangesServer;     // ZAH puts this behind CONFIRM
        public bool SafeWithoutArgs;   // with no arguments it only shows information
        public bool Blocked;
        public string BlockedReason;
        public string Source;

        // Does this exact line change the server? ("ticks" = no, "ticks set 10" = yes)
        public bool ChangesServerFor(string line)
        {
            if (!ChangesServer) return false;
            if (!SafeWithoutArgs) return true;
            return ConsoleCatalog.SplitFirstWord(line, out _).Length > 0;
        }

        public object ToJson() => new
        {
            name = Name,
            aliases = Aliases,
            description = Description,
            permission = Permission,
            min_permission = MinPermission,
            server_capable = ServerCapable,
            changes_server = ChangesServer,
            safe_without_args = SafeWithoutArgs,
            blocked = Blocked,
            blocked_reason = BlockedReason,
            source = Source
        };
    }

    public static class ConsoleCatalog
    {
        private static readonly List<ConsoleCommand> _all = new List<ConsoleCommand>();
        private static readonly Dictionary<string, ConsoleCommand> _byWord = new Dictionary<string, ConsoleCommand>(StringComparer.OrdinalIgnoreCase);

        static ConsoleCatalog()
        {
            foreach (var row in ConsoleCatalogData.Rows)
            {
                try
                {
                    // "debugmenu or dm" -> name debugmenu, alias dm
                    var parts = Regex.Split(row.SheetName.Trim(), @"\s+or\s+", RegexOptions.IgnoreCase)
                        .Select(p => p.Trim().ToLowerInvariant()).Where(p => p.Length > 0).ToArray();
                    if (parts.Length == 0) continue;
                    var cmd = new ConsoleCommand
                    {
                        Name = parts[0],
                        Keyword = parts[0].Split(' ')[0],
                        Aliases = parts.Skip(1).ToArray(),
                        Description = row.Description,
                        Permission = row.Permission,
                        MinPermission = ParseLevel(row.Permission),
                        ServerCapable = row.ServerCapable,
                        ChangesServer = row.ChangesServer,
                        SafeWithoutArgs = row.SafeWithoutArgs,
                        Blocked = row.BlockedReason != null,
                        BlockedReason = row.BlockedReason,
                        Source = row.Source
                    };
                    _all.Add(cmd);
                    if (!_byWord.ContainsKey(cmd.Keyword)) _byWord[cmd.Keyword] = cmd;
                    foreach (var a in cmd.Aliases) if (!_byWord.ContainsKey(a)) _byWord[a] = cmd;
                }
                catch (Exception ex)
                {
                    ZgbLog.Write($"[ZGB] -WARN- Console catalog row '{row.SheetName}' skipped: {ex.Message}");
                }
            }
        }

        public static IReadOnlyList<ConsoleCommand> All => _all;

        // Finds the command for a typed line ("dm", "kick 123", "ds reload")
        public static ConsoleCommand Find(string line)
        {
            SplitFirstWord(line, out string word);
            if (string.IsNullOrEmpty(word)) return null;
            return _byWord.TryGetValue(word, out var c) ? c : null;
        }

        // Returns the arguments after the first word; the first word goes to "word"
        internal static string SplitFirstWord(string line, out string word)
        {
            line = (line ?? "").Trim();
            int sp = line.IndexOfAny(new[] { ' ', '\t' });
            if (sp < 0) { word = line; return ""; }
            word = line.Substring(0, sp);
            return line.Substring(sp + 1).Trim();
        }

        private static int ParseLevel(string p)
        {
            var m = Regex.Match(p ?? "", @"^\s*(\d+)");
            return m.Success ? int.Parse(m.Groups[1].Value) : -1;
        }

        // Why a line may not be sent to the server, or null when it can be sent
        public static string Refusal(string line, out ConsoleCommand cmd, out string code)
        {
            cmd = Find(line);
            code = null;
            if (string.IsNullOrWhiteSpace(line)) { code = "empty"; return "No console command given."; }
            if (line.IndexOfAny(new[] { '\r', '\n', '\0' }) >= 0) { code = "bad_text"; return "The console command must be one line."; }
            if (cmd == null) { SplitFirstWord(line, out string word); code = "unknown_command"; return $"'{word}' is not in the console command list. Send 'cmds' for the list."; }
            if (cmd.Blocked) { code = "blocked"; return cmd.BlockedReason; }
            if (!cmd.ServerCapable) { code = "client_only"; return $"'{cmd.Name}' only works in the game client console, not over telnet or the server console."; }
            return null;
        }
    }
}
