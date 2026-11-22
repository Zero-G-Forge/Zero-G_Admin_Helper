## =====================================================================
## TEST: tests/test_server_files.py
## DESCRIPTION: Checks for the Settings page SERVER FILES download (read-only).
##   - the local-path safety checks and folder names
##   - the real download against the REAL C# ServerFiles code (via ZeroGBridge/tests/ServerFilesTest "serve" mode;
##     skipped when dotnet or the built test DLL is missing)
##   - an old bridge (fail-closed message), and an unreachable server
##   - the Settings page button states, offscreen
## Run from the app root:  QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q
## Nothing here touches data/ or any real server: settings and downloads go to a temporary folder,
## and the "server" is a local process with a made-up test token.
## =====================================================================

# region Imports

import os
import shutil
import socket
import subprocess
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMainWindow

from features.server_files import file_client, file_store
from features.server_files.download_worker import ServerFileDownloadWorker
from features.settings import app_settings, settings_page

# endregion


# region Helpers

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DLL = os.path.join(APP_ROOT, "ZeroGBridge", "tests", "ServerFilesTest", "bin", "Debug", "net10.0", "ServerFilesTest.dll")
TEST_TOKEN = "unit-test-token-not-a-real-secret"


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    ## Downloads and app settings go to a temporary folder, never to the real data/ folder.
    monkeypatch.setattr(file_store, "SERVER_FILES_DIR", str(tmp_path / "server_files"))
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", str(tmp_path / "app_settings.json"))
    monkeypatch.setattr(file_client, "COMMAND_GAP_SEC", 0.0)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_fake_bridge(tmp_path, scenario, save, old=False):
    port = free_port()
    env = dict(os.environ, ZGB_TEST_TOKEN=TEST_TOKEN)
    args = ["dotnet", TEST_DLL, "serve", str(port), str(scenario), str(save)] + (["old"] if old else [])
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    process.stdout.readline()
    return process, port


def make_profile(port):
    return {"server_name": "Test", "input_ip": "127.0.0.1", "input_pass": TEST_TOKEN, "bridge_port": str(port)}


def build_server_tree(root):
    scenario = root / "Content" / "Scenarios" / "Test-Scenario"
    save = root / "Saves" / "Games" / "TestSave"
    for folder in (scenario / "Content" / "Configuration", scenario / "SharedData" / "Content" / "Images",
                   scenario / "SharedData" / "Content" / "Extras" / "PDA", save / "Shared" / "Content" / "Configuration"):
        folder.mkdir(parents=True)
    (scenario / "Content" / "Configuration" / "Items.ecf").write_bytes(b"Item data\n" * 50)
    (scenario / "SharedData" / "Content" / "Extras" / "PDA" / "PDA.yaml").write_bytes(b"pda: 1\n")
    (save / "Shared" / "Content" / "Configuration" / "Save.ecf").write_bytes(b"save data\n")
    (save / "global.db").write_bytes(b"never sent")
    ## 120 small images fill many batches; one 400 KB file forces chunking.
    images = scenario / "SharedData" / "Content" / "Images"
    for number in range(120):
        (images / f"Item{number:03d}.jpg").write_bytes(bytes([number % 256]) * (1000 + number))
    (images / "Big.jpg").write_bytes(os.urandom(400 * 1024))
    return scenario, save


def run_worker(profile):
    worker = ServerFileDownloadWorker(profile_provider=lambda: profile)
    result = {"progress": [], "ok": None, "failed": None}
    worker.progress.connect(lambda done, total, text: result["progress"].append((done, total, text)))
    worker.finished_ok.connect(lambda summary: result.__setitem__("ok", summary))
    worker.failed.connect(lambda message: result.__setitem__("failed", message))
    ## run() called directly executes on this thread: same code as the thread, easier to test.
    worker.run()
    return result

# endregion


# region Local Path Safety

@pytest.mark.parametrize("bad", ["../x.ecf", "a/../../x.ecf", "/etc/x.ecf", "C:/x.ecf", "a//b.ecf", "./a.ecf", "a/./b.ecf",
                                 "", "a/b.ecf\0", "..\\x.ecf", "a\\..\\..\\x.ecf", "a:b.ecf", None, 5])
def test_local_target_path_refuses_unsafe(tmp_path, bad):
    assert file_store.local_target_path(str(tmp_path), bad) is None


