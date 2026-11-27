// =====================================================================
// MODULE: ZeroGBridge/Network/ApiCommands.cs
// DESCRIPTION: 1.6.0 ZAH commands for the full Eleon API and the server console:
//   api:<RequestName or short name> [json | id | text]   -> one API_RESULT line
//   con:<console command line>   (aliases cmd: and exec:) -> one CONSOLE_RESULT line
//   cmds  (aliases help:commands, api:list)              -> one COMMAND_CATALOG line
// Every handler has its own try/catch: a bad command gets an ERROR line, never a crash.
// =====================================================================

using System;
using System.Globalization;
using System.Linq;
using Eleon.Modding;
using Newtonsoft.Json;
using Newtonsoft.Json.Converters;
using Newtonsoft.Json.Linq;

namespace ZeroGBridge
{
    public static class ApiCommands
    {
        public const string ApiPrefix = "api:";
        private static readonly string[] ConsolePrefixes = { "con:", "cmd:", "exec:" };
        private static readonly string[] CatalogWords = { "cmds", "help:commands", "api:list" }; // not "con:list": that is the console "list" command

        // Game data -> JSON (enums by name, no reference loops)
        private static JsonSerializer DataSerializer => JsonSerializer.Create(new JsonSerializerSettings
        {
            ReferenceLoopHandling = ReferenceLoopHandling.Ignore,
            Converters = { new StringEnumConverter() },
            Error = (s, e) => { e.ErrorContext.Handled = true; }
        });

        private static string Now() => DateTime.UtcNow.ToString("dd-HH:mm:ss");

        private static string Error(string code, string message, string command = null, string reqId = null) =>
            JsonConvert.SerializeObject(new { type = "ERROR", status = code, code, command, req_id = reqId, message, timestamp = Now() });

        public static bool IsCatalogLine(string lower) => CatalogWords.Contains(lower);
        public static bool IsApiLine(string lower) => lower.StartsWith(ApiPrefix) && !IsCatalogLine(lower);
        public static bool IsConsoleLine(string lower) => ConsolePrefixes.Any(p => lower.StartsWith(p)) && !IsCatalogLine(lower);

        // ------------------------------------------------------------------ cmds

        public static string Catalog()
        {
            try
            {
                return JsonConvert.SerializeObject(new
                {
                    type = "COMMAND_CATALOG",
                    release = ModMain.Release,
                    timestamp = Now(),
                    syntax = new
                    {
                        api = "api:<RequestName or short name> [{json params} | id | text]",
                        console = "con:<console command line>  (cmd: and exec: work too)",
                        catalog = "cmds",
                        restart = "restart:<minutes> (integer 0-15) or restart:cancel",
                        save = "save is not available from the bridge",
                        backup = "backup is not available from the bridge"
                    },
                    eleon_count = EleonRequests.All.Count,
                    console_count = ConsoleCatalog.All.Count,
                    zah_count = ZahShortcuts.Length,
                    eleon = EleonRequests.All.Select(r => r.ToJson()).ToArray(),
                    console = ConsoleCatalog.All.Select(c => c.ToJson()).ToArray(),
                    zah = ZahShortcuts
                });
            }
            catch (Exception ex)
            {
                return Error("exception", "Command catalog failed: " + ex.Message, "cmds");
            }
        }

        // ------------------------------------------------------------------ api:

