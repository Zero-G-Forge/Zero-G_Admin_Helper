// =====================================================================
// MODULE: ZeroGBridge/Loader/Wire.cs
// DESCRIPTION: Value marshalling between the loader domain and the core AppDomain.
//
// None of the game's types (PlayerData, GlobalStructureInfo, Vector3, Mif DTOs such as IdMsgPrio,
// FactionInfoList) are [Serializable], and live objects (IPlayfield, IEntity ...) must stay where
// the game created them. So values are converted to small serializable "wire" objects:
//   primitives / string / enum  -> unchanged
//   live game object            -> HandleRef (id in the loader's handle table + its Eleon interfaces)
//   delegate (core -> game)     -> WireDelegate (MarshalByRef callback sink in the core domain)
//   dictionary / list / array   -> WireDict / WireList (elements converted)
//   any other struct or class   -> FieldBag (all instance fields, recursively)
// The same code runs on both sides; IWireSide supplies the side-specific parts.
// =====================================================================

using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Runtime.Serialization;
using ZeroGBridge.Hosting;

namespace ZeroGBridge.Hosting
{
    [Serializable]
    public sealed class HandleRef
    {
        public long Id;
        /// <summary>Assembly-qualified names of the Eleon interfaces the live object implements.</summary>
        public string[] Interfaces;
    }

    [Serializable]
    public sealed class WireDelegate
    {
        public string SinkId;
        public ICallbackSink Sink; // MarshalByRefObject: crosses by reference
    }

    [Serializable]
    public sealed class FieldBag
    {
        public string TypeAqn;
        public string[] Names;
        public object[] Values;
    }

    [Serializable]
    public sealed class WireList
    {
        public string TypeAqn;
        public object[] Items;
    }

    [Serializable]
    public sealed class WireDict
    {
        public string TypeAqn;
        public object[] Keys;
        public object[] Values;
    }

    public interface IWireSide
    {
        /// <summary>Return a HandleRef / WireDelegate for live objects, or null to use the generic rules.</summary>
        object TryEncodeLive(object value, Type declared);
        object DecodeHandle(HandleRef handle, Type expected);
        object DecodeDelegate(WireDelegate wireDelegate, Type expected);
    }

    public static class Wire
    {
        private const int MaxDepth = 24;
        private const BindingFlags InstanceFields = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;

        private static readonly Dictionary<Type, FieldInfo[]> FieldCache = new Dictionary<Type, FieldInfo[]>();
        private static readonly Dictionary<string, Type> TypeCache = new Dictionary<string, Type>();

        public static bool IsPassThrough(Type t)
        {
            if (t.IsPrimitive || t.IsEnum || t == typeof(string) || t == typeof(decimal) || t == typeof(DateTime)
                || t == typeof(TimeSpan) || t == typeof(Guid) || t == typeof(DateTimeOffset))
                return true;
            if (t.IsArray)
            {
                var e = t.GetElementType();
                return e.IsPrimitive || e.IsEnum || e == typeof(string);
            }
            return false;
        }

        /// <summary>True for interfaces from the game's modding assemblies (ModApi.dll, Mif.dll, Eleon.* namespaces).</summary>
        public static bool IsGameInterface(Type t)
        {
            if (t == null || !t.IsInterface) return false;
            if (t.IsGenericType) return false;
            string ns = t.Namespace ?? "";
            string asm = t.Assembly.GetName().Name;
            return ns.StartsWith("Eleon", StringComparison.Ordinal) || asm == "ModApi" || asm == "Mif";
        }

        private static readonly Dictionary<Type, string[]> IfaceCache = new Dictionary<Type, string[]>();

        /// <summary>Eleon interfaces implemented by a runtime type (empty for data objects).</summary>
        public static string[] GameInterfacesOf(Type t)
        {
            lock (IfaceCache)
            {
                if (IfaceCache.TryGetValue(t, out var cached)) return cached;
                var list = t.GetInterfaces().Where(IsGameInterface).Select(i => i.AssemblyQualifiedName).ToArray();
                IfaceCache[t] = list;
                return list;
            }
        }

        public static Type ResolveType(string aqn)
        {
            if (string.IsNullOrEmpty(aqn)) return null;
            lock (TypeCache)
            {
                if (TypeCache.TryGetValue(aqn, out var t)) return t;
                t = Type.GetType(aqn, false);
                if (t == null)
                {
                    // fall back to already loaded assemblies by simple name (LoadFrom contexts)
                    try
                    {
                        string typeName = aqn.Split(',')[0].Trim();
                        foreach (var a in AppDomain.CurrentDomain.GetAssemblies())
                        {
                            t = a.GetType(typeName, false);
                            if (t != null) break;
                        }
                        if (t == null && aqn.Contains("[")) t = ResolveGenericByName(aqn);
                    }
                    catch { t = null; }
                }
                if (t != null) TypeCache[aqn] = t;
                return t;
            }
        }

