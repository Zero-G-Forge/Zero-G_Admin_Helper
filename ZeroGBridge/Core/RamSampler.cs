// =====================================================================
// MODULE: ZeroGBridge/Core/RamSampler.cs
// DESCRIPTION: Process memory reading that works under Empyrion's runtime
// =====================================================================

using System;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace ZeroGBridge
{
    public struct RamSample
    {
        public long Bytes;
        public string Source; // "psapi" | "private" | "heap" | "none"
    }

    /// <summary>
    /// Process.WorkingSet64 returns 0 under the runtime the Empyrion dedicated
    /// server uses on Windows, so METRIC ram read "0MB". Order tried:
    ///   1. psapi GetProcessMemoryInfo (Windows working set)
    ///   2. Process.PrivateMemorySize64
    ///   3. GC heap (GC.GetTotalMemory) as a last resort
    /// The first non-zero value wins; Source says which one it was.
    /// </summary>
    public static class RamSampler
    {
        [StructLayout(LayoutKind.Sequential)]
        private struct PROCESS_MEMORY_COUNTERS
        {
            public uint cb;
            public uint PageFaultCount;
            public UIntPtr PeakWorkingSetSize;
            public UIntPtr WorkingSetSize;
            public UIntPtr QuotaPeakPagedPoolUsage;
            public UIntPtr QuotaPagedPoolUsage;
            public UIntPtr QuotaPeakNonPagedPoolUsage;
            public UIntPtr QuotaNonPagedPoolUsage;
            public UIntPtr PagefileUsage;
            public UIntPtr PeakPagefileUsage;
        }

        [DllImport("psapi.dll", SetLastError = true)]
        private static extern bool GetProcessMemoryInfo(IntPtr hProcess, out PROCESS_MEMORY_COUNTERS counters, uint size);

        [DllImport("kernel32.dll")]
        private static extern IntPtr GetCurrentProcess();

        // Once psapi throws (non-Windows, missing DLL) it is not retried.
        private static bool _psapiUnavailable = !IsWindows();

        private static bool IsWindows()
        {
            try { return Environment.OSVersion.Platform == PlatformID.Win32NT; }
            catch { return false; }
        }

        public static long ReadPsapiWorkingSet()
        {
            if (_psapiUnavailable) return 0;
            try
            {
                PROCESS_MEMORY_COUNTERS c;
                uint size = (uint)Marshal.SizeOf(typeof(PROCESS_MEMORY_COUNTERS));
                if (GetProcessMemoryInfo(GetCurrentProcess(), out c, size))
                {
                    return (long)c.WorkingSetSize.ToUInt64();
                }
            }
            catch
            {
                _psapiUnavailable = true;
            }
            return 0;
        }

        public static long ReadPrivateBytes(Process process)
        {
            try
            {
                if (process == null) return 0;
                return process.PrivateMemorySize64;
            }
            catch { return 0; }
        }

        public static long ReadHeapBytes()
        {
            try { return GC.GetTotalMemory(false); }
            catch { return 0; }
        }

        public static RamSample Sample(Process process)
        {
            return Sample(ReadPsapiWorkingSet, () => ReadPrivateBytes(process), ReadHeapBytes);
        }

        /// <summary>Pure fallback chain; readers are injectable for tests.</summary>
        public static RamSample Sample(Func<long> psapi, Func<long> privateBytes, Func<long> heap)
        {
            long v = SafeRead(psapi);
            if (v > 0) return new RamSample { Bytes = v, Source = "psapi" };
            v = SafeRead(privateBytes);
            if (v > 0) return new RamSample { Bytes = v, Source = "private" };
            v = SafeRead(heap);
            if (v > 0) return new RamSample { Bytes = v, Source = "heap" };
            return new RamSample { Bytes = 0, Source = "none" };
        }

        private static long SafeRead(Func<long> f)
        {
            if (f == null) return 0;
            try { return f(); } catch { return 0; }
        }

        public static string FormatMb(long bytes)
        {
            return (bytes / (1024 * 1024)).ToString() + "MB";
        }
    }
}
