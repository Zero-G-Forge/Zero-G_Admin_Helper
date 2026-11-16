// =====================================================================
// MODULE: ZeroGBridge/Network/AlertService.cs
// DESCRIPTION: alert:{json} -> in-game HUD message (legacy Request_InGameMessage_*)
// =====================================================================

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using System.Threading;
using Eleon.Modding;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace ZeroGBridge
{
    /// <summary>
    /// Handles one alert request line and returns exactly one ALERT_ACK JSON line.
    ///
    /// Request:  alert:{"req_id":"..","target":"all|faction|player","id":"..","text":"..","prio":0|1|2,"duration":10}
    /// Ack:      {"type":"ALERT_ACK","req_id":"..","status":"sent"}
    ///           {"type":"ALERT_ACK","req_id":"..","status":"failed","error":"auth|bad_request|unknown_target|api_error|timeout"}
    /// prio = Empyrion IdMsgPrio.prio: 0 red (default), 1 yellow, 2 blue. duration in seconds (default 10).
    /// </summary>
    public class AlertService
    {
        public const string Prefix = "alert:";
        public const int MaxTextLength = 200;
        public const byte DefaultPrio = 0;
        public const float DefaultDurationSeconds = 10f;
        public const float MaxDurationSeconds = 300f;
        public const int MaxAlertsPerSecond = 5;
        private const int MaxRateWaitMs = 3000;
        private const int GameCallTimeoutMs = 5000;

        private readonly PlayerCache _playerCache;
        private readonly Queue<long> _recent = new Queue<long>();
        private readonly object _rateLock = new object();

        public AlertService(PlayerCache playerCache)
        {
            _playerCache = playerCache;
        }

        public static bool IsAlertLine(string line)
        {
            return line != null && line.StartsWith(Prefix, StringComparison.OrdinalIgnoreCase);
        }

        public static string Ack(string reqId, string error)
        {
            if (error == null)
                return JsonConvert.SerializeObject(new { type = "ALERT_ACK", req_id = reqId, status = "sent" });
            return JsonConvert.SerializeObject(new { type = "ALERT_ACK", req_id = reqId, status = "failed", error = error });
        }

        /// <summary>Best-effort req_id extraction (used for the not-authenticated reply).</summary>
        public static string TryGetReqId(string line)
        {
            try
            {
                var jo = JObject.Parse(line.Substring(Prefix.Length));
                return ScalarToString(jo["req_id"]);
            }
            catch { return null; }
        }

        public string Handle(string line)
        {
            string reqId = null;
            JObject jo;
            try
            {
                string body = line.Substring(Prefix.Length).Trim();
                jo = JObject.Parse(body);
            }
            catch
            {
                ZgbLog.Write("[ZGB] -WARN- alert: request is not valid JSON.");
                return Ack(null, "bad_request");
            }

            reqId = ScalarToString(jo["req_id"]);

            // target
            string target = (ScalarToString(jo["target"]) ?? "").Trim().ToLowerInvariant();
            if (target != "all" && target != "faction" && target != "player")
                return Fail(reqId, "bad_request", "target must be all, faction or player");

            // text
            string text = ScalarToString(jo["text"]);
            text = CleanText(text);
            if (string.IsNullOrEmpty(text))
                return Fail(reqId, "bad_request", "text is empty");

            // prio (default 0 = red)
            byte prio = DefaultPrio;
            var prioTok = jo["prio"];
            if (prioTok != null && prioTok.Type != JTokenType.Null)
            {
                if (!TryGetInt(prioTok, out int pv) || pv < 0 || pv > 2)
                    return Fail(reqId, "bad_request", "prio must be 0, 1 or 2");
                prio = (byte)pv;
            }

            // duration (default 10 s, capped)
            float duration = DefaultDurationSeconds;
            var durTok = jo["duration"];
            if (durTok != null && durTok.Type != JTokenType.Null)
            {
                if (!TryGetDouble(durTok, out double dv) || dv <= 0 || double.IsNaN(dv) || double.IsInfinity(dv))
                    return Fail(reqId, "bad_request", "duration must be a positive number of seconds");
                duration = (float)Math.Min(dv, MaxDurationSeconds);
            }

            // target id
            CmdId cmd;
            int targetId = 0;
            string idRaw = ScalarToString(jo["id"]);
            if (target == "all")
            {
                cmd = CmdId.Request_InGameMessage_AllPlayers;
            }
            else if (target == "faction")
            {
                if (string.IsNullOrWhiteSpace(idRaw))
                    return Fail(reqId, "bad_request", "faction target needs an id");
                if (_playerCache == null || !_playerCache.TryResolveFaction(idRaw, out targetId))
                    return Fail(reqId, "unknown_target", "faction not found: " + Short(idRaw));
                cmd = CmdId.Request_InGameMessage_Faction;
            }
            else
            {
                if (string.IsNullOrWhiteSpace(idRaw))
                    return Fail(reqId, "bad_request", "player target needs an id");
                if (_playerCache == null || !_playerCache.TryResolvePlayer(idRaw, out targetId, out _))
                    return Fail(reqId, "unknown_target", "player not found: " + Short(idRaw));
                cmd = CmdId.Request_InGameMessage_SinglePlayer;
            }

            // rate limit: at most MaxAlertsPerSecond across all clients; excess alerts wait for a slot
            if (!WaitForRateSlot())
                return Fail(reqId, "timeout", "rate limit wait exceeded");

            var payload = new IdMsgPrio(targetId, text, prio, duration);
            var result = LegacyApi.Request(cmd, payload, GameCallTimeoutMs, out string apiErr);
            switch (result)
            {
                case LegacyApi.RequestResult.Accepted:
                    ZgbLog.Write($"[ZGB] -INFO- Alert sent: target={target}{(target == "all" ? "" : " id=" + targetId)} prio={prio} duration={duration.ToString(CultureInfo.InvariantCulture)}s len={text.Length} req_id={Short(reqId)}");
                    return Ack(reqId, null);
                case LegacyApi.RequestResult.Timeout:
                    return Fail(reqId, "timeout", apiErr);
                default:
                    return Fail(reqId, "api_error", apiErr ?? result.ToString());
            }
        }

        private static string Fail(string reqId, string error, string why)
        {
            ZgbLog.Write($"[ZGB] -WARN- Alert failed ({error}) req_id={Short(reqId)}: {why}");
            return Ack(reqId, error);
        }

        private bool WaitForRateSlot()
        {
            var deadline = DateTime.UtcNow.AddMilliseconds(MaxRateWaitMs);
            while (true)
            {
                int waitMs;
                lock (_rateLock)
                {
                    long now = DateTime.UtcNow.Ticks;
                    long windowStart = now - TimeSpan.TicksPerSecond;
                    while (_recent.Count > 0 && _recent.Peek() <= windowStart) _recent.Dequeue();
                    if (_recent.Count < MaxAlertsPerSecond)
                    {
                        _recent.Enqueue(now);
                        return true;
                    }
                    waitMs = (int)((_recent.Peek() - windowStart) / TimeSpan.TicksPerMillisecond) + 1;
                }
                if (DateTime.UtcNow.AddMilliseconds(waitMs) > deadline) return false;
                Thread.Sleep(Math.Max(1, waitMs));
            }
        }

        /// <summary>Removes control characters and caps at 200 characters (never splits a surrogate pair).</summary>
        public static string CleanText(string text)
        {
            if (string.IsNullOrEmpty(text)) return text;
            var sb = new StringBuilder(Math.Min(text.Length, MaxTextLength + 1));
            foreach (char ch in text)
            {
                if (char.IsControl(ch)) { if (sb.Length > 0 && sb[sb.Length - 1] != ' ') sb.Append(' '); continue; }
                sb.Append(ch);
            }
            string s = sb.ToString().Trim();
            if (s.Length > MaxTextLength)
            {
                int cut = MaxTextLength;
                if (char.IsHighSurrogate(s[cut - 1])) cut--;
                s = s.Substring(0, cut);
            }
            return s;
        }

        private static string ScalarToString(JToken t)
        {
            if (t == null || t.Type == JTokenType.Null) return null;
            if (t.Type == JTokenType.String) return (string)t;
            if (t.Type == JTokenType.Integer || t.Type == JTokenType.Float || t.Type == JTokenType.Boolean)
                return Convert.ToString(((JValue)t).Value, CultureInfo.InvariantCulture);
            return null;
        }

        private static bool TryGetInt(JToken t, out int v)
        {
            v = 0;
            if (t.Type == JTokenType.Integer) { long l = (long)t; if (l < int.MinValue || l > int.MaxValue) return false; v = (int)l; return true; }
            if (t.Type == JTokenType.String) return int.TryParse((string)t, NumberStyles.Integer, CultureInfo.InvariantCulture, out v);
            return false;
        }

        private static bool TryGetDouble(JToken t, out double v)
        {
            v = 0;
            if (t.Type == JTokenType.Integer || t.Type == JTokenType.Float) { v = (double)t; return true; }
            if (t.Type == JTokenType.String) return double.TryParse((string)t, NumberStyles.Float, CultureInfo.InvariantCulture, out v);
            return false;
        }

        private static string Short(string s)
        {
            if (s == null) return "(none)";
            s = s.Replace("\r", " ").Replace("\n", " ");
            return s.Length <= 64 ? s : s.Substring(0, 64) + "...";
        }
    }
}