        public static string HandleApi(string line)
        {
            string reqId = null;
            try
            {
                string rest = line.Substring(ApiPrefix.Length).Trim();
                int cut = rest.IndexOfAny(new[] { ' ', '\t', '{' });
                string name = cut < 0 ? rest : rest.Substring(0, cut);
                string args = cut < 0 ? "" : rest.Substring(cut).Trim();
                if (name.EndsWith(":")) name = name.TrimEnd(':');

                var def = EleonRequests.Find(name);
                if (def == null)
                    return Error("unknown_request", $"'{name}' is not an Eleon request. Send 'cmds' for the list.", name);

                object param;
                JObject controls;
                try { param = EleonRequests.BuildParam(def, args, out controls); }
                catch (BadParamsException bp) { return Error("bad_params", bp.Message, def.Name, TryReqId(args)); }
                reqId = (string)controls["req_id"];

                // console commands sent this way get the same checks as con:
                ConsoleCommand console = null;
                if (def.Cmd == CmdId.Request_ConsoleCommand)
                {
                    string text = (param as PString)?.pstr;
                    string why = ConsoleCatalog.Refusal(text, out console, out string code);
                    if (why != null) return Error(code, why, def.Name, reqId);
                }

                int? asked = controls["timeout_ms"]?.Type == JTokenType.Integer ? (int?)controls["timeout_ms"] : null;
                int timeout = EleonReplies.ReplyTimeout(def, asked);
                var res = EleonReplies.Run(def, param, timeout);
                // Request_Dedi_Stats is polled for uptime/fps; other api: calls stay ACTION.
                string apiTag = def.Name == "Request_Dedi_Stats" ? "DEBUG" : "ACTION";
                ZgbLog.Write($"[ZGB] -{apiTag}- api: {def.Name} seq {res.Seq} -> {res.Status}{(res.Event != null ? " (" + res.Event + ")" : "")} in {res.ElapsedMs} ms");

                return JsonConvert.SerializeObject(new
                {
                    type = "API_RESULT",
                    req_id = reqId,
                    request = def.Name,
                    cmd_id = (int)def.Cmd,
                    seq = res.Seq,
                    status = res.Status,
                    @event = res.Event?.ToString(),
                    error = res.Error,
                    data = ToData(res),
                    changes_server = console != null ? console.ChangesServerFor((param as PString)?.pstr) : def.ChangesServer,
                    elapsed_ms = res.ElapsedMs,
                    timeout_ms = timeout,
                    timestamp = Now()
                });
            }
            catch (Exception ex)
            {
                return Error("exception", "api: failed: " + ex.GetType().Name + ": " + ex.Message, null, reqId);
            }
        }

        private static string TryReqId(string args)
        {
            try { return args.StartsWith("{") ? (string)JObject.Parse(args)["req_id"] : null; } catch { return null; }
        }

        private static JToken ToData(EleonResult res)
        {
            if (res.Data == null) return null;
            try { return JToken.FromObject(res.Data, DataSerializer); }
            catch (Exception ex) { return new JObject { ["unreadable"] = res.Data.GetType().Name + ": " + ex.Message }; }
        }

        // ------------------------------------------------------------------ con: / cmd: / exec:

        public static string HandleConsole(string line)
        {
            string text = null;
            try
            {
                text = line.Substring(line.IndexOf(':') + 1).Trim();
                string why = ConsoleCatalog.Refusal(text, out var cmd, out string code);
                if (why != null)
                {
                    ZgbLog.Write($"[ZGB] -WARN- Console command refused ({code}): \"{text}\"");
                    return JsonConvert.SerializeObject(new
                    {
                        type = "ERROR", status = code, code, command = cmd?.Name, line = text,
                        server_capable = cmd?.ServerCapable, blocked = cmd?.Blocked, message = why, timestamp = Now()
                    });
                }

                var def = EleonRequests.Find("Request_ConsoleCommand");
                var res = EleonReplies.Run(def, new PString(text), EleonReplies.DefaultReplyTimeoutMs);
                ZgbLog.Write($"[ZGB] -ACTION- Console command \"{text}\" seq {res.Seq} -> {res.Status} in {res.ElapsedMs} ms");

                return JsonConvert.SerializeObject(new
                {
                    type = "CONSOLE_RESULT",
                    command = cmd.Name,
                    line = text,
                    seq = res.Seq,
                    status = res.Status,
                    @event = res.Event?.ToString(),
                    error = res.Error,
                    changes_server = cmd.ChangesServerFor(text),
                    elapsed_ms = res.ElapsedMs,
                    note = "The game only answers Ok or Error; the command's printed output goes to the server log.",
                    timestamp = Now()
                });
            }
            catch (Exception ex)
            {
                return JsonConvert.SerializeObject(new { type = "ERROR", status = "exception", code = "exception", line = text, message = "Console command failed: " + ex.Message, timestamp = Now() });
            }
        }

        // ------------------------------------------------------------------ save / backup / restart (CommandDispatcher)

