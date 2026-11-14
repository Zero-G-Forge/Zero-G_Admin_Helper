// =====================================================================
// MODULE: ZeroGBridge/Core/GlobalDbTime.cs
// DESCRIPTION: Converts global.db time values (game ticks, unix, text) to UTC
// =====================================================================

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;
using Mono.Data.Sqlite;

namespace ZeroGBridge
{
    public class StartStopSlice
    {
        public long StartTicks;
        public long StopTicks;      // 0 when the session has no stop row yet
        public DateTime StartUtc;
        public DateTime? StopUtc;

        // Both readings of the stored text: "local" = text minus the row's timezone,
        // "raw" = text already in UTC. Calibrate() picks one for every slice.
        public DateTime StartUtcLocal;
        public DateTime StartUtcRaw;
        public DateTime? StopUtcLocal;
        public DateTime? StopUtcRaw;
        public string StartText;
        public string TimezoneText;

        public double SecondsPerTick
        {
            get
            {
                if (StopUtc.HasValue && StopTicks > StartTicks)
                {
                    double s = (StopUtc.Value - StartUtc).TotalSeconds / (StopTicks - StartTicks);
                    if (s > 0 && s < 10) return s;
                }
                return GlobalDbTime.DefaultSecondsPerTick;
            }
        }
    }

    public static class GlobalDbTime
    {
        // Empyrion runs at ~20 ticks/s by default.
        public const double DefaultSecondsPerTick = 0.05;

        /// <summary>UTC offset from the newest ServerStartStop row (0 if unknown, or 0 in "raw" mode).</summary>
        public static TimeSpan LatestOffset { get; private set; } = TimeSpan.Zero;

        /// <summary>How starttime/stoptime text is read: "local" (minus timezone) or "raw" (already UTC).</summary>
        public static string TextMode { get; private set; } = "local";

        /// <summary>One-line description of the last Calibrate() decision (for the mod log).</summary>
        public static string CalibrationNote { get; private set; } = "not calibrated";

        // Values more than this far in the future are rejected (never reported as last_seen).
        public static readonly TimeSpan FutureTolerance = TimeSpan.FromMinutes(2);

        private static TimeSpan _rowOffset = TimeSpan.Zero;

        public static List<StartStopSlice> LoadServerStartStop(SqliteConnection connection, List<string> cols)
        {
            var slices = new List<StartStopSlice>();
            LatestOffset = TimeSpan.Zero;
            _rowOffset = TimeSpan.Zero;
            TextMode = "local";
            CalibrationNote = "not calibrated";
            if (cols == null || cols.Count == 0) return slices;

            bool has(string c) => cols.Any(x => string.Equals(x, c, StringComparison.OrdinalIgnoreCase));
            if (!has("startticks") || !has("starttime")) return slices;

            string sql = "SELECT startticks, "
                + (has("stopticks") ? "stopticks" : "NULL") + ", starttime, "
                + (has("stoptime") ? "stoptime" : "NULL") + ", "
                + (has("timezone") ? "timezone" : "NULL")
                + " FROM ServerStartStop ORDER BY " + (has("sid") ? "sid" : "startticks") + ";";

            using (var cmd = new SqliteCommand(sql, connection))
            using (var reader = cmd.ExecuteReader())
            {
                while (reader.Read())
                {
                    string tzText = reader.IsDBNull(4) ? null : Convert.ToString(reader.GetValue(4));
                    TimeSpan offset = ParseOffset(tzText);
                    string startText = reader.IsDBNull(2) ? null : Convert.ToString(reader.GetValue(2));
                    string stopText = reader.IsDBNull(3) ? null : Convert.ToString(reader.GetValue(3));
                    DateTime? start = ParseText(startText, offset);
                    DateTime? startRaw = ParseText(startText, TimeSpan.Zero);
                    if (!start.HasValue || !startRaw.HasValue || reader.IsDBNull(0)) continue;

                    DateTime? stop = ParseText(stopText, offset);
                    var slice = new StartStopSlice
                    {
                        StartTicks = Convert.ToInt64(reader.GetValue(0)),
                        StopTicks = reader.IsDBNull(1) ? 0 : Convert.ToInt64(reader.GetValue(1)),
                        StartUtc = start.Value,
                        StopUtc = stop,
                        StartUtcLocal = start.Value,
                        StartUtcRaw = startRaw.Value,
                        StopUtcLocal = stop,
                        StopUtcRaw = ParseText(stopText, TimeSpan.Zero),
                        StartText = startText,
                        TimezoneText = tzText
                    };
                    slices.Add(slice);
                    LatestOffset = offset;
                    _rowOffset = offset;
                }
            }
            return slices;
        }