def test_local_target_path_accepts_normal(tmp_path):
    target = file_store.local_target_path(str(tmp_path), "Content/Configuration/Items.ecf")
    assert target == os.path.join(os.path.abspath(str(tmp_path)), "Content", "Configuration", "Items.ecf")
    ## Backslashes from a Windows server are treated as folder separators.
    assert file_store.local_target_path(str(tmp_path), "Content\\Items.ecf") == os.path.join(os.path.abspath(str(tmp_path)), "Content", "Items.ecf")


@pytest.mark.parametrize("name,expected", [("Ascension-Reborn", "Ascension-Reborn"), ("../../etc", "_.._etc"),
                                           ("", "unknown_scenario"), (None, "unknown_scenario"), ("..", "unknown_scenario")])
def test_safe_folder_name(name, expected):
    result = file_store.safe_folder_name(name)
    assert result == expected
    assert "/" not in result and "\\" not in result and result not in ("", ".", "..")

# endregion


# region Download Against The Real Bridge Code

needs_dotnet = pytest.mark.skipif(shutil.which("dotnet") is None or not os.path.isfile(TEST_DLL),
                                  reason="needs dotnet and a built ZeroGBridge/tests/ServerFilesTest (dotnet build)")


@needs_dotnet
def test_full_download_skip_and_refresh(tmp_path, qapp):
    scenario, save = build_server_tree(tmp_path / "srv")
    process, port = start_fake_bridge(tmp_path, scenario, save)
    try:
        profile = make_profile(port)

        first = run_worker(profile)
        assert first["failed"] is None, first["failed"]
        summary = first["ok"]
        assert summary["scenario"] == "Test-Scenario"
        assert summary["failed"] == []
        ## 120 small + Big + Items.ecf + PDA.yaml + Save.ecf = 124 files, and global.db is never offered.
        assert summary["downloaded"] == 124 and summary["skipped"] == 0

        folder = file_store.scenario_folder("Test-Scenario")
        assert summary["folder"] == folder
        for rel in ("Content/Configuration/Items.ecf", "SharedData/Content/Images/Big.jpg", "SharedData/Content/Images/Item007.jpg",
                    "SharedData/Content/Extras/PDA/PDA.yaml"):
            assert open(os.path.join(folder, "scenario", *rel.split("/")), "rb").read() == open(os.path.join(scenario, *rel.split("/")), "rb").read()
        assert open(os.path.join(folder, "save", "Shared", "Content", "Configuration", "Save.ecf"), "rb").read() == b"save data\n"
        assert not os.path.exists(os.path.join(folder, "save", "global.db"))
        ## No half-finished files are left behind.
        leftovers = [name for _, _, names in os.walk(folder) for name in names if name.endswith(".part") and name != "_manifest.json.part"]
        assert leftovers == []
        ## The progress bar saw real numbers, ending at done == total.
        counted = [entry for entry in first["progress"] if entry[1] > 0]
        assert counted and counted[-1][0] == counted[-1][1] == 124

        ## Second run: nothing changed, so nothing is downloaded.
        second = run_worker(profile)
        assert second["ok"]["downloaded"] == 0 and second["ok"]["skipped"] == 124

        ## Change one file on the server (different size): only that file comes down again.
        (scenario / "Content" / "Configuration" / "Items.ecf").write_bytes(b"Changed item data\n")
        third = run_worker(profile)
        assert third["ok"]["downloaded"] == 1 and third["ok"]["skipped"] == 123
        assert open(os.path.join(folder, "scenario", "Content", "Configuration", "Items.ecf"), "rb").read() == b"Changed item data\n"
        ## The server's own file is untouched by all of this.
        assert (scenario / "Content" / "Configuration" / "Items.ecf").read_bytes() == b"Changed item data\n"
    finally:
        process.kill()
        process.wait()


@needs_dotnet
def test_old_bridge_fails_closed(tmp_path, qapp):
    scenario, save = build_server_tree(tmp_path / "srv")
    process, port = start_fake_bridge(tmp_path, scenario, save, old=True)
    try:
        result = run_worker(make_profile(port))
        assert result["ok"] is None
        assert "does not have the file commands yet" in result["failed"]
        ## Nothing was written locally.
        assert not os.path.exists(file_store.SERVER_FILES_DIR)
    finally:
        process.kill()
        process.wait()