        private static Type ResolveGenericByName(string aqn)
        {
            // Type.GetType with an assembly resolver that matches by simple name
            return Type.GetType(aqn,
                an => AppDomain.CurrentDomain.GetAssemblies().FirstOrDefault(a => a.GetName().Name == an.Name),
                (a, n, ic) => a != null ? a.GetType(n, false, ic) : Type.GetType(n, false, ic),
                false);
        }

        private static FieldInfo[] FieldsOf(Type t)
        {
            lock (FieldCache)
            {
                if (FieldCache.TryGetValue(t, out var f)) return f;
                var list = new List<FieldInfo>();
                for (var c = t; c != null && c != typeof(object) && c != typeof(ValueType); c = c.BaseType)
                    list.AddRange(c.GetFields(InstanceFields).Where(x => !x.IsLiteral && !x.FieldType.IsPointer));
                f = list.ToArray();
                FieldCache[t] = f;
                return f;
            }
        }

        public static Type ElementTypeOf(Type t)
        {
            if (t == null) return typeof(object);
            if (t.IsArray) return t.GetElementType();
            var ie = t.IsGenericType && t.GetGenericTypeDefinition() == typeof(IEnumerable<>) ? t
                : t.GetInterfaces().FirstOrDefault(i => i.IsGenericType && i.GetGenericTypeDefinition() == typeof(IEnumerable<>));
            return ie != null ? ie.GetGenericArguments()[0] : typeof(object);
        }

        public static bool TryDictTypes(Type t, out Type key, out Type value)
        {
            key = value = typeof(object);
            if (t == null) return false;
            var candidates = new List<Type>();
            if (t.IsInterface) candidates.Add(t);
            candidates.AddRange(t.GetInterfaces());
            foreach (var i in candidates)
            {
                if (!i.IsGenericType) continue;
                var g = i.GetGenericTypeDefinition();
                if (g == typeof(IDictionary<,>) || g == typeof(IReadOnlyDictionary<,>))
                {
                    var a = i.GetGenericArguments();
                    key = a[0]; value = a[1];
                    return true;
                }
            }
            return typeof(IDictionary).IsAssignableFrom(t);
        }

        // ------------------------------------------------------------------ encode

        public static object Encode(object value, Type declared, IWireSide side, int depth = 0)
        {
            if (value == null) return null;
            if (depth > MaxDepth) throw new InvalidOperationException("Wire: object graph too deep (cycle?)");
            Type t = value.GetType();
            if (IsPassThrough(t)) return value;
            if (value is HandleRef || value is WireDelegate || value is FieldBag || value is WireList || value is WireDict) return value;

            var live = side?.TryEncodeLive(value, declared);
            if (live != null) return live;

            if (value is Delegate) throw new NotSupportedException("Wire: delegates can only be passed from the core to the game");
            if (value is MarshalByRefObject) return value; // crosses by reference

            if (value is IDictionary dict)
            {
                TryDictTypes(t, out var kt, out var vt);
                var keys = new List<object>();
                var vals = new List<object>();
                foreach (DictionaryEntry e in dict)
                {
                    keys.Add(Encode(e.Key, kt, side, depth + 1));
                    vals.Add(Encode(e.Value, vt, side, depth + 1));
                }
                return new WireDict { TypeAqn = t.AssemblyQualifiedName, Keys = keys.ToArray(), Values = vals.ToArray() };
            }
            if (value is IEnumerable seq && !(value is string))
            {
                var et = ElementTypeOf(t);
                if (et == typeof(object)) et = ElementTypeOf(declared);
                var items = new List<object>();
                foreach (var item in seq) items.Add(Encode(item, et, side, depth + 1));
                return new WireList { TypeAqn = t.AssemblyQualifiedName, Items = items.ToArray() };
            }

            var fields = FieldsOf(t);
            var bag = new FieldBag { TypeAqn = t.AssemblyQualifiedName, Names = new string[fields.Length], Values = new object[fields.Length] };
            for (int i = 0; i < fields.Length; i++)
            {
                bag.Names[i] = fields[i].DeclaringType.Name + "." + fields[i].Name;
                bag.Values[i] = Encode(fields[i].GetValue(value), fields[i].FieldType, side, depth + 1);
            }
            return bag;
        }

        public static object[] EncodeArgs(object[] args, ParameterInfo[] ps, IWireSide side)
        {
            if (args == null) return new object[0];
            var r = new object[args.Length];
            for (int i = 0; i < args.Length; i++)
                r[i] = Encode(args[i], i < ps.Length ? ps[i].ParameterType : typeof(object), side);
            return r;
        }

        // ------------------------------------------------------------------ decode

