// =====================================================================
// MODULE: ZeroGBridge/Network/ServerFiles.cs
// DESCRIPTION: 1.6.1 READ-ONLY file access for ZAH. Three commands, each answered with one
//   single-line JSON reply of "type":"FILES" (file content travels as base64 text):
//   files:info                                  -> which roots are available and the limits
//   files:list:{"root":"scenario|save","offset":0,"limit":1000}   -> relative path, size, mtime
//   files:get:{"root":"...","items":[{"path":"...","offset":0}]}  -> base64 data, in chunks
// Nothing here writes, renames or deletes anything. A file is only ever opened with
// FileAccess.Read and FileShare.ReadWrite, so the running game is never blocked.
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

        // How long (seconds) a folder scan is reused, so paging through files:list does not rescan.
        private const int ListCacheSeconds = 10;

        // Seconds between re-reads of the two root folders from the game (done on the game thread).
        private const int RootRefreshSeconds = 30;

        // File types that may be listed or sent. Everything else (.db, .json, .dll, .key ...) is never reachable.
        private static readonly string[] AllowedExtensions = { ".ecf", ".yaml", ".yml", ".csv", ".jpg", ".jpeg", ".png" };

        // Root name -> sub-folders (relative to that root) that may be read. A file directly inside the
        // root folder is also allowed when its type is on the list above (for example gameoptions.yaml).
        // Change these lists to open or close folders. Names use "/" as the separator.
        private static readonly Dictionary<string, string[]> AllowedFolders = new Dictionary<string, string[]>(StringComparer.Ordinal)
        {
            { "scenario", new[] { "Content", "SharedData/Content" } },
            { "save", new[] { "Content", "Shared/Content", "SharedData/Content" } }
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
        /// Reads the active scenario and save game folders from the game (IApplication.GetPathFor).
        /// Called from ModMain.OnApplicationUpdate, which runs on the game thread. Throttled to one
        /// read every 30 seconds. When the game gives no usable folder, dedicated.yaml next to the
        /// server is used as a fallback (only the CustomScenario and GameName values are read).
        /// </summary>
        public static void RefreshRoots(IModApi api)
        {
            DateTime now = DateTime.UtcNow;
            if ((now - _lastRootRefreshUtc).TotalSeconds < RootRefreshSeconds) return;
            _lastRootRefreshUtc = now;

            string scenario = null, save = null, source = "none";
            try
            {
                var app = api?.Application;
                if (app != null)
                {
                    scenario = SafeGetPath(app, AppFolder.ActiveScenario);
                    save = SafeGetPath(app, AppFolder.SaveGame);
                    if (scenario != null || save != null) source = "game";
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write("[ZGB] -WARN- [ServerFiles] GetPathFor failed: " + ex.Message);
            }

            if (scenario == null || save == null)
            {
                string fallbackScenario, fallbackSave;
                ReadDedicatedYamlFolders(out fallbackScenario, out fallbackSave);
                if (scenario == null && fallbackScenario != null) { scenario = fallbackScenario; source = source == "game" ? "game+dedicated.yaml" : "dedicated.yaml"; }
                if (save == null && fallbackSave != null) { save = fallbackSave; source = source == "game" ? "game+dedicated.yaml" : "dedicated.yaml"; }
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

        // Fallback: dedicated.yaml in the server's working folder names the scenario (CustomScenario) and
        // the save game (GameName). Only those two keys are read, and only plain folder names are accepted.
        private static void ReadDedicatedYamlFolders(out string scenarioFolder, out string saveFolder)
        {
            scenarioFolder = null; saveFolder = null;
            try
            {
                string serverDir = Directory.GetCurrentDirectory();
                string yamlPath = Path.Combine(serverDir, "dedicated.yaml");
                if (!File.Exists(yamlPath)) return;
                string scenarioName = null, gameName = null;
                foreach (string raw in File.ReadLines(yamlPath))
                {
                    string line = raw.Trim();
                    if (line.StartsWith("CustomScenario:", StringComparison.Ordinal)) scenarioName = YamlValue(line.Substring(15));
                    else if (line.StartsWith("GameName:", StringComparison.Ordinal)) gameName = YamlValue(line.Substring(9));
                }
                if (IsPlainFolderName(scenarioName))
                {
                    string dir = Path.Combine(serverDir, "Content", "Scenarios", scenarioName);
                    if (Directory.Exists(dir)) scenarioFolder = Path.GetFullPath(dir);
                }
                if (IsPlainFolderName(gameName))
                {
                    string dir = Path.Combine(serverDir, "Saves", "Games", gameName);
                    if (Directory.Exists(dir)) saveFolder = Path.GetFullPath(dir);
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write("[ZGB] -WARN- [ServerFiles] dedicated.yaml fallback failed: " + ex.Message);
            }
        }

        // "  Name   # comment" -> "Name". Quotes are removed.
        private static string YamlValue(string rest)
        {
            int hash = rest.IndexOf('#');
            if (hash >= 0) rest = rest.Substring(0, hash);
            return rest.Trim().Trim('"', '\'').Trim();
        }

        // A folder name with no separators, no dots-only names and no control characters.
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
        /// Routes files:info, files:list and files:get. Always returns exactly one JSON line.
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
                    default: return Fail(sub, reqId, "unknown_command", "Use files:info, files:list or files:get.");
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
                source,
                scenario,
                saveName = save,
                roots,
                limits = new { maxFileBytes = MaxFileBytes, replyBudgetBytes = ReplyBudgetBytes, maxItemsPerGet = MaxItemsPerGet, maxListPage = MaxListPage },
                extensions = AllowedExtensions
            });
        }

        #endregion

        #region files:list

        private static string HandleList(JObject request, string reqId)
        {
            string rootName = (string)request?["root"];
            if (rootName == null || !AllowedFolders.ContainsKey(rootName)) return Fail("list", reqId, "unknown_root", "root must be scenario or save.");
            string rootFolder = RootFolderFor(rootName);
            if (rootFolder == null) return Fail("list", reqId, "root_unavailable", "The server has not reported the " + rootName + " folder yet.");

            int offset = Math.Max(0, ReadInt(request, "offset", 0));
            int limit = Math.Min(MaxListPage, Math.Max(1, ReadInt(request, "limit", 1000)));

            List<FileEntry> all = ScanRoot(rootName, rootFolder);
            var page = all.Skip(offset).Take(limit).Select(f => new { path = f.Path, size = f.Size, mtime = f.Mtime }).ToList();
            int next = offset + page.Count;
            ZgbLog.Write($"[ZGB] -INFO- [ServerFiles] list root={rootName} total={all.Count} offset={offset} returned={page.Count}");
            return JsonConvert.SerializeObject(new
            {
                type = "FILES",
                cmd = "list",
                req_id = reqId,
                ok = true,
                root = rootName,
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
        private static List<FileEntry> ScanRoot(string rootName, string rootFolder)
        {
            lock (ListCache)
            {
                KeyValuePair<DateTime, List<FileEntry>> cached;
                if (ListCache.TryGetValue(rootName, out cached) && (DateTime.UtcNow - cached.Key).TotalSeconds < ListCacheSeconds) return cached.Value;
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
            lock (ListCache) { ListCache[rootName] = new KeyValuePair<DateTime, List<FileEntry>>(DateTime.UtcNow, found); }
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
            string rootFolder = RootFolderFor(rootName);
            if (rootFolder == null) return Fail("get", reqId, "root_unavailable", "The server has not reported the " + rootName + " folder yet.");

            var items = request["items"] as JArray;
            if (items == null || items.Count == 0) return Fail("get", reqId, "bad_request", "items must be a non-empty list.");
            if (items.Count > MaxItemsPerGet) return Fail("get", reqId, "too_many_items", "At most " + MaxItemsPerGet + " items per request.");

            int budget = ReplyBudgetBytes;
            var results = new List<object>();
            foreach (JToken item in items)
            {
                results.Add(ReadOneItem(rootName, rootFolder, item as JObject, ref budget));
            }
            return JsonConvert.SerializeObject(new { type = "FILES", cmd = "get", req_id = reqId, ok = true, root = rootName, files = results });
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
