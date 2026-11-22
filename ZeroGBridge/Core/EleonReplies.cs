// =====================================================================
// MODULE: ZeroGBridge/Core/EleonReplies.cs
// DESCRIPTION: 1.6.0 sends one Eleon request and waits for its answer. The game answers
//              requests later through Game_Event with the same seqNr; this file matches the
//              answer (data event, Event_Ok or Event_Error) to the waiting ZAH command.
// =====================================================================

using System;
using System.Collections.Concurrent;
using System.Linq;
using System.Threading;
using Eleon.Modding;

namespace ZeroGBridge
{
    // What came back for one request
    public sealed class EleonResult
    {
        public string Status;      // ok | error | accepted | timeout | rejected | not_available | exception
        public ushort Seq;
        public CmdId? Event;       // the event that answered (null = none)
        public object Data;        // the event's data object
        public string Error;       // ErrorType name or bridge error text
        public bool SawOk;         // Event_Ok arrived (data requests may also send it)
        public long ElapsedMs;
    }

    public static class EleonReplies
    {
        // Timeouts (ms). The game-thread wait matches the alert service; reply waits are capped
        // so one slow request never holds a ZAH connection (or a hot reload) for long.
        public const int GameThreadTimeoutMs = 500;
        public const int DefaultReplyTimeoutMs = 500;
        public const int DefaultPlayerReplyTimeoutMs = 500;
        public const int MaxReplyTimeoutMs = 500;
        public const int MinReplyTimeoutMs = 50;

        private sealed class Waiter
        {
            public EleonRequest Def;
            public ushort Seq;
            public string MatchPlayfield;   // Request_Load_Playfield: Event_Playfield_Loaded can come without our seq
            public readonly ManualResetEventSlim Done = new ManualResetEventSlim(false);
            public CmdId? Event;
            public object Data;
            public string Error;
            public volatile bool SawOk;
        }

        private static readonly ConcurrentDictionary<ushort, Waiter> Waiting = new ConcurrentDictionary<ushort, Waiter>();
        public static int WaitingCount => Waiting.Count;

        // Called from LegacyApi.OnGameEvent (game thread) for every event. Returns true when it
        // answered a waiting request. Never throws.
        public static bool Deliver(CmdId eventId, ushort seqNr, object data)
        {
            try
            {
                Waiter w = null;
                if (!Waiting.TryGetValue(seqNr, out w))
                {
                    // playfield loads: match by name when the seq is not ours
                    if (eventId == CmdId.Event_Playfield_Loaded && data is PlayfieldLoad pl)
                        w = Waiting.Values.FirstOrDefault(x => x.MatchPlayfield != null
                            && string.Equals(x.MatchPlayfield, pl.playfield, StringComparison.OrdinalIgnoreCase));
                    if (w == null) return false;
                }
                if (w.Done.IsSet) return true;

                if (eventId == CmdId.Event_Error)
                {
                    w.Event = eventId;
                    w.Data = data;
                    w.Error = (data as ErrorInfo)?.errorType.ToString() ?? "unknown";
                    w.Done.Set();
                    return true;
                }
                if (eventId == CmdId.Event_Ok && !w.Def.Replies.Contains(CmdId.Event_Ok))
                {
                    w.SawOk = true; // data request: keep waiting for the data event
                    return true;
                }
                if (w.Def.Replies.Contains(eventId))
                {
                    if (eventId == CmdId.Event_Ok) w.SawOk = true;
                    w.Event = eventId;
                    w.Data = data;
                    w.Done.Set();
                    return true;
                }
                return false; // our seq but an event we do not expect: leave it for the other handlers
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -WARN- Eleon reply match failed for {eventId} seq {seqNr}: {ex.Message}");
                return false;
            }
        }

