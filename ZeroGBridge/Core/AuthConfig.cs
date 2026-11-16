// =====================================================================
// MODULE: ZeroGBridge/Core/AuthConfig.cs
// DESCRIPTION: Port 30500 auth token from ZeroGBridge.json ("AuthToken")
// =====================================================================

using System;
using System.IO;
using System.Reflection;
using Newtonsoft.Json.Linq;

namespace ZeroGBridge
{
    /// <summary>
    /// Supplies the shared secret for the auth:&lt;token&gt; handshake.
    /// Reads "AuthToken" from ZeroGBridge.json next to the DLL. The file is re-read only when
    /// its timestamp changes, so a new token takes effect without a restart.
    /// When AuthToken is missing or empty, the legacy built-in password is used and one WARN is logged
    /// (logged again only if the token is later removed after having been set).
    /// The token value itself is never logged.
    /// </summary>
    public static class AuthConfig
    {
        /// <summary>Pre-1.4 hardcoded password, kept only as a fallback so existing setups keep working.</summary>
        internal const string LegacyFallbackToken = "ZeroGAdmin2026";

        private static readonly object Sync = new object();
        private static string _configPathOverride;
        private static string _cachedToken;
        private static DateTime _cachedStamp = DateTime.MinValue;
        private static bool _cachedExists;
        private static bool _loadedOnce;
        private static bool _fallbackWarned;

        /// <summary>For tests: point at a specific ZeroGBridge.json.</summary>
        public static string ConfigPathOverride
        {
            get { return _configPathOverride; }
            set { lock (Sync) { _configPathOverride = value; _loadedOnce = false; } }
        }

        public static string ConfigPath
        {
            get
            {
                if (!string.IsNullOrEmpty(_configPathOverride)) return _configPathOverride;
                try
                {
                    string loc = Assembly.GetExecutingAssembly().Location;
                    if (!string.IsNullOrEmpty(loc))
                        return Path.Combine(Path.GetDirectoryName(loc), "ZeroGBridge.json");
                }
                catch { }
                return Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "ZeroGBridge.json");
            }
        }

        /// <summary>True when the current token comes from ZeroGBridge.json.</summary>
        public static bool UsingConfiguredToken
        {
            get { lock (Sync) { Refresh(); return !string.IsNullOrEmpty(_cachedToken); } }
        }

        /// <summary>The token clients must send. Never log the return value.</summary>
        public static string GetToken()
        {
            lock (Sync)
            {
                Refresh();
                if (!string.IsNullOrEmpty(_cachedToken))
                {
                    _fallbackWarned = false;
                    return _cachedToken;
                }
                if (!_fallbackWarned)
                {
                    _fallbackWarned = true;
                    ZgbLog.Write($"[ZGB] -WARN- No AuthToken set in {ConfigPath}; using the built-in fallback password. Set \"AuthToken\" in ZeroGBridge.json to secure port 30500.");
                }
                return LegacyFallbackToken;
            }
        }

        private static void Refresh()
        {
            string path = ConfigPath;
            bool exists = false;
            DateTime stamp = DateTime.MinValue;
            try
            {
                exists = File.Exists(path);
                if (exists) stamp = File.GetLastWriteTimeUtc(path);
            }
            catch { }

            if (_loadedOnce && exists == _cachedExists && stamp == _cachedStamp) return;

            string token = null;
            if (exists)
            {
                try
                {
                    var jo = JObject.Parse(File.ReadAllText(path));
                    var t = jo["AuthToken"];
                    if (t != null && t.Type == JTokenType.String)
                    {
                        string v = ((string)t)?.Trim();
                        if (!string.IsNullOrEmpty(v)) token = v;
                    }
                }
                catch (Exception ex)
                {
                    ZgbLog.Write($"[ZGB] -WARN- Could not read AuthToken from {path}: {ex.GetType().Name}");
                }
            }

            bool hadToken = !string.IsNullOrEmpty(_cachedToken);
            _cachedToken = token;
            _cachedExists = exists;
            _cachedStamp = stamp;
            if (!_loadedOnce || hadToken != (token != null))
            {
                ZgbLog.Write($"[ZGB] -INFO- Auth token source: {(token != null ? "ZeroGBridge.json AuthToken (set)" : "built-in fallback (AuthToken not set)")}");
            }
            _loadedOnce = true;
        }
    }
}
