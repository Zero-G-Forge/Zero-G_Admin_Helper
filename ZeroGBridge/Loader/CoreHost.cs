// =====================================================================
// MODULE: ZeroGBridge/Loader/CoreHost.cs
// DESCRIPTION: 1.5.0 hot reload. Loads the bridge core (Core/ZeroGBridge.Core.dll) into its own
//              AppDomain from an immutable copy in Core/versions/<id>/ (so the drop files are never
//              locked), self-tests it, swaps it in on the game thread, unloads the old domain, and
//              rolls back to the last good core when anything fails. The TCP listener and auth stay
//              in the loader, so ZAH connections survive reloads.
// =====================================================================

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Threading;
using Eleon.Modding;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace ZeroGBridge.Hosting
{
    public sealed class CoreVersion
    {
        public string Id { get; set; }
        public string Release { get; set; }
        public string AssemblyVersion { get; set; }
        public string Sha256 { get; set; }
        public DateTime ImportedUtc { get; set; }
        public long SizeBytes { get; set; }
        /// <summary>True once this version has been activated successfully.</summary>
        public bool Good { get; set; }
        /// <summary>Error code of the last failed activation (null when the last one worked).</summary>
        public string LastError { get; set; }
        [JsonIgnore] public string DllPath { get; set; }

        public object ToJson() => new
        {
            id = Id,
            release = Release ?? "?",
            assemblyVersion = AssemblyVersion,
            sha256 = Sha256 != null && Sha256.Length > 12 ? Sha256.Substring(0, 12) : Sha256,
            importedUtc = ImportedUtc.ToString("o", CultureInfo.InvariantCulture),
            sizeBytes = SizeBytes,
            good = Good,
            lastError = LastError
        };
    }

    public sealed class HotHistoryEntry
    {
        public DateTime TimeUtc { get; set; }
        public string Trigger { get; set; }   // boot | command | auto
        public string Action { get; set; }    // boot | reload | rollback | recover
        public string From { get; set; }
        public string To { get; set; }
        public bool Ok { get; set; }
        public string Error { get; set; }
        public string Message { get; set; }
        public long DurationMs { get; set; }
        public string Isolation { get; set; }
    }

    public sealed class HotState
    {
        public string Current { get; set; }
        public string LastGood { get; set; }
        public List<HotHistoryEntry> History { get; set; } = new List<HotHistoryEntry>();
    }

    public sealed class ActivationResult
    {
        public bool Ok;
        public string Result;       // reloaded | unchanged | rolled_back | booted
        public string Error;        // busy | no_source | load_failed | selftest_failed | contract_mismatch | start_failed | unknown_version | no_previous | disabled
        public string Message;
        public CoreVersion From;
        public CoreVersion To;
        public CoreVersion RolledBackTo;
        public long DurationMs;
        public string RanOn;
    }

    public sealed class CoreHost
    {
        public const string IsolationAppDomain = "AppDomain";
        public const string IsolationInProcess = "InProcess";

        private sealed class Session
        {
            public CoreVersion Info;
            public IBridgeCore Core;
            public AppDomain Domain;
            public GameGateway Gateway;
            public string Isolation;
            public string DomainName;
            public DateTime LoadedUtc;
            public int InFlight;
            public volatile bool Retired;
            public volatile bool Started;
        }

        // ------------------------------------------------------------------ static counters (tests / status)
        private static int _liveDomains;
        private static int _leakedAssemblies;
        public static int LiveDomainCount => Volatile.Read(ref _liveDomains);
        public static int LeakedInProcessAssemblies => Volatile.Read(ref _leakedAssemblies);

        private readonly string _modDir;
        private readonly string _loaderPath;
        private readonly string _loaderRelease;
        private readonly Func<IModApi> _modApi;
        private readonly Func<ModGameAPI> _legacy;
        private readonly GameThread _gameThread = new GameThread();
        private readonly object _reloadGate = new object();
        private readonly object _forwardLock = new object();
        private readonly ConcurrentQueue<Tuple<CmdId, ushort, object>> _queuedEvents = new ConcurrentQueue<Tuple<CmdId, ushort, object>>();
        private readonly ConcurrentDictionary<string, IPlayfield> _loadedPlayfields = new ConcurrentDictionary<string, IPlayfield>(StringComparer.OrdinalIgnoreCase);
        private volatile Session _current;
        private HotState _state = new HotState();
        private int _domainSeq;
        private bool _appDomainBroken;
        private Timer _watcher;
        private string _lastSeenSig, _lastAttemptSig;
        private volatile bool _shutdown;
        private int _gameEventDropWarned;

        public IClientHub Clients { get; set; }
        public GameThread GameThread => _gameThread;

        public string ModDirectory => _modDir;
        public string CoreDirectory => Path.Combine(_modDir, "Core");
        public string VersionsDirectory => Path.Combine(CoreDirectory, "versions");
        public string UpdatesDirectory => Path.Combine(_modDir, "Updates");
        public string FailedDirectory => Path.Combine(UpdatesDirectory, "failed");
        public string StatePath => Path.Combine(CoreDirectory, "hotreload_state.json");
        public string BootCorePath => Path.Combine(CoreDirectory, HotContract.CoreFileName);
        public string DropCorePath => Path.Combine(UpdatesDirectory, HotContract.CoreFileName);

        public bool HasCore => _current != null && _current.Started;
        public string CurrentVersionId => _current?.Info?.Id;
        public string CurrentIsolation => _current?.Isolation;
        public string CurrentDomainName => _current?.DomainName;
        /// <summary>For tests: the AppDomain of the active core (null in InProcess mode).</summary>
        public AppDomain CurrentDomainForTests => _current?.Domain;
        public int CurrentGatewaySubscriptions => _current?.Gateway?.SubscriptionCount ?? 0;

        public CoreHost(string modDir, string loaderPath, string loaderRelease, Func<IModApi> modApi, Func<ModGameAPI> legacy)
        {
            _modDir = modDir;
            _loaderPath = loaderPath;
            _loaderRelease = loaderRelease;
            _modApi = modApi;
            _legacy = legacy;
            Directory.CreateDirectory(VersionsDirectory);
            Directory.CreateDirectory(UpdatesDirectory);
            LoadState();
            AppDomain.CurrentDomain.AssemblyResolve += ResolveForInProcess;
        }

        // ------------------------------------------------------------------ settings

        public static bool HotReloadEnabled => AuthConfig.GetBool("HotReloadEnabled", true);
        public static bool AutoReloadOnDrop => AuthConfig.GetBool("AutoReloadOnDrop", false);
        public static int PollMs => AuthConfig.GetInt("HotReloadPollMs", 2000, 250, 60000);
        public static int KeepVersions => AuthConfig.GetInt("KeepCoreVersions", 5, 1, 100);
        public static string IsolationSetting => string.Equals(AuthConfig.GetString("CoreIsolation", IsolationAppDomain), IsolationInProcess, StringComparison.OrdinalIgnoreCase) ? IsolationInProcess : IsolationAppDomain;

        // ------------------------------------------------------------------ game callbacks (from the loader mod)

        public void OnPlayfieldLoaded(IPlayfield pf) { if (pf?.Name != null) _loadedPlayfields[pf.Name] = pf; }
        public void OnPlayfieldUnloading(IPlayfield pf) { if (pf?.Name != null) _loadedPlayfields.TryRemove(pf.Name, out _); }

        /// <summary>Application.Update (no legacy forwarding; the core hooks Update itself through the gateway).</summary>
        public void OnApplicationUpdate() => _gameThread.Tick();

        public void GameUpdate()
        {
            _gameThread.Tick();
            if (!Monitor.TryEnter(_forwardLock)) return; // an off-thread swap is running: skip this frame
            try
            {
                var s = _current;
                if (s == null || !s.Started || s.Retired) return;
                DeliverQueuedEvents(s);
                try { s.Core.GameUpdate(); } catch { }
            }
            finally { Monitor.Exit(_forwardLock); }
        }

        public void GameStart()
        {
            var s = _current;
            if (s == null || !s.Started) return;
            try { s.Core.AttachLegacy(onGameStart: true); }
            catch (Exception ex) { HostLog.Write($"[ZGB] -WARN- Core AttachLegacy (Game_Start) failed: {ex.Message}"); }
        }

        public void GameEvent(CmdId eventId, ushort seqNr, object data)
        {
            var s = _current;
            bool locked = Monitor.TryEnter(_forwardLock);
            try
            {
                if (!locked || s == null || !s.Started || s.Retired)
                {
                    if (_queuedEvents.Count < 512) _queuedEvents.Enqueue(Tuple.Create(eventId, seqNr, data));
                    else if (Interlocked.Exchange(ref _gameEventDropWarned, 1) == 0)
                        HostLog.Write("[ZGB] -WARN- No core loaded: dropping game events (queue full).");
                    return;
                }
                DeliverQueuedEvents(s);
                Forward(s, eventId, seqNr, data);
            }
            finally { if (locked) Monitor.Exit(_forwardLock); }
        }

        private void DeliverQueuedEvents(Session s)
        {
            while (_queuedEvents.TryDequeue(out var e)) Forward(s, e.Item1, e.Item2, e.Item3);
        }

        private static void Forward(Session s, CmdId id, ushort seq, object data)
        {
            try
            {
                object wire = s.Gateway.Passthrough ? data : Wire.Encode(data, typeof(object), s.Gateway);
                s.Core.GameEvent(id, seq, wire);
            }
            catch (Exception ex) { HostLog.Write($"[ZGB] -WARN- Forwarding {id} to the core failed: {ex.GetType().Name}: {ex.Message}"); }
        }

        public void GameExit()
        {
            var s = _current;
            if (s == null || !s.Started) return;
            try { s.Core.GameExit(); } catch { }
        }

        // ------------------------------------------------------------------ client lines

        public string HandleLine(string clientId, string line)
        {
            var deadline = DateTime.UtcNow.AddSeconds(15);
            while (true)
            {
                var s = _current;
                if (s != null && s.Started && !s.Retired)
                {
                    Interlocked.Increment(ref s.InFlight);
                    try
                    {
                        if (!s.Retired) return s.Core.HandleLine(clientId, line);
                    }
                    finally { Interlocked.Decrement(ref s.InFlight); }
                }
                else if (s == null && !Monitor.IsEntered(_reloadGate) && !ReloadInProgress)
                {
                    return JsonConvert.SerializeObject(new { type = "ERROR", message = "Bridge core is not loaded. Send hot:status / hot:rollback." });
                }
                if (DateTime.UtcNow > deadline)
                    return JsonConvert.SerializeObject(new { type = "ERROR", message = "Bridge core is reloading; try again." });
                Thread.Sleep(20); // swap in progress
            }
        }

        private volatile bool _reloadInProgress;
        public bool ReloadInProgress => _reloadInProgress;

        // ------------------------------------------------------------------ boot / reload / rollback

        /// <summary>Loads the core at server start: Updates/ drop if present, else Core/; falls back to the last good version.</summary>
        public ActivationResult Boot()
        {
            var r = Reload("boot", force: true);
            if (!r.Ok && _current == null)
                HostLog.Write("[ZGB] -ERROR- No bridge core could be loaded. The port stays open; ZAH can use hot:status, hot:versions and hot:rollback.");
            return r;
        }

        public ActivationResult Reload(string trigger, bool force)
        {
            if (!Monitor.TryEnter(_reloadGate))
                return new ActivationResult { Ok = false, Error = "busy", Message = "Another reload is running." };
            _reloadInProgress = true;
            try
            {
                if (trigger != "boot" && !HotReloadEnabled)
                    return new ActivationResult { Ok = false, Error = "disabled", Message = "HotReloadEnabled is false in ZeroGBridge.json." };
                bool fromDrop = File.Exists(DropCorePath);
                string src = fromDrop ? DropCorePath : BootCorePath;
                if (!File.Exists(src))
                {
                    var none = new ActivationResult { Ok = false, Error = "no_source", Message = $"No {HotContract.CoreFileName} in Updates/ or Core/." };
                    if (trigger == "boot") return RecoverToLastGood(none, trigger);
                    return none;
                }

                CoreVersion info;
                try { info = Import(src); }
                catch (Exception ex)
                {
                    if (fromDrop) Quarantine(src);
                    var bad = Fail("load_failed", $"{Path.GetFileName(src)} is not a loadable core: {ex.GetType().Name}: {ex.Message}", trigger, trigger == "boot" ? "boot" : "reload", null, 0);
                    return trigger == "boot" ? RecoverToLastGood(bad, trigger) : bad;
                }

                var cur = _current;
                if (!force && cur != null && cur.Info.Sha256 == info.Sha256)
                {
                    if (fromDrop) TryDeleteDrop();
                    return new ActivationResult { Ok = true, Result = "unchanged", Message = "That core is already loaded (send force to reload it anyway).", From = cur.Info, To = cur.Info };
                }

                var r = Activate(info, trigger, trigger == "boot" ? "boot" : "reload");
                if (fromDrop)
                {
                    if (r.Ok) TryDeleteDrop();
                    else Quarantine(src);
                }
                if (!r.Ok && trigger == "boot" && _current == null) return RecoverToLastGood(r, trigger);
                return r;
            }
            finally
            {
                _reloadInProgress = false;
                Monitor.Exit(_reloadGate);
            }
        }

        private ActivationResult RecoverToLastGood(ActivationResult failed, string trigger)
        {
            var lg = FindVersion(_state.LastGood);
            if (lg == null || (failed.To != null && lg.Id == failed.To.Id)) return failed;
            HostLog.Write($"[ZGB] -WARN- Falling back to the last good core {lg.Id}.");
            var r2 = Activate(lg, trigger, "recover");
            if (r2.Ok) failed.RolledBackTo = lg;
            return failed;
        }

        public ActivationResult Rollback(string versionId, string trigger = "command")
        {
            if (!Monitor.TryEnter(_reloadGate))
                return new ActivationResult { Ok = false, Error = "busy", Message = "Another reload is running." };
            _reloadInProgress = true;
            try
            {
                if (!HotReloadEnabled)
                    return new ActivationResult { Ok = false, Error = "disabled", Message = "HotReloadEnabled is false in ZeroGBridge.json." };
                CoreVersion target;
                if (!string.IsNullOrEmpty(versionId))
                {
                    target = FindVersion(versionId);
                    if (target == null) return new ActivationResult { Ok = false, Error = "unknown_version", Message = "No stored core version " + versionId + " (see hot:versions)." };
                }
                else
                {
                    string cur = _current?.Info?.Id;
                    // the most recent successfully activated version other than the current one
                    string prevId = _state.History.AsEnumerable().Reverse().Where(h => h.Ok && h.To != null && h.To != cur).Select(h => h.To).FirstOrDefault();
                    target = FindVersion(prevId);
                    if (target == null) return new ActivationResult { Ok = false, Error = "no_previous", Message = "No earlier good core version to roll back to." };
                }
                var r = Activate(target, trigger, "rollback");
                if (r.Ok) r.Result = "rolled_back";
                return r;
            }
            finally
            {
                _reloadInProgress = false;
                Monitor.Exit(_reloadGate);
            }
        }

        /// <summary>Prepare (load + self-test), swap on the game thread, unload the old domain; recover on failure.</summary>
        private ActivationResult Activate(CoreVersion info, string trigger, string action)
        {
            var sw = Stopwatch.StartNew();
            var prev = _current;
            var result = new ActivationResult { From = prev?.Info, To = info };

            Session next;
            try { next = Prepare(info); }
            catch (Exception ex)
            {
                string code = ex is ContractMismatchException ? "contract_mismatch" : ex is SelfTestException ? "selftest_failed" : "load_failed";
                var f = Fail(code, Describe(ex), trigger, action, info, sw.ElapsedMilliseconds, prev?.Info);
                f.From = prev?.Info;
                f.To = info;
                if (prev == null && action != "recover" && trigger != "boot")
                {
                    // nothing running (e.g. after a failed boot): try the last good one
                    return RecoverToLastGood(f, trigger);
                }
                return f; // the old core never stopped: nothing to roll back
            }

            string startError = null;
            try
            {
                result.RanOn = _gameThread.Run(() => startError = Swap(prev, next), 15000);
            }
            catch (Exception ex) { startError = Describe(ex); }

            if (prev != null) Unload(prev);

            if (startError != null)
            {
                Unload(next);
                var f = Fail("start_failed", startError, trigger, action, info, sw.ElapsedMilliseconds, prev?.Info);
                f.From = prev?.Info;
                f.To = info;
                if (action != "recover")
                {
                    var back = prev?.Info ?? FindVersion(_state.LastGood);
                    if (back != null && back.Id != info.Id)
                    {
                        HostLog.Write($"[ZGB] -WARN- Rolling back to core {back.Id}.");
                        var r2 = Activate(back, trigger, "recover");
                        if (r2.Ok) f.RolledBackTo = back;
                    }
                }
                return f;
            }

            info.Good = true;
            info.LastError = null;
            SaveMeta(info);
            result.Ok = true;
            result.Result = action == "boot" ? "booted" : action == "rollback" ? "rolled_back" : action == "recover" ? "recovered" : "reloaded";
            result.DurationMs = sw.ElapsedMilliseconds;
            _state.Current = info.Id;
            _state.LastGood = info.Id;
            AddHistory(new HotHistoryEntry { TimeUtc = DateTime.UtcNow, Trigger = trigger, Action = action, From = prev?.Info?.Id, To = info.Id, Ok = true, DurationMs = result.DurationMs, Isolation = next.Isolation });
            PromoteToBoot(info);
            Prune();
            HostLog.Write($"[ZGB] -SUCCESS- Bridge core {info.Release} ({info.Id}) active via {action} [{trigger}] in {next.Isolation} {(next.DomainName != null ? "'" + next.DomainName + "' " : "")}after {result.DurationMs} ms (swap ran on the {result.RanOn} thread){(prev != null ? "; replaced " + prev.Info.Id : "")}.");
            Broadcast(action == "boot" ? "booted" : action == "rollback" || action == "recover" ? "rolled_back" : "reloaded", trigger, prev?.Info, info, null);
            return result;
        }

        private string Swap(Session prev, Session next)
        {
            lock (_forwardLock)
            {
                if (prev != null)
                {
                    prev.Retired = true;
                    _current = null;
                    // let in-flight commands finish; keep pumping the old core's Game_Update so
                    // an alert waiting for the game thread can complete
                    var until = DateTime.UtcNow.AddSeconds(6);
                    while (Volatile.Read(ref prev.InFlight) > 0 && DateTime.UtcNow < until)
                    {
                        if (_gameThread.OnGameThread) { try { prev.Core.GameUpdate(); } catch { } }
                        Thread.Sleep(5);
                    }
                    StopSession(prev);
                }

                try
                {
                    next.Core.Start(new HostAdapter(Clients, next.Gateway, _modDir, _loaderRelease));
                    next.Started = true;
                    if (_legacy?.Invoke() != null) next.Core.AttachLegacy(onGameStart: false);
                    if (prev != null && !next.Gateway.Passthrough)
                    {
                        int replayed = 0;
                        foreach (var pf in _loadedPlayfields.Values) { next.Gateway.ReplayEvent("OnPlayfieldLoaded", pf); replayed++; }
                        if (replayed > 0) HostLog.Write($"[ZGB] -INFO- Replayed {replayed} loaded playfield(s) to the new core.");
                    }
                    next.Core.Diagnostics(); // post-start probe
                    next.LoadedUtc = DateTime.UtcNow;
                    _current = next;
                    DeliverQueuedEvents(next);
                    return null;
                }
                catch (Exception ex)
                {
                    next.Started = false;
                    StopSession(next);
                    _current = null;
                    return Describe(ex);
                }
            }
        }

        private Session Prepare(CoreVersion info)
        {
            string isolation = IsolationSetting;
            if (isolation == IsolationAppDomain && _appDomainBroken) isolation = IsolationInProcess;

            if (isolation == IsolationAppDomain)
            {
                AppDomain domain = null;
                CoreBootstrap boot;
                string name = "ZGB-Core-" + Interlocked.Increment(ref _domainSeq);
                try
                {
                    var parent = AppDomain.CurrentDomain.SetupInformation;
                    var setup = new AppDomainSetup
                    {
                        ApplicationBase = parent.ApplicationBase ?? AppDomain.CurrentDomain.BaseDirectory,
                        ConfigurationFile = parent.ConfigurationFile,
                        ShadowCopyFiles = "false" // we stage our own immutable copy in Core/versions
                    };
                    domain = AppDomain.CreateDomain(name, null, setup);
                    Interlocked.Increment(ref _liveDomains);
                    boot = (CoreBootstrap)domain.CreateInstanceFromAndUnwrap(_loaderPath, typeof(CoreBootstrap).FullName);
                    BuildProbe(out var probe, out var dirs);
                    boot.Init(probe, dirs, AuthConfig.ConfigPathOverride);
                }
                catch (Exception ex)
                {
                    if (domain != null) UnloadDomain(domain, name);
                    _appDomainBroken = true;
                    HostLog.Write($"[ZGB] -WARN- Could not create a core AppDomain ({ex.GetType().Name}: {ex.Message}). Falling back to InProcess isolation (each reload then leaks the old core assembly until restart).");
                    return PrepareInProcess(info);
                }

                try
                {
                    IBridgeCore core = boot.LoadCore(info.DllPath);
                    var s = new Session { Info = info, Core = core, Domain = domain, Isolation = IsolationAppDomain, DomainName = name };
                    s.Gateway = new GameGateway(name, Roots, passthrough: false);
                    CheckCore(s);
                    return s;
                }
                catch
                {
                    UnloadDomain(domain, name);
                    throw;
                }
            }
            return PrepareInProcess(info);
        }

        private Session PrepareInProcess(CoreVersion info)
        {
            byte[] dll = File.ReadAllBytes(info.DllPath);
            string pdbPath = Path.ChangeExtension(info.DllPath, ".pdb");
            byte[] pdb = File.Exists(pdbPath) ? File.ReadAllBytes(pdbPath) : null;
            var asm = pdb != null ? Assembly.Load(dll, pdb) : Assembly.Load(dll);
            Interlocked.Increment(ref _leakedAssemblies);
            var type = asm.GetTypes().FirstOrDefault(t => typeof(IBridgeCore).IsAssignableFrom(t) && !t.IsAbstract && t.IsClass)
                       ?? throw new InvalidOperationException("No IBridgeCore implementation in the core DLL.");
            var s = new Session { Info = info, Core = (IBridgeCore)Activator.CreateInstance(type), Isolation = IsolationInProcess };
            s.Gateway = new GameGateway("inprocess-" + Interlocked.Increment(ref _domainSeq), Roots, passthrough: true);
            CheckCore(s);
            return s;
        }

        private static void CheckCore(Session s)
        {
            int cv;
            try { cv = s.Core.ContractVersion; }
            catch (Exception ex) { throw new SelfTestException("ContractVersion threw: " + Describe(ex)); }
            if (cv != HotContract.Version)
                throw new ContractMismatchException($"Core was built for loader contract {cv}, this loader has {HotContract.Version}. Update the loader (needs a restart).");
            try { s.Info.Release = s.Core.CoreRelease; } catch { }
            string err;
            try { err = s.Core.SelfTest(); }
            catch (Exception ex) { throw new SelfTestException("SelfTest threw: " + Describe(ex)); }
            if (!string.IsNullOrEmpty(err)) throw new SelfTestException(err);
            try
            {
                s.Info.Release = s.Core.CoreRelease;
                s.Info.AssemblyVersion = s.Core.CoreAssemblyVersion ?? s.Info.AssemblyVersion;
            }
            catch { }
            SaveMeta(s.Info);
        }

        private object Roots(string name)
        {
            switch (name)
            {
                case "modapi": return _modApi?.Invoke();
                case "legacy": return _legacy?.Invoke();
                default: return null;
            }
        }

        private void StopSession(Session s)
        {
            if (s == null) return;
            try { s.Core.Stop(); }
            catch (Exception ex) { HostLog.Write($"[ZGB] -WARN- Core {s.Info?.Id} Stop failed: {Describe(ex)}"); }
            s.Started = false;
            try { s.Gateway?.Dispose(); } catch { }
        }

        private void Unload(Session s)
        {
            if (s?.Domain == null) return;
            var d = s.Domain;
            s.Domain = null;
            UnloadDomain(d, s.DomainName);
        }

        private static void UnloadDomain(AppDomain d, string name)
        {
            try
            {
                AppDomain.Unload(d);
                Interlocked.Decrement(ref _liveDomains);
                HostLog.Write($"[ZGB] -INFO- Unloaded core AppDomain '{name}'.");
            }
            catch (Exception ex)
            {
                HostLog.Write($"[ZGB] -WARN- Could not unload core AppDomain '{name}': {ex.GetType().Name}: {ex.Message}");
            }
        }

        private void BuildProbe(out Dictionary<string, string> probe, out string[] dirs)
        {
            probe = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            var dirSet = new List<string>();
            foreach (var a in AppDomain.CurrentDomain.GetAssemblies())
            {
                try
                {
                    if (a.IsDynamic || string.IsNullOrEmpty(a.Location)) continue;
                    string n = a.GetName().Name;
                    if (!probe.ContainsKey(n)) probe[n] = a.Location;
                    string dir = Path.GetDirectoryName(a.Location);
                    if (!dirSet.Contains(dir, StringComparer.OrdinalIgnoreCase)) dirSet.Add(dir);
                }
                catch { }
            }
            if (!string.IsNullOrEmpty(_loaderPath)) probe["ZeroGBridge"] = _loaderPath;
            dirs = dirSet.ToArray();
        }

        private Assembly ResolveForInProcess(object sender, ResolveEventArgs e)
        {
            string n = new AssemblyName(e.Name).Name;
            if (n == "ZeroGBridge") return typeof(CoreHost).Assembly;
            return AppDomain.CurrentDomain.GetAssemblies().FirstOrDefault(a => !a.IsDynamic && a.GetName().Name == n);
        }

        // ------------------------------------------------------------------ versions on disk

        private CoreVersion Import(string src)
        {
            byte[] bytes;
            using (var fs = new FileStream(src, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            using (var ms = new MemoryStream())
            {
                fs.CopyTo(ms);
                bytes = ms.ToArray();
            }
            string sha;
            using (var h = SHA256.Create()) sha = BitConverter.ToString(h.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();

            // read the version without loading it here (throws BadImageFormatException on a bad file)
            string tmp = Path.Combine(VersionsDirectory, ".incoming_" + sha.Substring(0, 8) + ".dll");
            File.WriteAllBytes(tmp, bytes);
            string asmVer;
            try { asmVer = AssemblyName.GetAssemblyName(tmp).Version.ToString(); }
            finally { try { File.Delete(tmp); } catch { } }

            string id = asmVer + "_" + sha.Substring(0, 8);
            string dir = Path.Combine(VersionsDirectory, id);
            string dll = Path.Combine(dir, HotContract.CoreFileName);
            var existing = FindVersion(id);
            if (existing != null && File.Exists(existing.DllPath)) return existing;

            Directory.CreateDirectory(dir);
            File.WriteAllBytes(dll, bytes);
            string pdbSrc = Path.ChangeExtension(src, ".pdb");
            if (File.Exists(pdbSrc)) try { File.Copy(pdbSrc, Path.ChangeExtension(dll, ".pdb"), true); } catch { }
            var info = new CoreVersion { Id = id, AssemblyVersion = asmVer, Sha256 = sha, ImportedUtc = DateTime.UtcNow, SizeBytes = bytes.Length, DllPath = dll };
            SaveMeta(info);
            HostLog.Write($"[ZGB] -INFO- Imported core {id} from {Path.GetFileName(Path.GetDirectoryName(src))}/{Path.GetFileName(src)} ({bytes.Length} bytes).");
            return info;
        }

        private static void SaveMeta(CoreVersion v)
        {
            try { File.WriteAllText(Path.Combine(Path.GetDirectoryName(v.DllPath), "meta.json"), JsonConvert.SerializeObject(v, Formatting.Indented)); } catch { }
        }

        public CoreVersion FindVersion(string id)
        {
            if (string.IsNullOrEmpty(id) || id.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 || id.Contains("..")) return null;
            string dir = Path.Combine(VersionsDirectory, id);
            string dll = Path.Combine(dir, HotContract.CoreFileName);
            if (!File.Exists(dll)) return null;
            CoreVersion v = null;
            try { v = JsonConvert.DeserializeObject<CoreVersion>(File.ReadAllText(Path.Combine(dir, "meta.json"))); } catch { }
            v = v ?? new CoreVersion { Id = id, ImportedUtc = Directory.GetCreationTimeUtc(dir) };
            v.Id = id;
            v.DllPath = dll;
            if (v.SizeBytes == 0) try { v.SizeBytes = new FileInfo(dll).Length; } catch { }
            return v;
        }

        public List<CoreVersion> ListVersions()
        {
            var list = new List<CoreVersion>();
            try
            {
                foreach (var d in Directory.GetDirectories(VersionsDirectory))
                {
                    var v = FindVersion(Path.GetFileName(d));
                    if (v != null) list.Add(v);
                }
            }
            catch { }
            return list.OrderByDescending(v => v.ImportedUtc).ToList();
        }

        private void PromoteToBoot(CoreVersion v)
        {
            // Core/ZeroGBridge.Core.dll always mirrors the active core, so a restart boots it.
            try
            {
                if (File.Exists(BootCorePath))
                {
                    string sha;
                    using (var h = SHA256.Create())
                    using (var fs = new FileStream(BootCorePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                        sha = BitConverter.ToString(h.ComputeHash(fs)).Replace("-", "").ToLowerInvariant();
                    if (sha == v.Sha256) return;
                }
                File.Copy(v.DllPath, BootCorePath, true);
                string pdb = Path.ChangeExtension(v.DllPath, ".pdb");
                if (File.Exists(pdb)) File.Copy(pdb, Path.ChangeExtension(BootCorePath, ".pdb"), true);
            }
            catch (Exception ex) { HostLog.Write($"[ZGB] -WARN- Could not update Core/{HotContract.CoreFileName}: {ex.Message}"); }
        }

        private void Prune()
        {
            try
            {
                var keep = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { _state.Current, _state.LastGood };
                var all = ListVersions();
                foreach (var v in all.Take(KeepVersions)) keep.Add(v.Id);
                foreach (var v in all.Where(v => !keep.Contains(v.Id)))
                {
                    try { Directory.Delete(Path.GetDirectoryName(v.DllPath), true); } catch { /* still mapped: next time */ }
                }
            }
            catch { }
        }

        private void TryDeleteDrop()
        {
            try { File.Delete(DropCorePath); } catch { }
            try { File.Delete(Path.ChangeExtension(DropCorePath, ".pdb")); } catch { }
        }

        private void Quarantine(string src)
        {
            try
            {
                Directory.CreateDirectory(FailedDirectory);
                string stamp = DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff", CultureInfo.InvariantCulture);
                string dst = Path.Combine(FailedDirectory, Path.GetFileNameWithoutExtension(src) + "_" + stamp + ".dll");
                for (int n = 2; File.Exists(dst); n++) dst = Path.Combine(FailedDirectory, Path.GetFileNameWithoutExtension(src) + "_" + stamp + "_" + n + ".dll");
                File.Copy(src, dst, true);
                File.Delete(src);
                string pdb = Path.ChangeExtension(src, ".pdb");
                if (File.Exists(pdb)) { File.Copy(pdb, Path.ChangeExtension(dst, ".pdb"), true); File.Delete(pdb); }
                HostLog.Write($"[ZGB] -WARN- Moved the rejected core to Updates/failed/{Path.GetFileName(dst)}.");
            }
            catch (Exception ex) { HostLog.Write($"[ZGB] -WARN- Could not move the rejected core out of Updates/: {ex.Message}"); }
        }

        // ------------------------------------------------------------------ state + history

        private void LoadState()
        {
            try
            {
                if (File.Exists(StatePath)) _state = JsonConvert.DeserializeObject<HotState>(File.ReadAllText(StatePath)) ?? new HotState();
            }
            catch { _state = new HotState(); }
            if (_state.History == null) _state.History = new List<HotHistoryEntry>();
        }

        private void SaveState()
        {
            try
            {
                string tmp = StatePath + ".tmp";
                File.WriteAllText(tmp, JsonConvert.SerializeObject(_state, Formatting.Indented));
                if (File.Exists(StatePath)) File.Delete(StatePath);
                File.Move(tmp, StatePath);
            }
            catch { }
        }

        private void AddHistory(HotHistoryEntry e)
        {
            lock (_state)
            {
                _state.History.Add(e);
                if (_state.History.Count > 50) _state.History.RemoveRange(0, _state.History.Count - 50);
                SaveState();
            }
        }

        private ActivationResult Fail(string code, string message, string trigger, string action, CoreVersion to, long ms, CoreVersion from = null)
        {
            HostLog.Write($"[ZGB] -ERROR- Core {action} [{trigger}] failed ({code}): {message}");
            if (to?.DllPath != null && File.Exists(to.DllPath)) { to.LastError = code; SaveMeta(to); }
            AddHistory(new HotHistoryEntry { TimeUtc = DateTime.UtcNow, Trigger = trigger, Action = action, From = from?.Id ?? _current?.Info?.Id, To = to?.Id, Ok = false, Error = code, Message = Truncate(message, 300), DurationMs = ms });
            Broadcast("reload_failed", trigger, from ?? _current?.Info, to, code + ": " + Truncate(message, 200));
            return new ActivationResult { Ok = false, Error = code, Message = message, DurationMs = ms };
        }

        private void Broadcast(string evt, string trigger, CoreVersion from, CoreVersion to, string error)
        {
            try
            {
                Clients?.BroadcastJson(JsonConvert.SerializeObject(new
                {
                    type = "HOT_EVENT",
                    @event = evt,
                    trigger,
                    from = from?.ToJson(),
                    to = to?.ToJson(),
                    current = _current?.Info?.ToJson(),
                    error,
                    timeUtc = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture)
                }), null);
            }
            catch { }
        }

        private static string Truncate(string s, int n) => s == null || s.Length <= n ? s : s.Substring(0, n);

        private static string Describe(Exception ex)
        {
            var e = ex;
            while ((e is TargetInvocationException || e is TypeInitializationException) && e.InnerException != null) e = e.InnerException;
            return e.GetType().Name + ": " + e.Message;
        }

        // ------------------------------------------------------------------ status

        public JObject StatusJson()
        {
            var s = _current;
            JToken diag = null;
            if (s != null && s.Started && !s.Retired)
            {
                try { diag = JToken.Parse(s.Core.Diagnostics() ?? "null"); }
                catch (Exception ex) { diag = new JObject { ["error"] = Describe(ex) }; }
            }
            var last = _state.History.LastOrDefault();
            return JObject.FromObject(new
            {
                loader = new { release = _loaderRelease, assemblyVersion = typeof(CoreHost).Assembly.GetName().Version.ToString(), contract = HotContract.Version },
                core = s == null ? null : new
                {
                    loaded = s.Started,
                    version = s.Info.ToJson(),
                    isolation = s.Isolation,
                    domain = s.DomainName,
                    loadedUtc = s.LoadedUtc.ToString("o", CultureInfo.InvariantCulture),
                    uptimeSeconds = (long)(DateTime.UtcNow - s.LoadedUtc).TotalSeconds,
                    gatewaySubscriptions = s.Gateway?.SubscriptionCount ?? 0,
                    gatewayHandles = s.Gateway?.HandleCount ?? 0
                },
                lastGood = _state.LastGood,
                reloadInProgress = _reloadInProgress,
                hotReloadEnabled = HotReloadEnabled,
                autoReloadOnDrop = AutoReloadOnDrop,
                isolationSetting = IsolationSetting,
                appDomainFallback = _appDomainBroken,
                dropFolder = "Updates",
                pendingDrop = File.Exists(DropCorePath),
                liveCoreDomains = LiveDomainCount,
                leakedInProcessAssemblies = LeakedInProcessAssemblies,
                gameThreadTicking = _gameThread.IsTicking,
                lastReload = last == null ? null : HistoryJson(last),
                history = _state.History.AsEnumerable().Reverse().Take(20).Select(HistoryJson).ToArray(),
                diagnostics = diag
            });
        }

        private static object HistoryJson(HotHistoryEntry h) => new
        {
            timeUtc = h.TimeUtc.ToString("o", CultureInfo.InvariantCulture),
            trigger = h.Trigger,
            action = h.Action,
            from = h.From,
            to = h.To,
            ok = h.Ok,
            error = h.Error,
            message = h.Message,
            durationMs = h.DurationMs,
            isolation = h.Isolation
        };

        // ------------------------------------------------------------------ hot: commands

        /// <summary>
        /// hot:status | hot:reload | hot:rollback | hot:versions, or hot:{"cmd":"...","req_id":"...","force":true,"version":"id"}.
        /// Exactly one {"type":"HOT",...} reply per line.
        /// </summary>
        public string HandleHotLine(string clientId, string line)
        {
            string body = line.Substring(BridgeListener.HotPrefix.Length).Trim();
            string cmd, reqId = null, version = null;
            bool force = false;
            if (body.StartsWith("{"))
            {
                JObject jo;
                try { jo = JObject.Parse(body); }
                catch { return Reply("?", null, false, "bad_request", "hot: JSON could not be parsed."); }
                cmd = ((string)jo["cmd"] ?? "").Trim().ToLowerInvariant();
                var rid = jo["req_id"];
                if (rid != null && rid.Type != JTokenType.Null) reqId = rid.Type == JTokenType.String ? (string)rid : rid.ToString(Formatting.None);
                var f = jo["force"];
                force = f != null && f.Type == JTokenType.Boolean && (bool)f;
                version = (string)jo["version"];
            }
            else
            {
                var parts = body.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
                cmd = parts.Length > 0 ? parts[0].ToLowerInvariant() : "";
                if (parts.Length > 1 && parts[1].Equals("force", StringComparison.OrdinalIgnoreCase)) force = true;
                else if (parts.Length > 1) version = parts[1];
            }

            // status is polled often by ZAH; reload/rollback stay at INFO.
            string hotTag = cmd == "status" ? "DEBUG" : "INFO";
            HostLog.Write($"[ZGB] -{hotTag}- Hot-reload command from ZAH: {cmd}{(force ? " (force)" : "")}{(version != null ? " " + version : "")}");
            switch (cmd)
            {
                case "status":
                    {
                        var st = StatusJson();
                        return Reply(cmd, reqId, true, null, null, st);
                    }
                case "versions":
                case "list-versions":
                case "list":
                    {
                        var cur = _current?.Info?.Id;
                        var arr = new JArray(ListVersions().Select(v =>
                        {
                            var o = JObject.FromObject(v.ToJson());
                            o["current"] = v.Id == cur;
                            o["lastGood"] = v.Id == _state.LastGood;
                            return o;
                        }));
                        return Reply("versions", reqId, true, null, null, new JObject { ["current"] = cur, ["lastGood"] = _state.LastGood, ["versions"] = arr });
                    }
                case "reload":
                    return ResultReply(cmd, reqId, Reload("command", force));
                case "rollback":
                    return ResultReply(cmd, reqId, Rollback(version));
                default:
                    return Reply(string.IsNullOrEmpty(cmd) ? "?" : cmd, reqId, false, "bad_request", "Unknown hot: command. Use status, reload, rollback or versions.");
            }
        }

        private string ResultReply(string cmd, string reqId, ActivationResult r)
        {
            var extra = new JObject
            {
                ["result"] = r.Result,
                ["from"] = r.From == null ? null : JObject.FromObject(r.From.ToJson()),
                ["to"] = r.To == null ? null : JObject.FromObject(r.To.ToJson()),
                ["rolledBackTo"] = r.RolledBackTo == null ? null : JObject.FromObject(r.RolledBackTo.ToJson()),
                ["current"] = _current?.Info == null ? null : JObject.FromObject(_current.Info.ToJson()),
                ["durationMs"] = r.DurationMs
            };
            return Reply(cmd, reqId, r.Ok, r.Error, r.Message, extra);
        }

        private static string Reply(string cmd, string reqId, bool ok, string error, string message, JObject extra = null)
        {
            var o = new JObject { ["type"] = "HOT", ["cmd"] = cmd, ["req_id"] = reqId, ["ok"] = ok };
            if (error != null) o["error"] = error;
            if (message != null) o["message"] = message;
            if (extra != null) foreach (var p in extra.Properties()) o[p.Name] = p.Value;
            return o.ToString(Formatting.None);
        }

        // ------------------------------------------------------------------ drop-folder watcher

        public void StartWatcher()
        {
            _watcher = new Timer(_ => PollDrop(), null, PollMs, PollMs);
        }

        private void PollDrop()
        {
            if (_shutdown) return;
            try
            {
                if (!AutoReloadOnDrop || !HotReloadEnabled) { _lastSeenSig = null; return; }
                var fi = new FileInfo(DropCorePath);
                if (!fi.Exists) { _lastSeenSig = null; return; }
                string sig = fi.Length + "|" + fi.LastWriteTimeUtc.Ticks;
                if (sig != _lastSeenSig) { _lastSeenSig = sig; return; } // wait until the file stops changing
                if (sig == _lastAttemptSig || ReloadInProgress) return;
                _lastAttemptSig = sig;
                HostLog.Write($"[ZGB] -INFO- New core dropped in Updates/; auto-reloading (AutoReloadOnDrop).");
                Reload("auto", force: false);
            }
            catch (Exception ex) { HostLog.Write($"[ZGB] -WARN- Drop-folder check failed: {ex.Message}"); }
        }

        // ------------------------------------------------------------------ shutdown

        public void Shutdown()
        {
            _shutdown = true;
            try { _watcher?.Dispose(); } catch { }
            lock (_reloadGate)
            {
                Session s;
                lock (_forwardLock)
                {
                    s = _current;
                    _current = null;
                    if (s != null) { s.Retired = true; StopSession(s); }
                }
                if (s != null) Unload(s);
            }
            AppDomain.CurrentDomain.AssemblyResolve -= ResolveForInProcess;
            HostLog.Write($"[ZGB] -INFO- Hot-reload host stopped (live core domains: {LiveDomainCount}).");
        }
    }

    [Serializable]
    public sealed class SelfTestException : Exception
    {
        public SelfTestException(string m) : base(m) { }
        private SelfTestException(System.Runtime.Serialization.SerializationInfo i, System.Runtime.Serialization.StreamingContext c) : base(i, c) { }
    }

    [Serializable]
    public sealed class ContractMismatchException : Exception
    {
        public ContractMismatchException(string m) : base(m) { }
        private ContractMismatchException(System.Runtime.Serialization.SerializationInfo i, System.Runtime.Serialization.StreamingContext c) : base(i, c) { }
    }
}
