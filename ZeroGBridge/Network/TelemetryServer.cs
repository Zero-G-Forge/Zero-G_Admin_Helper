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
    /// </summary>
    public class ClientSession
    {
        public string ClientId { get; set; }
        public TcpClient Client { get; set; }
        public bool IsAuthenticated { get; set; }
        public DateTime ConnectedAt { get; set; }
    }

    /// <summary>
    /// Manages the TCP socket server on Port 30500 with password authentication gating
    /// and protected JSON telemetry broadcasting.
    /// </summary>
    public class TelemetryServer
    {
        private readonly int _port;
        private readonly CommandDispatcher _commandDispatcher;
        private readonly string _serverPassword;
        private TcpListener _listener;
        private Thread _listenerThread;
        private bool _isRunning;

        // Thread-safe map of active client sessions
        private readonly ConcurrentDictionary<string, ClientSession> _connectedSessions = new ConcurrentDictionary<string, ClientSession>();

        public bool HasActiveConnections => !_connectedSessions.IsEmpty;

        public TelemetryServer(int port, CommandDispatcher commandDispatcher, string serverPassword = "ZeroGAdmin2026")
        {
            _port = port;
            _commandDispatcher = commandDispatcher;
            _serverPassword = serverPassword;
        }

        /// <summary>
        /// Spawns the background listener thread.
        /// </summary>
        public void Start()
        {
            _isRunning = true;
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
                Console.WriteLine($"[ZGB] -STATUS- TelemetryServer listening on port {_port} with password protection enabled.");

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

                        _connectedSessions.TryAdd(clientId, session);

                        // Dispatch client session handling to ThreadPool
                        ThreadPool.QueueUserWorkItem(state => HandleClientSession(session), null);
                    }
                    else
                    {
                        Thread.Sleep(100);
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -ERROR- TelemetryServer listener exception: {ex.Message}");
            }
        }

        private void HandleClientSession(ClientSession session)
        {
            try
            {
                using (NetworkStream stream = session.Client.GetStream())
                using (StreamReader reader = new StreamReader(stream, Encoding.UTF8))
                using (StreamWriter writer = new StreamWriter(stream, Encoding.UTF8) { AutoFlush = true })
                {
                    string line;
                    while (_isRunning && session.Client.Connected && (line = reader.ReadLine()) != null)
                    {
                        if (string.IsNullOrEmpty(line)) continue;

                        string trimmedLine = line.Trim();

                        // 1. Evaluate Authentication Handshake if unauthenticated
                        if (!session.IsAuthenticated)
                        {
                            if (trimmedLine.StartsWith("auth:", StringComparison.OrdinalIgnoreCase))
                            {
                                string submittedPassword = trimmedLine.Substring(5).Trim();
                                if (submittedPassword == _serverPassword)
                                {
                                    session.IsAuthenticated = true;
                                    Console.WriteLine($"[ZGB] -INFO- Client ZAH successfully authenticated on Port {_port}.");
                                    var authSuccess = new { type = "AUTH", status = "Authenticated", message = "Access Granted" };
                                    writer.WriteLine(JsonConvert.SerializeObject(authSuccess));
                                    continue;
                                }
                                else
                                {
                                    Console.WriteLine($"[ZGB] -WARN- Client ZAH provided an invalid password.");
                                    var authDenied = new { type = "AUTH", status = "Denied", message = "Invalid Credentials" };
                                    writer.WriteLine(JsonConvert.SerializeObject(authDenied));
                                    Thread.Sleep(1000);
                                    break;
                                }
                            }
                            else
                            {
                                // Reject unauthenticated commands
                                var authRequired = new { type = "AUTH", status = "Required", message = "Authentication Required. Submit auth:<password>" };
                                Console.WriteLine($"[ZGB] -WARN- Invalid Command Provided");
                                writer.WriteLine(JsonConvert.SerializeObject(authRequired));
                                continue;
                            }
                        }

                        // 2. Process authenticated commands via CommandDispatcher
                        Console.WriteLine($"[ZGB] -INFO- Received command from ZAH : \"{trimmedLine}\"");
                        string response = _commandDispatcher?.ProcessIncomingCommand(trimmedLine);
                        if (!string.IsNullOrEmpty(response))
                        {
                            // Send directly to the requesting socket
                            writer.WriteLine(response);
                            writer.Flush();

                            // Also broadcast to ensure all listening GUI workers receive the packet
                            BroadcastJson(response);
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -TRACE- Client session ZAH disconnected: {ex.Message}");
            }
            finally
            {
                _connectedSessions.TryRemove(session.ClientId, out _);
                CloseClientConnection(session.Client);
            }
        }

        /// <summary>
        /// Broadcasts serialized JSON data packages exclusively to authenticated clients.
        /// </summary>
        public void BroadcastJson(string jsonPayload)
        {
            if (string.IsNullOrEmpty(jsonPayload) || _connectedSessions.IsEmpty)
            {
                return;
            }

            string formattedPayload = jsonPayload.EndsWith("\n") ? jsonPayload : jsonPayload + "\n";
            byte[] buffer = Encoding.UTF8.GetBytes(formattedPayload);

            foreach (var kvp in _connectedSessions)
            {
                ClientSession session = kvp.Value;
                
                // Gate telemetry push behind authentication
                if (session == null || !session.IsAuthenticated || session.Client == null || !session.Client.Connected)
                {
                    continue;
                }

                try
                {
                    NetworkStream stream = session.Client.GetStream();
                    if (stream.CanWrite)
                    {
                        stream.Write(buffer, 0, buffer.Length);
                        stream.Flush();
                    }
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
            try
            {
                _listener?.Stop();
                foreach (var kvp in _connectedSessions)
                {
                    CloseClientConnection(kvp.Value.Client);
                }
                _connectedSessions.Clear();
                _listenerThread?.Join(1000);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ZGB] -ERROR- TelemetryServer shutdown exception: {ex.Message}");
            }
            Console.WriteLine("[ZGB] -INFO- TelemetryServer stopped cleanly.");
        }

        private void CloseClientConnection(TcpClient client)
        {
            try { client?.GetStream()?.Close(); } catch { }
            try { client?.Close(); } catch { }
        }
    }
}