        /// <summary>
        /// Decides whether ServerStartStop text is server-local ("local") or already UTC ("raw")
        /// by checking it against the live clock. Real tick rate is 20/s (verified on real saves:
        /// every closed slice is 20.0 ticks/s, and live METRIC shows 520 ticks in 26 s).
        ///   - newest slice open (current session): its start must equal
        ///     now - (GameTicks - startticks) * 0.05 s, or the process start time;
        ///   - newest slice closed (Init ran before the new row was written): the current session
        ///     began at its stopticks, so the stop time must be shortly before that moment.
        /// Keeps "local" (the 1.2 behaviour) when nothing decides it.
        /// </summary>
        public static string Calibrate(List<StartStopSlice> slices, ulong gameTicks, DateTime nowUtc, DateTime? processStartUtc)
        {
            TextMode = "local";
            if (slices == null || slices.Count == 0) { CalibrationNote = "no ServerStartStop rows"; return Apply(slices, "local"); }

            var last = slices[slices.Count - 1];
            string row = $"newest row startticks={last.StartTicks} stopticks={last.StopTicks} starttime='{last.StartText}' timezone='{last.TimezoneText}'";
            if (Math.Abs((last.StartUtcLocal - last.StartUtcRaw).TotalMinutes) < 1)
            {
                CalibrationNote = row + "; timezone 0, nothing to calibrate";
                return Apply(slices, "local");
            }

            DateTime? expected = null;
            string how = null;
            bool open = last.StopTicks <= 0 && !last.StopUtcLocal.HasValue;

            if (open)
            {
                if (gameTicks > 0 && (long)gameTicks >= last.StartTicks)
                {
                    expected = nowUtc.AddSeconds(-((long)gameTicks - last.StartTicks) * DefaultSecondsPerTick);
                    how = "GameTicks";
                }
                else if (processStartUtc.HasValue)
                {
                    expected = processStartUtc.Value;
                    how = "process start";
                }

                if (expected.HasValue)
                {
                    double errLocal = Math.Abs((last.StartUtcLocal - expected.Value).TotalMinutes);
                    double errRaw = Math.Abs((last.StartUtcRaw - expected.Value).TotalMinutes);
                    string pick = Math.Min(errLocal, errRaw) <= 20 ? (errRaw < errLocal ? "raw" : "local") : "local";
                    CalibrationNote = $"{row}; session start by {how}={expected.Value:yyyy-MM-dd HH:mm:ss}Z, error local={errLocal:0.#}m raw={errRaw:0.#}m -> {pick}";
                    return Apply(slices, pick);
                }
            }
            else if (last.StopTicks > 0)
            {
                if (gameTicks > 0 && (long)gameTicks >= last.StopTicks)
                {
                    expected = nowUtc.AddSeconds(-((long)gameTicks - last.StopTicks) * DefaultSecondsPerTick);
                    how = "GameTicks";
                }
                else if (processStartUtc.HasValue)
                {
                    expected = processStartUtc.Value;
                    how = "process start";
                }

                if (expected.HasValue && last.StopUtcLocal.HasValue && last.StopUtcRaw.HasValue)
                {
                    // downtime between the newest stop row and the current session start
                    double dLocal = (expected.Value - last.StopUtcLocal.Value).TotalMinutes;
                    double dRaw = (expected.Value - last.StopUtcRaw.Value).TotalMinutes;
                    bool okLocal = dLocal >= -5 && dLocal <= 360;
                    bool okRaw = dRaw >= -5 && dRaw <= 360;
                    string pick = okRaw && !okLocal ? "raw"
                                : okLocal && !okRaw ? "local"
                                : okLocal && okRaw ? (Math.Abs(dRaw) < Math.Abs(dLocal) ? "raw" : "local")
                                : "local";
                    CalibrationNote = $"{row}; current session start by {how}={expected.Value:yyyy-MM-dd HH:mm:ss}Z, downtime local={dLocal:0.#}m raw={dRaw:0.#}m -> {pick}";
                    return Apply(slices, pick);
                }
            }

            CalibrationNote = row + "; no live anchor (GameTicks/process start), keeping local";
            return Apply(slices, "local");
        }

