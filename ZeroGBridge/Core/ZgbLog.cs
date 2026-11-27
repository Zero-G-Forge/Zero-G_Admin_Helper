// =====================================================================
// MODULE: ZeroGBridge/Core/ZgbLog.cs
// DESCRIPTION: Routes bridge messages to the Empyrion mod log (IModApi)
// =====================================================================

using System;
using Eleon.Modding;

namespace ZeroGBridge
{
    /// <summary>
    /// Central log sink. On a real server Console output does not reach the
    /// dedicated server log the panel shows, so messages go through
    /// IModApi.Log / LogWarning / LogError once the API is available.
    /// Level is taken from the "-TAG-" in the message:
    ///   -ERROR-            -> LogError
    ///   -WARN-             -> LogWarning
    ///   -DEBUG- / -TRACE-  -> console only (too chatty for the server log)
    ///   anything else      -> Log
    /// Before Init (or in unit tests without an API) everything goes to Console.
    /// </summary>
    public static class ZgbLog
    {
        /// <summary>1.5.0: set by CoreEntry when the core runs under the hot-reload loader (lines go to the loader's log).</summary>
        public static volatile Action<string> Sink;

        public static void Write(string message)
        {
            if (message == null) message = string.Empty;
            // -DEBUG- / -TRACE- are off unless ZeroGBridge.json has "LogLevel": "Debug" (or "Trace").
            // They used to go to Console.WriteLine, which still showed up in the dedicated server log.
            if (IsConsoleOnly(message) && !DebugEnabled()) return;
            var sink = Sink;
            if (sink != null)
            {
                try { sink(message); return; } catch { /* loader gone: fall through */ }
            }
            IModApi api = ModMain.ModApiInstance;

            if (api == null || IsConsoleOnly(message))
            {
                Console.WriteLine(message);
                return;
            }

            try
            {
                if (message.IndexOf("-ERROR-", StringComparison.Ordinal) >= 0)
                {
                    api.LogError(message);
                }
                else if (message.IndexOf("-WARN-", StringComparison.Ordinal) >= 0)
                {
                    api.LogWarning(message);
                }
                else
                {
                    api.Log(message);
                }
            }
            catch
            {
                // Never let logging break the bridge.
                Console.WriteLine(message);
            }
        }

        public static void Info(string message) { Write("[ZGB] -INFO- " + message); }
        public static void Warn(string message) { Write("[ZGB] -WARN- " + message); }
        public static void Error(string message) { Write("[ZGB] -ERROR- " + message); }

        private static bool IsConsoleOnly(string message)
        {
            return message.IndexOf("-DEBUG-", StringComparison.Ordinal) >= 0
                || message.IndexOf("-TRACE-", StringComparison.Ordinal) >= 0;
        }

        // Reads the existing AuthConfig.GetString helper. Missing or any other value means off.
        private static bool DebugEnabled()
        {
            try
            {
                string level = AuthConfig.GetString("LogLevel", "Info");
                return level.Equals("Debug", StringComparison.OrdinalIgnoreCase)
                    || level.Equals("Trace", StringComparison.OrdinalIgnoreCase);
            }
            catch { return false; }
        }
    }
}
