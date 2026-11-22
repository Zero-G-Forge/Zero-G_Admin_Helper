// =====================================================================
// MODULE: ZeroGBridge/tests/ServerFilesTest/Program.cs
// DESCRIPTION: Self-checks for the read-only files: commands (path safety, list, get, chunking)
//              and (1.6.2) the write commands files:put and coreupload: (backup first, hashes, chunks).
// Exit code 0 = every check passed, 1 = at least one failed.
// =====================================================================

using System;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using Eleon.Modding;
using Newtonsoft.Json.Linq;
using ZeroGBridge;

namespace ServerFilesTest
{
    internal class FakeApplication : IApplication, IModApi
    {
        public string Scenario, Save;
        public IApplication Application => this;
        public string GetPathFor(AppFolder folder) => folder == AppFolder.ActiveScenario ? Scenario : folder == AppFolder.SaveGame ? Save : null;
    }

    internal static class Program
    {
        private static int _passed, _failed;

        private static void Check(string name, bool ok, string detail = "")
        {
            if (ok) { _passed++; Console.WriteLine("PASS  " + name); }
            else { _failed++; Console.WriteLine("FAIL  " + name + (detail.Length > 0 ? "  -> " + detail : "")); }
        }

        private static JObject Run(string command) => JObject.Parse(ServerFiles.Handle(command));

        private static JObject RunCore(string command) => JObject.Parse(ServerFileWrites.HandleCoreUpload(command));