        private static string Apply(List<StartStopSlice> slices, string mode)
        {
            TextMode = mode;
            LatestOffset = mode == "raw" ? TimeSpan.Zero : _rowOffset;
            if (slices != null)
            {
                foreach (var sl in slices)
                {
                    sl.StartUtc = mode == "raw" ? sl.StartUtcRaw : sl.StartUtcLocal;
                    sl.StopUtc = mode == "raw" ? sl.StopUtcRaw : sl.StopUtcLocal;
                }
            }
            return mode;
        }

        /// <summary>Rejects values in the future (beyond FutureTolerance); returns null for them.</summary>
        public static DateTime? NotInFuture(DateTime? value, DateTime nowUtc)
        {
            if (!value.HasValue) return null;
            return value.Value > nowUtc + FutureTolerance ? (DateTime?)null : value;
        }

        /// <summary>
        /// value may be: game ticks (&lt; 1e9), unix seconds, unix ms, .NET ticks, or text.
        /// Text without an explicit offset is treated as server-local using tzOffset.
        /// </summary>
        public static DateTime? ToUtc(object value, List<StartStopSlice> slices, TimeSpan tzOffset)
        {
            if (value == null || value is DBNull) return null;

            if (value is string s)
            {
                s = s.Trim();
                if (s.Length == 0) return null;
                double n;
                if (double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out n)) return FromNumber(n, slices);
                return ParseText(s, tzOffset);
            }

            if (value is DateTime dt)
            {
                return dt.Kind == DateTimeKind.Utc ? dt : DateTime.SpecifyKind(dt - tzOffset, DateTimeKind.Utc);
            }

            try { return FromNumber(Convert.ToDouble(value, CultureInfo.InvariantCulture), slices); }
            catch { return null; }
        }

        public static DateTime? FromNumber(double n, List<StartStopSlice> slices)
        {
            if (n <= 0) return null;
            if (n >= 6e17) return new DateTime((long)n, DateTimeKind.Utc);                 // .NET ticks
            if (n >= 1e11) return UnixEpoch.AddMilliseconds(n);                              // unix ms
            if (n >= 1e9) return UnixEpoch.AddSeconds(n);                                    // unix seconds
            return FromGameTicks((long)n, slices);                                           // game ticks
        }

        public static DateTime? FromGameTicks(long ticks, List<StartStopSlice> slices)
        {
            if (slices == null || slices.Count == 0) return null;

            int idx = -1;
            for (int i = 0; i < slices.Count; i++)
            {
                if (slices[i].StartTicks <= ticks) idx = i;
            }
            if (idx < 0) idx = 0;
            StartStopSlice slice = slices[idx];
            DateTime t = slice.StartUtc.AddSeconds((ticks - slice.StartTicks) * slice.SecondsPerTick);

            // A tick inside a session can never be later than that session's stop or the next start.
            if (slice.StopUtc.HasValue && slice.StopTicks > 0 && ticks <= slice.StopTicks && t > slice.StopUtc.Value) t = slice.StopUtc.Value;
            if (idx + 1 < slices.Count && t > slices[idx + 1].StartUtc) t = slices[idx + 1].StartUtc;
            return t;
        }

        // "...Z", "...+02:00", "...-0600" (time part present, so a date "-" is not matched)
        private static readonly Regex ExplicitOffset = new Regex(@"\d{2}:\d{2}(:\d{2}(\.\d+)?)?\s*(Z|[+-]\d{2}:?\d{2})$", RegexOptions.Compiled);

        private static readonly DateTime UnixEpoch = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);

        public static DateTime? ParseText(string s, TimeSpan offset)
        {
            if (string.IsNullOrWhiteSpace(s)) return null;
            DateTimeOffset dto;
            // Explicit offset in the string wins.
            if (ExplicitOffset.IsMatch(s.Trim()) &&
                DateTimeOffset.TryParse(s, CultureInfo.InvariantCulture, DateTimeStyles.None, out dto))
            {
                return dto.UtcDateTime;
            }
            DateTime local;
            if (DateTime.TryParse(s, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out local))
            {
                return DateTime.SpecifyKind(local - offset, DateTimeKind.Utc);
            }
            return null;
        }

        public static TimeSpan ParseOffset(string tz)
        {
            if (string.IsNullOrWhiteSpace(tz)) return TimeSpan.Zero;
            string t = tz.Trim();
            bool neg = t.StartsWith("-");
            t = t.TrimStart('+', '-');
            TimeSpan ts;
            if (TimeSpan.TryParse(t, CultureInfo.InvariantCulture, out ts))
            {
                return neg ? ts.Negate() : ts;
            }
            return TimeSpan.Zero;
        }
    }
}
