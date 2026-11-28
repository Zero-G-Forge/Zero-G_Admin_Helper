## =====================================================================
## TEST: tests/test_server_files.py
## DESCRIPTION: Checks for the Settings page SERVER FILES download (read-only).
##   - the local-path safety checks and folder names
##   - the real download against the REAL C# ServerFiles code (via ZeroGBridge/tests/ServerFilesTest "serve" mode;
##     skipped when dotnet or the built test DLL is missing)
##   - an old bridge (fail-closed message), and an unreachable server
##   - the Settings page button states, offscreen
##   - the download keeps running after Settings is closed and rebuilt, and CANCEL still works
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

from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMainWindow

from features.server_files import download_settings, file_client, file_store
from features.server_files.download_worker import ServerFileDownloadWorker
from features.server_files.file_client import ServerFilesSession
from features.settings import app_settings, settings_page
from features.server_files import download_manager
import importlib
import threading

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
    monkeypatch.setattr(download_settings, "DOWNLOAD_SETTINGS_FILE", str(tmp_path / "download_settings.json"))
    monkeypatch.setattr(file_client, "COMMAND_GAP_SEC", 0.0)
    ## Existing page tests must not open a catalog thread against a real server.
    monkeypatch.setattr(settings_page, "AUTO_FETCH_CATALOG", False)
    download_manager.reset()
    yield
    download_manager.reset()


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


def run_worker(profile, selection=None):
    worker = ServerFileDownloadWorker(profile_provider=lambda: profile, selection=selection)
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
def test_harness_lists_epb_under_prefabs(tmp_path, qapp):
    """The local ServerFilesTest serve harness, with ZGB_TEST_MODDIR set, lists a Prefabs .epb."""
    scenario, save = build_server_tree(tmp_path / "srv")
    prefabs = scenario / "Prefabs"
    prefabs.mkdir(parents=True)
    (prefabs / "TestShip.epb").write_bytes(b"\x45\x52\x94\x78" + b"\x00" * 8)
    (prefabs / "note.txt").write_bytes(b"not listed\n")
    moddir = tmp_path / "moddir"
    moddir.mkdir()
    port = free_port()
    env = dict(os.environ, ZGB_TEST_TOKEN=TEST_TOKEN, ZGB_TEST_MODDIR=str(moddir))
    process = subprocess.Popen(
        ["dotnet", TEST_DLL, "serve", str(port), str(scenario), str(save)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    try:
        process.stdout.readline()
        with ServerFilesSession(make_profile(port)) as session:
            reply = session.request("list", {"root": "scenario", "offset": 0, "limit": 2000})
        assert reply.get("ok") is True, reply
        paths = [entry["path"] for entry in (reply.get("files") or [])]
        assert "Prefabs/TestShip.epb" in paths
        assert not any(path.endswith(".txt") for path in paths)
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
        self.bridge_connected: bool | None = None
        self.bridge_server_name = None


class FakeWorker(QThread):
    ## A thread that finishes at once, with a made-up result.
    progress = pyqtSignal(int, int, str)
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)
    outcome = {"downloaded": 3, "skipped": 2, "failed": [], "folder": "/tmp/zah_fake_folder"}
    fail_message: str | None = None
    last_selection = None

    def __init__(self, parent=None, selection=None, **kwargs):
        super().__init__(parent)
        FakeWorker.last_selection = selection

    def run(self):
        self.progress.emit(1, 5, "Downloading 1 of 5 files")
        if FakeWorker.fail_message:
            self.failed.emit(FakeWorker.fail_message)
        else:
            self.finished_ok.emit(dict(FakeWorker.outcome))


def build_page(qapp):
    cockpit = FakeCockpit()
    page: Any = settings_page.SettingsPage()
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

    def __init__(self, parent=None, selection=None, **kwargs):
        super().__init__(parent)
        self.stop_asked = False
        self.selection = selection

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


def test_download_keeps_running_after_the_page_is_closed(qapp):
    cockpit, page = build_page(qapp)
    page.create_download_worker = SlowWorker
    cockpit.bridge_connected = True
    cockpit.bridge_status_changed.emit("Test", True)
    page.btn_download_files.click()
    worker = page.download_worker
    assert worker is not None and worker.isRunning()
    page.hide()
    page.deleteLater()
    cockpit.close()
    qapp.processEvents()
    assert download_manager.is_running()
    cockpit2, page2 = build_page(qapp)
    cockpit2.bridge_connected = True
    qapp.processEvents()
    assert page2.btn_download_files.text() == "DOWNLOADING"
    assert page2.btn_download_files.isEnabled() is False
    assert page2.btn_cancel_download.isVisible() and page2.btn_cancel_download.isEnabled()
    assert page2.bar_download_progress.isVisible()
    assert page2.download_worker is worker
    page2.btn_cancel_download.click()
    assert wait_until(qapp, lambda: page2.download_worker is None)
    assert "Download stopped." in page2.lbl_download_status.text()
    assert page2.btn_cancel_download.isHidden() and page2.btn_download_files.isEnabled()
    cockpit2.close()


class HoldWorker(QThread):
    ## Starts, reports progress, then waits until release is set, then finishes successfully.
    progress = pyqtSignal(int, int, str)
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)
    release: threading.Event | None = None
    outcome = {"downloaded": 3, "skipped": 2, "failed": [], "folder": "/tmp/zah_fake_folder"}

    def __init__(self, parent=None, selection=None, **kwargs):
        super().__init__(parent)
        self.selection = selection

    def run(self):
        self.progress.emit(2, 5, "Downloading 2 of 5 files")
        if HoldWorker.release is not None:
            HoldWorker.release.wait(5)
        self.finished_ok.emit(dict(HoldWorker.outcome))


