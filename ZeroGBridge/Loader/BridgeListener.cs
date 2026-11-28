using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Collections.Concurrent;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using ZeroGBridge.Hosting;

// =====================================================================
// MODULE: ZeroGBridge/Loader/BridgeListener.cs (was Network/TelemetryServer.cs)
// DESCRIPTION: Bridge TCP listener + auth. 1.5.0: lives in the stable loader so ZAH
//              connections survive core hot reloads. Lines after auth go to a handler
//              (the current core) or, for "hot:" lines, to the hot-reload controller.
// =====================================================================

namespace ZeroGBridge
{
    /// <summary>
    /// Represents an active connected client session and its authentication status.
    /// A single StreamWriter is used for every write to this client.
    /// </summary>
    public class ClientSession
    {
        public string ClientId { get; set; }
        public TcpClient Client { get; set; }
        public StreamWriter Writer { get; set; }
        public readonly object WriteLock = new object();
        public bool IsAuthenticated { get; set; }
        public DateTime ConnectedAt { get; set; }
        public string RemoteEndpoint { get; set; } = "unknown";
    }

    /// <summary>
    /// Manages the bridge TCP socket server (ZeroGBridge.json "Port", default 30500) with password authentication gating
    /// and protected JSON telemetry broadcasting. MarshalByRefObject so a core in another AppDomain can broadcast.
    /// </summary>
    public class BridgeListener : MarshalByRefObject, IClientHub
    {
        /// <summary>Describes the owning process for the "listening" log line (set by the loader / standalone core).</summary>
        public static Func<string> OwnerDescription = () => "ZeroGBridge";

        public override object InitializeLifetimeService() => null; // live as long as the listener
        private static readonly Encoding Utf8NoBom = new UTF8Encoding(false);

        private readonly int _port;
        private readonly Func<string, string, string> _lineHandler;   // (clientId, line) -> reply
        private readonly Func<string, string, string> _hotHandler;    // (clientId, line) -> reply for "hot:" lines
        private readonly Func<string> _tokenProvider;
        private TcpListener _listener;
        private Thread _listenerThread;
        private volatile bool _isRunning;
        private readonly ManualResetEventSlim _stopEvent = new ManualResetEventSlim(false);

        // Thread-safe map of active client sessions
        private readonly ConcurrentDictionary<string, ClientSession> _connectedSessions = new ConcurrentDictionary<string, ClientSession>();

        public bool HasActiveConnections => !_connectedSessions.IsEmpty;

        /// <summary>The TCP port this server listens on (ZeroGBridge.json "Port", default 30500).</summary>
        public int Port => _port;

        /// <summary>True once the listener socket is bound (for tests and status).</summary>
        public bool IsListening { get; private set; }

        // Incremented on every successful auth. TelemetryBroadcaster watches it so a newly
        // connected client receives the online roster on the next METRIC tick.
        private int _authGeneration;
        public int AuthGeneration => Volatile.Read(ref _authGeneration);

        // Last INFO auth line, keyed by remote address without the ephemeral port.
        // ZAH opens a new TCP session per request, so a per-connection log is too noisy.
        private static readonly ConcurrentDictionary<string, DateTime> _lastAuthInfoUtc =
            new ConcurrentDictionary<string, DateTime>(StringComparer.OrdinalIgnoreCase);
        private static readonly TimeSpan AuthInfoInterval = TimeSpan.FromMinutes(5);
        private static readonly object _authInfoLock = new object();

        /// <param name="tokenProvider">Returns the current auth token (ZeroGBridge.json AuthToken or the fallback).
        /// Called on every auth attempt so a changed token applies without a restart. Never logged.</param>
        /// <param name="lineHandler">Authenticated non-hot lines (commands and alert:). Exactly one reply per line.</param>
        /// <param name="hotHandler">Optional handler for "hot:" lines (loader only).</param>
        public BridgeListener(int port, Func<string, string, string> lineHandler, Func<string> tokenProvider = null, Func<string, string, string> hotHandler = null)
        {
            _port = port;
            _lineHandler = lineHandler;
            _tokenProvider = tokenProvider ?? AuthConfig.GetToken;
            _hotHandler = hotHandler;
        }

