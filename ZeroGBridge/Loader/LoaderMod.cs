// =====================================================================
// MODULE: ZeroGBridge/Loader/LoaderMod.cs
// DESCRIPTION: The class Empyrion loads (IMod v2 + legacy ModInterface). Small and stable:
//              owns the TCP listener and auth, forwards game callbacks to the current core,
//              and hosts the hot-reload controller (CoreHost). Bridge logic lives in
//              Core/ZeroGBridge.Core.dll and can be swapped without a server restart.
// =====================================================================

using System;
using System.IO;
using System.Reflection;
using System.Threading;
using Eleon.Modding;
using ZeroGBridge.Hosting;

namespace ZeroGBridge.Loader
{
    public class ZeroGBridgeLoader : IMod, ModInterface
    {
        /// <summary>Loader release. A loader change needs a server restart; core changes do not.</summary>
        public const string Release = "1.5.0";

        /// <summary>For tests: use this folder instead of the DLL's folder for Core/, Updates/ and the json.</summary>
        public static string ModDirectoryOverride;

        public static ZeroGBridgeLoader Instance { get; private set; }

        private IModApi _api;
        private volatile ModGameAPI _legacy;
        private BridgeListener _listener;
        private CoreHost _host;
        private int _initDone;
        private bool _hooked;

        public CoreHost Host => _host;
        public BridgeListener Listener => _listener;

        public void Init(IModApi modApi)
        {
            if (Interlocked.Exchange(ref _initDone, 1) == 1) return;
            Instance = this;
            _api = modApi;
            HostLog.Api = modApi;
            BridgeListener.OwnerDescription = DescribeProcess;

            string loaderPath = typeof(ZeroGBridgeLoader).Assembly.Location;
            string modDir = !string.IsNullOrEmpty(ModDirectoryOverride) ? ModDirectoryOverride
                : !string.IsNullOrEmpty(loaderPath) ? Path.GetDirectoryName(loaderPath) : AppDomain.CurrentDomain.BaseDirectory;

            HostLog.Write("[ZGB] -INFO- " + DescribeProcess() + " starting (hot-reload loader).");

            _host = new CoreHost(modDir, loaderPath, Release, () => _api, () => _legacy);

            AuthConfig.GetToken(); // logs the token source once (never the value)
            int port = AuthConfig.GetPort(out string portSource);
            HostLog.Write($"[ZGB] -INFO- Bridge port in use: {port} ({(portSource == "json" ? "from ZeroGBridge.json Port" : portSource == "invalid" ? "default; ZeroGBridge.json Port is invalid" : "default; Port not set in ZeroGBridge.json")}).");
            _listener = new BridgeListener(port, _host.HandleLine, AuthConfig.GetToken, _host.HandleHotLine);
            _host.Clients = _listener;
            _listener.Start();

            HookGame();
            _host.Boot();
            _host.StartWatcher();
            HostLog.Write("[ZGB] -INFO- ZeroGBridge loader ready.");
        }

        public void Shutdown()
        {
            HostLog.Write("[ZGB] -INFO- Shutting down ZeroGBridge loader...");
            UnhookGame();
            try { _host?.Shutdown(); } catch (Exception ex) { HostLog.Write($"[ZGB] -ERROR- Core host shutdown: {ex.Message}"); }
            try { _listener?.Stop(); } catch (Exception ex) { HostLog.Write($"[ZGB] -ERROR- Listener shutdown: {ex.Message}"); }
            HostLog.Write("[ZGB] -INFO- ZeroGBridge shut down cleanly.");
        }

        private void HookGame()
        {
            try
            {
                var app = _api?.Application;
                if (app == null) return;
                app.Update += OnUpdate;
                app.OnPlayfieldLoaded += OnPlayfieldLoaded;
                app.OnPlayfieldUnloading += OnPlayfieldUnloading;
                _hooked = true;
            }
            catch (Exception ex) { HostLog.Write($"[ZGB] -WARN- Loader could not hook Application events: {ex.Message}"); }
        }

        private void UnhookGame()
        {
            if (!_hooked) return;
            try
            {
                var app = _api?.Application;
                if (app == null) return;
                app.Update -= OnUpdate;
                app.OnPlayfieldLoaded -= OnPlayfieldLoaded;
                app.OnPlayfieldUnloading -= OnPlayfieldUnloading;
            }
            catch { }
            _hooked = false;
        }

        private void OnUpdate() { try { _host?.OnApplicationUpdate(); } catch { } }
        private void OnPlayfieldLoaded(IPlayfield pf) { try { _host?.OnPlayfieldLoaded(pf); } catch { } }
        private void OnPlayfieldUnloading(IPlayfield pf) { try { _host?.OnPlayfieldUnloading(pf); } catch { } }

        // ---------------- legacy ModInterface ----------------

        public void Game_Start(ModGameAPI dediAPI)
        {
            _legacy = dediAPI;
            try { _host?.GameStart(); }
            catch (Exception ex) { HostLog.Write($"[ZGB] -WARN- Game_Start: {ex.Message}"); }
        }

        public void Game_Update()
        {
            try { _host?.GameUpdate(); } catch { /* never let the frame loop see an exception */ }
        }

        public void Game_Event(CmdId eventId, ushort seqNr, object data)
        {
            try { _host?.GameEvent(eventId, seqNr, data); } catch { }
        }

        public void Game_Exit()
        {
            try { _host?.GameExit(); } catch { }
            _legacy = null;
        }

        public static string DescribeProcess()
        {
            string version = "?";
            try { version = typeof(ZeroGBridgeLoader).Assembly.GetName().Version.ToString(); } catch { }
            string mode = "unknown";
            try { if (Instance?._api?.Application != null) mode = Instance._api.Application.Mode.ToString(); }
            catch (Exception ex) { mode = "unavailable (" + ex.GetType().Name + ")"; }
            string proc = "?";
            int pid = 0;
            try { var p = System.Diagnostics.Process.GetCurrentProcess(); proc = p.ProcessName; pid = p.Id; } catch { }
            return $"ZeroGBridge loader {Release} (v{version}) process: mode={mode} name={proc} pid={pid}";
        }
    }
}