        public static object Decode(object wire, Type expected, IWireSide side, int depth = 0)
        {
            if (expected == null || expected == typeof(void)) expected = typeof(object);
            if (expected.IsByRef) expected = expected.GetElementType();
            if (wire == null)
            {
                if (expected.IsValueType && Nullable.GetUnderlyingType(expected) == null) return Activator.CreateInstance(expected);
                return null;
            }
            if (depth > MaxDepth) throw new InvalidOperationException("Wire: object graph too deep");

            switch (wire)
            {
                case HandleRef h:
                    return side != null ? side.DecodeHandle(h, expected) : throw new InvalidOperationException("Wire: no side for HandleRef");
                case WireDelegate d:
                    return side?.DecodeDelegate(d, expected);
                case FieldBag bag:
                    return DecodeBag(bag, side, depth);
                case WireList list:
                    return DecodeList(list, expected, side, depth);
                case WireDict dict:
                    return DecodeDict(dict, expected, side, depth);
            }
            return wire;
        }

        public static object[] DecodeArgs(object[] wireArgs, ParameterInfo[] ps, IWireSide side)
        {
            var r = new object[ps.Length];
            for (int i = 0; i < ps.Length; i++)
                r[i] = Decode(wireArgs != null && i < wireArgs.Length ? wireArgs[i] : null, ps[i].ParameterType, side);
            return r;
        }

        private static object DecodeBag(FieldBag bag, IWireSide side, int depth)
        {
            Type t = ResolveType(bag.TypeAqn) ?? throw new InvalidOperationException("Wire: type not found: " + bag.TypeAqn);
            object obj = FormatterServices.GetUninitializedObject(t); // boxed for structs; SetValue writes into the box
            var fields = FieldsOf(t);
            var byName = new Dictionary<string, FieldInfo>();
            foreach (var f in fields) byName[f.DeclaringType.Name + "." + f.Name] = f;
            for (int i = 0; i < bag.Names.Length; i++)
            {
                if (!byName.TryGetValue(bag.Names[i], out var f)) continue; // field removed in this build: skip
                f.SetValue(obj, Decode(bag.Values[i], f.FieldType, side, depth + 1));
            }
            return obj;
        }

        private static bool IsConstructibleCollection(Type t)
        {
            return t != null && !t.IsAbstract && !t.IsInterface && t.IsPublic && !t.IsArray
                   && t.GetConstructor(Type.EmptyTypes) != null;
        }

        private static object DecodeList(WireList list, Type expected, IWireSide side, int depth)
        {
            Type rt = ResolveType(list.TypeAqn);
            Type target = null;
            if (rt != null && rt.IsArray) target = rt;
            else if (rt != null && IsConstructibleCollection(rt) && expected.IsAssignableFrom(rt) && rt.GetMethod("Add", new[] { ElementTypeOf(rt) }) != null) target = rt;
            else if (expected.IsArray) target = expected;
            else if (IsConstructibleCollection(expected) && expected.GetMethod("Add", new[] { ElementTypeOf(expected) }) != null) target = expected;
            else target = typeof(List<>).MakeGenericType(ElementTypeOf(expected) != typeof(object) ? ElementTypeOf(expected) : (rt != null ? ElementTypeOf(rt) : typeof(object)));

            Type et = ElementTypeOf(target);
            if (target.IsArray)
            {
                var arr = Array.CreateInstance(et, list.Items.Length);
                for (int i = 0; i < list.Items.Length; i++) arr.SetValue(Decode(list.Items[i], et, side, depth + 1), i);
                return arr;
            }
            object coll = Activator.CreateInstance(target);
            var add = target.GetMethod("Add", new[] { et });
            foreach (var item in list.Items) add.Invoke(coll, new[] { Decode(item, et, side, depth + 1) });
            return coll;
        }

        private static object DecodeDict(WireDict wd, Type expected, IWireSide side, int depth)
        {
            Type rt = ResolveType(wd.TypeAqn);
            Type target;
            if (rt != null && IsConstructibleCollection(rt) && expected.IsAssignableFrom(rt) && typeof(IDictionary).IsAssignableFrom(rt)) target = rt;
            else if (IsConstructibleCollection(expected) && typeof(IDictionary).IsAssignableFrom(expected)) target = expected;
            else
            {
                TryDictTypes(expected, out var ek, out var ev);
                if (ek == typeof(object) && ev == typeof(object) && rt != null) TryDictTypes(rt, out ek, out ev);
                target = typeof(Dictionary<,>).MakeGenericType(ek, ev);
            }
            TryDictTypes(target, out var kt, out var vt);
            var d = (IDictionary)Activator.CreateInstance(target);
            for (int i = 0; i < wd.Keys.Length; i++)
                d[Decode(wd.Keys[i], kt, side, depth + 1)] = Decode(wd.Values[i], vt, side, depth + 1);
            return d;
        }
    }
}