        // ZAH shortcuts listed in the cmds catalog (not telnet commands)
        private static readonly object[] ZahShortcuts =
        {
            new { name = "restart", syntax = "restart:<minutes>", description = "Warns players with say, then sends saveandexit <minutes> (integer 0-15). That saves and stops the server; starting it again is the host panel's job.", changes_server = true, status = "implemented" },
            new { name = "restart:cancel", syntax = "restart:cancel", description = "Cancels a scheduled saveandexit (optional say, then saveandexit cancel).", changes_server = true, status = "implemented" },
            new { name = "save", syntax = "save", description = "Empyrion has no save-only command; the game autosaves and saveandexit saves before stopping.", changes_server = false, status = "not_available" },
            new { name = "backup", syntax = "backup", description = "Backups are done by ZAH over sFTP after the server stops, not by the bridge.", changes_server = false, status = "not_available" }
        };

        public static bool IsSaveOrBackupLine(string lower) => lower == "save" || lower == "backup";
        public static bool IsRestartLine(string lower) => lower == "restart" || lower.StartsWith("restart:");

        public static string HandleSaveOrBackup(string lowerCmd)
        {
            try
            {
                bool isSave = lowerCmd == "save";
                string message = isSave
                    ? "Empyrion has no save-only command; the game autosaves and saveandexit saves before stopping"
                    : "Backups are done by ZAH over sFTP after the server stops, not by the bridge";
                ZgbLog.Write($"[ZGB] -ACTION- Received '{lowerCmd}' directive from ZAH: not available.");
                return JsonConvert.SerializeObject(new
                {
                    type = "RESPONSE",
                    status = "not_available",
                    action = isSave ? "ServerSave" : "ServerBackup",
                    timestamp = Now(),
                    message,
                    executed = false
                });
            }
            catch (Exception ex)
            {
                return Error("exception", lowerCmd + " failed: " + ex.Message, lowerCmd);
            }
        }

        // restart:<minutes> (0-15) sends say, then saveandexit <minutes>.
        // restart:cancel sends an optional say, then saveandexit cancel.
        // Bare restart, or a bad minutes value, is refused and nothing is sent.
        public static string HandleRestart(string cleanCmd)
        {
            try
            {
                int colon = cleanCmd.IndexOf(':');
                string arg = colon < 0 ? "" : cleanCmd.Substring(colon + 1).Trim();

                if (string.IsNullOrEmpty(arg))
                {
                    ZgbLog.Write("[ZGB] -WARN- restart refused: minutes required (usage: restart:<minutes> or restart:cancel).");
                    return JsonConvert.SerializeObject(new
                    {
                        type = "ERROR",
                        status = "bad_params",
                        code = "bad_params",
                        action = "ServerRestart",
                        executed = false,
                        timestamp = Now(),
                        message = "Usage: restart:<minutes> (integer 0-15) or restart:cancel. Bare restart does not run."
                    });
                }

                if (arg.Equals("cancel", StringComparison.OrdinalIgnoreCase))
                {
                    ZgbLog.Write("[ZGB] -ACTION- Cancelling a scheduled restart (say, then saveandexit cancel).");
                    var say = SendConsole("say 'Server restart cancelled'");
                    var exit = SendConsole("saveandexit cancel");
                    bool executed = exit.Status == "ok";
                    string message = executed
                        ? "Scheduled restart cancelled."
                        : exit.Status == "timeout"
                            ? "saveandexit cancel was sent but the game did not answer before the deadline; the cancel may still have been applied."
                            : "Could not cancel the scheduled restart: " + (exit.Error ?? exit.Status);
                    return JsonConvert.SerializeObject(new
                    {
                        type = "RESPONSE",
                        status = executed ? "ok" : exit.Status,
                        action = "ServerRestart",
                        cancel = true,
                        executed,
                        say = say.ToJson(),
                        saveandexit = exit.ToJson(),
                        timestamp = Now(),
                        message
                    });
                }

                if (!int.TryParse(arg, NumberStyles.Integer, CultureInfo.InvariantCulture, out int minutes) || minutes < 0 || minutes > 15)
                {
                    ZgbLog.Write($"[ZGB] -WARN- restart refused: invalid minutes '{arg}'.");
                    return JsonConvert.SerializeObject(new
                    {
                        type = "ERROR",
                        status = "bad_params",
                        code = "bad_params",
                        action = "ServerRestart",
                        executed = false,
                        timestamp = Now(),
                        message = "restart:<minutes> needs an integer from 0 to 15, or use restart:cancel."
                    });
                }

                string unit = minutes == 1 ? "minute" : "minutes";
                string sayLine = "say 'Server restarting in " + minutes + " " + unit + "'";
                string exitLine = "saveandexit " + minutes;
                ZgbLog.Write($"[ZGB] -ACTION- Scheduling server restart in {minutes} {unit} ({sayLine}, then {exitLine}).");
                var sayRes = SendConsole(sayLine);
                var exitRes = SendConsole(exitLine);
                bool ok = exitRes.Status == "ok";
                string msg = ok
                    ? "Server restart scheduled in " + minutes + " " + unit + "."
                    : exitRes.Status == "timeout"
                        ? "saveandexit was sent but the game did not answer before the deadline; the restart may still be scheduled."
                        : "Server restart was not scheduled: " + (exitRes.Error ?? exitRes.Status);
                return JsonConvert.SerializeObject(new
                {
                    type = "RESPONSE",
                    status = ok ? "ok" : exitRes.Status,
                    action = "ServerRestart",
                    minutes,
                    executed = ok,
                    say = sayRes.ToJson(),
                    saveandexit = exitRes.ToJson(),
                    timestamp = Now(),
                    message = msg
                });
            }
            catch (Exception ex)
            {
                return JsonConvert.SerializeObject(new { type = "ERROR", status = "exception", code = "exception", action = "ServerRestart", executed = false, message = "restart failed: " + ex.Message, timestamp = Now() });
            }
        }