        private static string Sha(byte[] bytes)
        {
            using (var sha = System.Security.Cryptography.SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
        }

        // Sends a whole file through files:put (or coreupload:put when coreFile is "dll"/"pdb") in chunks. Returns the last reply.
        private static JObject SendInChunks(string root, string path, byte[] bytes, string baseSha, int chunk, string coreFile = null, string shaOverride = null)
        {
            JObject reply = null;
            long offset = 0;
            do
            {
                int length = (int)Math.Min(chunk, bytes.Length - offset);
                var request = new JObject
                {
                    ["offset"] = offset, ["total"] = bytes.Length, ["sha256"] = shaOverride ?? Sha(bytes),
                    ["data"] = Convert.ToBase64String(bytes, (int)offset, length), ["req_id"] = "p" + offset
                };
                if (coreFile != null)
                {
                    request["file"] = coreFile;
                    reply = RunCore("coreupload:put:" + request.ToString(Newtonsoft.Json.Formatting.None));
                }
                else
                {
                    request["root"] = root; request["path"] = path; request["base_sha256"] = baseSha;
                    reply = Run("files:put:" + request.ToString(Newtonsoft.Json.Formatting.None));
                }
                if (!(bool)reply["ok"]) return reply;
                offset += length;
            } while (offset < bytes.Length);
            return reply;
        }

        // =============================================================
        // "serve" mode for ZAH's end-to-end test: a tiny stand-in for the bridge's TCP side that runs the REAL
        // ServerFiles.Handle on a folder you pass in. Usage:
        //   dotnet run -- serve <port> <scenarioFolder> <saveFolder> [old]
        // The login token is read from the environment variable ZGB_TEST_TOKEN (never from the command line,
        // never printed). With "old" every command gets the generic acknowledgement an old bridge gives.
        // Lines in and out end with CRLF, as on the Windows dedicated server. Stop it with Ctrl+C or by killing it.
        // =============================================================
        private static int Serve(string[] args)
        {
            int port = int.Parse(args[1]);
            var fake = new FakeApplication { Scenario = args[2], Save = args[3] };
            bool oldBridge = args.Length > 4 && args[4] == "old";
            string token = Environment.GetEnvironmentVariable("ZGB_TEST_TOKEN") ?? "";

            // 1.6.2: files:put and coreupload: keep their Uploads/, Backups/ and Updates/ in this folder.
            // Set ZGB_TEST_MODDIR to a test folder; without it the write commands answer not_ready.
            ServerFileWrites.ModDirectory = Environment.GetEnvironmentVariable("ZGB_TEST_MODDIR");
            if (!oldBridge) ServerFiles.RefreshRoots(fake);
            var listener = new TcpListener(IPAddress.Loopback, port);
            listener.Start();
            Console.WriteLine("LISTENING " + port);
            while (true)
            {
                TcpClient client = listener.AcceptTcpClient();
                new Thread(() =>
                {
                    try
                    {
                        using (client)
                        using (var reader = new StreamReader(client.GetStream(), new UTF8Encoding(false)))
                        using (var writer = new StreamWriter(client.GetStream(), new UTF8Encoding(false)) { AutoFlush = true, NewLine = "\r\n" })
                        {
                            string first = reader.ReadLine();
                            if (first == null || first != "auth:" + token) { writer.WriteLine("{\"type\":\"AUTH\",\"status\":\"Denied\"}"); return; }
                            writer.WriteLine("{\"type\":\"AUTH\",\"status\":\"Authenticated\"}");
                            string line;
                            while ((line = reader.ReadLine()) != null)
                            {
                                // A telemetry line first, like the real bridge sends between replies.
                                writer.WriteLine("{\"type\":\"METRIC\",\"fps\":60}");
                                if (!oldBridge && line.StartsWith("files:", StringComparison.OrdinalIgnoreCase)) writer.WriteLine(ServerFiles.Handle(line));
                                else if (!oldBridge && line.StartsWith("coreupload:", StringComparison.OrdinalIgnoreCase)) writer.WriteLine(ServerFileWrites.HandleCoreUpload(line));
                                else writer.WriteLine("{\"type\":\"RESPONSE\",\"status\":\"Acknowledged\",\"command\":\"" + line.Replace("\"", "'") + "\"}");
                            }
                        }
                    }
                    catch { }
                }) { IsBackground = true }.Start();
            }
        }

        private static int Main(string[] args)
        {
            if (args.Length >= 4 && args[0] == "serve") return Serve(args);

            string temp = Path.Combine(Path.GetTempPath(), "zgb_files_test_" + Guid.NewGuid().ToString("N").Substring(0, 8));
            try
            {
                string serverDir = Path.Combine(temp, "server");
                string scenario = Path.Combine(serverDir, "Content", "Scenarios", "TestScenario");
                string save = Path.Combine(serverDir, "Saves", "Games", "TestSave");
                string outside = Path.Combine(temp, "outside");
                Directory.CreateDirectory(Path.Combine(scenario, "Content", "Configuration"));
                Directory.CreateDirectory(Path.Combine(scenario, "SharedData", "Content", "Images"));
                Directory.CreateDirectory(Path.Combine(scenario, "SharedData", "Content", "Extras", "PDA"));
                Directory.CreateDirectory(Path.Combine(scenario, "Playfields", "Secret"));
                Directory.CreateDirectory(Path.Combine(save, "Shared", "Content", "Configuration"));
                Directory.CreateDirectory(outside);

                File.WriteAllText(Path.Combine(scenario, "Content", "Configuration", "Items.ecf"), "Item text\n");
                File.WriteAllText(Path.Combine(scenario, "Content", "Configuration", "Block Config.ecf"), "name with space\n");
                File.WriteAllText(Path.Combine(scenario, "Content", "Configuration", "notes.exe"), "not allowed type\n");
                File.WriteAllText(Path.Combine(scenario, "Content", "Configuration", "secrets.json"), "{}\n");
                File.WriteAllText(Path.Combine(scenario, "SharedData", "Content", "Extras", "PDA", "PDA.yaml"), "pda: 1\n");
                File.WriteAllText(Path.Combine(scenario, "Playfields", "Secret", "playfield_static.yaml"), "not in a whitelisted folder\n");
                File.WriteAllText(Path.Combine(scenario, "gameoptions.yaml"), "top: level\n");
                File.WriteAllText(Path.Combine(scenario, "description.txt"), "txt is not whitelisted\n");
                File.WriteAllText(Path.Combine(save, "Shared", "Content", "Configuration", "Save.ecf"), "save file\n");
                File.WriteAllText(Path.Combine(save, "global.db"), "database\n");
                File.WriteAllText(Path.Combine(outside, "stolen.ecf"), "must never be readable\n");
                // A 400 KB binary-looking image: forces chunking (budget is 192 KB per reply).
                var bigBytes = new byte[400 * 1024];
                new Random(7).NextBytes(bigBytes);
                File.WriteAllBytes(Path.Combine(scenario, "SharedData", "Content", "Images", "Big.jpg"), bigBytes);
                File.WriteAllBytes(Path.Combine(scenario, "SharedData", "Content", "Images", "Small.png"), new byte[] { 1, 2, 3, 4 });

                // Optional symlink checks (skipped quietly where symlinks cannot be made).
                bool symlinkMade = false;
                try
                {
                    Directory.CreateSymbolicLink(Path.Combine(scenario, "Content", "LinkToOutside"), outside);
                    File.CreateSymbolicLink(Path.Combine(scenario, "Content", "Configuration", "Linked.ecf"), Path.Combine(outside, "stolen.ecf"));
                    symlinkMade = true;
                }
                catch { }

                var fake = new FakeApplication { Scenario = scenario, Save = save };
                ServerFiles.RefreshRoots(fake);

                // ---------------- info
                JObject info = Run("files:info");
                Check("info ok and read-only", (bool)info["ok"] && (bool)info["readOnly"] && (int)info["protocol"] == 1);
                Check("info names scenario and save", (string)info["scenario"] == "TestScenario" && (string)info["saveName"] == "TestSave");
                Check("info source is game", (string)info["source"] == "game");

                // ---------------- list
                JObject list = Run("files:list:{\"root\":\"scenario\",\"req_id\":\"r1\"}");
                var listed = list["files"].Select(f => (string)f["path"]).ToList();
                Check("list echoes req_id", (string)list["req_id"] == "r1");
                Check("list has Items.ecf", listed.Contains("Content/Configuration/Items.ecf"));
                Check("list has file name with a space", listed.Contains("Content/Configuration/Block Config.ecf"));
                Check("list has PDA.yaml", listed.Contains("SharedData/Content/Extras/PDA/PDA.yaml"));
                Check("list has top-level gameoptions.yaml", listed.Contains("gameoptions.yaml"));
                Check("list skips .exe, .json and .txt", !listed.Any(p => p.EndsWith(".exe") || p.EndsWith(".json") || p.EndsWith(".txt")));
                Check("list skips non-whitelisted Playfields folder", !listed.Any(p => p.StartsWith("Playfields")));
                Check("list is sorted", listed.SequenceEqual(listed.OrderBy(p => p, StringComparer.Ordinal)));
                if (symlinkMade) Check("list skips symlinked folder and file", !listed.Any(p => p.Contains("LinkToOutside") || p.Contains("Linked.ecf")));

                JObject saveList = Run("files:list:{\"root\":\"save\"}");
                var savePaths = saveList["files"].Select(f => (string)f["path"]).ToList();
                Check("save list has Save.ecf and not global.db", savePaths.Contains("Shared/Content/Configuration/Save.ecf") && !savePaths.Any(p => p.EndsWith(".db")));

                JObject page1 = Run("files:list:{\"root\":\"scenario\",\"offset\":0,\"limit\":2}");
                Check("list paging returns next", (int)page1["count"] == 2 && page1["next"] != null && (int)page1["next"] == 2);
                JObject lastPage = Run("files:list:{\"root\":\"scenario\",\"offset\":" + ((int)page1["total"] - 1) + ",\"limit\":2}");
                Check("last page has null next", (int)lastPage["count"] == 1 && lastPage["next"].Type == JTokenType.Null);
                Check("list rejects unknown root", !(bool)Run("files:list:{\"root\":\"server\"}")["ok"]);

                // ---------------- get (simple)
                JObject got = Run("files:get:{\"root\":\"scenario\",\"items\":[{\"path\":\"Content/Configuration/Items.ecf\"}]}");
                JToken first = got["files"][0];
                string text = Encoding.UTF8.GetString(Convert.FromBase64String((string)first["data"]));
                Check("get returns exact content", text == "Item text\n" && (bool)first["eof"] && (long)first["size"] == text.Length);

                // ---------------- get (chunked, must reassemble to identical bytes)
                var assembled = new MemoryStream();
                long offset = 0; int calls = 0; bool eof = false;
                while (!eof && calls < 20)
                {
                    calls++;
                    JToken e = Run("files:get:{\"root\":\"scenario\",\"items\":[{\"path\":\"SharedData/Content/Images/Big.jpg\",\"offset\":" + offset + "}]}")["files"][0];
                    byte[] part = Convert.FromBase64String((string)e["data"]);
                    assembled.Write(part, 0, part.Length);
                    offset += part.Length;
                    eof = (bool)e["eof"];
                }
                Check("chunked download needs more than one call", calls >= 3, "calls=" + calls);
                Check("chunked download reassembles identical bytes", assembled.ToArray().SequenceEqual(bigBytes));

                // ---------------- get (batch budget: second big item is deferred)
                JObject batch = Run("files:get:{\"root\":\"scenario\",\"items\":[{\"path\":\"SharedData/Content/Images/Big.jpg\"},{\"path\":\"SharedData/Content/Images/Small.png\"},{\"path\":\"Content/Configuration/Items.ecf\"}]}");
                Check("batch defers items after the budget is used", batch["files"][1]["deferred"] != null && batch["files"][2]["deferred"] != null);
                string oneLine = ServerFiles.Handle("files:get:{\"root\":\"scenario\",\"items\":[{\"path\":\"SharedData/Content/Images/Big.jpg\"}]}");
                Check("reply is a single line with no BOM", oneLine.IndexOf('\n') < 0 && oneLine.IndexOf('\r') < 0 && oneLine[0] == '{');

                // ---------------- path safety
                string[] evil =
                {
                    "../outside/stolen.ecf", "Content/../../outside/stolen.ecf", "Content/Configuration/../../../outside/stolen.ecf",
                    "..\\outside\\stolen.ecf", "/etc/passwd.ecf", "\\Windows\\win.ini", "C:\\Windows\\win.ini", "C:/x.ecf",
                    "Content//Configuration/Items.ecf", "./Content/Configuration/Items.ecf", "Content/./Configuration/Items.ecf",
                    "Content/Configuration/Items.ecf.", "Content/Configuration/Items.ecf ", "Content/Configuration/Items.ecf:stream.ecf",
                    "Content/Configuration/NUL.ecf", "Content/CON/Items.ecf", "Content/Configuration/It\0ems.ecf",
                    "Content/Configuration/*.ecf", "", "Content", "Content/Configuration/"
                };
                foreach (string path in evil)
                {
                    string err;
                    string normalized = ServerFiles.NormalizeRelativePath("scenario", path, out err);
                    Check("refused path: " + path.Replace("\0", "\\0"), normalized == null && err != null, "normalized=" + normalized);
                }
                string e1;
                Check("refused: not whitelisted extension", ServerFiles.NormalizeRelativePath("scenario", "Content/Configuration/notes.exe", out e1) == null && e1 == "not_allowed");
                Check("refused: not whitelisted folder", ServerFiles.NormalizeRelativePath("scenario", "Playfields/Secret/playfield_static.yaml", out e1) == null && e1 == "not_allowed");
                Check("refused: folder prefix is whole segments only", ServerFiles.NormalizeRelativePath("scenario", "ContentEvil/Items.ecf", out e1) == null && e1 == "not_allowed");
                Check("refused: unknown root", ServerFiles.NormalizeRelativePath("../x", "Content/Items.ecf", out e1) == null);
                Check("save-only folder refused for scenario", ServerFiles.NormalizeRelativePath("scenario", "Shared/Content/Configuration/Save.ecf", out e1) == null);
                Check("save-only folder allowed for save", ServerFiles.NormalizeRelativePath("save", "Shared/Content/Configuration/Save.ecf", out e1) != null);
                Check("backslashes are normalized", ServerFiles.NormalizeRelativePath("scenario", "Content\\Configuration\\Items.ecf", out e1) == "Content/Configuration/Items.ecf");

                // Attacks through the full command, including the file that really exists outside the root.
                foreach (string path in new[] { "../outside/stolen.ecf", "Content/../../../outside/stolen.ecf", "..\\..\\outside\\stolen.ecf" })
                {
                    JObject r = Run("files:get:{\"root\":\"scenario\",\"items\":[{\"path\":" + Newtonsoft.Json.JsonConvert.SerializeObject(path) + "}]}");
                    Check("get refuses traversal: " + path, r["files"][0]["data"] == null && r["files"][0]["error"] != null);
                }
                JObject missing = Run("files:get:{\"root\":\"scenario\",\"items\":[{\"path\":\"Content/Configuration/Nope.ecf\"}]}");
                Check("get reports not_found", (string)missing["files"][0]["error"] == "not_found");
                JObject wrongRoot = Run("files:get:{\"root\":\"scenario\",\"items\":[{\"path\":\"Shared/Content/Configuration/Save.ecf\"}]}");
                Check("get refuses a save path under the scenario root", wrongRoot["files"][0]["data"] == null);
                if (symlinkMade)
                {
                    JObject l1 = Run("files:get:{\"root\":\"scenario\",\"items\":[{\"path\":\"Content/Configuration/Linked.ecf\"}]}");
                    Check("get refuses a symlinked file", l1["files"][0]["data"] == null);
                    JObject l2 = Run("files:get:{\"root\":\"scenario\",\"items\":[{\"path\":\"Content/LinkToOutside/stolen.ecf\"}]}");
                    Check("get refuses a path through a symlinked folder", l2["files"][0]["data"] == null);
                }
                else Console.WriteLine("SKIP  symlink checks (symlinks could not be created here)");

                // ---------------- request shape errors
                Check("get with no items fails", !(bool)Run("files:get:{\"root\":\"scenario\"}")["ok"]);
                string manyItems = string.Join(",", Enumerable.Range(0, 51).Select(i => "{\"path\":\"Content/Configuration/Items.ecf\"}"));
                Check("get with 51 items fails", (string)Run("files:get:{\"root\":\"scenario\",\"items\":[" + manyItems + "]}")["error"] == "too_many_items");
                Check("bad JSON fails", (string)Run("files:get:{not json")["error"] == "bad_request");
                Check("unknown sub-command fails", (string)Run("files:delete:{\"root\":\"scenario\"}")["error"] == "unknown_command");
                Check("negative offset reads from zero", (long)Run("files:get:{\"root\":\"scenario\",\"items\":[{\"path\":\"Content/Configuration/Items.ecf\",\"offset\":-5}]}")["files"][0]["offset"] == 0);
                Check("offset past the end is refused", Run("files:get:{\"root\":\"scenario\",\"items\":[{\"path\":\"Content/Configuration/Items.ecf\",\"offset\":999}]}")["files"][0]["error"] != null);
                Check("numeric req_id echoed as string", (string)Run("files:info:{\"req_id\":42}")["req_id"] == "42");

                // ---------------- file stays unchanged (read-only proof)
                Check("source file untouched after reads", File.ReadAllText(Path.Combine(scenario, "Content", "Configuration", "Items.ecf")) == "Item text\n");

                // ---------------- read while another handle holds the file open for writing
                using (var writer = new FileStream(Path.Combine(scenario, "Content", "Configuration", "Items.ecf"), FileMode.Open, FileAccess.Write, FileShare.ReadWrite))
                {
                    JToken shared = Run("files:get:{\"root\":\"scenario\",\"items\":[{\"path\":\"Content/Configuration/Items.ecf\"}]}")["files"][0];
                    Check("readable while the game holds it open for writing", shared["data"] != null);
                }

                // =============================================================
                // 1.6.2 write commands: files:put and coreupload:
                // =============================================================
                string modDir = Path.Combine(temp, "mod");
                Directory.CreateDirectory(modDir);
                string itemsPath = Path.Combine(scenario, "Content", "Configuration", "Items.ecf");
                byte[] oldItems = File.ReadAllBytes(itemsPath);
                byte[] newItems = Encoding.UTF8.GetBytes("Item text\nedited by ZAH\n");

                // ---------------- not ready without a mod folder
                ServerFileWrites.ModDirectory = null;
                Check("put refused before the mod folder is known", (string)SendInChunks("scenario", "Content/Configuration/Items.ecf", newItems, Sha(oldItems), 64)["error"] == "not_ready");
                ServerFileWrites.ModDirectory = modDir;
                Check("info reports canWrite", (bool)Run("files:info")["canWrite"] && (int)Run("files:info")["writeProtocol"] == 1);

                // ---------------- kill switch
                AuthConfig.WritesOff = true;
                Check("put refused when FileWritesEnabled is false", (string)SendInChunks("scenario", "Content/Configuration/Items.ecf", newItems, Sha(oldItems), 64)["error"] == "writes_disabled");
                Check("coreupload refused when FileWritesEnabled is false", (string)SendInChunks(null, null, new byte[] { 1 }, null, 64, "dll")["error"] == "writes_disabled");
                AuthConfig.WritesOff = false;
                Check("file unchanged after refused puts", File.ReadAllBytes(itemsPath).SequenceEqual(oldItems));

                // ---------------- a good put, in several chunks
                JObject put = SendInChunks("scenario", "Content/Configuration/Items.ecf", newItems, Sha(oldItems), 7);
                Check("put succeeds", (bool)put["ok"] && (bool)put["done"], put.ToString());
                Check("put replaced the file exactly", File.ReadAllBytes(itemsPath).SequenceEqual(newItems));
                string backupFull = put["backup"] != null ? Path.Combine(modDir, ((string)put["backup"]).Replace('/', Path.DirectorySeparatorChar)) : "";
                Check("put made a backup first under Backups/files/scenario", ((string)put["backup"] ?? "").StartsWith("Backups/files/scenario/Content/Configuration/Items.ecf.") && File.Exists(backupFull));
                Check("backup holds the old content", File.Exists(backupFull) && File.ReadAllBytes(backupFull).SequenceEqual(oldItems));
                Check("no temp or part files left behind",
                    !Directory.GetFiles(Path.Combine(scenario, "Content", "Configuration")).Any(f => f.EndsWith(".tmp")) && Directory.GetFiles(Path.Combine(modDir, "Uploads")).Length == 0);
                Check("put reply is one line", ServerFiles.Handle("files:put:{\"root\":\"scenario\"}").IndexOf('\n') < 0);

                // ---------------- second put keeps both backups
                byte[] newer = Encoding.UTF8.GetBytes("third version\n");
                JObject put2 = SendInChunks("scenario", "Content/Configuration/Items.ecf", newer, Sha(newItems), 1024);
                Check("second put succeeds and keeps the first backup", (bool)put2["ok"] && File.Exists(backupFull) && (string)put2["backup"] != (string)put["backup"]);

                // ---------------- refusals
                Check("put refused when the server copy changed (stale base)", (string)SendInChunks("scenario", "Content/Configuration/Items.ecf", newItems, Sha(oldItems), 64)["error"] == "changed_on_server");
                Check("put refused on hash mismatch", (string)SendInChunks("scenario", "Content/Configuration/Items.ecf", newItems, Sha(newer), 4, null, new string('a', 64))["error"] == "hash_mismatch");
                Check("file unchanged after hash mismatch", File.ReadAllBytes(itemsPath).SequenceEqual(newer));
                Check("put refuses a new file", (string)SendInChunks("scenario", "Content/Configuration/New.ecf", newItems, new string('0', 64), 64)["error"] == "not_found");
                Check("put refuses .png", (string)SendInChunks("scenario", "SharedData/Content/Images/Small.png", newItems, new string('0', 64), 64)["error"] == "not_allowed");
                Check("put refuses .json", SendInChunks("scenario", "Content/Configuration/secrets.json", newItems, new string('0', 64), 64)["ok"].Value<bool>() == false);
                Check("put refuses traversal", SendInChunks("scenario", "../outside/stolen.ecf", newItems, new string('0', 64), 64)["ok"].Value<bool>() == false
                    && File.ReadAllText(Path.Combine(outside, "stolen.ecf")) == "must never be readable\n");
                Check("put refuses a non-whitelisted folder", SendInChunks("scenario", "Playfields/Secret/playfield_static.yaml", newItems, new string('0', 64), 64)["ok"].Value<bool>() == false);
                if (symlinkMade) Check("put refuses a symlinked file", SendInChunks("scenario", "Content/Configuration/Linked.ecf", newItems, Sha(Encoding.UTF8.GetBytes("must never be readable\n")), 64)["ok"].Value<bool>() == false
                    && File.ReadAllText(Path.Combine(outside, "stolen.ecf")) == "must never be readable\n");
                Check("put refuses a chunk out of order", (string)Run("files:put:" + new JObject { ["root"] = "scenario", ["path"] = "Content/Configuration/Items.ecf", ["offset"] = 5, ["total"] = 10, ["sha256"] = new string('a', 64), ["data"] = "AAAA" }.ToString(Newtonsoft.Json.Formatting.None))["error"] == "bad_offset");
                Check("put refuses a file over 16 MB", (string)Run("files:put:" + new JObject { ["root"] = "scenario", ["path"] = "Content/Configuration/Items.ecf", ["offset"] = 0, ["total"] = ServerFiles.MaxFileBytes + 1, ["sha256"] = new string('a', 64), ["base_sha256"] = Sha(newer), ["data"] = "" }.ToString(Newtonsoft.Json.Formatting.None))["error"] == "too_large");
                Check("put refuses an oversized chunk", (string)SendInChunks("scenario", "Content/Configuration/Items.ecf", new byte[ServerFileWrites.MaxChunkBytes + 1], Sha(newer), ServerFileWrites.MaxChunkBytes + 1)["error"] == "bad_request");
                Check("put needs base_sha256", (string)SendInChunks("scenario", "Content/Configuration/Items.ecf", newItems, "", 64)["error"] == "bad_request");
                Check("save root put works", (bool)SendInChunks("save", "Shared/Content/Configuration/Save.ecf", newItems, Sha(Encoding.UTF8.GetBytes("save file\n")), 64)["ok"]);
                Check("file still the last good version after refusals", File.ReadAllBytes(itemsPath).SequenceEqual(newer));

                // ---------------- coreupload: with the real core build when it exists
                string builtCore = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "CoreProject", "bin", "Release", "net48", "ZeroGBridge.Core.dll"));
                Check("corestatus empty at first", RunCore("coreupload:status")["files"].Count() == 0);
                Check("coreupload refuses a non-DLL", (string)SendInChunks(null, null, Encoding.UTF8.GetBytes("not a dll"), null, 64, "dll")["error"] == "bad_core");
                string otherDll = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "Newtonsoft.Json.dll"));
                if (File.Exists(otherDll)) Check("coreupload refuses a DLL that is not ZeroGBridge.Core", (string)SendInChunks(null, null, File.ReadAllBytes(otherDll), null, 100000, "dll")["error"] == "bad_core");
                Check("coreupload refuses an unknown file kind", (string)RunCore("coreupload:put:{\"file\":\"json\",\"offset\":0,\"total\":1}")["error"] == "bad_request");
                Check("coreupload refuses over 8 MB", (string)RunCore("coreupload:put:" + new JObject { ["file"] = "dll", ["offset"] = 0, ["total"] = ServerFileWrites.MaxCoreBytes + 1, ["sha256"] = new string('a', 64), ["data"] = "" }.ToString(Newtonsoft.Json.Formatting.None))["error"] == "too_large");
                Check("nothing placed in Updates/ after refusals", !Directory.Exists(Path.Combine(modDir, "Updates")) || Directory.GetFiles(Path.Combine(modDir, "Updates")).Length == 0);
                if (File.Exists(builtCore))
                {
                    byte[] coreBytes = File.ReadAllBytes(builtCore);
                    byte[] pdbBytes = File.Exists(Path.ChangeExtension(builtCore, ".pdb")) ? File.ReadAllBytes(Path.ChangeExtension(builtCore, ".pdb")) : new byte[] { 1, 2, 3 };
                    JObject pdbPut = SendInChunks(null, null, pdbBytes, null, ServerFileWrites.MaxChunkBytes, "pdb");
                    JObject dllPut = SendInChunks(null, null, coreBytes, null, ServerFileWrites.MaxChunkBytes, "dll");
                    string placed = Path.Combine(modDir, "Updates", "ZeroGBridge.Core.dll");
                    Check("coreupload places the pdb", (bool)pdbPut["ok"] && File.ReadAllBytes(Path.Combine(modDir, "Updates", "ZeroGBridge.Core.pdb")).SequenceEqual(pdbBytes));
                    Check("coreupload places the dll byte for byte", (bool)dllPut["ok"] && File.ReadAllBytes(placed).SequenceEqual(coreBytes) && (bool)dllPut["pendingDrop"], dllPut.ToString());
                    Check("coreupload reads the core version", ((string)dllPut["assemblyVersion"] ?? "").StartsWith("1.6."));
                    JObject again = SendInChunks(null, null, coreBytes, null, ServerFileWrites.MaxChunkBytes, "dll");
                    Check("second coreupload backs up the waiting dll", (bool)again["ok"] && ((string)again["backup"] ?? "").StartsWith("Backups/core/ZeroGBridge.Core.dll."));
                    JObject status = RunCore("coreupload:status");
                    Check("corestatus shows the waiting dll with its sha256", status["files"].Any(f => (string)f["name"] == "ZeroGBridge.Core.dll" && (string)f["sha256"] == Sha(coreBytes)));
                }
                else Console.WriteLine("SKIP  real core upload (build CoreProject Release first)");
            }
            finally
            {
                // Only the temporary folder this test made is removed.
                try { Directory.Delete(temp, true); } catch { }
            }

            Console.WriteLine($"\nResult: {_passed} passed, {_failed} failed");
            return _failed == 0 ? 0 : 1;
        }
    }
}