def test_finished_download_shows_last_pulled_on_a_new_page(qapp):
    release = threading.Event()
    HoldWorker.release = release
    cockpit, page = build_page(qapp)
    page.create_download_worker = HoldWorker
    cockpit.bridge_connected = True
    cockpit.bridge_status_changed.emit("Test", True)
    page.btn_download_files.click()
    assert wait_until(qapp, lambda: "Downloading 2 of 5 files" in page.lbl_download_status.text())
    page.hide()
    page.deleteLater()
    cockpit.close()
    qapp.processEvents()
    assert download_manager.is_running()
    release.set()
    assert wait_until(qapp, lambda: not download_manager.is_running() and download_manager.current_worker() is None)
    cockpit2, page2 = build_page(qapp)
    cockpit2.bridge_connected = True
    cockpit2.bridge_status_changed.emit("Test", True)
    qapp.processEvents()
    assert "Done. 3 new or changed, 2 already up to date." in page2.lbl_download_status.text()
    assert page2.lbl_files_folder.text() == "LOCAL COPY:  /tmp/zah_fake_folder"
    assert page2.lbl_files_pulled.text() != "LAST PULLED:  never"
    assert page2.btn_cancel_download.isHidden()
    assert page2.bar_download_progress.isHidden()
    assert page2.btn_download_files.isEnabled()
    cockpit2.close()
    HoldWorker.release = None


def test_second_download_does_not_start_while_one_is_running(qapp):
    cockpit, page = build_page(qapp)
    page.create_download_worker = SlowWorker
    cockpit.bridge_connected = True
    cockpit.bridge_status_changed.emit("Test", True)
    page.btn_download_files.click()
    first = page.download_worker
    assert first is not None
    page.btn_download_files.click()
    assert page.download_worker is first
    assert len(download_manager.running_workers()) == 1
    first.request_stop()
    assert wait_until(qapp, lambda: page.download_worker is None)
    cockpit.close()


def test_reload_of_settings_module_does_not_drop_a_running_download(qapp):
    cockpit, page = build_page(qapp)
    page.create_download_worker = SlowWorker
    cockpit.bridge_connected = True
    cockpit.bridge_status_changed.emit("Test", True)
    page.btn_download_files.click()
    assert download_manager.is_running()
    importlib.reload(settings_page)
    assert download_manager.is_running()
    download_manager.request_stop()
    assert wait_until(qapp, lambda: not download_manager.is_running())
    cockpit.close()