@needs_dotnet
def test_wrong_token_is_a_clear_error(tmp_path, qapp):
    scenario, save = build_server_tree(tmp_path / "srv")
    process, port = start_fake_bridge(tmp_path, scenario, save)
    try:
        profile = make_profile(port)
        profile["input_pass"] = "some-other-token"
        result = run_worker(profile)
        assert result["ok"] is None and "rejected" in result["failed"]
        ## The wrong or right token never appears in the message.
        assert "some-other-token" not in result["failed"] and TEST_TOKEN not in result["failed"]
    finally:
        process.kill()
        process.wait()


def test_unreachable_server_message(qapp):
    result = run_worker(make_profile(free_port()))
    assert result["ok"] is None
    assert "Could not reach the server" in result["failed"]


def test_missing_profile_message(qapp):
    result = run_worker(None)
    assert result["failed"] == "No active server is saved in ZAH."

# endregion


# region Settings Page States

class FakeCockpit(QMainWindow):
    ## Stands in for MainCockpit: the same signal and the same two attributes the page reads.
    bridge_status_changed = pyqtSignal(str, bool)

    def __init__(self):
        super().__init__()
        self.bridge_connected = None
        self.bridge_server_name = None


class FakeWorker(QThread):
    ## A thread that finishes at once, with a made-up result.
    progress = pyqtSignal(int, int, str)
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)
    outcome = {"downloaded": 3, "skipped": 2, "failed": [], "folder": "/tmp/zah_fake_folder"}
    fail_message = None

    def run(self):
        self.progress.emit(1, 5, "Downloading 1 of 5 files")
        if FakeWorker.fail_message:
            self.failed.emit(FakeWorker.fail_message)
        else:
            self.finished_ok.emit(dict(FakeWorker.outcome))


def build_page(qapp):
    cockpit = FakeCockpit()
    page = settings_page.SettingsPage()
    cockpit.setCentralWidget(page)
    cockpit.show()
    qapp.processEvents()
    return cockpit, page


