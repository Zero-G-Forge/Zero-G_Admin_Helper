// =====================================================================
// MODULE: ZeroGBridge/Network/ServerFileWrites.cs
// DESCRIPTION: 1.6.2 WRITE commands for ZAH (core only, hot-swappable on the 1.5.0 loader).
//   files:put:{"root","path","offset","total","sha256","base_sha256","data"}
//       -> replaces ONE existing editable file in the scenario or save root, in chunks of base64 data.
//   coreupload:put:{"file":"dll|pdb","offset","total","sha256","data"}
//       -> places a new ZeroGBridge.Core.dll (or its .pdb) in the mod's Updates/ drop folder.
//          The loader only loads it on hot:reload (or by itself when AutoReloadOnDrop is true).
//   coreupload:status -> what is waiting in Updates/ (size and sha256).
// The loader owns every "hot:" line, so this upload cannot be called hot:upload without a loader
// update (and a server restart). That is why it uses its own coreupload: prefix in the core.
// Safety, for both commands:
//   - Only authenticated lines reach the core; the dispatcher still refuses a line holding the AuthToken.
//   - Every chunk is staged in the bridge's own Uploads/ folder, never in a game folder.
//   - The finished file must match the sha256 ZAH sent, or nothing is replaced.
//   - The old file is copied to the bridge's Backups/ folder FIRST. Backups are never deleted here.
//   - The new file is written next to the target as a temp file, then swapped in with File.Replace
//     (one step, so the game never sees a half-written file).
//   - files:put uses the same path checks as files:get, only replaces files that already exist,
//     only .ecf .yaml .yml .csv .epb, and refuses when the server copy changed since ZAH downloaded it.
//   - coreupload only ever writes the two fixed names ZeroGBridge.Core.dll / ZeroGBridge.Core.pdb.
//   - "FileWritesEnabled": false in ZeroGBridge.json turns both commands off (read on every call, no restart).
// =====================================================================

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace ZeroGBridge
{
    public static class ServerFileWrites
    {
        #region Constants

        // Prefix of the core upload command (files:put is routed here from ServerFiles.Handle).
        public const string CoreUploadPrefix = "coreupload:";

        // Protocol number for the write commands. Bump it when the request or reply format changes.
        public const int WriteProtocolVersion = 1;

        // Largest raw chunk accepted in one line (base64 makes the line about one third larger).
        public const int MaxChunkBytes = 128 * 1024;

        // Largest core DLL or PDB accepted (the 1.6.1 core is about 260 KB).
        public const long MaxCoreBytes = 8L * 1024 * 1024;

        // Staged uploads not finished within this time are thrown away (only the bridge's own .part files).
        private const int StaleUploadMinutes = 30;

        // File types files:put may replace. Smaller than the read list on purpose: no pictures, and never .json/.dll/.key.
        // 1.6.13: .epb prefabs
        private static readonly string[] WritableExtensions = { ".ecf", ".yaml", ".yml", ".csv", ".epb" };

        // Error codes only used by the write commands (the path codes come from ServerFiles).
        public const string ErrDisabled = "writes_disabled";
        public const string ErrNotReady = "not_ready";
        public const string ErrBadOffset = "bad_offset";
        public const string ErrHashMismatch = "hash_mismatch";
        public const string ErrChanged = "changed_on_server";
        public const string ErrWriteFailed = "write_failed";
        public const string ErrBadCore = "bad_core";

        #endregion

        #region State

        // Mod folder (where ZeroGBridge.json lives). Set by CoreEntry.Start from the loader; tests set it directly.
        public static string ModDirectory;

        // One write at a time, so two uploads can never mix their chunks or swap the same file together.
        private static readonly object WriteLock = new object();

        // Upload key ("put|scenario|Content/Configuration/Items.ecf" or "core|dll") -> what has arrived so far.
        private static readonly Dictionary<string, Upload> Uploads = new Dictionary<string, Upload>(StringComparer.OrdinalIgnoreCase);

        private sealed class Upload
        {
            public string PartPath;      // staged bytes in Uploads/
            public long Total;           // full size ZAH announced at offset 0
            public long Received;        // bytes written to the part file so far
            public string Sha256;        // hash the finished file must have
            public string BaseSha256;    // files:put only: hash of the server file the edit was based on
            public DateTime StartedUtc;
        }

        public static string UploadsDirectory => ModDirectory == null ? null : Path.Combine(ModDirectory, "Uploads");
        public static string BackupsDirectory => ModDirectory == null ? null : Path.Combine(ModDirectory, "Backups");
        public static string UpdatesDirectory => ModDirectory == null ? null : Path.Combine(ModDirectory, "Updates");

        // Read on every call, so the switch in ZeroGBridge.json works without a restart. On unless set to false.
        public static bool WritesEnabled => AuthConfig.GetBool("FileWritesEnabled", true);

        public static bool IsCoreUploadLine(string lower) => lower != null && lower.StartsWith(CoreUploadPrefix, StringComparison.Ordinal);

        #endregion

        #region files:put

        /// <summary>
        /// One chunk of a file replacement. offset 0 starts (or restarts) the upload; the chunk that reaches
        /// "total" checks the hash, backs up the old file and swaps the new one in. Always one JSON line back.
        /// </summary>
        public static string HandlePut(JObject request, string reqId)
        {
            if (!WritesEnabled) return Fail("put", reqId, ErrDisabled, "File writes are turned off in ZeroGBridge.json (FileWritesEnabled).");
            if (string.IsNullOrEmpty(ModDirectory)) return Fail("put", reqId, ErrNotReady, "The bridge does not know its mod folder yet.");
            if (request == null) return Fail("put", reqId, "bad_request", "files:put needs a JSON request.");

            string rootName = ((string)request["root"] ?? "").Trim().ToLowerInvariant();
            string rootFolder = ServerFiles.RootFolderForWrite(rootName);
            if (rootName != "scenario" && rootName != "save") return Fail("put", reqId, "unknown_root", "root must be scenario or save.");
            if (rootFolder == null) return Fail("put", reqId, "root_unavailable", "The game has not reported this folder yet.");

            // Same text checks as files:get, then the smaller write whitelist.
            string error;
            string relative = ServerFiles.NormalizeRelativePath(rootName, (string)request["path"], out error);
            if (relative == null) return Fail("put", reqId, error, "The path was refused.");
            if (!WritableExtensions.Contains(Path.GetExtension(relative).ToLowerInvariant())) return Fail("put", reqId, ServerFiles.ErrNotAllowed, "Only .ecf, .yaml, .yml, .csv and .epb files can be replaced.");

            // The file must already exist (no new files), stay inside the root, and not be a symlink.
            string target = ServerFiles.ResolveUnderRoot(rootFolder, relative, out error);
            if (target == null) return Fail("put", reqId, error, "Only an existing file can be replaced.");

            lock (WriteLock)
            {
                string key = "put|" + rootName + "|" + relative;
                string reply = ReceiveChunk("put", key, request, reqId, ServerFiles.MaxFileBytes, isPut: true, target: target, out Upload upload, out bool finished);
                if (reply != null) return reply;
                if (!finished) return Progress("put", reqId, relative, upload);

                try
                {
                    // Second look at the server copy: it may have changed while the chunks were arriving.
                    string currentSha = HashFile(target);
                    if (!string.Equals(currentSha, upload.BaseSha256, StringComparison.OrdinalIgnoreCase))
                    {
                        Discard(key);
                        return Fail("put", reqId, ErrChanged, "The file on the server changed after it was downloaded. Download it again first.", new { current_sha256 = currentSha });
                    }
                    string backupRelative;
                    string backupPath = MakeBackupPath(Path.Combine("files", rootName), relative, out backupRelative);
                    SwapIn(upload.PartPath, target, backupPath);
                    Discard(key);
                    long size = new FileInfo(target).Length;
                    ZgbLog.Write($"[ZGB] -INFO- [ServerFiles] put: replaced {rootName}/{relative} ({size} bytes, sha256 {upload.Sha256.Substring(0, 12)}), backup {backupRelative}");
                    return JsonConvert.SerializeObject(new { type = "FILES", cmd = "put", req_id = reqId, ok = true, done = true, root = rootName, path = relative, size, sha256 = upload.Sha256, backup = backupRelative });
                }
                catch (Exception ex)
                {
                    Discard(key);
                    ZgbLog.Write($"[ZGB] -ERROR- [ServerFiles] put: could not replace {rootName}/{relative}: {ex.GetType().Name}: {ex.Message}");
                    return Fail("put", reqId, ErrWriteFailed, "The file could not be replaced. The server copy was left as it was.");
                }
            }
        }

        #endregion

        #region coreupload:

        /// <summary>coreupload:status and coreupload:put. Always one JSON line back.</summary>
        public static string HandleCoreUpload(string line)
        {
            string reqId = null;
            try
            {
                string rest = line.Substring(CoreUploadPrefix.Length).Trim();
                int colon = rest.IndexOf(':');
                string sub = (colon >= 0 ? rest.Substring(0, colon) : rest).Trim().ToLowerInvariant();
                string body = colon >= 0 ? rest.Substring(colon + 1).Trim() : "";
                JObject request = null;
                if (body.Length > 0)
                {
                    try { request = JObject.Parse(body); }
                    catch { return Fail("core" + sub, null, "bad_request", "The request after the second colon must be a JSON object."); }
                }
                reqId = ReadReqId(request);
                if (sub == "status") return CoreStatus(reqId);
                if (sub != "put") return Fail("core", reqId, "unknown_command", "Use coreupload:status or coreupload:put.");

                if (!WritesEnabled) return Fail("coreput", reqId, ErrDisabled, "File writes are turned off in ZeroGBridge.json (FileWritesEnabled).");
                if (string.IsNullOrEmpty(ModDirectory)) return Fail("coreput", reqId, ErrNotReady, "The bridge does not know its mod folder yet.");
                string which = ((string)request?["file"] ?? "").Trim().ToLowerInvariant();
                if (which != "dll" && which != "pdb") return Fail("coreput", reqId, "bad_request", "file must be dll or pdb.");
                string targetName = which == "dll" ? CoreFileName : Path.ChangeExtension(CoreFileName, ".pdb");
                string target = Path.Combine(UpdatesDirectory, targetName);

                lock (WriteLock)
                {
                    string key = "core|" + which;
                    string reply = ReceiveChunk("coreput", key, request, reqId, MaxCoreBytes, isPut: false, target: target, out Upload upload, out bool finished);
                    if (reply != null) return reply;
                    if (!finished) return Progress("coreput", reqId, targetName, upload);

                    try
                    {
                        string assemblyVersion = null;
                        if (which == "dll")
                        {
                            // Must be a .NET assembly named ZeroGBridge.Core, read without loading it.
                            string checkError = CheckCoreAssembly(upload.PartPath, out assemblyVersion);
                            if (checkError != null)
                            {
                                Discard(key);
                                return Fail("coreput", reqId, ErrBadCore, checkError);
                            }
                        }
                        Directory.CreateDirectory(UpdatesDirectory);
                        string backupRelative = null;
                        string backupPath = File.Exists(target) ? MakeBackupPath("core", targetName, out backupRelative) : null;
                        SwapIn(upload.PartPath, target, backupPath);
                        Discard(key);
                        ZgbLog.Write($"[ZGB] -INFO- [CoreUpload] Placed Updates/{targetName} ({upload.Total} bytes, sha256 {upload.Sha256.Substring(0, 12)}){(assemblyVersion != null ? " v" + assemblyVersion : "")}. It loads on hot:reload.");
                        return JsonConvert.SerializeObject(new { type = "FILES", cmd = "coreput", req_id = reqId, ok = true, done = true, file = which, name = targetName, size = upload.Total, sha256 = upload.Sha256, assemblyVersion, backup = backupRelative, pendingDrop = File.Exists(Path.Combine(UpdatesDirectory, CoreFileName)) });
                    }
                    catch (Exception ex)
                    {
                        Discard(key);
                        ZgbLog.Write($"[ZGB] -ERROR- [CoreUpload] Could not place Updates/{targetName}: {ex.GetType().Name}: {ex.Message}");
                        return Fail("coreput", reqId, ErrWriteFailed, "The file could not be placed in Updates/.");
                    }
                }
            }
            catch (Exception ex)
            {
                ZgbLog.Write("[ZGB] -ERROR- [CoreUpload] Unhandled error: " + ex.Message);
                return Fail("core", reqId, "exception", "The upload command could not be processed.");
            }
        }

        // Same name the loader looks for (HotContract.CoreFileName); kept here so the tests need no loader types.
        public const string CoreFileName = "ZeroGBridge.Core.dll";

        private static string CoreStatus(string reqId)
        {
            var files = new List<object>();
            if (UpdatesDirectory != null)
            {
                foreach (string name in new[] { CoreFileName, Path.ChangeExtension(CoreFileName, ".pdb") })
                {
                    string path = Path.Combine(UpdatesDirectory, name);
                    if (File.Exists(path)) files.Add(new { name, size = new FileInfo(path).Length, sha256 = HashFile(path) });
                }
            }
            return JsonConvert.SerializeObject(new { type = "FILES", cmd = "corestatus", req_id = reqId, ok = true, protocol = WriteProtocolVersion, enabled = WritesEnabled, maxCoreBytes = MaxCoreBytes, maxChunkBytes = MaxChunkBytes, files });
        }

        // Reads the assembly name and version from the file without loading it. Null = looks like a core.
        private static string CheckCoreAssembly(string path, out string version)
        {
            version = null;
            try
            {
                using (var stream = File.OpenRead(path))
                {
                    if (stream.ReadByte() != 'M' || stream.ReadByte() != 'Z') return "The file is not a DLL.";
                }
                AssemblyName name = AssemblyName.GetAssemblyName(path);
                if (!string.Equals(name.Name, "ZeroGBridge.Core", StringComparison.Ordinal)) return "The DLL is not ZeroGBridge.Core.";
                version = name.Version?.ToString();
                return null;
            }
            catch (Exception ex)
            {
                return "The DLL could not be read as a .NET assembly (" + ex.GetType().Name + ").";
            }
        }

        #endregion

        #region Chunks

        // Takes one chunk. Returns a failure reply, or null with the upload state (finished = all bytes arrived and the hash matched).
        private static string ReceiveChunk(string cmd, string key, JObject request, string reqId, long maxBytes, bool isPut, string target, out Upload upload, out bool finished)
        {
            upload = null; finished = false;
            long offset = ReadLong(request, "offset", -1);
            long total = ReadLong(request, "total", -1);
            string sha = ((string)request["sha256"] ?? "").Trim().ToLowerInvariant();
            byte[] data;
            try { data = Convert.FromBase64String((string)request["data"] ?? ""); }
            catch { return Fail(cmd, reqId, "bad_request", "data must be base64 text."); }

            if (offset < 0 || total < 0) return Fail(cmd, reqId, "bad_request", "offset and total are needed.");
            if (total > maxBytes) return Fail(cmd, reqId, ServerFiles.ErrTooLarge, "The file is larger than the bridge accepts.");
            if (data.Length > MaxChunkBytes) return Fail(cmd, reqId, "bad_request", "One chunk may hold at most " + MaxChunkBytes + " bytes.");
            if (!IsSha256Text(sha)) return Fail(cmd, reqId, "bad_request", "sha256 must be 64 hex characters.");

            CleanStaleUploads();
            if (offset == 0)
            {
                string baseSha = null;
                if (isPut)
                {
                    // ZAH sends the hash of the copy it downloaded; a different server copy means someone else changed it.
                    baseSha = ((string)request["base_sha256"] ?? "").Trim().ToLowerInvariant();
                    if (!IsSha256Text(baseSha)) return Fail(cmd, reqId, "bad_request", "base_sha256 (hash of the downloaded copy) must be 64 hex characters.");
                    string currentSha = HashFile(target);
                    if (!string.Equals(currentSha, baseSha, StringComparison.OrdinalIgnoreCase))
                        return Fail(cmd, reqId, ErrChanged, "The file on the server changed after it was downloaded. Download it again first.", new { current_sha256 = currentSha });
                }
                Discard(key);
                Directory.CreateDirectory(UploadsDirectory);
                string part = Path.Combine(UploadsDirectory, ShortHash(key) + ".part");
                File.WriteAllBytes(part, new byte[0]);
                Uploads[key] = new Upload { PartPath = part, Total = total, Received = 0, Sha256 = sha, BaseSha256 = baseSha, StartedUtc = DateTime.UtcNow };
            }

            Upload current;
            if (!Uploads.TryGetValue(key, out current)) return Fail(cmd, reqId, ErrBadOffset, "No upload is in progress for this file. Start again at offset 0.", new { expected_offset = 0 });
            if (offset != current.Received || total != current.Total || sha != current.Sha256)
                return Fail(cmd, reqId, ErrBadOffset, "This chunk does not follow the last one.", new { expected_offset = current.Received });
            if (current.Received + data.Length > current.Total)
            {
                Discard(key);
                return Fail(cmd, reqId, "bad_request", "More bytes arrived than total. The upload was cancelled.");
            }

            using (var stream = new FileStream(current.PartPath, FileMode.Append, FileAccess.Write, FileShare.None))
            {
                stream.Write(data, 0, data.Length);
            }
            current.Received += data.Length;
            upload = current;
            if (current.Received < current.Total) return null;

            string arrivedSha = HashFile(current.PartPath);
            if (!string.Equals(arrivedSha, current.Sha256, StringComparison.OrdinalIgnoreCase))
            {
                Discard(key);
                return Fail(cmd, reqId, ErrHashMismatch, "The file that arrived does not match its sha256. Nothing was replaced.");
            }
            finished = true;
            return null;
        }

        private static string Progress(string cmd, string reqId, string name, Upload upload)
        {
            return JsonConvert.SerializeObject(new { type = "FILES", cmd, req_id = reqId, ok = true, done = false, path = name, received = upload.Received, total = upload.Total, next_offset = upload.Received });
        }

        // Forgets an upload and removes its own .part file (never anything else).
        private static void Discard(string key)
        {
            Upload old;
            if (!Uploads.TryGetValue(key, out old)) return;
            Uploads.Remove(key);
            try { if (File.Exists(old.PartPath)) File.Delete(old.PartPath); } catch { }
        }

        private static void CleanStaleUploads()
        {
            foreach (string key in Uploads.Where(pair => (DateTime.UtcNow - pair.Value.StartedUtc).TotalMinutes > StaleUploadMinutes).Select(pair => pair.Key).ToList())
            {
                Discard(key);
            }
        }

        #endregion

        #region Backup and swap

        // Backups/<area>/<relative folder>/<name>.<yyyyMMdd-HHmmss>.bak (a number is added if that name exists).
        private static string MakeBackupPath(string area, string relative, out string backupRelative)
        {
            string stamp = DateTime.Now.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture);
            string relativeNative = relative.Replace('/', Path.DirectorySeparatorChar);
            string folder = Path.Combine(BackupsDirectory, area, Path.GetDirectoryName(relativeNative) ?? "");
            string name = Path.GetFileName(relativeNative) + "." + stamp;
            string path = Path.Combine(folder, name + ".bak");
            for (int n = 2; File.Exists(path); n++) path = Path.Combine(folder, name + "_" + n + ".bak");
            backupRelative = path.Substring(ModDirectory.TrimEnd(Path.DirectorySeparatorChar).Length + 1).Replace(Path.DirectorySeparatorChar, '/');
            return path;
        }

        // Backup first (when there is an old file), then temp file next to the target, then one-step swap.
        private static void SwapIn(string partPath, string target, string backupPath)
        {
            if (backupPath != null && File.Exists(target))
            {
                Directory.CreateDirectory(Path.GetDirectoryName(backupPath));
                using (var source = new FileStream(target, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                using (var copy = new FileStream(backupPath, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    source.CopyTo(copy);
                }
                if (new FileInfo(backupPath).Length != new FileInfo(target).Length) throw new IOException("backup size does not match");
            }

            string temp = target + ".zgbput.tmp";
            try
            {
                File.Copy(partPath, temp, true);
                if (File.Exists(target)) File.Replace(temp, target, null);
                else File.Move(temp, target);
            }
            finally
            {
                // Only the bridge's own temp file is removed, and only if the swap did not use it.
                try { if (File.Exists(temp)) File.Delete(temp); } catch { }
            }
        }

        #endregion

        #region Helpers

        public static string HashFile(string path)
        {
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            using (var sha = SHA256.Create())
            {
                return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
            }
        }

        private static string ShortHash(string text)
        {
            using (var sha = SHA256.Create())
            {
                return BitConverter.ToString(sha.ComputeHash(System.Text.Encoding.UTF8.GetBytes(text))).Replace("-", "").Substring(0, 16).ToLowerInvariant();
            }
        }

        private static bool IsSha256Text(string text) => text != null && text.Length == 64 && text.All(c => (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'));

        private static long ReadLong(JObject request, string name, long fallback)
        {
            JToken token = request?[name];
            return token != null && token.Type == JTokenType.Integer ? (long)token : fallback;
        }

        private static string ReadReqId(JObject request)
        {
            JToken token = request?["req_id"];
            if (token == null) return null;
            if (token.Type == JTokenType.String) return (string)token;
            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float) return Convert.ToString(((JValue)token).Value, CultureInfo.InvariantCulture);
            return null;
        }

        // One failure line. No full server paths and no secrets in the text.
        private static string Fail(string cmd, string reqId, string code, string message, object extra = null)
        {
            var reply = JObject.FromObject(new { type = "FILES", cmd, req_id = reqId, ok = false, error = code, message });
            if (extra != null) foreach (var property in JObject.FromObject(extra).Properties()) reply[property.Name] = property.Value;
            return reply.ToString(Formatting.None);
        }

        #endregion
    }
}
