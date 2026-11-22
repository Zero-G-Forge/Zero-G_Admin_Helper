// =====================================================================
// MODULE: ZeroGBridge/Network/ChatLog.cs
// DESCRIPTION: 1.6.3 READ-ONLY chat history for ZAH (core only, hot-swappable on the 1.5.0 loader).
//   chat:recent                      -> the newest messages (up to 200)
//   chat:recent:{"since":N,"max":M}  -> only messages with seq greater than N (M up to 500)
// The core fills the history from the API v2 Application.ChatMessageSent event (ModMain.OnChatMessageSent).
// It keeps the last 500 messages in memory only: nothing is written to disk, and a reload starts empty.
// Sending chat is NOT done here; ZAH sends with the existing con:say / msg: / msgfaction: commands.
// =====================================================================

using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace ZeroGBridge
{
    public static class ChatLog
    {
        #region Constants

        // Prefix of the chat command line.
        public const string Prefix = "chat:";

        // Messages kept in memory (oldest drop off first).
        public const int MaxKept = 500;

        // Messages sent back when ZAH does not ask for a number.
        public const int DefaultMax = 200;

        #endregion

        #region State

        // One message as ZAH sees it. Field names are the JSON keys.
        public sealed class ChatEntry
        {
            public long seq;
            public string time;            // UTC, ISO 8601
            public string channel;         // Global, Faction, Alliance, SinglePlayer, Server
            public string senderType;      // Player, ServerPrio, ServerInfo, ...
            public int senderId;           // entity id of the sender (0 for the server)
            public string senderName;      // name override from the game, when it sends one
            public int senderFactionId;
            public int recipientId;
            public int recipientFactionId;
            public string text;
        }

        // The history and the next number. The lock keeps the game thread and the network thread apart.
        private static readonly LinkedList<ChatEntry> Entries = new LinkedList<ChatEntry>();
        private static readonly object Gate = new object();
        private static long _nextSeq = 1;

        #endregion

        #region Adding

        // Called for every chat line the game reports. Never throws (a bad line is only skipped).
        public static void Add(string channel, string senderType, int senderId, string senderName,
            int senderFactionId, int recipientId, int recipientFactionId, string text)
        {
            try
            {
                var entry = new ChatEntry
                {
                    time = DateTime.UtcNow.ToString("o"),
                    channel = channel ?? "Unknown",
                    senderType = senderType ?? "Unknown",
                    senderId = senderId,
                    senderName = senderName ?? "",
                    senderFactionId = senderFactionId,
                    recipientId = recipientId,
                    recipientFactionId = recipientFactionId,
                    text = text ?? ""
                };
                lock (Gate)
                {
                    entry.seq = _nextSeq++;
                    Entries.AddLast(entry);
                    while (Entries.Count > MaxKept) Entries.RemoveFirst();
                }
            }
            catch { }
        }

        #endregion

        #region Command

        public static bool IsChatLine(string lowerCmd) => lowerCmd != null && lowerCmd.StartsWith(Prefix);

        // Answers chat:recent with one CHAT_LOG line; anything else under chat: gets an ERROR line.
        public static string Handle(string cleanCmd)
        {
            try
            {
                string rest = cleanCmd.Substring(Prefix.Length).Trim();
                string sub = rest;
                string args = "";
                int colon = rest.IndexOf(':');
                if (colon >= 0) { sub = rest.Substring(0, colon); args = rest.Substring(colon + 1).Trim(); }
                if (!string.Equals(sub, "recent", StringComparison.OrdinalIgnoreCase))
                    return JsonConvert.SerializeObject(new { type = "ERROR", code = "unknown_command", message = "Only chat:recent exists." });

                long since = 0;
                int max = DefaultMax;
                if (args.Length > 0)
                {
                    JObject body;
                    try { body = JObject.Parse(args); }
                    catch { return JsonConvert.SerializeObject(new { type = "ERROR", code = "bad_json", message = "chat:recent expects {\"since\":N,\"max\":M}." }); }
                    if (body["since"]?.Type == JTokenType.Integer) since = Math.Max(0, (long)body["since"]);
                    if (body["max"]?.Type == JTokenType.Integer) max = Math.Max(1, Math.Min(MaxKept, (int)body["max"]));
                }

                List<ChatEntry> picked;
                long next;
                lock (Gate)
                {
                    picked = Entries.Where(e => e.seq > since).ToList();
                    next = _nextSeq - 1;
                }
                if (picked.Count > max) picked = picked.Skip(picked.Count - max).ToList();
                return JsonConvert.SerializeObject(new
                {
                    type = "CHAT_LOG",
                    ok = true,
                    count = picked.Count,
                    last_seq = next,
                    kept = MaxKept,
                    messages = picked,
                    timestamp = DateTime.UtcNow.ToString("dd-HH:mm:ss")
                });
            }
            catch (Exception ex)
            {
                return JsonConvert.SerializeObject(new { type = "ERROR", code = "exception", message = "chat failed: " + ex.Message });
            }
        }

        #endregion
    }
}
