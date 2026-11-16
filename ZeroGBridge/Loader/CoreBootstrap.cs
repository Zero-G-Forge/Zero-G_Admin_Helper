// =====================================================================
// MODULE: ZeroGBridge/Loader/CoreBootstrap.cs
// DESCRIPTION: Runs inside a new core AppDomain. Sets up assembly resolution (the game's Managed
//              folder is not under the domain's ApplicationBase) and loads the core DLL from its
//              immutable versions/ copy. Keep this class free of game types in its signatures:
//              it is created before the resolver exists.
// =====================================================================

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;

namespace ZeroGBridge.Hosting
{
    public sealed class CoreBootstrap : MarshalByRefObject
    {
        private Dictionary<string, string> _probe = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        private string[] _probeDirs = new string[0];

        public override object InitializeLifetimeService() => null;

        public void Init(Dictionary<string, string> probe, string[] probeDirs, string configPathOverride)
        {
            _probe = new Dictionary<string, string>(probe ?? new Dictionary<string, string>(), StringComparer.OrdinalIgnoreCase);
            _probeDirs = probeDirs ?? new string[0];
            AppDomain.CurrentDomain.AssemblyResolve += Resolve;
            if (!string.IsNullOrEmpty(configPathOverride)) SetConfigOverride(configPathOverride);
        }

        // separate method so AuthConfig (Newtonsoft) is only touched after the resolver is in place
        private static void SetConfigOverride(string path) { AuthConfig.ConfigPathOverride = path; }

        private Assembly Resolve(object sender, ResolveEventArgs e)
        {
            string name = new AssemblyName(e.Name).Name;
            var loaded = AppDomain.CurrentDomain.GetAssemblies().FirstOrDefault(a => !a.IsDynamic && a.GetName().Name == name);
            if (loaded != null) return loaded;
            if (_probe.TryGetValue(name, out var path) && File.Exists(path)) return Assembly.LoadFrom(path);
            foreach (var dir in _probeDirs)
            {
                string p = Path.Combine(dir, name + ".dll");
                if (File.Exists(p)) return Assembly.LoadFrom(p);
            }
            return null;
        }

        public IBridgeCore LoadCore(string corePath)
        {
            var asm = Assembly.LoadFrom(corePath);
            var type = asm.GetTypes().FirstOrDefault(t => typeof(IBridgeCore).IsAssignableFrom(t) && !t.IsAbstract && t.IsClass);
            if (type == null) throw new InvalidOperationException("No IBridgeCore implementation in " + Path.GetFileName(corePath));
            return (IBridgeCore)Activator.CreateInstance(type);
        }

        public string DomainName => AppDomain.CurrentDomain.FriendlyName;
    }
}
