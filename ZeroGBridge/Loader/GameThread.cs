// =====================================================================
// MODULE: ZeroGBridge/Loader/GameThread.cs
// DESCRIPTION: Runs loader work (core activation) on the game main thread when the game is ticking.
// =====================================================================

using System;
using System.Collections.Concurrent;
using System.Threading;

namespace ZeroGBridge.Hosting
{
    public sealed class GameThread
    {
        private sealed class Work
        {
            public Action Action;
            public int Claimed;
            public Exception Error;
            public readonly ManualResetEventSlim Done = new ManualResetEventSlim(false);
        }

        private readonly ConcurrentQueue<Work> _queue = new ConcurrentQueue<Work>();
        private long _lastTickTicks;
        private volatile int _threadId;

        public int ThreadId => _threadId;
        public bool IsTicking
        {
            get
            {
                long last = Interlocked.Read(ref _lastTickTicks);
                return last != 0 && DateTime.UtcNow.Ticks - last < TimeSpan.TicksPerSecond;
            }
        }
        public bool OnGameThread => _threadId != 0 && Thread.CurrentThread.ManagedThreadId == _threadId;

        /// <summary>Called from Game_Update / Application.Update.</summary>
        public void Tick()
        {
            _threadId = Thread.CurrentThread.ManagedThreadId;
            Interlocked.Exchange(ref _lastTickTicks, DateTime.UtcNow.Ticks);
            int budget = 4;
            while (budget-- > 0 && _queue.TryDequeue(out var w))
            {
                if (Interlocked.CompareExchange(ref w.Claimed, 1, 0) != 0) continue;
                try { w.Action(); } catch (Exception ex) { w.Error = ex; }
                w.Done.Set();
            }
        }

        /// <summary>
        /// Runs the action on the game thread when it is ticking (waits up to timeoutMs), otherwise
        /// on the calling thread. Returns where it ran ("game" or "caller").
        /// </summary>
        public string Run(Action action, int timeoutMs)
        {
            if (OnGameThread || !IsTicking)
            {
                action();
                return OnGameThread ? "game" : "caller";
            }
            var w = new Work { Action = action };
            _queue.Enqueue(w);
            if (!w.Done.Wait(timeoutMs) && Interlocked.CompareExchange(ref w.Claimed, 1, 0) == 0)
            {
                HostLog.Write("[ZGB] -WARN- Game thread did not pick up the core swap in time; running it on the caller thread.");
                action();
                return "caller";
            }
            w.Done.Wait();
            if (w.Error != null) throw new InvalidOperationException("Swap failed on the game thread: " + w.Error.Message, w.Error);
            return "game";
        }
    }
}