        public const string HotPrefix = "hot:";

        public static bool IsHotLine(string line) => line != null && line.StartsWith(HotPrefix, StringComparison.OrdinalIgnoreCase);

        private static bool IsAlertLine(string line) => line != null && line.StartsWith("alert:", StringComparison.OrdinalIgnoreCase);

        /// <summary>Same JSON as AlertService.Ack(reqId, "auth") (the core's class is not visible here).</summary>
        private static string AlertAuthAck(string line)
        {
            string reqId = null;
            try
            {
                var t = JObject.Parse(line.Substring(6))["req_id"];
                if (t != null && t.Type == JTokenType.String) reqId = (string)t;
                else if (t != null && (t.Type == JTokenType.Integer || t.Type == JTokenType.Float)) reqId = Convert.ToString(((JValue)t).Value, System.Globalization.CultureInfo.InvariantCulture);
            }
            catch { }
            return JsonConvert.SerializeObject(new { type = "ALERT_ACK", req_id = reqId, status = "failed", error = "auth" });
        }

        private static string SafeOwner()
        {
            try { return OwnerDescription?.Invoke() ?? "ZeroGBridge"; } catch { return "ZeroGBridge"; }
        }

        private static bool TokenEquals(string a, string b)
        {
            if (a == null || b == null) return false;
            // constant-time compare
            int diff = a.Length ^ b.Length;
            int n = Math.Max(a.Length, b.Length);
            for (int i = 0; i < n; i++)
            {
                char ca = i < a.Length ? a[i] : '\0';
                char cb = i < b.Length ? b[i] : '\0';
                diff |= ca ^ cb;
            }
            return diff == 0;
        }

        /// <summary>
        /// Spawns the background listener thread.
        /// </summary>
        public void Start()
        {
            _isRunning = true;
            _stopEvent.Reset();
            _listenerThread = new Thread(ListenForClients)
            {
                IsBackground = true,
                Name = "ZeroGBridge_TCP_Listener"
            };
            _listenerThread.Start();
        }

        private void ListenForClients()
        {
            try
            {
                _listener = new TcpListener(IPAddress.Any, _port);
                _listener.Start();
                IsListening = true;
                HostLog.Write($"[ZGB] -STATUS- TelemetryServer listening on port {_port} with password protection enabled. Owner: {SafeOwner()}");

                while (_isRunning)
                {
                    if (_listener.Pending())
                    {
                        TcpClient client = _listener.AcceptTcpClient();
                        string clientId = Guid.NewGuid().ToString();

                        var session = new ClientSession
                        {
                            ClientId = clientId,
                            Client = client,
                            IsAuthenticated = false,
                            ConnectedAt = DateTime.UtcNow
                        };
                        try { session.RemoteEndpoint = client.Client?.RemoteEndPoint?.ToString() ?? "unknown"; } catch { }

                        _connectedSessions.TryAdd(clientId, session);

                        // Dispatch client session handling to ThreadPool
                        ThreadPool.QueueUserWorkItem(state => HandleClientSession(session), null);
                    }
                    else
                    {
                        _stopEvent.Wait(100);
                    }
                }
            }
            catch (Exception ex)
            {
                if (_isRunning)
                {
                    HostLog.Write($"[ZGB] -ERROR- TelemetryServer listener exception on port {_port}: {ex.Message} ({SafeOwner()}). If the port is in use, another ZeroGBridge process already owns it.");
                }
            }
        }