        // Clamp a ZAH timeout_ms to the allowed range; null = default for this request
        public static int ReplyTimeout(EleonRequest def, int? asked)
        {
            int t = asked ?? (def.Wait == ReplyWait.Player ? DefaultPlayerReplyTimeoutMs : DefaultReplyTimeoutMs);
            return Math.Max(MinReplyTimeoutMs, Math.Min(MaxReplyTimeoutMs, t));
        }

        // Sends one request (on the game thread when Game_Update ticks) and waits for its answer.
        public static EleonResult Run(EleonRequest def, object param, int replyTimeoutMs)
        {
            var started = DateTime.UtcNow;
            var res = new EleonResult();
            ushort seq = LegacyApi.NextSeq();
            res.Seq = seq;
            var w = new Waiter { Def = def, Seq = seq };
            if (def.Cmd == CmdId.Request_Load_Playfield && param is PlayfieldLoad load) w.MatchPlayfield = load.playfield;

            // register first: the game may answer inside Game_Request
            Waiting[seq] = w;
            try
            {
                var sent = LegacyApi.Request(def.Cmd, param, replyTimeoutMs, seq, out string sendError, queueOnly: true);
                switch (sent)
                {
                    case LegacyApi.RequestResult.Accepted:
                        break;
                    case LegacyApi.RequestResult.NotAvailable:
                        res.Status = "not_available"; res.Error = sendError ?? "legacy API not attached"; return Finish(res, started);
                    case LegacyApi.RequestResult.Rejected:
                        res.Status = "rejected"; res.Error = sendError ?? "Game_Request returned false"; return Finish(res, started);
                    case LegacyApi.RequestResult.Timeout:
                        res.Status = "timeout"; res.Error = sendError ?? "game thread did not run the request in time"; return Finish(res, started);
                    default:
                        res.Status = "exception"; res.Error = sendError ?? "Game_Request failed"; return Finish(res, started);
                }

                int remaining = Math.Max(0, replyTimeoutMs - (int)(DateTime.UtcNow - started).TotalMilliseconds);
                bool answered = w.Done.Wait(remaining);
                res.SawOk = w.SawOk;
                if (answered)
                {
                    res.Event = w.Event;
                    res.Data = w.Data;
                    res.Error = w.Error;
                    res.Status = w.Event == CmdId.Event_Error ? "error" : w.Event == null ? "not_available" : "ok";
                }
                else if (w.SawOk)
                {
                    res.Status = "timeout";
                    res.Error = "Event_Ok arrived, but the requested data did not arrive before the deadline";
                }
                else if (def.Wait == ReplyWait.Player)
                {
                    res.Status = "accepted";      // shown to the player; the answer comes when they click
                }
                else if (def.Wait == ReplyWait.Message)
                {
                    // HUD messages: Game_Request was accepted. The game usually sends no Event_Ok
                    // or Event_Error, so a quiet timeout is not a failure. Event_Error still fails above.
                    res.Status = "ok";
                    res.Error = "sent (the game sends no confirmation for messages)";
                }
                else
                {
                    res.Status = "timeout";
                    res.Error = $"no answer from the game within {replyTimeoutMs} ms (the request was accepted)";
                }
                return Finish(res, started);
            }
            catch (Exception ex)
            {
                res.Status = "exception";
                res.Error = ex.GetType().Name + ": " + ex.Message;
                return Finish(res, started);
            }
            finally
            {
                Waiting.TryRemove(seq, out _);
            }
        }

        private static EleonResult Finish(EleonResult r, DateTime started)
        {
            r.ElapsedMs = (long)(DateTime.UtcNow - started).TotalMilliseconds;
            return r;
        }

        // Game_Exit / core stop: wake every waiting command (it then reports timeout / not_available)
        public static void CancelAll()
        {
            foreach (var kv in Waiting.ToArray())
            {
                if (Waiting.TryRemove(kv.Key, out var w) && !w.Done.IsSet)
                {
                    w.Error = "bridge core stopping";
                    w.Event = null;
                    w.Done.Set();
                }
            }
        }
    }
}
