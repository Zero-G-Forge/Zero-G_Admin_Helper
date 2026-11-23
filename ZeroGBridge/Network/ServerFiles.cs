// =====================================================================
// MODULE: ZeroGBridge/Network/ServerFiles.cs
// DESCRIPTION: 1.6.1 READ-ONLY file access for ZAH. Commands, each answered with one
//   single-line JSON reply of "type":"FILES" (file content travels as base64 text):
//   files:info                                  -> which roots are available and the limits
//   files:list:{"root":"scenario|save","offset":0,"limit":1000}   -> relative path, size, mtime
//   files:get:{"root":"scenario","items":[{"path":"<relative path>","offset":0}]}  -> base64 data, in chunks
// Nothing here writes, renames or deletes anything. A file is only ever opened with
// FileAccess.Read and FileShare.ReadWrite, so the running game is never blocked.
// 1.6.2: files:put is routed from here to Network/ServerFileWrites.cs, which does the writing
// (backup first, same path checks). This file itself still only reads.
// 1.6.4: files:catalog lists the scenario folders under Content/Scenarios and the save folders
//   under Saves/Games (names only), plus the pair dedicated.yaml / the game currently reports.
//   files:list and files:get accept an optional "scenario" or "save" folder name. That name must
//   be a plain folder name (no separators, no "..", no rooted path) and must be in the catalog.
//   The same allowed folders and extensions apply. files:put stays pinned to the reported pair
//   and ignores any extra name. ProtocolVersion stays 1 (reply shape of info/list/get is unchanged).
// 1.6.5: AllowedFolders adds scenario Playfields, RandomPresets, Extras, Sectors and Prefabs,
//   and save PDA. ProtocolVersion stays 1.
// 1.6.6: AllowedExtensions adds .epb so Prefabs blueprints can be listed and downloaded.
//   MaxFileBytes stays 16 MB; local scenario .epb files are well under 1 MB. ProtocolVersion stays 1.
// 1.6.7: the current scenario comes from CustomScenario in the dedicated yaml the server was
//   started with (-dedicated, or dedicated.yaml / dedicated.yml in the server folder). That value
//   wins over a wrong ActiveScenario from the game (for example "Default Multiplayer"). Inline
//   # comments and spaces around the colon are accepted. ProtocolVersion stays 1.
// Safety: two whitelisted roots, whitelisted sub-folders and file types, no ".." or absolute
// paths, the resolved full path must stay under the root, no symlinks or junctions, size caps.
// The bridge AuthToken is never read or printed here (the auth handshake already happened).
// =====================================================================

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Eleon.Modding;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace ZeroGBridge
{
    public static class ServerFiles
    {
        #region Constants

        // Prefix of every command handled here.
        public const string Prefix = "files:";

        // Protocol number that ZAH can check. Bump it when the reply format changes.
        public const int ProtocolVersion = 1;

        // Largest single file the bridge will send (bigger files are refused with "too_large").
        public const long MaxFileBytes = 16L * 1024 * 1024;

        // Raw bytes put into one files:get reply. Base64 makes it about one third larger, so a reply
        // line stays near 256 KB. When the budget runs out, the remaining items come back "deferred".
        public const int ReplyBudgetBytes = 192 * 1024;

        // Most items accepted in one files:get request.
        public const int MaxItemsPerGet = 50;

        // Most entries returned by one files:list page (the default when "limit" is missing is 1000).
        public const int MaxListPage = 2000;

        // Most files the folder scan will collect per root, so a huge folder cannot stall the bridge.
        public const int MaxFilesPerRoot = 50000;

        // Deepest folder level the scan follows below a whitelisted sub-folder.
        public const int MaxFolderDepth = 12;

        // How long (seconds) a folder scan is reused for the later pages of files:list. The first page
        // (offset 0) always rescans, so a new list request sees changed files at once.
        private const int ListCacheSeconds = 60;

        // Seconds between re-reads of the two root folders from the game (done on the game thread).
        private const int RootRefreshSeconds = 30;

        // File types that may be listed or sent. Everything else (.db, .json, .dll, .key and similar) is never reachable.
        // 1.6.6: .epb is included. MaxFileBytes (16 MB) is enough; typical .epb files are under 1 MB.
        private static readonly string[] AllowedExtensions = { ".ecf", ".yaml", ".yml", ".csv", ".jpg", ".jpeg", ".png", ".epb" };

        // Root name -> sub-folders (relative to that root) that may be read. A file directly inside the
        // root folder is also allowed when its type is on the list above (for example gameoptions.yaml).
        // Change these lists to open or close folders. Names use "/" as the separator.
        private static readonly Dictionary<string, string[]> AllowedFolders = new Dictionary<string, string[]>(StringComparer.Ordinal)
        {
            { "scenario", new[] { "Content", "SharedData/Content", "Playfields", "RandomPresets", "Extras", "Sectors", "Prefabs" } },
            { "save", new[] { "Content", "Shared/Content", "SharedData/Content", "PDA" } }
        };

        // Names Windows treats as devices. They are refused as path segments on every platform.
        private static readonly string[] ReservedNames =
        {
            "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
            "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
        };

        #endregion

        #region Root folders (set on the game thread)

        // The two folders everything is read from. Written by RefreshRoots, read by command handlers.
        private static readonly object RootLock = new object();
        private static string _scenarioRoot;
        private static string _saveRoot;
        private static string _scenarioName;
        private static string _saveName;
        private static string _rootSource = "none";
        private static DateTime _lastRootRefreshUtc = DateTime.MinValue;

        // Tests can set these. The running server leaves them null.
        public static string ServerDirectoryOverride;
        public static string[] CommandLineOverride;

        /// <summary>Full path of the live save folder used by files:info, or null.</summary>
        public static string CurrentSaveRoot
        {
            get { lock (RootLock) return _saveRoot; }
        }

        /// <summary>Folder name of the live save used by files:info, or null.</summary>
        public static string CurrentSaveName
        {
            get { lock (RootLock) return _saveName; }
        }

        // Scan results reused for a few seconds: root name -> (time, files).
        private static readonly Dictionary<string, KeyValuePair<DateTime, List<FileEntry>>> ListCache =
            new Dictionary<string, KeyValuePair<DateTime, List<FileEntry>>>(StringComparer.Ordinal);

        private sealed class FileEntry
        {
            public string Path;      // relative path with "/" separators
            public long Size;
            public string Mtime;     // ISO 8601, UTC
        }

        /// <summary>
        /// Reads the active scenario and save game folders. Called from ModMain.OnApplicationUpdate,
        /// which runs on the game thread. Throttled to one read every 30 seconds. CustomScenario and
        /// GameName from the dedicated yaml the server was started with win over GetPathFor, which
        /// can report "Default Multiplayer" (or nothing) even when a custom scenario is running.
        /// </summary>
        public static void RefreshRoots(IModApi api)
        {
            RefreshRoots(api, false);
        }

        public static void RefreshRoots(IModApi api, bool force)
        {
            DateTime now = DateTime.UtcNow;
            if (!force && (now - _lastRootRefreshUtc).TotalSeconds < RootRefreshSeconds) return;
            _lastRootRefreshUtc = now;

            string gameScenario = null, gameSave = null;
            try
            {
                var app = api?.Application;
                if (app != null)
                {
                    gameScenario = SafeGetPath(app, AppFolder.ActiveScenario);
                    gameSave = SafeGetPath(app, AppFolder.SaveGame);
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write("[ZGB] -WARN- [ServerFiles] GetPathFor failed: " + ex.Message);
            }

            string yamlScenario, yamlSave;
            ReadDedicatedYamlFolders(gameScenario, gameSave, out yamlScenario, out yamlSave);
            // The yaml the server was started with is the real pair when those folders exist.
            string scenario = yamlScenario ?? gameScenario;
            string save = yamlSave ?? gameSave;
            string source = "none";
            if (yamlScenario != null || yamlSave != null)
            {
                bool gameAlso = gameScenario != null || gameSave != null;
                source = gameAlso ? "game+dedicated.yaml" : "dedicated.yaml";
            }
            else if (gameScenario != null || gameSave != null)
            {
                source = "game";
            }

            lock (RootLock)
            {
                bool changed = scenario != _scenarioRoot || save != _saveRoot;
                _scenarioRoot = scenario;
                _saveRoot = save;
                _scenarioName = scenario == null ? null : LastSegment(scenario);
                _saveName = save == null ? null : LastSegment(save);
                _rootSource = source;
                if (changed)
                {
                    ListCache.Clear();
                    ZgbLog.Write($"[ZGB] -INFO- [ServerFiles] Roots set (source={source}): scenario=\"{_scenarioName}\" save=\"{_saveName}\"");
                }
            }
        }

        // GetPathFor can throw or return an empty text. Both become null (no root).
        private static string SafeGetPath(IApplication app, AppFolder folder)
        {
            try
            {
                string path = app.GetPathFor(folder);
                if (string.IsNullOrWhiteSpace(path)) return null;
                string full = Path.GetFullPath(path.Trim());
                // A root must be a real folder that is not a drive root or the top of the file system.
                if (!Directory.Exists(full) || Directory.GetParent(full.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)) == null) return null;
                return full;
            }
            catch { return null; }
        }

        private static string LastSegment(string fullPath)
        {
            return Path.GetFileName(fullPath.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
        }

        // CustomScenario and GameName from the yaml the server was started with. Only those two
        // keys are read, and only plain folder names that exist on disk are accepted.
        private static void ReadDedicatedYamlFolders(string gameScenario, string gameSave, out string scenarioFolder, out string saveFolder)
        {
            scenarioFolder = null; saveFolder = null;
            try
            {
                string serverDir = ResolveServerDirectory(gameScenario, gameSave);
                if (string.IsNullOrEmpty(serverDir)) return;
                string yamlPath = FindDedicatedYamlPath(serverDir, CommandLineOverride ?? Environment.GetCommandLineArgs());
                if (yamlPath == null) return;
                string yamlText = ReadAllTextShared(yamlPath);
                if (yamlText == null) return;
                string scenarioName, gameName;
                ReadDedicatedYamlNames(yamlText, out scenarioName, out gameName);
                if (IsPlainFolderName(scenarioName))
                {
                    string dir = Path.Combine(serverDir, "Content", "Scenarios", scenarioName);
                    if (Directory.Exists(dir) && !IsReparsePoint(dir)) scenarioFolder = Path.GetFullPath(dir);
                }
                if (IsPlainFolderName(gameName))
                {
                    string dir = Path.Combine(serverDir, "Saves", "Games", gameName);
                    if (!Directory.Exists(dir)) dir = Path.Combine(serverDir, "Saves", gameName);
                    if (Directory.Exists(dir) && !IsReparsePoint(dir)) saveFolder = Path.GetFullPath(dir);
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write("[ZGB] -WARN- [ServerFiles] dedicated yaml read failed: " + ex.Message);
            }
        }

        // The server folder: a test override, then the parent of Content/Scenarios or Saves/Games,
        // then the process working directory.
        private static string ResolveServerDirectory(string gameScenario, string gameSave)
        {
            if (!string.IsNullOrEmpty(ServerDirectoryOverride))
            {
                try { return Path.GetFullPath(ServerDirectoryOverride); }
                catch { return null; }
            }
            string inferred = InferServerDirectory(gameScenario) ?? InferServerDirectory(gameSave);
            if (!string.IsNullOrEmpty(inferred)) return inferred;
            try { return Directory.GetCurrentDirectory(); }
            catch { return null; }
        }

        // Walks up from a game-reported folder when it sits at Content/Scenarios/<name> or
        // Saves/Games/<name> (or directly under Saves).
        private static string InferServerDirectory(string rootFolder)
        {
            if (string.IsNullOrEmpty(rootFolder)) return null;
            try
            {
                var current = new DirectoryInfo(Path.GetFullPath(rootFolder));
                if (!current.Exists) return null;
                var parent = current.Parent;
                var grand = parent != null ? parent.Parent : null;
                var great = grand != null ? grand.Parent : null;
                if (parent != null && grand != null && great != null
                    && string.Equals(parent.Name, "Scenarios", StringComparison.OrdinalIgnoreCase)
                    && string.Equals(grand.Name, "Content", StringComparison.OrdinalIgnoreCase)
                    && Directory.Exists(great.FullName))
                    return great.FullName;
                if (parent != null && grand != null && great != null
                    && string.Equals(parent.Name, "Games", StringComparison.OrdinalIgnoreCase)
                    && string.Equals(grand.Name, "Saves", StringComparison.OrdinalIgnoreCase)
                    && Directory.Exists(great.FullName))
                    return great.FullName;
                if (parent != null && grand != null
                    && string.Equals(parent.Name, "Saves", StringComparison.OrdinalIgnoreCase)
                    && Directory.Exists(grand.FullName))
                    return grand.FullName;
            }
            catch { }
            return null;
        }

        // The yaml from -dedicated / -dedicated=path, then dedicated.yaml or dedicated.yml in the server folder.
        public static string FindDedicatedYamlPath(string serverDir, string[] commandLine)
        {
            if (commandLine != null)
            {
                for (int i = 0; i < commandLine.Length; i++)
                {
                    string arg = commandLine[i] ?? "";
                    string given = null;
                    if (arg.StartsWith("-dedicated=", StringComparison.OrdinalIgnoreCase)
                        || arg.StartsWith("/dedicated=", StringComparison.OrdinalIgnoreCase))
                    {
                        given = arg.Substring(arg.IndexOf('=') + 1);
                    }
                    else if (string.Equals(arg, "-dedicated", StringComparison.OrdinalIgnoreCase)
                             || string.Equals(arg, "/dedicated", StringComparison.OrdinalIgnoreCase))
                    {
                        if (i + 1 < commandLine.Length) given = commandLine[i + 1];
                    }
                    if (string.IsNullOrWhiteSpace(given)) continue;
                    given = given.Trim().Trim('"');
                    string resolved = given;
                    if (!Path.IsPathRooted(resolved) && !string.IsNullOrEmpty(serverDir))
                        resolved = Path.Combine(serverDir, given);
                    try
                    {
                        string full = Path.GetFullPath(resolved);
                        if (File.Exists(full) && !IsReparsePoint(full)) return full;
                    }
                    catch { }
                }
            }
            if (string.IsNullOrEmpty(serverDir)) return null;
            foreach (string name in new[] { "dedicated.yaml", "dedicated.yml" })
            {
                try
                {
                    string candidate = Path.Combine(serverDir, name);
                    if (File.Exists(candidate) && !IsReparsePoint(candidate)) return Path.GetFullPath(candidate);
                }
                catch { }
            }
            return null;
        }

        // Reads CustomScenario and GameName from yaml text. Spaces around the colon and trailing
        // # comments are accepted. Other keys that only contain those words are ignored.
        public static void ReadDedicatedYamlNames(string yamlText, out string customScenario, out string gameName)
        {
            customScenario = null;
            gameName = null;
            if (string.IsNullOrEmpty(yamlText)) return;
            using (var reader = new StringReader(yamlText))
            {
                string raw;
                while ((raw = reader.ReadLine()) != null)
                {
                    string value;
                    if (TryYamlKey(raw, "CustomScenario", out value) && IsPlainFolderName(value))
                        customScenario = value;
                    else if (TryYamlKey(raw, "GameName", out value) && IsPlainFolderName(value))
                        gameName = value;
                }
            }
        }

        private static string ReadAllTextShared(string path)
        {
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            using (var reader = new StreamReader(stream, Encoding.UTF8, true))
            {
                return reader.ReadToEnd();
            }
        }

        // "CustomScenario :  Ascension-Reborn   # comment" -> key matches, value is the folder name.
        private static bool TryYamlKey(string raw, string key, out string value)
        {
            value = null;
            if (string.IsNullOrEmpty(raw) || string.IsNullOrEmpty(key)) return false;
            string line = raw.Trim();
            if (line.StartsWith("- ", StringComparison.Ordinal)) line = line.Substring(2).Trim();
            if (!line.StartsWith(key, StringComparison.Ordinal)) return false;
            string rest = line.Substring(key.Length).TrimStart();
            if (!rest.StartsWith(":")) return false;
            value = YamlValue(rest.Substring(1));
            return true;
        }

        // "  Name   # comment" -> "Name". Quotes are removed.
        private static string YamlValue(string rest)
        {
            int hash = rest.IndexOf('#');
            if (hash >= 0) rest = rest.Substring(0, hash);
            return rest.Trim().Trim('"', '\'').Trim();
        }

        // A folder name with no separators, no dots-only names and no control characters.
        // Spaces, parentheses, hyphens and underscores are allowed (Empyrion scenario names use them).
        private static bool IsPlainFolderName(string name)
        {
            if (string.IsNullOrWhiteSpace(name) || name == "." || name == "..") return false;
            return name.IndexOfAny(new[] { '/', '\\', ':', '*', '?', '"', '<', '>', '|' }) < 0 && !name.Any(c => c < 0x20);
        }

        #endregion

        #region Path safety

        /// <summary>Reply codes used when a path is refused (also unit-tested by ZAH-side scripts).</summary>
        public const string ErrBadPath = "bad_path";
        public const string ErrNotAllowed = "not_allowed";
        public const string ErrNotFound = "not_found";
        public const string ErrTooLarge = "too_large";
        public const string ErrReadFailed = "read_failed";

        /// <summary>
        /// Checks a request path text and returns it normalized ("/" separators) or null with an error code.
        /// This part only looks at the text: no file system access. Refuses empty text, absolute or rooted
        /// paths, drive letters, "..", ".", empty segments (double slashes), control characters, ":" (also
        /// blocks NTFS streams), segments ending in a dot or space, Windows device names, and file types
        /// that are not on the whitelist. The first segment must be a whitelisted folder, or the path must
        /// be a single file name directly in the root.
        /// </summary>
        public static string NormalizeRelativePath(string rootName, string requested, out string error)
        {
            error = null;
            if (string.IsNullOrEmpty(requested) || requested.Length > 260 || !AllowedFolders.ContainsKey(rootName ?? ""))
            {
                error = ErrBadPath; return null;
            }
            if (requested.Any(c => c < 0x20 || c == ':' || c == '*' || c == '?' || c == '"' || c == '<' || c == '>' || c == '|'))
            {
                error = ErrBadPath; return null;
            }
            string text = requested.Replace('\\', '/');
            if (text.StartsWith("/", StringComparison.Ordinal)) { error = ErrBadPath; return null; }
            string[] segments = text.Split('/');
            foreach (string segment in segments)
            {
                if (segment.Length == 0 || segment == "." || segment == ".." || segment.EndsWith(".", StringComparison.Ordinal) || segment.EndsWith(" ", StringComparison.Ordinal) || segment.StartsWith(" ", StringComparison.Ordinal))
                {
                    error = ErrBadPath; return null;
                }
                string stem = segment.Split('.')[0].ToUpperInvariant();
                if (ReservedNames.Contains(stem)) { error = ErrBadPath; return null; }
            }
            string extension = Path.GetExtension(segments[segments.Length - 1]).ToLowerInvariant();
            if (!AllowedExtensions.Contains(extension)) { error = ErrNotAllowed; return null; }

            string normalized = string.Join("/", segments);
            if (segments.Length > 1 && !IsUnderAllowedFolder(rootName, normalized)) { error = ErrNotAllowed; return null; }
            return normalized;
        }

        // True when the relative path starts with one of the root's whitelisted folders (whole segments only).
        private static bool IsUnderAllowedFolder(string rootName, string normalized)
        {
            foreach (string folder in AllowedFolders[rootName])
            {
                if (normalized.StartsWith(folder + "/", StringComparison.OrdinalIgnoreCase)) return true;
            }
            return false;
        }

        /// <summary>
        /// Turns a normalized relative path into a full path and proves it is safe: the full path must stay
        /// inside the root, and neither the file nor any folder on the way may be a symlink or junction.
        /// Returns null with an error code when anything is wrong.
        /// </summary>
        public static string ResolveUnderRoot(string rootFull, string normalizedRelative, out string error)
        {
            error = null;
            try
            {
                if (string.IsNullOrEmpty(rootFull)) { error = ErrNotFound; return null; }
                string rootWithSeparator = rootFull.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
                string candidate = Path.GetFullPath(Path.Combine(rootWithSeparator, normalizedRelative.Replace('/', Path.DirectorySeparatorChar)));
                StringComparison comparison = Path.DirectorySeparatorChar == '\\' ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
                if (!candidate.StartsWith(rootWithSeparator, comparison)) { error = ErrBadPath; return null; }

                // Walk from the root down to the file: a reparse point (symlink / junction) anywhere is refused.
                string current = rootWithSeparator.TrimEnd(Path.DirectorySeparatorChar);
                foreach (string segment in normalizedRelative.Split('/'))
                {
                    current = Path.Combine(current, segment);
                    if (!File.Exists(current) && !Directory.Exists(current)) { error = ErrNotFound; return null; }
                    if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0) { error = ErrNotAllowed; return null; }
                }
                if (!File.Exists(candidate)) { error = ErrNotFound; return null; }
                return candidate;
            }
            catch { error = ErrBadPath; return null; }
        }

        #endregion

        #region Command entry

        public static bool IsFilesLine(string lower) => lower != null && lower.StartsWith(Prefix, StringComparison.Ordinal);

        /// <summary>
        /// Routes files:info, files:list, files:get, files:catalog and files:put. Always returns exactly one JSON line.
        /// </summary>
        public static string Handle(string line)
        {
            string reqId = null;
            try
            {
                string rest = line.Substring(Prefix.Length).Trim();
                int colon = rest.IndexOf(':');
                string sub = (colon >= 0 ? rest.Substring(0, colon) : rest).Trim().ToLowerInvariant();
                string body = colon >= 0 ? rest.Substring(colon + 1).Trim() : "";

                JObject request = null;
                if (body.Length > 0)
                {
                    try { request = JObject.Parse(body); }
                    catch { return Fail(sub, null, "bad_request", "The request after the second colon must be a JSON object."); }
                }
                reqId = ReadReqId(request);

                switch (sub)
                {
                    case "info": return HandleInfo(reqId);
                    case "list": return HandleList(request, reqId);
                    case "get": return HandleGet(request, reqId);

                    // 1.6.4: names of every scenario and save folder, plus the reported pair.
                    case "catalog": return HandleCatalog(reqId);

                    // 1.6.2: the one write command (Network/ServerFileWrites.cs).
                    case "put": return ServerFileWrites.HandlePut(request, reqId);
                    default: return Fail(sub, reqId, "unknown_command", "Use files:info, files:list, files:get, files:put or files:catalog.");
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write("[ZGB] -ERROR- [ServerFiles] Unhandled error: " + ex.Message);
                return Fail("error", reqId, "exception", "The file command could not be processed.");
            }
        }

        // One failure line. No file system paths and no secrets in the text.
        private static string Fail(string cmd, string reqId, string code, string message)
        {
            return JsonConvert.SerializeObject(new { type = "FILES", cmd, req_id = reqId, ok = false, error = code, message });
        }

        // req_id may be a string or a number; it is echoed back as a string (same rule as alert:).
        private static string ReadReqId(JObject request)
        {
            JToken token = request?["req_id"];
            if (token == null) return null;
            if (token.Type == JTokenType.String) return (string)token;
            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float) return Convert.ToString(((JValue)token).Value, CultureInfo.InvariantCulture);
            return null;
        }

        // The same root folder for ServerFileWrites (files:put), which lives in its own file.
        internal static string RootFolderForWrite(string rootName) => RootFolderFor(rootName);

        // Current root folder for a root name, or null when the game has not reported it.
        private static string RootFolderFor(string rootName)
        {
            lock (RootLock)
            {
                if (rootName == "scenario") return _scenarioRoot;
                if (rootName == "save") return _saveRoot;
                return null;
            }
        }

        // Most folder names one catalog reply will include for one parent (scenarios or saves).
        private const int MaxCatalogEntries = 500;

        // Parent of the reported scenario or save (Content/Scenarios or Saves/Games). Prefers the
        // parent of the game-reported folder; falls back to dedicated.yaml's usual place under the
        // server working directory. Returns null when that parent cannot be used.
        private static string CatalogParentFor(string rootName)
        {
            string currentRoot = RootFolderFor(rootName);
            if (!string.IsNullOrEmpty(currentRoot))
            {
                try
                {
                    var parent = Directory.GetParent(currentRoot.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
                    if (parent != null && Directory.Exists(parent.FullName) && !IsReparsePoint(parent.FullName)
                        && parent.Parent != null)
                    {
                        return parent.FullName;
                    }
                }
                catch { }
            }

            try
            {
                // Prefer the parent of the live folder above (so a save under Saves/Games or
                // directly under Saves is both fine). These paths are only used when that parent
                // is not known yet: Scenarios under Content, then Saves/Games, then Saves.
                string serverDir = Directory.GetCurrentDirectory();
                if (rootName == "scenario") return UsableCatalogDirectory(Path.Combine(serverDir, "Content", "Scenarios"));
                if (rootName == "save")
                {
                    string games = UsableCatalogDirectory(Path.Combine(serverDir, "Saves", "Games"));
                    if (games != null) return games;
                    return UsableCatalogDirectory(Path.Combine(serverDir, "Saves"));
                }
                return null;
            }
            catch { return null; }
        }

        // A real, non-rooted, non-symlink folder that catalog listing may use as a parent.
        private static string UsableCatalogDirectory(string path)
        {
            if (string.IsNullOrEmpty(path)) return null;
            try
            {
                string full = Path.GetFullPath(path);
                if (!Directory.Exists(full) || IsReparsePoint(full)) return null;
                if (Directory.GetParent(full.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)) == null) return null;
                return full;
            }
            catch { return null; }
        }

        // Immediate child folder names under a catalog parent. Names only, no paths, no files.
        // Reparse points and names that fail IsPlainFolderName are skipped. Sorted for a stable reply.
        private static List<string> ListCatalogNames(string rootName)
        {
            var names = new List<string>();
            string parent = CatalogParentFor(rootName);
            if (parent == null) return names;
            try
            {
                foreach (string dir in Directory.GetDirectories(parent))
                {
                    if (names.Count >= MaxCatalogEntries) break;
                    if (IsReparsePoint(dir)) continue;
                    string name = LastSegment(dir);
                    if (!IsPlainFolderName(name)) continue;
                    string stem = name.Split('.')[0].ToUpperInvariant();
                    if (ReservedNames.Contains(stem)) continue;
                    names.Add(name);
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write("[ZGB] -WARN- [ServerFiles] Catalog scan stopped early: " + ex.Message);
            }
            names.Sort(StringComparer.OrdinalIgnoreCase);
            return names;
        }

        // Optional "scenario" or "save" folder name on files:list / files:get. Missing or blank means
        // the pair reported by the game or dedicated.yaml. A bad name fails closed (no fallback).
        // outName is the requested name when it is present and valid, otherwise null.
        private static bool TryOptionalFolderName(JObject request, string rootName, string cmd, string reqId, out string outName, out string failLine)
        {
            outName = null;
            failLine = null;
            string key = rootName == "scenario" ? "scenario" : "save";
            JToken token = request?[key];
            if (token == null || token.Type == JTokenType.Null) return true;
            if (token.Type != JTokenType.String)
            {
                failLine = Fail(cmd, reqId, ErrBadPath, "The " + key + " value must be a folder name.");
                return false;
            }
            string raw = ((string)token).Trim();
            if (raw.Length == 0) return true;
            if (raw.Length > 255 || !IsPlainFolderName(raw))
            {
                failLine = Fail(cmd, reqId, ErrBadPath, "The " + key + " value must be a plain folder name.");
                return false;
            }
            outName = raw;
            return true;
        }

        // Resolves a catalog folder name to a full path. The name must appear in the live listing
        // (exact match). The resolved path must stay under the parent and must be a real folder,
        // not a symlink or junction. error and message are set when this returns null.
        private static string ResolveCatalogFolder(string rootName, string folderName, out string error, out string message)
        {
            error = null;
            message = null;
            string kind = rootName == "scenario" ? "scenario" : "save";
            List<string> names = ListCatalogNames(rootName);
            if (!names.Contains(folderName, StringComparer.Ordinal))
            {
                error = "unknown_folder";
                message = "That folder is not in the " + kind + " list.";
                return null;
            }
            string parent = CatalogParentFor(rootName);
            if (parent == null)
            {
                error = "root_unavailable";
                message = "The server has not reported the " + kind + " folder yet.";
                return null;
            }
            try
            {
                string parentWithSeparator = parent.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
                string candidate = Path.GetFullPath(Path.Combine(parentWithSeparator, folderName));
                StringComparison comparison = Path.DirectorySeparatorChar == '\\' ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
                if (!candidate.StartsWith(parentWithSeparator, comparison))
                {
                    error = ErrBadPath;
                    message = "The " + kind + " value must be a plain folder name.";
                    return null;
                }
                if (!Directory.Exists(candidate) || IsReparsePoint(candidate))
                {
                    error = "unknown_folder";
                    message = "That folder is not in the " + kind + " list.";
                    return null;
                }
                return candidate;
            }
            catch
            {
                error = ErrBadPath;
                message = "The " + kind + " value must be a plain folder name.";
                return null;
            }
        }

        // The folder list or get will read from: the optional name when it is present, otherwise
        // the reported pair. Returns null and has already built failLine when something is refused.
        private static string ResolveReadRoot(JObject request, string rootName, string cmd, string reqId, out string failLine)
        {
            failLine = null;
            string named;
            if (!TryOptionalFolderName(request, rootName, cmd, reqId, out named, out failLine)) return null;
            if (named == null)
            {
                string current = RootFolderFor(rootName);
                if (current == null)
                {
                    failLine = Fail(cmd, reqId, "root_unavailable", "The server has not reported the " + rootName + " folder yet.");
                    return null;
                }
                return current;
            }
            string error, message;
            string resolved = ResolveCatalogFolder(rootName, named, out error, out message);
            if (resolved == null)
            {
                failLine = Fail(cmd, reqId, error, message);
                return null;
            }
            return resolved;
        }

        #endregion

        #region files:catalog

        // 1.6.4: folder names only, plus the pair the game or dedicated.yaml currently reports.
        // originScenario is the scenario the current save was created from, when a save yaml names
        // it and that name is in the scenario catalog. It is independent of the reported pair.
        private static string HandleCatalog(string reqId)
        {
            string scenario, save, source;
            lock (RootLock) { scenario = _scenarioName; save = _saveName; source = _rootSource; }

            List<string> scenarios = ListCatalogNames("scenario");
            List<string> saves = ListCatalogNames("save");
            string originSource;
            string originScenario = ReadOriginScenario(scenarios, out originSource);
            ZgbLog.Write($"[ZGB] -INFO- [ServerFiles] catalog: current scenario=\"{scenario}\" save=\"{save}\" origin=\"{originScenario}\" scenarios={scenarios.Count} saves={saves.Count}");
            return JsonConvert.SerializeObject(new
            {
                type = "FILES",
                cmd = "catalog",
                req_id = reqId,
                ok = true,
                protocol = ProtocolVersion,
                source,
                current = new { scenario, save },
                originScenario,
                originSource,
                scenarios,
                saves
            });
        }

        // Read-only: looks in the current save's own yaml (never dedicated.yaml, which can name the
        // wrong scenario) for a plain folder name that is also in the scenario catalog.
        private static string ReadOriginScenario(List<string> scenarioNames, out string originSource)
        {
            originSource = null;
            string saveRoot = RootFolderFor("save");
            if (string.IsNullOrEmpty(saveRoot) || scenarioNames == null || scenarioNames.Count == 0) return null;

            foreach (string fileName in new[] { "gameoptions.yaml", "gameoptions.yml", "game.yaml", "game.yml" })
            {
                string found = TryReadScenarioKey(Path.Combine(saveRoot, fileName));
                if (string.IsNullOrEmpty(found)) continue;
                if (!scenarioNames.Contains(found, StringComparer.Ordinal)) continue;
                originSource = "save/" + fileName;
                return found;
            }
            return null;
        }

        // Opens one yaml file read-only (the game may have it open) and returns the first usable
        // CustomScenario, ScenarioName or Scenario value. Other keys that only contain those words
        // (for example IsManagedScenario or CustomPlayerTab) are ignored.
        private static string TryReadScenarioKey(string path)
        {
            try
            {
                if (!File.Exists(path) || IsReparsePoint(path)) return null;
                var info = new FileInfo(path);
                if (info.Length <= 0 || info.Length > 1024 * 1024) return null;
                using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                using (var reader = new StreamReader(stream, Encoding.UTF8, true))
                {
                    string line;
                    while ((line = reader.ReadLine()) != null)
                    {
                        string value = ScenarioKeyValue(line);
                        if (IsPlainFolderName(value)) return value;
                    }
                }
            }
            catch { }
            return null;
        }

        private static string ScenarioKeyValue(string raw)
        {
            if (string.IsNullOrEmpty(raw)) return null;
            string line = raw.Trim();
            if (line.StartsWith("- ", StringComparison.Ordinal)) line = line.Substring(2).Trim();
            string[] keys = { "CustomScenario:", "ScenarioName:", "Scenario:" };
            foreach (string key in keys)
            {
                if (line.StartsWith(key, StringComparison.Ordinal)) return YamlValue(line.Substring(key.Length));
            }
            return null;
        }

        #endregion

        #region files:info

        private static string HandleInfo(string reqId)
        {
            string scenario, save, source;
            lock (RootLock) { scenario = _scenarioName; save = _saveName; source = _rootSource; }

            var roots = new List<object>();
            foreach (string name in new[] { "scenario", "save" })
            {
                string folder = RootFolderFor(name);
                var top = new List<string>();
                if (folder != null)
                {
                    try { foreach (string dir in Directory.GetDirectories(folder)) top.Add(LastSegment(dir)); }
                    catch { }
                }
                top.Sort(StringComparer.OrdinalIgnoreCase);
                roots.Add(new { root = name, available = folder != null, name = name == "scenario" ? scenario : save, topFolders = top, allowedFolders = AllowedFolders[name] });
            }

            ZgbLog.Write($"[ZGB] -INFO- [ServerFiles] info: scenario=\"{scenario}\" save=\"{save}\" source={source}");
            return JsonConvert.SerializeObject(new
            {
                type = "FILES",
                cmd = "info",
                req_id = reqId,
                ok = true,
                protocol = ProtocolVersion,
                readOnly = true,

                // 1.6.2: files:put exists (writeProtocol) and whether ZeroGBridge.json allows it right now.
                // readOnly stays true because list and get never write; ZAH checks canWrite before an upload.
                writeProtocol = ServerFileWrites.WriteProtocolVersion,
                canWrite = ServerFileWrites.WritesEnabled && !string.IsNullOrEmpty(ServerFileWrites.ModDirectory),
                source,
                scenario,
                saveName = save,
                roots,
                limits = new { maxFileBytes = MaxFileBytes, replyBudgetBytes = ReplyBudgetBytes, maxItemsPerGet = MaxItemsPerGet, maxListPage = MaxListPage, maxPutChunkBytes = ServerFileWrites.MaxChunkBytes },
                extensions = AllowedExtensions
            });
        }

        #endregion

        #region files:list

        private static string HandleList(JObject request, string reqId)
        {
            string rootName = (string)request?["root"];
            if (rootName == null || !AllowedFolders.ContainsKey(rootName)) return Fail("list", reqId, "unknown_root", "root must be scenario or save.");
            string failLine;
            string rootFolder = ResolveReadRoot(request, rootName, "list", reqId, out failLine);
            if (rootFolder == null) return failLine;

            int offset = Math.Max(0, ReadInt(request, "offset", 0));
            int limit = Math.Min(MaxListPage, Math.Max(1, ReadInt(request, "limit", 1000)));

            List<FileEntry> all = ScanRoot(rootName, rootFolder, offset == 0);
            var page = all.Skip(offset).Take(limit).Select(f => new { path = f.Path, size = f.Size, mtime = f.Mtime }).ToList();
            int next = offset + page.Count;
            string folderName = LastSegment(rootFolder);
            ZgbLog.Write($"[ZGB] -INFO- [ServerFiles] list root={rootName} name=\"{folderName}\" total={all.Count} offset={offset} returned={page.Count}");
            return JsonConvert.SerializeObject(new
            {
                type = "FILES",
                cmd = "list",
                req_id = reqId,
                ok = true,
                root = rootName,
                name = folderName,
                total = all.Count,
                offset,
                count = page.Count,
                next = next < all.Count ? (int?)next : null,
                files = page
            });
        }

        private static int ReadInt(JObject request, string name, int fallback)
        {
            JToken token = request?[name];
            if (token == null) return fallback;
            if (token.Type == JTokenType.Integer) { long value = (long)token; return value > int.MaxValue ? int.MaxValue : value < int.MinValue ? int.MinValue : (int)value; }
            return fallback;
        }

        // Lists every allowed file under the whitelisted folders of a root. Sorted by path so paging is stable.
        // Symlinked folders and files are skipped, files over the size cap are skipped.
        private static List<FileEntry> ScanRoot(string rootName, string rootFolder, bool forceFresh)
        {
            lock (ListCache)
            {
                // forceFresh (first page) skips the saved scan; later pages reuse it so the paging stays consistent.
                KeyValuePair<DateTime, List<FileEntry>> cached;
                string cacheKey = rootName + "\0" + rootFolder;
                if (!forceFresh && ListCache.TryGetValue(cacheKey, out cached) && (DateTime.UtcNow - cached.Key).TotalSeconds < ListCacheSeconds) return cached.Value;
            }

            var found = new List<FileEntry>();
            try
            {
                // Files directly in the root.
                AddFilesIn(rootName, rootFolder, "", found, 0, false);
                // Whitelisted sub-folders, followed recursively.
                foreach (string folder in AllowedFolders[rootName])
                {
                    string full = Path.Combine(rootFolder, folder.Replace('/', Path.DirectorySeparatorChar));
                    if (Directory.Exists(full) && !IsReparsePoint(full)) AddFilesIn(rootName, full, folder, found, 0, true);
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write("[ZGB] -WARN- [ServerFiles] Folder scan stopped early: " + ex.Message);
            }

            found.Sort((a, b) => string.CompareOrdinal(a.Path, b.Path));
            lock (ListCache) { ListCache[rootName + "\0" + rootFolder] = new KeyValuePair<DateTime, List<FileEntry>>(DateTime.UtcNow, found); }
            return found;
        }

        private static bool IsReparsePoint(string path)
        {
            try { return (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0; }
            catch { return true; }
        }

        private static void AddFilesIn(string rootName, string folderFull, string relativePrefix, List<FileEntry> found, int depth, bool recurse)
        {
            if (found.Count >= MaxFilesPerRoot || depth > MaxFolderDepth) return;
            foreach (string file in Directory.EnumerateFiles(folderFull))
            {
                if (found.Count >= MaxFilesPerRoot) return;
                string name = Path.GetFileName(file);
                string extension = Path.GetExtension(name).ToLowerInvariant();
                if (!AllowedExtensions.Contains(extension)) continue;
                string relative = relativePrefix.Length == 0 ? name : relativePrefix + "/" + name;
                // Same text rules as a request, so the list never shows a path that files:get would refuse.
                string error;
                if (NormalizeRelativePath(rootName, relative, out error) == null) continue;
                try
                {
                    if (IsReparsePoint(file)) continue;
                    var info = new FileInfo(file);
                    if (info.Length > MaxFileBytes) continue;
                    found.Add(new FileEntry { Path = relative, Size = info.Length, Mtime = info.LastWriteTimeUtc.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture) });
                }
                catch { /* a file that vanished or cannot be read is simply not listed */ }
            }
            if (!recurse) return;
            foreach (string dir in Directory.EnumerateDirectories(folderFull))
            {
                if (IsReparsePoint(dir)) continue;
                string name = Path.GetFileName(dir);
                AddFilesIn(rootName, dir, relativePrefix.Length == 0 ? name : relativePrefix + "/" + name, found, depth + 1, true);
            }
        }

        #endregion

        #region files:get

        private static string HandleGet(JObject request, string reqId)
        {
            string rootName = (string)request?["root"];
            if (rootName == null || !AllowedFolders.ContainsKey(rootName)) return Fail("get", reqId, "unknown_root", "root must be scenario or save.");
            string failLine;
            string rootFolder = ResolveReadRoot(request, rootName, "get", reqId, out failLine);
            if (rootFolder == null) return failLine;

            var items = request["items"] as JArray;
            if (items == null || items.Count == 0) return Fail("get", reqId, "bad_request", "items must be a non-empty list.");
            if (items.Count > MaxItemsPerGet) return Fail("get", reqId, "too_many_items", "At most " + MaxItemsPerGet + " items per request.");

            int budget = ReplyBudgetBytes;
            var results = new List<object>();
            foreach (JToken item in items)
            {
                results.Add(ReadOneItem(rootName, rootFolder, item as JObject, ref budget));
            }
            return JsonConvert.SerializeObject(new { type = "FILES", cmd = "get", req_id = reqId, ok = true, root = rootName, name = LastSegment(rootFolder), files = results });
        }

        // Reads one item. Per-item problems are reported inside the reply, never as a thrown error.
        private static object ReadOneItem(string rootName, string rootFolder, JObject item, ref int budget)
        {
            string requested = (string)item?["path"];
            string error;
            string relative = NormalizeRelativePath(rootName, requested, out error);
            if (relative == null) return new { path = requested, error };

            string full = ResolveUnderRoot(rootFolder, relative, out error);
            if (full == null) return new { path = relative, error };

            if (budget <= 0) return new { path = relative, deferred = true };

            try
            {
                // Read-only open that lets the game keep writing the file.
                using (var stream = new FileStream(full, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                {
                    long size = stream.Length;
                    if (size > MaxFileBytes) return new { path = relative, error = ErrTooLarge };
                    long offset = Math.Max(0, item["offset"] != null && item["offset"].Type == JTokenType.Integer ? (long)item["offset"] : 0);
                    if (offset > size) return new { path = relative, error = ErrBadPath };

                    int wanted = (int)Math.Min(Math.Min(size - offset, budget), ReplyBudgetBytes);
                    var buffer = new byte[wanted];
                    stream.Seek(offset, SeekOrigin.Begin);
                    int read = 0;
                    while (read < wanted)
                    {
                        int n = stream.Read(buffer, read, wanted - read);
                        if (n <= 0) break;
                        read += n;
                    }
                    budget -= read;
                    string mtime = File.GetLastWriteTimeUtc(full).ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture);
                    return new
                    {
                        path = relative,
                        size,
                        mtime,
                        offset,
                        length = read,
                        eof = offset + read >= size,
                        data = Convert.ToBase64String(buffer, 0, read)
                    };
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write("[ZGB] -WARN- [ServerFiles] Could not read \"" + relative + "\": " + ex.GetType().Name);
                return new { path = relative, error = ErrReadFailed };
            }
        }

        #endregion
    }
}