def test_editor_download_folder_runs_the_read_only_download(qapp, tmp_path):
    from features.ecf_editor.ecf_editor_page import EcfEditorPage
    FakeWorker.fail_message = None
    cockpit = FakeCockpit()
    page: Any = EcfEditorPage()
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
    assert reloaded == [None] and page.btn_download.text() == "FROM SERVER (READ-ONLY)"
    assert app_settings.load_app_settings()["server_files_local_folder"] == "/tmp/zah_fake_folder"
    cockpit.close()

# endregion


# region Download Picker and files:catalog

@pytest.mark.parametrize("name,ok", [
    ("Ascension-Reborn", True),
    ("Zero-G Server - Season 4", True),
    ("Stranded at Nemesis (Survival Challenge)", True),
    ("Invader vs Defender - Conflict of Cygnus", True),
    ("_TestEmpyrion-SE", True),
    ("Default Akua-Omicron", True),
    ("..", False),
    (".", False),
    ("Content/Scenarios", False),
    ("/Ascension-Reborn", False),
    ("Saves\\Games", False),
    ("", False),
    (None, False),
])
def test_plain_folder_names_allow_spaces_and_parentheses(name, ok):
    assert download_settings.is_plain_folder_name(name) is ok


def test_download_settings_persist_per_server(tmp_path):
    assert download_settings.save_server_download_settings(
        "Zero-G Forge Reborn",
        scenario="Ascension-Reborn",
        save="Zero-G Server - Season 4",
        types={"ecf": True, "yaml": True, "csv": False, "images": False},
    )
    saved = download_settings.load_server_download_settings("Zero-G Forge Reborn")
    assert saved["scenario"] == "Ascension-Reborn"
    assert saved["save"] == "Zero-G Server - Season 4"
    assert saved["types"]["csv"] is False and saved["types"]["ecf"] is True
    other = download_settings.load_server_download_settings("Some Other Server")
    assert "scenario" not in other
    assert download_settings.save_server_download_settings("Zero-G Forge Reborn", scenario="..") is False
    assert download_settings.load_server_download_settings("Zero-G Forge Reborn")["scenario"] == "Ascension-Reborn"
    ## A newly added type, missing from the saved file, defaults to on.
    assert saved["types"]["blueprints"] is True


def test_blueprints_type_defaults_on_and_maps_to_epb():
    assert "blueprints" in download_settings.FILE_TYPE_KEYS
    assert download_settings.FILE_TYPE_EXTENSIONS["blueprints"] == (".epb",)
    assert download_settings.DEFAULT_TYPES["blueprints"] is True
    assert ".epb" in download_settings.allowed_extensions({})
    saved = download_settings.types_from_saved({"ecf": True, "yaml": True, "csv": False, "images": False})
    assert saved["blueprints"] is True
    off = download_settings.types_from_saved({"blueprints": False})
    assert off["blueprints"] is False
    assert ".epb" not in download_settings.allowed_extensions(off)


def test_first_available_name_prefers_saved_then_origin_then_fallback():
    names = ["Default Multiplayer", "Ascension-Reborn", "Tutorial"]
    assert download_settings.first_available_name(names, "saved-missing", "Ascension-Reborn", "Tutorial") == "Ascension-Reborn"
    assert download_settings.first_available_name(names, "Tutorial") == "Tutorial"
    assert download_settings.first_available_name(names, "Nope") == "Default Multiplayer"
    assert download_settings.first_available_name([], "Ascension-Reborn") == ""


def test_selection_for_download_is_independent_and_fail_closed():
    types = dict(download_settings.DEFAULT_TYPES)
    assert download_settings.selection_for_download("S", False, "Ascension-Reborn", "Zero-G Server - Season 4", types) is None
    picked = download_settings.selection_for_download("S", True, "Ascension-Reborn", "Zero-G Server - Season 4", types)
    assert picked["scenario"] == "Ascension-Reborn" and picked["save"] == "Zero-G Server - Season 4"
    assert download_settings.selection_for_download("S", True, "..", "Zero-G Server - Season 4", types) is None
    none_types = {key: False for key in download_settings.FILE_TYPE_KEYS}
    assert download_settings.selection_for_download("S", True, "Ascension-Reborn", "Zero-G Server - Season 4", none_types) is None