        private void HandleClientSession(ClientSession session)
        {
            try
            {
                NetworkStream stream = session.Client.GetStream();
                using (StreamReader reader = new StreamReader(stream, Utf8NoBom, detectEncodingFromByteOrderMarks: false, 1024, leaveOpen: true))
                using (StreamWriter writer = new StreamWriter(stream, Utf8NoBom, 1024, leaveOpen: true) { AutoFlush = true })
                {
                    session.Writer = writer;

                    string line;
                    while (_isRunning && session.Client.Connected && (line = reader.ReadLine()) != null)
                    {
                        if (string.IsNullOrEmpty(line)) continue;

                        // Tolerate a client that prefixes its first line with a UTF-8 BOM
                        // (e.g. .NET StreamWriter with Encoding.UTF8); the bridge never emits one.
                        string trimmedLine = line.Trim().TrimStart('\uFEFF').Trim();
                        if (trimmedLine.Length == 0) continue;

                        // 1. Evaluate Authentication Handshake if unauthenticated
                        if (!session.IsAuthenticated)
                        {
                            if (trimmedLine.StartsWith("auth:", StringComparison.OrdinalIgnoreCase))
                            {
                                string submittedPassword = trimmedLine.Substring(5).Trim();
                                string expected = null;
                                try { expected = _tokenProvider(); } catch { }
                                if (!string.IsNullOrEmpty(expected) && TokenEquals(submittedPassword, expected))
                                {
                                    session.IsAuthenticated = true;
                                    Interlocked.Increment(ref _authGeneration);
                                    LogAuthSuccess(session);
                                    var authSuccess = new { type = "AUTH", status = "Authenticated", message = "Access Granted" };
                                    SendToClient(session, JsonConvert.SerializeObject(authSuccess));
                                    continue;
                                }
                                else
                                {
                                    HostLog.Write($"[ZGB] -WARN- Client {session.RemoteEndpoint} provided an invalid auth token; closing.");
                                    var authDenied = new { type = "AUTH", status = "Denied", message = "Invalid Credentials" };
                                    SendToClient(session, JsonConvert.SerializeObject(authDenied));
                                    Thread.Sleep(1000);
                                    break;
                                }
                            }
                            else if (IsAlertLine(trimmedLine))
                            {
                                // alert before auth: one failed ack, one WARN, close
                                HostLog.Write($"[ZGB] -WARN- Unauthenticated alert from {session.RemoteEndpoint}; closing connection.");
                                SendToClient(session, AlertAuthAck(trimmedLine));
                                break;
                            }
                            else
                            {
                                // Not authenticated and not an auth line (e.g. port scanners sending HTTP):
                                // reply once, log ONE warning with the remote address, close the connection.
                                var authRequired = new { type = "AUTH", status = "Required", message = "Authentication Required. Submit auth:<password>" };
                                HostLog.Write($"[ZGB] -WARN- Unauthenticated non-auth line from {session.RemoteEndpoint}; sent Auth Required and closed the connection.");
                                SendToClient(session, JsonConvert.SerializeObject(authRequired));
                                break;
                            }
                        }

                        // 2. 1.5.0 hot-reload commands (loader). Exactly one HOT reply per line.
                        string response;
                        if (IsHotLine(trimmedLine))
                        {
                            try
                            {
                                response = _hotHandler != null
                                    ? _hotHandler(session.ClientId, trimmedLine)
                                    : JsonConvert.SerializeObject(new { type = "HOT", ok = false, error = "not_supported", message = "This bridge build runs without the hot-reload loader." });
                            }
                            catch (Exception hex)
                            {
                                response = JsonConvert.SerializeObject(new { type = "HOT", ok = false, error = "exception", message = hex.GetType().Name + ": " + hex.Message });
                            }
                            SendToClient(session, response);
                            continue;
                        }

                        // 3. Commands and alert: lines go to the core (CommandDispatcher / AlertService).
                        // Exactly one reply per request, written only to the requesting client.
                        // (CommandDispatcher logs the received command, so it is not logged twice here.)
                        try { response = _lineHandler?.Invoke(session.ClientId, trimmedLine); }
                        catch (Exception hex)
                        {
                            HostLog.Write($"[ZGB] -WARN- Line handler failed: {hex.GetType().Name}: {hex.Message}");
                            response = JsonConvert.SerializeObject(new { type = "ERROR", message = "Bridge core error: " + hex.GetType().Name });
                        }
                        if (!string.IsNullOrEmpty(response))
                        {
                            SendToClient(session, response);
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                HostLog.Write($"[ZGB] -TRACE- Client session ZAH disconnected: {ex.Message}");
            }
            finally
            {
                session.Writer = null;
                _connectedSessions.TryRemove(session.ClientId, out _);
                CloseClientConnection(session.Client);
            }
        }

        /// <summary>
        /// Writes one JSON line to a single client using that session's StreamWriter.
        /// </summary>
        public void SendToClient(ClientSession session, string jsonPayload)
        {
            if (session == null || session.Writer == null || string.IsNullOrEmpty(jsonPayload))
            {
                return;
            }

            string line = jsonPayload.TrimEnd('\r', '\n');
            lock (session.WriteLock)
            {
                session.Writer.WriteLine(line);
                session.Writer.Flush();
            }
        }

        /// <summary>
        /// Broadcasts serialized JSON data packages exclusively to authenticated clients.
        /// When exceptClientId is set, that client is skipped (used after a direct command reply).
        /// </summary>
        public void BroadcastJson(string jsonPayload, string exceptClientId = null)
        {
            if (string.IsNullOrEmpty(jsonPayload) || _connectedSessions.IsEmpty)
            {
                return;
            }

            foreach (var kvp in _connectedSessions)
            {
                ClientSession session = kvp.Value;

                if (session == null || !session.IsAuthenticated || session.Client == null || !session.Client.Connected)
                {
                    continue;
                }

                if (exceptClientId != null && session.ClientId == exceptClientId)
                {
                    continue;
                }

                try
                {
                    SendToClient(session, jsonPayload);
                }
                catch
                {
                    _connectedSessions.TryRemove(kvp.Key, out _);
                }
            }
        }

        public void Stop()
        {
            _isRunning = false;
            _stopEvent.Set();
            try
            {
                _listener?.Stop();
                foreach (var kvp in _connectedSessions)
                {
                    CloseClientConnection(kvp.Value.Client);
                }
                _connectedSessions.Clear();
                if (_listenerThread != null && _listenerThread.IsAlive)
                {
                    _listenerThread.Join(3000);
                }
            }
            catch (Exception ex)
            {
                HostLog.Write($"[ZGB] -ERROR- TelemetryServer shutdown exception: {ex.Message}");
            }
            HostLog.Write("[ZGB] -INFO- TelemetryServer stopped cleanly.");
        }

        private void CloseClientConnection(TcpClient client)
        {
            try { client?.GetStream()?.Close(); } catch { }
            try { client?.Close(); } catch { }
        }

        private static string AuthClientKey(ClientSession session)
        {
            string ep = session != null ? session.RemoteEndpoint : null;
            if (string.IsNullOrEmpty(ep)) return "unknown";
            int colon = ep.LastIndexOf(':');
            return colon > 0 ? ep.Substring(0, colon) : ep;
        }

        // INFO the first time (and again after AuthInfoInterval); repeats go to DEBUG.
        private void LogAuthSuccess(ClientSession session)
        {
            string key = AuthClientKey(session);
            DateTime now = DateTime.UtcNow;
            // 1.5.1: the check and the update are one locked step, so parallel logins from the same
            // address (ZAH opens several at once) print one INFO line, not one each.
            bool printInfo;
            lock (_authInfoLock)
            {
                DateTime last;
                printInfo = !(_lastAuthInfoUtc.TryGetValue(key, out last) && (now - last) < AuthInfoInterval);
                if (printInfo) _lastAuthInfoUtc[key] = now;
            }
            if (!printInfo)
            {
                HostLog.Write($"[ZGB] -DEBUG- Client ZAH successfully authenticated on Port {_port}.");
                return;
            }
            HostLog.Write($"[ZGB] -INFO- Client ZAH successfully authenticated on Port {_port}.");
        }
    }
}