def wait_until(qapp, condition, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not condition():
        qapp.processEvents()
        time.sleep(0.01)
    return condition()


def test_button_follows_bridge_connection(qapp):
    cockpit, page = build_page(qapp)
    ## No news from the bridge yet: fail closed.
    assert page.btn_download_files.isEnabled() is False
    cockpit.bridge_connected = True
    cockpit.bridge_status_changed.emit("Test", True)
    assert page.btn_download_files.isEnabled() is True
    cockpit.bridge_connected = False
    cockpit.bridge_status_changed.emit("Test", False)
    assert page.btn_download_files.isEnabled() is False
    assert "Connect to the server first" in page.btn_download_files.toolTip()
    ## LIVE MODE stays off and disabled in every state.
    assert page.chk_live_mode.isEnabled() is False and page.chk_live_mode.isChecked() is False
    cockpit.close()


def test_page_without_a_cockpit_stays_disabled(qapp):
    page = settings_page.SettingsPage()
    page.show()
    qapp.processEvents()
    assert page.btn_download_files.isEnabled() is False
    page.close()


def test_click_runs_worker_and_saves_result(qapp, monkeypatch):
    FakeWorker.fail_message = None
    cockpit, page = build_page(qapp)
    page.create_download_worker = FakeWorker
    cockpit.bridge_connected = True
    cockpit.bridge_status_changed.emit("Test", True)
    assert page.lbl_files_pulled.text() == "LAST PULLED:  never"
    page.btn_download_files.click()
    ## While running the button is off and shows DOWNLOADING.
    assert page.download_worker is not None
    assert page.btn_download_files.isEnabled() is False and page.btn_download_files.text() == "DOWNLOADING"
    assert wait_until(qapp, lambda: page.download_worker is None)
    assert page.btn_download_files.isEnabled() is True
    assert page.btn_download_files.text() == "DOWNLOAD SERVER FILES (READ-ONLY)"
    assert page.bar_download_progress.isHidden()
    assert "Done. 3 new or changed, 2 already up to date." in page.lbl_download_status.text()
    assert page.lbl_files_folder.text() == "LOCAL COPY:  /tmp/zah_fake_folder"
    assert page.lbl_files_pulled.text() != "LAST PULLED:  never"
    saved = app_settings.load_app_settings()
    assert saved["server_files_local_folder"] == "/tmp/zah_fake_folder" and saved["server_files_last_pulled"]
    ## A new page shows the saved values.
    cockpit2, page2 = build_page(qapp)
    assert page2.lbl_files_folder.text() == "LOCAL COPY:  /tmp/zah_fake_folder"
    assert page2.lbl_files_pulled.text().startswith("LAST PULLED:  20")
    cockpit.close()
    cockpit2.close()


def test_failed_download_shows_message_and_keeps_last_pulled(qapp):
    FakeWorker.fail_message = "This server's ZeroGBridge does not have the file commands yet. Ask the owner to update the bridge."
    cockpit, page = build_page(qapp)
    page.create_download_worker = FakeWorker
    cockpit.bridge_connected = True
    cockpit.bridge_status_changed.emit("Test", True)
    page.btn_download_files.click()
    assert wait_until(qapp, lambda: page.download_worker is None)
    assert page.lbl_download_status.text().startswith("Download failed: This server's ZeroGBridge does not have the file commands yet")
    assert page.lbl_files_pulled.text() == "LAST PULLED:  never"
    assert page.btn_download_files.isEnabled() is True
    assert app_settings.load_app_settings()["server_files_last_pulled"] == ""
    FakeWorker.fail_message = None
    cockpit.close()


def test_partial_download_does_not_update_last_pulled(qapp):
    FakeWorker.fail_message = None
    monkey = dict(FakeWorker.outcome)
    FakeWorker.outcome = {"downloaded": 3, "skipped": 0, "failed": [{"path": "scenario/x.ecf", "error": "read_failed"}], "folder": "/tmp/zah_fake_folder"}
    try:
        cockpit, page = build_page(qapp)
        page.create_download_worker = FakeWorker
        cockpit.bridge_connected = True
        cockpit.bridge_status_changed.emit("Test", True)
        page.btn_download_files.click()
        assert wait_until(qapp, lambda: page.download_worker is None)
        assert "would not send 1 file(s)" in page.lbl_download_status.text()
        assert page.lbl_files_pulled.text() == "LAST PULLED:  never"
        cockpit.close()
    finally:
        FakeWorker.outcome = monkey

# endregion


# region Download Cancel and Editor DOWNLOAD FOLDER

class SlowWorker(QThread):
    ## Runs until request_stop, then reports "Download stopped." like the real worker.
    progress = pyqtSignal(int, int, str)
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stop_asked = False

    def request_stop(self):
        self.stop_asked = True

    def run(self):
        end = time.monotonic() + 5
        while not self.stop_asked and time.monotonic() < end:
            time.sleep(0.01)
        self.failed.emit("Download stopped.")


def test_cancel_stops_a_running_download(qapp):
    cockpit, page = build_page(qapp)
    page.create_download_worker = SlowWorker
    cockpit.bridge_connected = True
    cockpit.bridge_status_changed.emit("Test", True)
    assert page.chk_live_mode.toolTip() != "Coming in a later step."
    page.btn_download_files.click()
    assert page.btn_cancel_download.isVisible() and page.btn_cancel_download.isEnabled()
    page.btn_cancel_download.click()
    assert wait_until(qapp, lambda: page.download_worker is None)
    assert "Download stopped." in page.lbl_download_status.text()
    assert page.btn_cancel_download.isHidden() and page.btn_download_files.isEnabled()
    cockpit.close()


def test_editor_download_folder_runs_the_read_only_download(qapp, tmp_path):
    from features.ecf_editor.ecf_editor_page import EcfEditorPage
    FakeWorker.fail_message = None
    cockpit = FakeCockpit()
    page = EcfEditorPage()
    cockpit.setCentralWidget(page)
    cockpit.show()
    qapp.processEvents()
    assert page.btn_download.isEnabled() is False and "Connect" in page.btn_download.toolTip()
    cockpit.bridge_connected = True
    page._refresh_edit_buttons()
    assert page.btn_download.isEnabled() is True
    page.create_download_worker = FakeWorker
    reloaded = []
    page.load_server_files = lambda folder=None: reloaded.append(folder)
    page.btn_download.click()
    assert wait_until(qapp, lambda: page.download_worker is None)
    assert reloaded == [None] and page.btn_download.text() == "DOWNLOAD FOLDER FROM SERVER (READ-ONLY)"
    assert app_settings.load_app_settings()["server_files_local_folder"] == "/tmp/zah_fake_folder"
    cockpit.close()

# endregion
