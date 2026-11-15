using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Collections.Concurrent;
using Newtonsoft.Json;

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
    /// Manages the TCP socket server on Port 30500 with password authentication gating
    /// and protected JSON telemetry broadcasting.
    /// </summary>
    public class TelemetryServer
    {
        private static readonly Encoding Utf8NoBom = new UTF8Encoding(false);

        private readonly int _port;
        private readonly CommandDispatcher _commandDispatcher;
        private readonly Func<string> _tokenProvider;
        private readonly AlertService _alertService;
        private TcpListener _listener;
        private Thread _listenerThread;
        private volatile bool _isRunning;
        private readonly ManualResetEventSlim _stopEvent = new ManualResetEventSlim(false);

        // Thread-safe map of active client sessions
        private readonly ConcurrentDictionary<string, ClientSession> _connectedSessions = new ConcurrentDictionary<string, ClientSession>();

        public bool HasActiveConnections => !_connectedSessions.IsEmpty;

        // Incremented on every successful auth. TelemetryBroadcaster watches it so a newly
        // connected client receives the online roster on the next METRIC tick.
        private int _authGeneration;
        public int AuthGeneration => Volatile.Read(ref _authGeneration);

        /// <param name="tokenProvider">Returns the current auth token (ZeroGBridge.json AuthToken or the fallback).
        /// Called on every auth attempt so a changed token applies without a restart. Never logged.</param>
        public TelemetryServer(int port, CommandDispatcher commandDispatcher, Func<string> tokenProvider = null, AlertService alertService = null)
        {
            _port = port;
            _commandDispatcher = commandDispatcher;
            _tokenProvider = tokenProvider ?? AuthConfig.GetToken;
            _alertService = alertService;
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
                ZgbLog.Write($"[ZGB] -STATUS- TelemetryServer listening on port {_port} with password protection enabled. Owner: {ModMain.DescribeProcess()}");

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
                    ZgbLog.Write($"[ZGB] -ERROR- TelemetryServer listener exception on port {_port}: {ex.Message} ({ModMain.DescribeProcess()}). If the port is in use, another ZeroGBridge process already owns it.");
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
                                    ZgbLog.Write($"[ZGB] -INFO- Client ZAH successfully authenticated on Port {_port}.");
                                    var authSuccess = new { type = "AUTH", status = "Authenticated", message = "Access Granted" };
                                    SendToClient(session, JsonConvert.SerializeObject(authSuccess));
                                    continue;
                                }
                                else
                                {
                                    ZgbLog.Write($"[ZGB] -WARN- Client {session.RemoteEndpoint} provided an invalid auth token; closing.");
                                    var authDenied = new { type = "AUTH", status = "Denied", message = "Invalid Credentials" };
                                    SendToClient(session, JsonConvert.SerializeObject(authDenied));
                                    Thread.Sleep(1000);
                                    break;
                                }
                            }
                            else if (AlertService.IsAlertLine(trimmedLine))
                            {
                                // alert before auth: one failed ack, one WARN, close
                                ZgbLog.Write($"[ZGB] -WARN- Unauthenticated alert from {session.RemoteEndpoint}; closing connection.");
                                SendToClient(session, AlertService.Ack(AlertService.TryGetReqId(trimmedLine), "auth"));
                                break;
                            }
                            else
                            {
                                // Not authenticated and not an auth line (e.g. port scanners sending HTTP):
                                // reply once, log ONE warning with the remote address, close the connection.
                                var authRequired = new { type = "AUTH", status = "Required", message = "Authentication Required. Submit auth:<password>" };
                                ZgbLog.Write($"[ZGB] -WARN- Unauthenticated non-auth line from {session.RemoteEndpoint}; sent Auth Required and closed the connection.");
                                SendToClient(session, JsonConvert.SerializeObject(authRequired));
                                break;
                            }
                        }

                        // 2. In-game alerts: exactly one ALERT_ACK per request.
                        if (AlertService.IsAlertLine(trimmedLine))
                        {
                            string ack = _alertService != null
                                ? _alertService.Handle(trimmedLine)
                                : AlertService.Ack(AlertService.TryGetReqId(trimmedLine), "api_error");
                            SendToClient(session, ack);
                            continue;
                        }

                        // 3. Process authenticated commands via CommandDispatcher.
                        // Exactly one reply per request, written only to the requesting client.
                        // (CommandDispatcher logs the received command, so it is not logged twice here.)
                        string response = _commandDispatcher?.ProcessIncomingCommand(trimmedLine);
                        if (!string.IsNullOrEmpty(response))
                        {
                            SendToClient(session, response);
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -TRACE- Client session ZAH disconnected: {ex.Message}");
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
                ZgbLog.Write($"[ZGB] -ERROR- TelemetryServer shutdown exception: {ex.Message}");
            }
            ZgbLog.Write("[ZGB] -INFO- TelemetryServer stopped cleanly.");
        }

        private void CloseClientConnection(TcpClient client)
        {
            try { client?.GetStream()?.Close(); } catch { }
            try { client?.Close(); } catch { }
        }
    }
}
