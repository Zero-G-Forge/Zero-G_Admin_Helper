// =====================================================================
// MODULE: ZeroGBridge/Loader/GatewayClient.cs
// DESCRIPTION: Core-side half of the game gateway (runs inside the core AppDomain).
//              Live game objects appear as transparent proxies that implement the real
//              Eleon interfaces (IModApi, IPlayfield, IEntity ...), so the core code is unchanged.
// =====================================================================

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Runtime.Remoting;
using System.Runtime.Remoting.Lifetime;
using System.Runtime.Remoting.Messaging;
using System.Runtime.Remoting.Proxies;
using System.Threading;

namespace ZeroGBridge.Hosting
{
    public sealed class GatewayClient : IWireSide
    {
        private readonly IGameGateway _gw;
        private readonly Dictionary<long, WeakReference> _proxies = new Dictionary<long, WeakReference>();
        private readonly Dictionary<Delegate, CallbackSink> _eventSinks = new Dictionary<Delegate, CallbackSink>();
        private readonly ConcurrentQueue<KeyValuePair<long, int>> _released = new ConcurrentQueue<KeyValuePair<long, int>>();
        private long _lastFlushTicks = DateTime.UtcNow.Ticks;

        [ThreadStatic] private static string _eventContext; // "add" / "remove" while marshalling an event accessor

        public GatewayClient(IGameGateway gateway) { _gw = gateway; }

        public bool Passthrough => _gw.Passthrough;

        public int LiveProxyCount { get { lock (_proxies) return _proxies.Count(kv => kv.Value.IsAlive); } }

        public T Root<T>(string name) where T : class
        {
            object w = _gw.GetRoot(name);
            return _gw.Passthrough ? w as T : Wire.Decode(w, typeof(T), this) as T;
        }

        internal object Call(GameObjectProxy proxy, MethodInfo mi, object[] args)
        {
            FlushReleases(false);
            var ps = mi.GetParameters();
            string ctx = mi.IsSpecialName && mi.Name.StartsWith("add_", StringComparison.Ordinal) ? "add"
                : mi.IsSpecialName && mi.Name.StartsWith("remove_", StringComparison.Ordinal) ? "remove" : null;
            object[] wireArgs;
            _eventContext = ctx;
            try { wireArgs = Wire.EncodeArgs(args, ps, this); }
            finally { _eventContext = null; }

            object r = _gw.Invoke(proxy.Id, mi.DeclaringType.AssemblyQualifiedName, mi.MetadataToken, wireArgs);

            if (ctx == "remove" && args.Length == 1 && args[0] is Delegate d)
                lock (_eventSinks) _eventSinks.Remove(d);
            return mi.ReturnType == typeof(void) ? null : Wire.Decode(r, mi.ReturnType, this);
        }

        internal void QueueRelease(long id, int count)
        {
            _released.Enqueue(new KeyValuePair<long, int>(id, count));
        }

        public void FlushReleases(bool force)
        {
            if (_released.IsEmpty) return;
            long now = DateTime.UtcNow.Ticks;
            if (!force && _released.Count < 256 && now - Interlocked.Read(ref _lastFlushTicks) < TimeSpan.TicksPerSecond * 10) return;
            Interlocked.Exchange(ref _lastFlushTicks, now);
            var ids = new List<long>(); var counts = new List<int>();
            while (_released.TryDequeue(out var kv))
            {
                lock (_proxies)
                {
                    if (_proxies.TryGetValue(kv.Key, out var wr) && !wr.IsAlive) _proxies.Remove(kv.Key);
                }
                ids.Add(kv.Key); counts.Add(kv.Value);
            }
            try { _gw.Release(ids.ToArray(), counts.ToArray()); } catch { }
        }

        // ------------------------------------------------------------------ IWireSide (core side)

        public object TryEncodeLive(object value, Type declared)
        {
            if (RemotingServices.IsTransparentProxy(value) && RemotingServices.GetRealProxy(value) is GameObjectProxy gp)
                return new HandleRef { Id = gp.Id, Interfaces = gp.Interfaces };
            if (value is Delegate d)
            {
                string ctx = _eventContext;
                CallbackSink sink;
                if (ctx != null)
                {
                    lock (_eventSinks)
                    {
                        if (!_eventSinks.TryGetValue(d, out sink))
                        {
                            if (ctx == "remove") return new WireDelegate { SinkId = "none" };
                            sink = new CallbackSink(this, d, persistent: true);
                            _eventSinks[d] = sink;
                        }
                    }
                }
                else sink = new CallbackSink(this, d, persistent: false); // one-shot callback (e.g. GetStructures)
                return new WireDelegate { SinkId = sink.Id, Sink = sink };
            }
            return null;
        }

