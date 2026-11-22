// =====================================================================
// MODULE: ZeroGBridge/tests/ServerFilesTest/Program.cs
// DESCRIPTION: Self-checks for the read-only files: commands (path safety, list, get, chunking).
// Exit code 0 = every check passed, 1 = at least one failed.
// =====================================================================

using System;
using System.IO;
using System.Linq;
using System.Text;
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

        private static int Main()
        {
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
