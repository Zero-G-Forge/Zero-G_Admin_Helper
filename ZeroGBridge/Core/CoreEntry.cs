// =====================================================================
// MODULE: ZeroGBridge/Core/CoreEntry.cs
// DESCRIPTION: 1.5.0 entry point of the reloadable core. The loader creates one CoreEntry per load
//              (inside its own AppDomain) and drives it through IBridgeCore.
// =====================================================================

using System;
using System.Linq;
using System.Threading;
using Eleon.Modding;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using ZeroGBridge.Hosting;

namespace ZeroGBridge
{
    public sealed class CoreEntry : MarshalByRefObject, IBridgeCore
    {
        private IBridgeHost _host;
        private GatewayClient _client;
        private ModMain _mod;
        private volatile bool _stopped;

        public override object InitializeLifetimeService() => null; // lives until Stop + domain unload

        public int ContractVersion => HotContract.Version;
        public string CoreRelease => ModMain.Release;
        public string CoreAssemblyVersion => typeof(CoreEntry).Assembly.GetName().Version.ToString();

        public string SelfTest()
        {
#if ZGB_TEST_BREAK_SELFTEST
            return "test build: self-test reports failure";
#else
            // Dependencies resolve and the JSON stack works in this domain.
            var probe = JsonConvert.SerializeObject(new { type = "SELFTEST", cmd = CmdId.Request_Get_Factions.ToString() });
            if (JObject.Parse(probe)["type"]?.ToString() != "SELFTEST") return "JSON round trip failed";
            if (string.IsNullOrEmpty(ModMain.Release)) return "release name missing";
            if (AlertService.Ack("selftest", null).IndexOf("ALERT_ACK", StringComparison.Ordinal) < 0) return "AlertService not usable";
            if (typeof(IModApi).Assembly == null || typeof(ModGameAPI).Assembly == null) return "game API assemblies missing";
            // 1.6.0: both command catalogs load and the console command is reachable
            if (EleonRequests.All.Count < 29 || EleonRequests.Find("Request_ConsoleCommand") == null) return "Eleon request table incomplete";
            if (ConsoleCatalog.All.Count == 0 || ConsoleCatalog.Find("kick") == null) return "console catalog empty";
            return null;
#endif
        }

        public void Start(IBridgeHost host)
        {
#if ZGB_TEST_BREAK_INIT
            throw new InvalidOperationException("test build: Start throws on purpose");
#else
            _host = host;
            Action<string> log = host.Log;
            ZgbLog.Sink = log;
            var gw = host.Gateway;
            if (!gw.Passthrough) HostLog.Sink = log; // this domain's copy of the loader classes logs to the loader too

            IModApi api;
            if (gw.Passthrough) api = gw.GetRoot("modapi") as IModApi;
            else
            {
                _client = new GatewayClient(gw);
                api = _client.Root<IModApi>("modapi");
            }
            ZgbLog.Write($"[ZGB] -INFO- Core {ModMain.Release} (v{CoreAssemblyVersion}) starting in '{AppDomain.CurrentDomain.FriendlyName}' under loader {host.LoaderRelease}.");
            _mod = new ModMain();
            _mod.StartHosted(api, host.Clients);
#endif
        }

        private ModGameAPI LegacyRoot()
        {
            var gw = _host.Gateway;
            return gw.Passthrough ? gw.GetRoot("legacy") as ModGameAPI : _client.Root<ModGameAPI>("legacy");
        }

        public void AttachLegacy(bool onGameStart)
        {
            var api = LegacyRoot();
            if (api == null) return;
            if (onGameStart) _mod.Game_Start(api);
            else LegacyApi.AttachAfterReload(api);
        }

        public void GameUpdate()
        {
            if (_stopped) return;
            _mod?.Game_Update();
        }

        public void GameEvent(CmdId eventId, ushort seqNr, object wireData)
        {
            if (_stopped || _mod == null) return;
            object data = _client == null ? wireData : Wire.Decode(wireData, typeof(object), _client);
            _mod.Game_Event(eventId, seqNr, data);
        }

        public void GameExit()
        {
            _mod?.Game_Exit();
        }

        public string HandleLine(string clientId, string line)
        {
            if (_stopped || _mod == null) return JsonConvert.SerializeObject(new { type = "ERROR", message = "Core stopped." });
            return _mod.HandleLine(line);
        }

        public string Diagnostics()
        {
            var cache = _mod?.PlayerCache;
            var view = _mod?.ServerView;
            return JsonConvert.SerializeObject(new
            {
                release = ModMain.Release,
                assemblyVersion = CoreAssemblyVersion,
                domain = AppDomain.CurrentDomain.FriendlyName,
                assemblyLocation = typeof(CoreEntry).Assembly.Location,
                legacyAttached = LegacyApi.IsAvailable,
                updateTicking = LegacyApi.UpdateIsTicking,
                gameThreadId = LegacyApi.MainThreadId,
                gameStartThreadId = LegacyApi.GameStartThreadId,
                factionRequestsSent = LegacyApi.FactionRequestsSent,
                lastFactionRequestThreadId = LegacyApi.LastFactionRequestThreadId,
                lastAlertExecThreadId = LegacyApi.LastExecThreadId,
                factionRequestPending = LegacyApi.FactionRequestPending,
                playerFactions = cache?.PlayerFactionCount ?? 0,
                players = cache?.GetAllPlayers()?.Count ?? 0,
                online = cache?.GetOnlinePlayers()?.Count ?? 0,
                serverView = view == null ? null : new { enabled = view.Enabled, driver = view.LastDriver, online = view.OnlineCount, runningPlayfields = view.RunningPlayfieldCount },
                structures = ModMain.CachedEntityRecords.Count + (view?.Structures?.Count ?? 0),
                loadedPlayfields = ModMain.LoadedPlayfields.Keys.OrderBy(k => k).ToArray(),
                broadcaster = _mod?.BroadcasterRunning ?? false,
                liveProxies = _client?.LiveProxyCount ?? 0
            });
        }

        public void Stop()
        {
            if (_stopped) return;
            _stopped = true;
            if (_mod == null) return; // never started (e.g. Start threw): nothing to stop or log
            try { _mod?.Shutdown(); } catch (Exception ex) { ZgbLog.Write($"[ZGB] -WARN- Core shutdown: {ex.Message}"); }
            try { LegacyApi.OnGameExit(); } catch { } // stop the faction timer, fail queued requests
            try { _client?.FlushReleases(true); } catch { }
            ZgbLog.Write($"[ZGB] -INFO- Core {ModMain.Release} (v{CoreAssemblyVersion}) stopped.");
            ZgbLog.Sink = null;
            HostLog.Sink = null;
        }
    }
}
