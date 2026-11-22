// =====================================================================
// MODULE: ZeroGBridge/Core/EleonRequests.cs
// DESCRIPTION: 1.6.0 table of every legacy Eleon.Modding request (Mif.dll CmdId.Request_*):
//              the param type the game expects, the event(s) it answers with, and whether it
//              changes the server. Param objects are built from JSON by their real field names.
// =====================================================================

using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using Eleon.Modding;
using Newtonsoft.Json.Linq;

namespace ZeroGBridge
{
    // How long a request normally waits for its answer
    public enum ReplyWait
    {
        Data,    // a data event (Event_Player_Info ...) or Event_Error
        Ok,      // Event_Ok or Event_Error
        Player,  // the answer comes when a player clicks (dialog / item exchange): short wait, then "accepted"
        Message  // HUD messages: the game often sends no event; accepted with no answer is success, Event_Error is still a failure
    }

    public sealed class EleonRequest
    {
        public string Name;              // "Request_Player_Info"
        public CmdId Cmd;
        public Type ParamType;           // null = no param (data = null)
        public string[] Required = new string[0];          // field names that must be given
        public Dictionary<string, string> KeyAliases = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase); // friendly key -> field
        public Dictionary<string, object> Defaults = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);   // field -> default
        public CmdId[] Replies = new CmdId[0];             // events that answer it (besides Event_Error)
        public ReplyWait Wait = ReplyWait.Data;
        public bool ChangesServer;
        public bool VisibleToPlayers;    // shows something to players (messages, dialogs)
        public bool OnRaysList;          // one of the 29 requests on Ray's list
        public string[] ShortNames = new string[0];
        public string Description;
        public string Note;              // known limits

        public object ToJson() => new
        {
            name = Name,
            cmd_id = (int)Cmd,
            short_names = ShortNames,
            param_type = ParamType?.Name,
            param_fields = ParamType == null ? new string[0] : EleonRequests.FieldNames(ParamType),
            required = Required,
            key_aliases = KeyAliases,
            replies = Replies.Select(r => r.ToString()).ToArray(),
            wait = Wait.ToString().ToLowerInvariant(),
            changes_server = ChangesServer,
            visible_to_players = VisibleToPlayers,
            on_rays_list = OnRaysList,
            description = Description,
            note = Note
        };
    }

    // Thrown when ZAH sent params the request cannot use (reply status "bad_params")
    public sealed class BadParamsException : Exception
    {
        public BadParamsException(string message) : base(message) { }
    }

    public static class EleonRequests
    {
        private static readonly List<EleonRequest> _all = new List<EleonRequest>();
        private static readonly Dictionary<string, EleonRequest> _byName = new Dictionary<string, EleonRequest>(StringComparer.OrdinalIgnoreCase);

        public static IReadOnlyList<EleonRequest> All => _all;

        // Keys every request accepts that are not param fields
        internal static readonly HashSet<string> ControlKeys = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "req_id", "timeout_ms" };

        static EleonRequests()
        {
            var ok = new[] { CmdId.Event_Ok };
            // ---- Ray's 29 requests (Eleon.Modding.CmdId wiki list) ----
            Add("Request_Player_List", null, new[] { CmdId.Event_Player_List }, ray: true, shortNames: new[] { "players" },
                desc: "Entity ids of the players (Event_Player_List = IdList).");
            Add("Request_Player_Info", typeof(Id), new[] { CmdId.Event_Player_Info }, ray: true, req: new[] { "id" }, shortNames: new[] { "playerinfo", "pinfo" },
                desc: "Full info for one player by entity id (Event_Player_Info = PlayerInfo).");
            Add("Request_Player_SetPlayerInfo", typeof(PlayerInfoSet), new[] { CmdId.Event_Player_Info, CmdId.Event_Ok }, ray: true, changes: true, req: new[] { "entityId" }, alias: new[] { "id=entityId" }, wait: ReplyWait.Ok,
                desc: "Sets start playfield, health, stamina, food, oxygen, xp, faction ... (only the fields you send).",
                note: "Answer event not documented; Event_Ok assumed.");
            Add("Request_Player_GetInventory", typeof(Id), new[] { CmdId.Event_Player_Inventory }, ray: true, req: new[] { "id" }, shortNames: new[] { "getinv", "getinventory", "inventory" },
                desc: "Toolbar and bag of one player (Event_Player_Inventory = Inventory).");
            Add("Request_Player_SetInventory", typeof(Inventory), new[] { CmdId.Event_Player_Inventory, CmdId.Event_Ok }, ray: true, changes: true, req: new[] { "playerId" },
                alias: new[] { "id=playerId", "toolbar=toolbelt" }, desc: "Replaces a player's toolbelt and bag (ItemStack lists).");
            Add("Request_Player_AddItem", typeof(IdItemStack), ok, ray: true, changes: true, req: new[] { "id", "itemStack" }, alias: new[] { "item=itemStack" }, wait: ReplyWait.Ok,
                shortNames: new[] { "additem" }, desc: "Adds one item stack to a player: {\"id\":player,\"item\":{\"id\":itemId,\"count\":n}}.");
            Add("Request_Player_ItemExchange", typeof(ItemExchangeInfo), new[] { CmdId.Event_Player_ItemExchange }, ray: true, changes: true, visible: true, req: new[] { "id" },
                alias: new[] { "description=desc", "button=buttonText" }, wait: ReplyWait.Player,
                desc: "Opens the item exchange window for a player; the answer comes when the player closes it.");
            Add("Request_Player_Credits", typeof(Id), new[] { CmdId.Event_Player_Credits }, ray: true, req: new[] { "id" }, shortNames: new[] { "credits", "getcredits" },
                desc: "Credits of one player (Event_Player_Credits = IdCredits).");
            Add("Request_Player_SetCredits", typeof(IdCredits), new[] { CmdId.Event_Player_Credits, CmdId.Event_Ok }, ray: true, changes: true, req: new[] { "id", "credits" },
                alias: new[] { "amount=credits" }, shortNames: new[] { "setcredits" }, desc: "Sets a player's credits.");
            Add("Request_Player_AddCredits", typeof(IdCredits), new[] { CmdId.Event_Player_Credits, CmdId.Event_Ok }, ray: true, changes: true, req: new[] { "id", "credits" },
                alias: new[] { "amount=credits" }, shortNames: new[] { "addcredits" }, desc: "Adds (or with a negative amount removes) credits.");
            Add("Request_Player_ChangePlayerfield", typeof(IdPlayfieldPositionRotation), ok, ray: true, changes: true, req: new[] { "id", "playfield", "pos" }, wait: ReplyWait.Ok,
                desc: "Moves a player to another playfield at pos/rot.");
            Add("Request_Blueprint_Finish", typeof(Id), ok, ray: true, changes: true, req: new[] { "id" }, wait: ReplyWait.Ok,
                desc: "Finishes the blueprint the player is building in the factory.");
            Add("Request_Blueprint_Resources", typeof(BlueprintResources), ok, ray: true, changes: true, req: new[] { "PlayerId" },
                alias: new[] { "id=PlayerId", "items=ItemStacks" }, wait: ReplyWait.Ok, desc: "Puts resources into the player's factory.");
            Add("Request_NewEntityId", null, new[] { CmdId.Event_NewEntityId }, ray: true, changes: true, desc: "Reserves a new entity id (Event_NewEntityId = Id).");
            Add("Request_Entity_Teleport", typeof(IdPositionRotation), ok, ray: true, changes: true, req: new[] { "id", "pos" }, wait: ReplyWait.Ok,
                desc: "Teleports an entity inside its playfield.");
            Add("Request_Entity_ChangePlayfield", typeof(IdPlayfieldPositionRotation), ok, ray: true, changes: true, req: new[] { "id", "playfield", "pos" }, wait: ReplyWait.Ok,
                desc: "Moves an entity to another playfield.");
            Add("Request_Entity_Destroy", typeof(Id), ok, ray: true, changes: true, req: new[] { "id" }, wait: ReplyWait.Ok, shortNames: new[] { "destroy", "destroyentity", "destroystruct" },
                desc: "Destroys an entity or structure (the playfield must be loaded).");
            Add("Request_Entity_PosAndRot", typeof(Id), new[] { CmdId.Event_Entity_PosAndRot }, ray: true, req: new[] { "id" }, shortNames: new[] { "posrot", "entitypos" },
                desc: "Position and rotation of an entity (Event_Entity_PosAndRot = IdPositionRotation).");
            Add("Request_Entity_Spawn", typeof(EntitySpawnInfo), ok, ray: true, changes: true, req: new[] { "playfield" }, wait: ReplyWait.Ok,
                desc: "Spawns an entity / blueprint (EntitySpawnInfo fields).");
            Add("Request_Playfield_List", null, new[] { CmdId.Event_Playfield_List }, ray: true, shortNames: new[] { "pflist" },
                desc: "Names of the loaded playfields (Event_Playfield_List = PlayfieldList).");
            Add("Request_Playfield_Stats", typeof(PString), new[] { CmdId.Event_Playfield_Stats }, ray: true, req: new[] { "pstr" }, alias: new[] { "playfield=pstr", "name=pstr" },
                shortNames: new[] { "pfstats", "playfieldstats" }, desc: "Stats of a loaded playfield (Event_Playfield_Stats = PlayfieldStats).");
            Add("Request_Dedi_Stats", null, new[] { CmdId.Event_Dedi_Stats }, ray: true, shortNames: new[] { "dedistats" },
                desc: "Dedicated server stats (Event_Dedi_Stats = DediStats).");
            Add("Request_GlobalStructure_List", null, new[] { CmdId.Event_GlobalStructure_List }, ray: true, shortNames: new[] { "gslist" },
                desc: "All structures on all playfields (Event_GlobalStructure_List).",
                note: "Forum reports say A12+ dedicated servers no longer answer this; then the reply times out. 'gents' is the working structure list.");
            Add("Request_GlobalStructure_Update", typeof(PString), new[] { CmdId.Event_GlobalStructure_List }, ray: true, changes: true, req: new[] { "pstr" }, alias: new[] { "playfield=pstr", "name=pstr" },
                shortNames: new[] { "gsupdate" }, desc: "Structures of one loaded playfield (Event_GlobalStructure_List).",
                note: "Conservatively marked changes_server for ZAH confirmation. Forum reports say A12+ servers may not answer it.");
            Add("Request_Structure_Touch", typeof(Id), ok, ray: true, changes: true, req: new[] { "id" }, wait: ReplyWait.Ok, shortNames: new[] { "touch", "touchstruct" },
                desc: "Marks a structure as visited (resets its decay / wipe timer).");
            Add("Request_Get_Factions", typeof(Id), new[] { CmdId.Event_Get_Factions }, ray: true, defaults: new Dictionary<string, object> { { "id", 1 } }, shortNames: new[] { "factions" },
                desc: "Faction list starting at id (default 1) (Event_Get_Factions = FactionInfoList). Also refreshes the bridge's faction cache.");
            Add("Request_InGameMessage_SinglePlayer", typeof(IdMsgPrio), ok, ray: true, visible: true, req: new[] { "id", "msg" }, alias: new[] { "text=msg", "duration=time" },
                defaults: new Dictionary<string, object> { { "prio", (byte)1 }, { "time", 10f } }, wait: ReplyWait.Message, shortNames: new[] { "msg", "msgplayer" },
                desc: "HUD message to one player (entity id). Shown on the player's HUD, not in the dedicated server console.",
                note: "The game usually sends no Event_Ok or Event_Error for this request.");
            Add("Request_InGameMessage_AllPlayers", typeof(IdMsgPrio), ok, ray: true, visible: true, req: new[] { "msg" }, alias: new[] { "text=msg", "duration=time" },
                defaults: new Dictionary<string, object> { { "prio", (byte)1 }, { "time", 10f } }, wait: ReplyWait.Message, shortNames: new[] { "broadcast", "msgall" },
                desc: "HUD message to every player. Shown on each player's HUD (top right), not in the dedicated server console.",
                note: "The game usually sends no Event_Ok or Event_Error for this request.");
            Add("Request_ShowDialog_SinglePlayer", typeof(DialogBoxData), new[] { CmdId.Event_DialogButtonIndex }, ray: true, visible: true, req: new[] { "Id", "MsgText" },
                alias: new[] { "text=MsgText", "msg=MsgText", "yes=PosButtonText", "no=NegButtonText" }, wait: ReplyWait.Player, shortNames: new[] { "dialog" },
                desc: "Dialog box for one player; the answer (Event_DialogButtonIndex = IdAndIntValue) comes when the player clicks.");

            // ---- the other requests in this Mif.dll (not on Ray's list) ----
            Add("Request_Player_GetAndRemoveInventory", typeof(Id), new[] { CmdId.Event_Player_GetAndRemoveInventory }, changes: true, req: new[] { "id" },
                desc: "Returns a player's inventory AND empties it.");
            Add("Request_Entity_Destroy2", typeof(IdPlayfield), ok, changes: true, req: new[] { "id", "playfield" }, wait: ReplyWait.Ok,
                desc: "Destroys an entity on a named playfield.");
            Add("Request_Entity_SetName", typeof(IdPlayfieldName), ok, changes: true, req: new[] { "id", "playfield", "name" }, wait: ReplyWait.Ok,
                desc: "Renames an entity / structure.");
            Add("Request_Entity_Export", typeof(EntityExportInfo), ok, changes: true, req: new[] { "id", "playfield", "filePath" }, wait: ReplyWait.Ok,
                desc: "Exports an entity to a file on the server.");
            Add("Request_Structure_BlockStatistics", typeof(Id), new[] { CmdId.Event_Structure_BlockStatistics }, req: new[] { "id" },
                desc: "Block counts of a structure (Event_Structure_BlockStatistics = IdStructureBlockInfo).");
            Add("Request_AlliancesAll", null, new[] { CmdId.Event_AlliancesAll }, shortNames: new[] { "alliances" },
                desc: "All alliances (Event_AlliancesAll = AlliancesTable).");
            Add("Request_AlliancesFaction", typeof(AlliancesFaction), new[] { CmdId.Event_AlliancesFaction }, req: new[] { "faction1Id", "faction2Id" },
                desc: "Are two factions allied (Event_AlliancesFaction = AlliancesFaction).");
            Add("Request_GetBannedPlayers", null, new[] { CmdId.Event_BannedPlayers }, shortNames: new[] { "banned" },
                desc: "Banned players (Event_BannedPlayers = BannedPlayerData).");
            Add("Request_InGameMessage_Faction", typeof(IdMsgPrio), ok, visible: true, req: new[] { "id", "msg" }, alias: new[] { "text=msg", "duration=time" },
                defaults: new Dictionary<string, object> { { "prio", (byte)1 }, { "time", 10f } }, wait: ReplyWait.Message, shortNames: new[] { "msgfaction", "factionmsg" },
                desc: "HUD message to one faction (faction id). Shown on those players' HUDs, not in the dedicated server console.",
                note: "The game usually sends no Event_Ok or Event_Error for this request.");
            Add("Request_Load_Playfield", typeof(PlayfieldLoad), new[] { CmdId.Event_Playfield_Loaded, CmdId.Event_Ok }, changes: true, req: new[] { "playfield" },
                alias: new[] { "name=playfield", "seconds=sec" }, defaults: new Dictionary<string, object> { { "sec", 60f } }, wait: ReplyWait.Ok,
                shortNames: new[] { "loadpf", "loadplayfield" }, desc: "Starts a playfield for 'sec' seconds (default 60) so commands can reach it.",
                note: "Event_Playfield_Loaded may arrive without our seq; it is also matched by playfield name.");
            Add("Request_ConsoleCommand", typeof(PString), ok, changes: true, req: new[] { "pstr" }, alias: new[] { "command=pstr", "text=pstr", "line=pstr" }, wait: ReplyWait.Ok,
                shortNames: new[] { "console", "consolecommand" },
                desc: "Runs a server console / telnet command. Same checks as con: (client-only and blocked commands are refused).",
                note: "The game only answers Ok / Error; the command's printed output goes to the server log.");
            Add("Request_Playfield_Entity_List", typeof(PString), new[] { CmdId.Event_Playfield_Entity_List }, req: new[] { "pstr" }, alias: new[] { "playfield=pstr", "name=pstr" },
                shortNames: new[] { "pfents", "playfieldentities", "pfentlist" }, desc: "Entities of a loaded playfield (Event_Playfield_Entity_List = PlayfieldEntityList).");
        }

        private static void Add(string name, Type paramType, CmdId[] replies, bool ray = false, bool changes = false, bool visible = false,
            string[] req = null, string[] alias = null, Dictionary<string, object> defaults = null, ReplyWait wait = ReplyWait.Data,
            string[] shortNames = null, string desc = null, string note = null)
        {
            try
            {
                var def = new EleonRequest
                {
                    Name = name,
                    Cmd = (CmdId)Enum.Parse(typeof(CmdId), name),
                    ParamType = paramType,
                    Required = req ?? new string[0],
                    Replies = replies ?? new CmdId[0],
                    Wait = wait,
                    ChangesServer = changes || visible,
                    VisibleToPlayers = visible,
                    OnRaysList = ray,
                    Description = desc,
                    Note = note
                };
                if (alias != null)
                    foreach (var a in alias) { var kv = a.Split('='); def.KeyAliases[kv[0]] = kv[1]; }
                if (defaults != null)
                    foreach (var kv in defaults) def.Defaults[kv.Key] = kv.Value;

                // short names: "player_info", "playerinfo" + the ones given
                string bare = name.Substring("Request_".Length);
                var shorts = new List<string> { bare.ToLowerInvariant(), bare.Replace("_", "").ToLowerInvariant() };
                if (shortNames != null) shorts.AddRange(shortNames.Select(s => s.ToLowerInvariant()));
                def.ShortNames = shorts.Distinct().ToArray();

                _all.Add(def);
                _byName[name] = def;
                foreach (var s in def.ShortNames) if (!_byName.ContainsKey(s)) _byName[s] = def;
            }
            catch (Exception ex)
            {
                ZgbLog.Write($"[ZGB] -WARN- Eleon request '{name}' not added: {ex.Message}");
            }
        }

        public static EleonRequest Find(string name)
        {
            if (string.IsNullOrWhiteSpace(name)) return null;
            return _byName.TryGetValue(name.Trim(), out var d) ? d : null;
        }

        // ------------------------------------------------------------------ param building

        private const BindingFlags Pub = BindingFlags.Public | BindingFlags.Instance;

        internal static string[] FieldNames(Type t) => t.GetFields(Pub).Select(f => f.Name).ToArray();

        // Builds the param object for a request. "text" is what followed the request name:
        // empty, a JSON object, or a short form (a number for Id, plain text for PString).
        public static object BuildParam(EleonRequest def, string text, out JObject controls)
        {
            controls = new JObject();
            text = (text ?? "").Trim();
            JObject o;
            if (text.Length == 0) o = new JObject();
            else if (text.StartsWith("{"))
            {
                try { o = JObject.Parse(text); }
                catch (Exception ex) { throw new BadParamsException("Params are not valid JSON: " + ex.Message); }
            }
            else if (def.ParamType == typeof(Id))
            {
                if (!int.TryParse(text, out int idv)) throw new BadParamsException($"Expected an entity id number or JSON for {def.Name}.");
                o = new JObject { ["id"] = idv };
            }
            else if (def.ParamType == typeof(PString)) o = new JObject { ["pstr"] = text };
            else if (def.ParamType == null) throw new BadParamsException($"{def.Name} takes no params.");
            else throw new BadParamsException($"{def.Name} needs JSON params: {{{string.Join(", ", FieldNames(def.ParamType).Select(f => "\"" + f + "\":..."))}}}");

            // req_id / timeout_ms are for the bridge, not the game
            foreach (var p in o.Properties().ToList())
                if (ControlKeys.Contains(p.Name)) { controls[p.Name.ToLowerInvariant()] = p.Value; p.Remove(); }

            if (def.ParamType == null)
            {
                if (o.Properties().Any()) throw new BadParamsException($"{def.Name} takes no params.");
                return null;
            }
            return Fill(def, o);
        }

        private static object Fill(EleonRequest def, JObject o)
        {
            Type t = def.ParamType;
            object target = Activator.CreateInstance(t);
            var fields = t.GetFields(Pub).ToDictionary(f => f.Name, StringComparer.OrdinalIgnoreCase);
            var given = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            foreach (var kv in def.Defaults)
                if (fields.TryGetValue(kv.Key, out var df)) df.SetValue(target, Convert(JToken.FromObject(kv.Value), df.FieldType, df.Name));

            foreach (var p in o.Properties())
            {
                string key = def.KeyAliases.TryGetValue(p.Name, out var real) ? real : p.Name;
                if (!fields.TryGetValue(key, out var f))
                    throw new BadParamsException($"Unknown field '{p.Name}' for {def.Name} ({t.Name}: {string.Join(", ", fields.Keys)}).");
                f.SetValue(target, Convert(p.Value, f.FieldType, f.Name));
                given.Add(f.Name);
            }

            foreach (var r in def.Required)
                if (!given.Contains(r) && !def.Defaults.ContainsKey(r))
                    throw new BadParamsException($"Missing field '{r}' for {def.Name}.");
            return target;
        }

        // JSON -> the field's real type (PVector3 / ItemStack get friendly forms)
        internal static object Convert(JToken v, Type type, string field)
        {
            try
            {
                if (v == null || v.Type == JTokenType.Null)
                {
                    if (!type.IsValueType || Nullable.GetUnderlyingType(type) != null) return null;
                    throw new BadParamsException($"Field '{field}' cannot be null.");
                }
                if (type == typeof(PVector3)) return ToVector(v, field);
                if (type == typeof(ItemStack)) return ToItem(v, field);
                if (type == typeof(ItemStack[])) return ToItems(v, field).ToArray();
                if (type == typeof(List<ItemStack>)) return ToItems(v, field);
                return v.ToObject(type);
            }
            catch (BadParamsException) { throw; }
            catch (Exception ex) { throw new BadParamsException($"Field '{field}' has the wrong type (needs {type.Name}): {ex.Message}"); }
        }

        // {"x":1,"y":2,"z":3}, [1,2,3] or "1,2,3"
        internal static PVector3 ToVector(JToken v, string field)
        {
            float[] n;
            if (v.Type == JTokenType.Object)
            {
                var o = (JObject)v;
                n = new[] { "x", "y", "z" }.Select(k => (float?)(o.GetValue(k, StringComparison.OrdinalIgnoreCase)) ?? 0f).ToArray();
            }
            else if (v.Type == JTokenType.Array) n = v.Select(x => (float)x).ToArray();
            else n = ((string)v).Split(',').Select(s => float.Parse(s.Trim(), System.Globalization.CultureInfo.InvariantCulture)).ToArray();
            if (n.Length != 3) throw new BadParamsException($"Field '{field}' needs x, y and z.");
            return new PVector3(n[0], n[1], n[2]);
        }

        // {"id":itemId,"count":n,"slotIdx":0,"ammo":0,"decay":0}
        internal static ItemStack ToItem(JToken v, string field)
        {
            if (!(v is JObject o)) throw new BadParamsException($"Field '{field}' needs an item object {{\"id\":..,\"count\":..}}.");
            int id = (int?)o.GetValue("id", StringComparison.OrdinalIgnoreCase) ?? throw new BadParamsException($"Item in '{field}' needs 'id'.");
            int count = (int?)o.GetValue("count", StringComparison.OrdinalIgnoreCase) ?? 1;
            var s = new ItemStack(id, count);
            s.slotIdx = (byte?)o.GetValue("slotIdx", StringComparison.OrdinalIgnoreCase) ?? 0;
            s.ammo = (int?)o.GetValue("ammo", StringComparison.OrdinalIgnoreCase) ?? 0;
            s.decay = (int?)o.GetValue("decay", StringComparison.OrdinalIgnoreCase) ?? 0;
            return s;
        }

        internal static List<ItemStack> ToItems(JToken v, string field)
        {
            if (!(v is JArray a)) throw new BadParamsException($"Field '{field}' needs a list of items.");
            return a.Select(x => ToItem(x, field)).ToList();
        }
    }
}
