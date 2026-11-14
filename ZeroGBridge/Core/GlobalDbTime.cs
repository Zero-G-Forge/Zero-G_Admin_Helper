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

        /// <summary>UTC offset from the newest ServerStartStop row (0 if unknown).</summary>
        public static TimeSpan LatestOffset { get; private set; } = TimeSpan.Zero;

        public static List<StartStopSlice> LoadServerStartStop(SqliteConnection connection, List<string> cols)
        {
            var slices = new List<StartStopSlice>();
            LatestOffset = TimeSpan.Zero;
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
                    TimeSpan offset = ParseOffset(reader.IsDBNull(4) ? null : Convert.ToString(reader.GetValue(4)));
                    DateTime? start = ParseText(reader.IsDBNull(2) ? null : Convert.ToString(reader.GetValue(2)), offset);
                    if (!start.HasValue || reader.IsDBNull(0)) continue;

                    var slice = new StartStopSlice
                    {
                        StartTicks = Convert.ToInt64(reader.GetValue(0)),
                        StopTicks = reader.IsDBNull(1) ? 0 : Convert.ToInt64(reader.GetValue(1)),
                        StartUtc = start.Value,
                        StopUtc = ParseText(reader.IsDBNull(3) ? null : Convert.ToString(reader.GetValue(3)), offset)
                    };
                    slices.Add(slice);
                    LatestOffset = offset;
                }
            }
            return slices;
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

            StartStopSlice slice = slices.LastOrDefault(x => x.StartTicks <= ticks);
            if (slice == null) slice = slices[0];
            return slice.StartUtc.AddSeconds((ticks - slice.StartTicks) * slice.SecondsPerTick);
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