        // Sends one console line on the game thread via Request_ConsoleCommand, same path as con:.
        private static StepResult SendConsole(string text)
        {
            string why = ConsoleCatalog.Refusal(text, out var cmd, out string code);
            if (why != null)
            {
                ZgbLog.Write($"[ZGB] -WARN- Console command refused ({code}): \"{text}\"");
                return new StepResult { Line = text, Status = code, Error = why, Sent = false };
            }
            var def = EleonRequests.Find("Request_ConsoleCommand");
            var res = EleonReplies.Run(def, new PString(text), EleonReplies.DefaultReplyTimeoutMs);
            ZgbLog.Write($"[ZGB] -ACTION- Console command \"{text}\" seq {res.Seq} -> {res.Status} in {res.ElapsedMs} ms");
            return new StepResult
            {
                Line = text,
                Seq = res.Seq,
                Status = res.Status,
                Event = res.Event?.ToString(),
                Error = res.Error,
                ElapsedMs = res.ElapsedMs,
                Sent = true
            };
        }

        private sealed class StepResult
        {
            public string Line, Status, Event, Error;
            public ushort Seq;
            public long ElapsedMs;
            public bool Sent;
            public object ToJson() => new { line = Line, seq = Seq, status = Status, @event = Event, error = Error, elapsed_ms = ElapsedMs, sent = Sent };
        }

        // ------------------------------------------------------------------ loadpf (CommandDispatcher)

        // Sends Request_Load_Playfield and waits briefly; the reply keeps the old loadpf keys.
        public static string LoadPlayfield(string playfieldName, float seconds)
        {
            try
            {
                var def = EleonRequests.Find("Request_Load_Playfield");
                var param = new PlayfieldLoad { playfield = playfieldName, sec = seconds, processId = 0 };
                var res = EleonReplies.Run(def, param, 500);
                bool sent = res.Status == "ok" || (res.Status == "timeout" && res.Error != null && res.Error.StartsWith("no answer from the game")); // timeout = accepted, still loading
                string status = res.Status == "ok" ? (res.Event == CmdId.Event_Playfield_Loaded ? "Loaded" : "Initiated")
                    : sent ? "Initiated" : "Failed";
                return JsonConvert.SerializeObject(new
                {
                    type = sent ? "RESPONSE" : "ERROR",
                    status,
                    action = "LoadPlayfield",
                    playfield = playfieldName,
                    seconds,
                    seq = res.Seq,
                    api_status = res.Status,
                    @event = res.Event?.ToString(),
                    error = res.Error,
                    timestamp = Now(),
                    message = sent ? $"Playfield load request dispatched for {playfieldName}." : $"Playfield load request for {playfieldName} failed: {res.Error}"
                });
            }
            catch (Exception ex)
            {
                return JsonConvert.SerializeObject(new { type = "ERROR", message = "loadpf failed: " + ex.Message });
            }
        }
    }
}
