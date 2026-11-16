// =====================================================================
// MODULE: ZeroGBridge/Loader/HostAdapter.cs
// DESCRIPTION: IBridgeHost given to a core (MarshalByRef, so it works across domains).
// =====================================================================

using System;

namespace ZeroGBridge.Hosting
{
    public sealed class HostAdapter : MarshalByRefObject, IBridgeHost
    {
        public HostAdapter(IClientHub clients, IGameGateway gateway, string modDirectory, string loaderRelease)
        {
            Clients = clients;
            Gateway = gateway;
            ModDirectory = modDirectory;
            LoaderRelease = loaderRelease;
        }

        public override object InitializeLifetimeService() => null;

        public void Log(string message) => HostLog.Write(message);
        public IClientHub Clients { get; }
        public IGameGateway Gateway { get; }
        public string ModDirectory { get; }
        public string LoaderRelease { get; }
    }
}