def test_picker_defaults_to_origin_then_preferred_pair(qapp, monkeypatch):
    monkeypatch.setattr(settings_page, "AUTO_FETCH_CATALOG", True)
    monkeypatch.setattr(settings_page, "get_active_profile", lambda: {"server_name": "Zero-G Forge Reborn"})

    def fake_catalog(profile):
        return {
            "ok": True,
            "current": {"scenario": "Default Multiplayer", "save": "Zero-G Server - Season 4"},
            "originScenario": None,
            "scenarios": ["Default Multiplayer", "Ascension-Reborn", "Tutorial"],
            "saves": ["Zero-G Server", "Zero-G Server - Season 4"],
        }

    monkeypatch.setattr(settings_page, "fetch_file_catalog", fake_catalog)
    cockpit, page = build_page(qapp)
    cockpit.bridge_connected = True
    page._refresh_catalog()
    assert wait_until(qapp, lambda: page.picker_ready)
    ## No saved choice and no origin: the known live pair, not Default Multiplayer.
    assert page.cmb_scenario.currentText() == "Ascension-Reborn"
    assert page.cmb_save.currentText() == "Zero-G Server - Season 4"
    page.cmb_scenario.setCurrentText("Tutorial")
    assert page.cmb_scenario.currentText() == "Tutorial"
    assert page.cmb_save.currentText() == "Zero-G Server - Season 4"
    cockpit.close()


def test_picker_uses_detected_origin_over_preferred(qapp, monkeypatch):
    monkeypatch.setattr(settings_page, "AUTO_FETCH_CATALOG", True)
    monkeypatch.setattr(settings_page, "get_active_profile", lambda: {"server_name": "Zero-G Forge Reborn"})

    def fake_catalog(profile):
        return {
            "ok": True,
            "current": {"scenario": "Default Multiplayer", "save": "Zero-G Server - Season 4"},
            "originScenario": "Tutorial",
            "scenarios": ["Default Multiplayer", "Ascension-Reborn", "Tutorial"],
            "saves": ["Zero-G Server", "Zero-G Server - Season 4"],
        }

    monkeypatch.setattr(settings_page, "fetch_file_catalog", fake_catalog)
    cockpit, page = build_page(qapp)
    cockpit.bridge_connected = True
    page._refresh_catalog()
    assert wait_until(qapp, lambda: page.picker_ready)
    assert page.cmb_scenario.currentText() == "Tutorial"
    assert page.cmb_save.currentText() == "Zero-G Server - Season 4"
    cockpit.close()


def test_picker_fails_closed_when_catalog_is_missing(qapp, monkeypatch):
    monkeypatch.setattr(settings_page, "AUTO_FETCH_CATALOG", True)
    monkeypatch.setattr(settings_page, "get_active_profile", lambda: {"server_name": "Zero-G Forge Reborn"})

    def fake_catalog(profile):
        raise file_client.ServerFilesError("refused", "The server refused the request: unknown_command.", "unknown_command")

    monkeypatch.setattr(settings_page, "fetch_file_catalog", fake_catalog)
    cockpit, page = build_page(qapp)
    cockpit.bridge_connected = True
    page._refresh_catalog()
    assert wait_until(qapp, lambda: "1.6.4" in page.cmb_scenario.toolTip())
    assert page.picker_ready is False
    assert page.cmb_scenario.isEnabled() is False
    assert page._current_selection() is None
    cockpit.close()


