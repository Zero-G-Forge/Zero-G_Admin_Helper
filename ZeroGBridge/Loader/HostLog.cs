// =====================================================================
// MODULE: ZeroGBridge/Loader/HostLog.cs
// DESCRIPTION: Loader-side log sink (same level routing as the core's ZgbLog)
// =====================================================================

using System;
using Eleon.Modding;

namespace ZeroGBridge
{
    /// <summary>
    /// Log sink for code that lives in the loader assembly (ZeroGBridge.dll): the listener,
    /// AuthConfig and the hot-reload host. The core's ZgbLog forwards here when it runs under
    /// the loader, so every line ends up in one place.
    /// Level from the "-TAG-": -ERROR- LogError, -WARN- LogWarning, -DEBUG-/-TRACE- console only,
    /// anything else Log. Without an API (tests, before Init) everything goes to Console.
    /// Never pass secrets (AuthToken) to this class.
    /// </summary>
    public static class HostLog
    {
        /// <summary>The real game API (loader Init) or the API the standalone core got.</summary>
        public static volatile IModApi Api;

        /// <summary>When set (core running in its own AppDomain), every line goes here instead (the loader's log).</summary>
        public static volatile Action<string> Sink;

        public static void Write(string message)
        {
            if (message == null) message = string.Empty;
            // -DEBUG- / -TRACE- are off unless ZeroGBridge.json has "LogLevel": "Debug" (or "Trace").
            // They used to go to Console.WriteLine, which still showed up in the dedicated server log.
            if (IsDebugOrTrace(message) && !DebugEnabled()) return;
            var sink = Sink;
            if (sink != null)
            {
                try { sink(message); return; } catch { }
            }
            IModApi api = Api;
            if (api == null || message.IndexOf("-DEBUG-", StringComparison.Ordinal) >= 0
                || message.IndexOf("-TRACE-", StringComparison.Ordinal) >= 0)
            {
                Console.WriteLine(message);
                return;
            }
            try
            {
                if (message.IndexOf("-ERROR-", StringComparison.Ordinal) >= 0) api.LogError(message);
                else if (message.IndexOf("-WARN-", StringComparison.Ordinal) >= 0) api.LogWarning(message);
                else api.Log(message);
            }
            catch
            {
                Console.WriteLine(message);
            }
        }

        private static bool IsDebugOrTrace(string message)
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
