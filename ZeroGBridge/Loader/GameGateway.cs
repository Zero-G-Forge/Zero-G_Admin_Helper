// =====================================================================
// MODULE: ZeroGBridge/Loader/GameGateway.cs
// DESCRIPTION: Loader-side broker that lets a core in another AppDomain use the live game API.
//              Live objects stay here in a handle table; the core sends (handle, method, args).
//              Event subscriptions made by a core are tracked and removed when that core unloads,
//              so the game never calls into an unloaded domain.
// =====================================================================

using System;
using System.Collections.Generic;
using System.Linq;
using System.Linq.Expressions;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.Remoting;
using System.Threading;

namespace ZeroGBridge.Hosting
{
    public sealed class GameGateway : MarshalByRefObject, IGameGateway, IWireSide, IDisposable
    {
        private sealed class RefEq : IEqualityComparer<object>
        {
            public new bool Equals(object a, object b) => ReferenceEquals(a, b);
            public int GetHashCode(object o) => RuntimeHelpers.GetHashCode(o);
        }

        private sealed class Entry { public object Obj; public int Issued; }

        private sealed class Subscription
        {
            public object Target;
            public string EventName;
            public MethodInfo Remove;
            public Delegate Stub;
            public string SinkId;
        }

        private readonly object _sync = new object();
        private readonly Dictionary<long, Entry> _byId = new Dictionary<long, Entry>();
        private readonly Dictionary<object, long> _byObj = new Dictionary<object, long>(new RefEq());
        private readonly List<Subscription> _subs = new List<Subscription>();
        private readonly Dictionary<string, MethodInfo> _methodCache = new Dictionary<string, MethodInfo>();
        private readonly Func<string, object> _roots;
        private readonly bool _passthrough;
        private long _nextId;
        private volatile bool _disposed;
        private int _stubWarned;

        public string Name { get; }

        public GameGateway(string name, Func<string, object> roots, bool passthrough)
        {
            Name = name;
            _roots = roots;
            _passthrough = passthrough;
        }

        public override object InitializeLifetimeService() => null;

        public bool Passthrough => _passthrough;
        public bool IsDisposed => _disposed;
        public int HandleCount { get { lock (_sync) return _byId.Count; } }
        public int SubscriptionCount { get { lock (_sync) return _subs.Count; } }

        public object GetRoot(string name)
        {
            object obj = _roots?.Invoke(name);
            return _passthrough ? obj : Wire.Encode(obj, typeof(object), this);
        }

        public object Invoke(long handle, string declaringTypeAqn, int metadataToken, object[] wireArgs)
        {
            if (_disposed) throw new InvalidOperationException("Game gateway is closed (core was unloaded).");
            object target;
            lock (_sync)
            {
                if (!_byId.TryGetValue(handle, out var e)) throw new InvalidOperationException("Stale game object handle " + handle + ".");
                target = e.Obj;
            }
            MethodInfo mi = ResolveMethod(declaringTypeAqn, metadataToken);
            if (!mi.DeclaringType.IsInstanceOfType(target))
                throw new InvalidOperationException("Method " + mi.Name + " is not implemented by handle " + handle + ".");
            var ps = mi.GetParameters();
            object[] args = Wire.DecodeArgs(wireArgs, ps, this);

            bool isAdd = mi.IsSpecialName && mi.Name.StartsWith("add_", StringComparison.Ordinal);
            bool isRemove = mi.IsSpecialName && mi.Name.StartsWith("remove_", StringComparison.Ordinal);
            string eventName = isAdd ? mi.Name.Substring(4) : isRemove ? mi.Name.Substring(7) : null;
            Subscription removed = null;

            if (isRemove)
            {
                string sinkId = (wireArgs != null && wireArgs.Length > 0 ? wireArgs[0] as WireDelegate : null)?.SinkId;
                lock (_sync)
                {
                    removed = _subs.FirstOrDefault(s => ReferenceEquals(s.Target, target) && s.EventName == eventName && s.SinkId == sinkId);
                    if (removed == null) return null; // never subscribed through us: nothing to remove
                    _subs.Remove(removed);
                }
                args[0] = removed.Stub;
            }

            object result;
            try
            {
                result = mi.Invoke(target, args);
            }
            catch (TargetInvocationException tie) when (tie.InnerException != null)
            {
                // only mscorlib exception types cross the domain boundary safely
                throw new InvalidOperationException(tie.InnerException.GetType().Name + ": " + tie.InnerException.Message);
            }

            if (isAdd && args.Length == 1 && args[0] is Delegate stub)
            {
                var wd = wireArgs[0] as WireDelegate;
                var rm = mi.DeclaringType.GetMethod("remove_" + eventName);
                lock (_sync) _subs.Add(new Subscription { Target = target, EventName = eventName, Remove = rm, Stub = stub, SinkId = wd?.SinkId });
            }
            return Wire.Encode(result, mi.ReturnType, this);
        }

        public void Release(long[] handles, int[] counts)
        {
            if (handles == null) return;
            lock (_sync)
            {
                for (int i = 0; i < handles.Length; i++)
                {
                    if (!_byId.TryGetValue(handles[i], out var e)) continue;
                    e.Issued -= counts != null && i < counts.Length ? counts[i] : e.Issued;
                    if (e.Issued <= 0)
                    {
                        _byId.Remove(handles[i]);
                        _byObj.Remove(e.Obj);
                    }
                }
            }
        }

