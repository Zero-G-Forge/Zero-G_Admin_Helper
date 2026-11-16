// =====================================================================
// MODULE: ZeroGBridge/Loader/Contracts.cs
// DESCRIPTION: Interfaces between the stable loader (ZeroGBridge.dll) and the reloadable core
//              (Core/ZeroGBridge.Core.dll). Both sides load this assembly, so the types match
//              inside the core AppDomain too. Changing these needs a loader update (server restart).
// =====================================================================

using System;
using Eleon.Modding;

namespace ZeroGBridge.Hosting
{
    public static class HotContract
    {
        /// <summary>Bump when IBridgeCore / IBridgeHost / IGameGateway change. The loader refuses a core with another value.</summary>
        public const int Version = 1;

        /// <summary>File name of the core DLL in Core/ (boot copy) and Updates/ (drop folder).</summary>
        public const string CoreFileName = "ZeroGBridge.Core.dll";
    }

    /// <summary>Connected ZAH clients. Implemented by the loader's BridgeListener (owns the TCP port).</summary>
    public interface IClientHub
    {
        bool HasActiveConnections { get; }
        /// <summary>Incremented on every successful auth (the broadcaster sends the roster to new clients).</summary>
        int AuthGeneration { get; }
        void BroadcastJson(string jsonPayload, string exceptClientId);
    }

    /// <summary>
    /// Game API access for the core. In AppDomain mode this is the loader's broker: live game objects
    /// (IModApi, IPlayfield, IEntity ...) stay in the loader domain and the core gets proxies.
    /// Values cross as Wire objects (see Wire.cs). Calls run on the caller's thread (no thread hop),
    /// so a call made from Game_Update / Application.Update still runs on the game thread.
    /// </summary>
    public interface IGameGateway
    {
        /// <summary>True when core and loader share one domain (objects pass through unchanged).</summary>
        bool Passthrough { get; }
        /// <summary>"modapi" (IModApi) or "legacy" (ModGameAPI, null until Game_Start). Returns a Wire value.</summary>
        object GetRoot(string name);
        /// <summary>Invoke an interface member on a live game object. Arguments and result are Wire values.</summary>
        object Invoke(long handle, string declaringTypeAqn, int metadataToken, object[] wireArgs);
        /// <summary>Release handles the core no longer references (id, number of times the core received it).</summary>
        void Release(long[] handles, int[] counts);
    }

    /// <summary>Callback object living in the core domain (delegates the core hands to the game).</summary>
    public interface ICallbackSink
    {
        string Id { get; }
        object Invoke(object[] wireArgs);
    }

    /// <summary>What the loader offers the core.</summary>
    public interface IBridgeHost
    {
        void Log(string message);
        IClientHub Clients { get; }
        IGameGateway Gateway { get; }
        /// <summary>Mod folder (where ZeroGBridge.dll and ZeroGBridge.json live).</summary>
        string ModDirectory { get; }
        string LoaderRelease { get; }
    }

    /// <summary>
    /// The reloadable bridge core. One instance per load. Lifecycle:
    /// SelfTest (not active yet) -> Start -> [AttachLegacy] -> GameUpdate/GameEvent/HandleLine ... -> Stop.
    /// </summary>
    public interface IBridgeCore
    {
        int ContractVersion { get; }
        /// <summary>Human release, e.g. "1.5.0".</summary>
        string CoreRelease { get; }
        /// <summary>Assembly version Major.Minor.MMDD.HHmm.</summary>
        string CoreAssemblyVersion { get; }

        /// <summary>Checks the core can run here without starting anything. Throws or returns an error text on failure, null when OK.</summary>
        string SelfTest();

        /// <summary>Equivalent of the old ModMain.Init without the TCP listener (the loader owns it).</summary>
        void Start(IBridgeHost host);

        /// <summary>
        /// Attach the legacy ModGameAPI (host.Gateway root "legacy"). onGameStart=true when called from
        /// Empyrion's Game_Start (game thread, faction request goes out at once); false after a reload
        /// (the request is only marked pending and goes out on the next Game_Update).
        /// </summary>
        void AttachLegacy(bool onGameStart);

        void GameUpdate();
        void GameEvent(CmdId eventId, ushort seqNr, object wireData);
        void GameExit();

        /// <summary>One authenticated line (command or alert:) -> one reply line (or null).</summary>
        string HandleLine(string clientId, string line);

        /// <summary>Small JSON object with core health numbers (for hot:status and tests).</summary>
        string Diagnostics();

        /// <summary>Stop threads/timers and unhook game events. The core must not run anything after this.</summary>
        void Stop();
    }
}