def test_download_button_passes_independent_selection(qapp, monkeypatch):
    monkeypatch.setattr(settings_page, "AUTO_FETCH_CATALOG", True)
    monkeypatch.setattr(settings_page, "get_active_profile", lambda: {"server_name": "Zero-G Forge Reborn"})

    def fake_catalog(profile):
        return {
            "ok": True,
            "current": {"scenario": "Default Multiplayer", "save": "Zero-G Server - Season 4"},
            "originScenario": "Ascension-Reborn",
            "scenarios": ["Default Multiplayer", "Ascension-Reborn", "Tutorial"],
            "saves": ["Zero-G Server", "Zero-G Server - Season 4"],
        }

    monkeypatch.setattr(settings_page, "fetch_file_catalog", fake_catalog)
    FakeWorker.fail_message = None
    FakeWorker.last_selection = None
    cockpit, page = build_page(qapp)
    cockpit.bridge_connected = True
    page._refresh_catalog()
    assert wait_until(qapp, lambda: page.picker_ready)
    page.create_download_worker = FakeWorker
    page.cmb_scenario.setCurrentText("Tutorial")
    page.cmb_save.setCurrentText("Zero-G Server")
    page._refresh_download_state()
    page.btn_download_files.click()
    assert wait_until(qapp, lambda: page.download_worker is None)
    picked = FakeWorker.last_selection
    assert picked["scenario"] == "Tutorial" and picked["save"] == "Zero-G Server"
    cockpit.close()


@needs_dotnet
def test_catalog_and_named_download_against_real_core(tmp_path, qapp):
    scenario, save = build_server_tree(tmp_path / "srv")
    other = scenario.parent / "Ascension-Reborn"
    (other / "Content" / "Configuration").mkdir(parents=True)
    (other / "Content" / "Configuration" / "Items.ecf").write_bytes(b"ascension\n")
    (other / "gameoptions.yaml").write_bytes(b"other: scenario\n")
    paren = scenario.parent / "Stranded at Nemesis (Survival Challenge)"
    (paren / "Content" / "Configuration").mkdir(parents=True)
    (paren / "Content" / "Configuration" / "Nemesis.ecf").write_bytes(b"nemesis\n")
    (save / "gameoptions.yaml").write_bytes(b"CustomScenario: Ascension-Reborn\n")

    process, port = start_fake_bridge(tmp_path, scenario, save)
    try:
        profile = make_profile(port)
        with ServerFilesSession(profile) as session:
            catalog = session.request("catalog")
        assert catalog["ok"] is True
        assert "Ascension-Reborn" in catalog["scenarios"]
        assert "Stranded at Nemesis (Survival Challenge)" in catalog["scenarios"]
        assert "Test-Scenario" in catalog["scenarios"]
        assert catalog["current"]["scenario"] == "Test-Scenario"
        assert catalog["current"]["save"] == "TestSave"
        assert catalog["originScenario"] == "Ascension-Reborn"

        first = run_worker(profile, {
            "scenario": "Ascension-Reborn",
            "save": "TestSave",
            "types": {"ecf": True, "yaml": False, "csv": False, "images": False},
        })
        assert first["failed"] is None, first["failed"]
        summary = first["ok"]
        assert summary["scenario"] == "Ascension-Reborn"
        folder = file_store.scenario_folder("Ascension-Reborn")
        assert summary["folder"] == folder
        assert open(os.path.join(folder, "scenario", "Content", "Configuration", "Items.ecf"), "rb").read() == b"ascension\n"
        assert not any(name.endswith(".jpg") for _, _, names in os.walk(folder) for name in names)
        assert not os.path.exists(os.path.join(folder, "scenario", "gameoptions.yaml"))

        second = run_worker(profile, {
            "scenario": "Stranded at Nemesis (Survival Challenge)",
            "save": "TestSave",
            "types": dict(download_settings.DEFAULT_TYPES),
        })
        assert second["failed"] is None, second["failed"]
        nest = file_store.scenario_folder("Stranded at Nemesis (Survival Challenge)")
        assert second["ok"]["folder"] == nest
        assert open(os.path.join(nest, "scenario", "Content", "Configuration", "Nemesis.ecf"), "rb").read() == b"nemesis\n"
    finally:
        process.kill()
        process.wait()

# endregion