        /// <summary>Invokes every delegate a core subscribed to the named event (e.g. replay OnPlayfieldLoaded after a reload).</summary>
        public int ReplayEvent(string eventName, params object[] args)
        {
            Subscription[] subs;
            lock (_sync) subs = _subs.Where(s => s.EventName == eventName).ToArray();
            foreach (var s in subs)
            {
                try { s.Stub.DynamicInvoke(args); }
                catch (Exception ex) { HostLog.Write("[ZGB] -WARN- Replay of " + eventName + " failed: " + (ex.InnerException ?? ex).Message); }
            }
            return subs.Length;
        }

        /// <summary>Removes every game event subscription the core made and drops all handles.</summary>
        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            Subscription[] subs;
            lock (_sync)
            {
                subs = _subs.ToArray();
                _subs.Clear();
            }
            int removed = 0;
            foreach (var s in subs)
            {
                try { s.Remove?.Invoke(s.Target, new object[] { s.Stub }); removed++; }
                catch (Exception ex) { HostLog.Write("[ZGB] -WARN- Could not unhook " + s.EventName + " left by the old core: " + (ex.InnerException ?? ex).Message); }
            }
            if (subs.Length > 0)
                HostLog.Write($"[ZGB] -INFO- Gateway {Name}: removed {removed} game event subscription(s) the core left behind.");
            lock (_sync)
            {
                _byId.Clear();
                _byObj.Clear();
            }
            try { RemotingServices.Disconnect(this); } catch { }
        }

        private MethodInfo ResolveMethod(string aqn, int token)
        {
            string key = aqn + "|" + token;
            lock (_methodCache)
            {
                if (_methodCache.TryGetValue(key, out var cached)) return cached;
            }
            Type t = Wire.ResolveType(aqn) ?? throw new InvalidOperationException("Unknown type " + aqn);
            if (!Wire.IsGameInterface(t)) throw new InvalidOperationException("Only game API interfaces can be called through the gateway.");
            var mi = t.Module.ResolveMethod(token) as MethodInfo;
            if (mi == null || mi.DeclaringType != t) throw new InvalidOperationException("Unknown method token on " + t.Name);
            if (mi.ContainsGenericParameters) throw new NotSupportedException("Generic game API methods are not supported across domains: " + mi.Name);
            lock (_methodCache) _methodCache[key] = mi;
            return mi;
        }

        // ------------------------------------------------------------------ IWireSide (loader side)

        public object TryEncodeLive(object value, Type declared)
        {
            if (value is Delegate || value is MarshalByRefObject) return null;
            string[] ifaces = Wire.GameInterfacesOf(value.GetType());
            if (ifaces.Length == 0) return null; // plain data -> FieldBag
            lock (_sync)
            {
                if (!_byObj.TryGetValue(value, out long id))
                {
                    id = ++_nextId;
                    _byObj[value] = id;
                    _byId[id] = new Entry { Obj = value };
                }
                _byId[id].Issued++;
                return new HandleRef { Id = id, Interfaces = ifaces };
            }
        }

        public object DecodeHandle(HandleRef handle, Type expected)
        {
            lock (_sync)
            {
                if (_byId.TryGetValue(handle.Id, out var e)) return e.Obj;
            }
            throw new InvalidOperationException("Stale game object handle " + handle.Id + ".");
        }

        public object DecodeDelegate(WireDelegate wd, Type expected)
        {
            if (wd?.Sink == null) return null;
            if (!typeof(Delegate).IsAssignableFrom(expected) || expected == typeof(Delegate) || expected == typeof(MulticastDelegate))
                throw new NotSupportedException("Cannot build a delegate for parameter type " + expected);
            var invoke = expected.GetMethod("Invoke");
            var stub = new DelegateStub(this, wd.Sink, invoke.GetParameters(), invoke.ReturnType);
            var ps = invoke.GetParameters().Select(p => Expression.Parameter(p.ParameterType, p.Name)).ToArray();
            Expression call = Expression.Call(Expression.Constant(stub), typeof(DelegateStub).GetMethod(nameof(DelegateStub.Fire)),
                Expression.NewArrayInit(typeof(object), ps.Select(p => (Expression)Expression.Convert(p, typeof(object)))));
            Expression body = invoke.ReturnType == typeof(void) ? call : Expression.Convert(call, invoke.ReturnType);
            return Expression.Lambda(expected, body, ps).Compile();
        }

        internal void StubFailed(Exception ex)
        {
            if (Interlocked.Exchange(ref _stubWarned, 1) == 0)
                HostLog.Write($"[ZGB] -WARN- Gateway {Name}: a game callback into the core failed: {ex.GetType().Name}: {ex.Message} (further failures are not logged)");
        }

        /// <summary>Target of the compiled delegate the game holds. Never lets an exception reach the game.</summary>
        public sealed class DelegateStub
        {
            private readonly GameGateway _g;
            private readonly ICallbackSink _sink;
            private readonly ParameterInfo[] _ps;
            private readonly Type _ret;

            public DelegateStub(GameGateway g, ICallbackSink sink, ParameterInfo[] ps, Type ret)
            {
                _g = g; _sink = sink; _ps = ps; _ret = ret;
            }

            public object Fire(object[] args)
            {
                object fallback = _ret != typeof(void) && _ret.IsValueType ? Activator.CreateInstance(_ret) : null;
                if (_g._disposed) return fallback;
                try
                {
                    object r = _sink.Invoke(Wire.EncodeArgs(args, _ps, _g));
                    return _ret == typeof(void) ? null : Wire.Decode(r, _ret, _g);
                }
                catch (Exception ex)
                {
                    _g.StubFailed(ex);
                    return fallback;
                }
            }
        }
    }
}
