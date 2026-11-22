// Stand-ins for the few game types ServerFiles.cs touches, so the test runs without ModApi.dll.

using System;

namespace Eleon.Modding
{
    public enum AppFolder { Root, Content, SaveGame, Mod, ActiveScenario, Cache, Dedicated }

    public interface IApplication
    {
        string GetPathFor(AppFolder folder);
    }

    public interface IModApi
    {
        IApplication Application { get; }
    }
}

namespace ZeroGBridge
{
    // Same call shape as the real ZgbLog; the test prints nothing unless a failure needs the detail.
    public static class ZgbLog
    {
        public static void Write(string message) { }
    }

    // Stand-in for the loader's AuthConfig: only the FileWritesEnabled switch is used by ServerFileWrites.cs.
    public static class AuthConfig
    {
        public static bool WritesOff;
        public static bool GetBool(string key, bool fallback) => key == "FileWritesEnabled" ? !WritesOff : fallback;
    }
}