        public object DecodeHandle(HandleRef h, Type expected)
        {
            lock (_proxies)
            {
                if (_proxies.TryGetValue(h.Id, out var wr))
                {
                    var existing = wr.Target;
                    if (existing != null)
                    {
                        ((GameObjectProxy)RemotingServices.GetRealProxy(existing)).AddReceived();
                        return existing;
                    }
                }
                Type iface = expected != null && expected.IsInterface && Wire.IsGameInterface(expected) ? expected
                    : h.Interfaces.Select(Wire.ResolveType).FirstOrDefault(t => t != null);
                if (iface == null) throw new InvalidOperationException("No interface type for game object handle " + h.Id);
                var rp = new GameObjectProxy(this, iface, h.Id, h.Interfaces);
                object tp = rp.GetTransparentProxy();
                _proxies[h.Id] = new WeakReference(tp);
                return tp;
            }
        }

        public object DecodeDelegate(WireDelegate wd, Type expected) => null; // the game never hands delegates to the core
    }

    /// <summary>Transparent proxy for one live game object in the loader domain.</summary>
    public sealed class GameObjectProxy : RealProxy, IRemotingTypeInfo
    {
        private readonly GatewayClient _client;
        private readonly Type[] _ifaceTypes;
        private int _received = 1;

        public long Id { get; }
        public string[] Interfaces { get; }
        public string TypeName { get; set; }

        internal GameObjectProxy(GatewayClient client, Type iface, long id, string[] interfaces) : base(iface)
        {
            _client = client;
            Id = id;
            Interfaces = interfaces ?? new string[0];
            _ifaceTypes = Interfaces.Select(Wire.ResolveType).Where(t => t != null).ToArray();
            TypeName = iface.FullName;
        }

        internal void AddReceived() => Interlocked.Increment(ref _received);

        ~GameObjectProxy()
        {
            try { _client.QueueRelease(Id, Volatile.Read(ref _received)); } catch { }
        }

        public bool CanCastTo(Type fromType, object o)
        {
            if (fromType == typeof(object)) return true;
            return _ifaceTypes.Any(t => fromType.IsAssignableFrom(t));
        }

        public override IMessage Invoke(IMessage msg)
        {
            var call = (IMethodCallMessage)msg;
            var mi = (MethodInfo)call.MethodBase;
            try
            {
                object result;
                if (mi.DeclaringType == typeof(object))
                {
                    switch (mi.Name)
                    {
                        case "Equals":
                            var other = call.Args[0];
                            result = other != null && RemotingServices.IsTransparentProxy(other)
                                     && RemotingServices.GetRealProxy(other) is GameObjectProxy op && op.Id == Id;
                            break;
                        case "GetHashCode": result = Id.GetHashCode(); break;
                        case "ToString": result = "GameObject(" + TypeName + "#" + Id + ")"; break;
                        case "GetType": result = GetProxiedType(); break;
                        default: throw new NotSupportedException(mi.Name);
                    }
                }
                else
                {
                    result = _client.Call(this, mi, call.Args);
                }
                return new ReturnMessage(result, null, 0, call.LogicalCallContext, call);
            }
            catch (Exception ex)
            {
                return new ReturnMessage(ex is TargetInvocationException tie && tie.InnerException != null ? tie.InnerException : ex, call);
            }
        }
    }

    /// <summary>A core delegate the game can call (lives in the core domain).</summary>
    public sealed class CallbackSink : MarshalByRefObject, ICallbackSink
    {
        private readonly GatewayClient _client;
        private readonly Delegate _target;
        private readonly ParameterInfo[] _ps;
        private readonly Type _ret;
        private readonly bool _persistent;

        public string Id { get; } = Guid.NewGuid().ToString("N");

        public CallbackSink(GatewayClient client, Delegate target, bool persistent)
        {
            _client = client;
            _target = target;
            var invoke = target.GetType().GetMethod("Invoke");
            _ps = invoke.GetParameters();
            _ret = invoke.ReturnType;
            _persistent = persistent;
        }

        public override object InitializeLifetimeService()
        {
            if (_persistent) return null; // event handlers live until removed or the domain unloads
            var lease = (ILease)base.InitializeLifetimeService();
            if (lease.CurrentState == LeaseState.Initial)
            {
                lease.InitialLeaseTime = TimeSpan.FromMinutes(10);
                lease.RenewOnCallTime = TimeSpan.FromMinutes(2);
            }
            return lease;
        }

        public object Invoke(object[] wireArgs)
        {
            object[] args = Wire.DecodeArgs(wireArgs, _ps, _client);
            object r;
            try { r = _target.DynamicInvoke(args); }
            catch (TargetInvocationException tie) when (tie.InnerException != null)
            {
                throw new InvalidOperationException("Core callback failed: " + tie.InnerException.GetType().Name + ": " + tie.InnerException.Message);
            }
            return _ret == typeof(void) ? null : Wire.Encode(r, _ret, _client);
        }
    }
}
