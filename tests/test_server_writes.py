## =====================================================================
## TEST: tests/test_server_writes.py
## Checks the server write path added with core 1.6.2:
##   - the role gate (developer and owner; admin and moderator only with Live file editing; fail closed)
##   - the online-player count used by confirmation 2 (unreadable = stop)
##   - UPLOAD from the ECF editor through all three confirmations, against the REAL C# write code
##     (ZeroGBridge/tests/ServerFilesTest "serve" mode with ZGB_TEST_MODDIR), including a stale-base refusal
##   - coreupload:put of a real built core, and the portal's developer-only Browse upload
##   - the Settings LIVE MODE switch
## Nothing here touches data/ or any real server: every file lives in a temporary folder and the
## "server" is a local process with a made-up test token.
## =====================================================================

# region Imports

import os
import shutil
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox, QWidget

from features.server_files import file_client, file_store, upload_flow, write_worker
from features.server_files.file_client import ServerFilesError, ServerFilesSession
from features.settings import app_settings, settings_page
from features.shared import editor_actions
from features.shared.roles import can_edit_live_files
from tests.test_server_files import build_server_tree, make_profile, run_worker, start_fake_bridge, TEST_DLL

# endregion


# region Helpers

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_BUILD = os.path.join(APP_ROOT, "ZeroGBridge", "CoreProject", "bin", "Release", "net48")
ITEMS_PATH = "Content/Configuration/Items.ecf"

## A small valid ECF file (UPLOAD refuses text that VALIDATE finds errors in) and the edited version.
OLD_ECF = b"{ +Item Id: 1, Name: Old\n}\n"
NEW_ECF = b"{ +Item Id: 1, Name: Old\n}\n{ +Item Id: 2, Name: New\n}\n"
ADDED_TEXT = "{ +Item Id: 2, Name: New\n}\n"
## Windows built by a test stay referenced here, so Python does not delete them while Qt still uses them.
KEEP_ALIVE = []
NEEDS_HARNESS = pytest.mark.skipif(not os.path.isfile(TEST_DLL), reason="ServerFilesTest harness is not built")


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    ## Downloads and app settings go to a temporary folder, never to the real data/ folder.
    monkeypatch.setattr(file_store, "SERVER_FILES_DIR", str(tmp_path / "server_files"))
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", str(tmp_path / "app_settings.json"))
    monkeypatch.setattr(file_client, "COMMAND_GAP_SEC", 0.0)

    ## No message box may ever block a test.
    for name in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok))


class FakeCockpit(QMainWindow):
    ## Stands in for MainCockpit: the signal and the attributes the pages read.
    bridge_status_changed = pyqtSignal(str, bool)

    def __init__(self, role="developer", live_flag=False, connected=True):
        super().__init__()
        self.signed_in_role = role
        self.signed_in_live_files = live_flag
        self.bridge_connected = connected
        self.bridge_server_name = "Test"
        self.live_mode = False

    def can_edit_live_files(self):
        return can_edit_live_files(self.signed_in_role, self.signed_in_live_files)

    def user_has_role(self, needed_role):
        from features.shared.roles import has_role_at_least
        return has_role_at_least(self.signed_in_role, needed_role)


def start_harness(tmp_path):
    scenario, save = build_server_tree(tmp_path / "srv")
    (scenario / "Content" / "Configuration" / "Items.ecf").write_bytes(OLD_ECF)
    mod_dir = tmp_path / "mod"
    mod_dir.mkdir()
    os.environ["ZGB_TEST_MODDIR"] = str(mod_dir)
    try:
        process, port = start_fake_bridge(tmp_path, scenario, save)
    finally:
        os.environ.pop("ZGB_TEST_MODDIR", None)
    return process, port, scenario, mod_dir


def open_items_in_editor(qapp, folder, cockpit):
    from features.ecf_editor.ecf_editor_page import EcfEditorPage
    page = EcfEditorPage()
    KEEP_ALIVE.append(cockpit)
    cockpit.setCentralWidget(page)
    cockpit.show()
    page.load_server_files(folder)
    labels = [page.cmb_file.itemText(row) for row in range(page.cmb_file.count())]
    page.cmb_file.setCurrentIndex(labels.index("Items.ecf  (scenario)"))
    qapp.processEvents()
    return page


def answer_all(monkeypatch, changes=True, players=True, name=True, payload=None):
    ## Answers the three confirmations without clicking, and runs the write thread on this thread.
    calls = []
    monkeypatch.setattr(upload_flow, "ask_changes", lambda parent, file_name, diff: calls.append("changes") or changes)
    monkeypatch.setattr(upload_flow, "ask_players", lambda parent, count, names: calls.append(("players", count)) or players)
    monkeypatch.setattr(upload_flow, "ask_type_name", lambda parent, file_name: calls.append("name") or name)
    monkeypatch.setattr(upload_flow, "fetch_players_for_upload", lambda: payload if payload is not None else {"player_list": []})
    monkeypatch.setattr(editor_actions, "start_write_worker", lambda worker: worker.run())
    return calls


def wait_for_players(qapp):
    from features.zgb_portal.live_client import wait_for_tasks
    wait_for_tasks(5000)
    for _ in range(20):
        qapp.processEvents()

# endregion


# region Role Gate

@pytest.mark.parametrize("role, flag, expected", [
    ("developer", False, True), ("owner", False, True),
    ("admin", False, False), ("moderator", False, False),
    ("admin", True, True), ("moderator", True, True),
    ("admin", "true", False), ("admin", 1, False),
    (None, True, False), ("guest", True, False), ("", True, False),
])
def test_role_gate(role, flag, expected):
    assert can_edit_live_files(role, flag) is expected


def test_gate_fails_closed_without_cockpit(qapp):
    widget = QWidget()
    assert upload_flow.user_can_write_server_files(widget) is False
    assert upload_flow.bridge_is_connected(widget) is False
    assert upload_flow.live_mode_on(widget) is False


def test_count_online():
    payload = {"players": 3, "player_list": [{"name": "A", "status": "Online"}, {"name": "B", "status": "Offline"},
                                             {"name": "C", "status": "online"}]}
    assert upload_flow.count_online(payload) == (2, ["A", "C"])
    assert upload_flow.count_online({"player_list": []}) == (0, [])
    assert upload_flow.count_online(None) == (None, [])
    assert upload_flow.count_online({"players": 4}) == (None, [])

# endregion


# region Editor Upload Against The Harness

@NEEDS_HARNESS
def test_upload_through_three_confirmations(tmp_path, qapp, monkeypatch):
    process, port, scenario, mod_dir = start_harness(tmp_path)
    try:
        profile = make_profile(port)
        folder = run_worker(profile)["ok"]["folder"]
        monkeypatch.setattr(editor_actions, "CREATE_WRITE_WORKER",
                            lambda job: write_worker.ServerWriteWorker(job, profile_provider=lambda: profile))
        calls = answer_all(monkeypatch)
        cockpit = FakeCockpit("owner")
        page = open_items_in_editor(qapp, folder, cockpit)
        assert page.btn_upload.isEnabled()
        page.code_editor.load_text(page.original_text + ADDED_TEXT)
        page._on_upload_clicked()
        wait_for_players(qapp)
        assert calls == ["changes", ("players", 0), "name"]
        server_file = scenario / "Content" / "Configuration" / "Items.ecf"
        assert server_file.read_bytes() == NEW_ECF

        ## The bridge kept the old server file, and the local download follows the server.
        backups = list((mod_dir / "Backups" / "files" / "scenario" / "Content" / "Configuration").glob("Items.ecf.*.bak"))
        assert len(backups) == 1 and backups[0].read_bytes() == OLD_ECF
        assert open(page.current_entry["full"], "rb").read() == NEW_ECF
        assert page._refresh_changes() == []
        assert "Uploaded Items.ecf" in page.lbl_backup.text()
    finally:
        process.kill()


@NEEDS_HARNESS
def test_stale_upload_is_refused_and_server_unchanged(tmp_path, qapp, monkeypatch):
    process, port, scenario, mod_dir = start_harness(tmp_path)
    try:
        profile = make_profile(port)
        folder = run_worker(profile)["ok"]["folder"]
        server_file = scenario / "Content" / "Configuration" / "Items.ecf"
        server_file.write_bytes(b"changed by someone else\n")
        monkeypatch.setattr(editor_actions, "CREATE_WRITE_WORKER",
                            lambda job: write_worker.ServerWriteWorker(job, profile_provider=lambda: profile))
        answer_all(monkeypatch)
        page = open_items_in_editor(qapp, folder, FakeCockpit("developer"))
        page.code_editor.load_text(page.original_text + ADDED_TEXT)
        page._on_upload_clicked()
        wait_for_players(qapp)
        assert server_file.read_bytes() == b"changed by someone else\n"
        assert "Upload failed" in page.lbl_backup.text()
    finally:
        process.kill()


@NEEDS_HARNESS
@pytest.mark.parametrize("stop_at", ["changes", "players", "name", "unreadable"])
def test_any_no_sends_nothing(tmp_path, qapp, monkeypatch, stop_at):
    process, port, scenario, mod_dir = start_harness(tmp_path)
    try:
        profile = make_profile(port)
        folder = run_worker(profile)["ok"]["folder"]
        monkeypatch.setattr(editor_actions, "CREATE_WRITE_WORKER",
                            lambda job: write_worker.ServerWriteWorker(job, profile_provider=lambda: profile))
        answer_all(monkeypatch, changes=stop_at != "changes", players=stop_at != "players",
                   name=stop_at != "name", payload={"bad": 1} if stop_at == "unreadable" else None)
        if stop_at == "unreadable":
            monkeypatch.setattr(upload_flow, "ask_players", lambda parent, count, names: count is not None)
        page = open_items_in_editor(qapp, folder, FakeCockpit("developer"))
        page.code_editor.load_text(page.original_text + ADDED_TEXT)
        page._on_upload_clicked()
        wait_for_players(qapp)
        assert (scenario / "Content" / "Configuration" / "Items.ecf").read_bytes() == OLD_ECF
        assert not (mod_dir / "Backups").exists()
    finally:
        process.kill()


@pytest.mark.parametrize("role, flag, connected", [("admin", False, True), ("moderator", False, True),
                                                    ("developer", True, False)])
def test_upload_button_gate(tmp_path, qapp, monkeypatch, role, flag, connected):
    from tests.test_local_files import build_download
    folder = build_download(tmp_path)
    sent = []
    monkeypatch.setattr(editor_actions, "CREATE_WRITE_WORKER", lambda job: sent.append(job))
    answer_all(monkeypatch)
    cockpit = FakeCockpit(role, flag, connected)
    from features.ecf_editor.ecf_editor_page import EcfEditorPage
    page = EcfEditorPage()
    cockpit.setCentralWidget(page)
    page.load_server_files(folder)
    page.cmb_file.setCurrentIndex(0)
    page.code_editor.load_text(page.original_text + "x\n")
    assert not page.btn_upload.isEnabled()
    page._on_upload_clicked()
    wait_for_players(qapp)
    assert sent == []


def test_admin_with_grant_gets_the_button(tmp_path, qapp):
    from tests.test_local_files import build_download
    folder = build_download(tmp_path)
    cockpit = FakeCockpit("admin", True, True)
    from features.ecf_editor.ecf_editor_page import EcfEditorPage
    page = EcfEditorPage()
    cockpit.setCentralWidget(page)
    page.load_server_files(folder)
    page.cmb_file.setCurrentIndex(0)
    assert page.btn_upload.isEnabled()

# endregion


# region Core Upload Against The Harness

def copy_core(tmp_path):
    target = tmp_path / "build"
    target.mkdir()
    for name in ("ZeroGBridge.Core.dll", "ZeroGBridge.Core.pdb"):
        shutil.copy(os.path.join(CORE_BUILD, name), target / name)
    return str(target / "ZeroGBridge.Core.dll")


NEEDS_CORE = pytest.mark.skipif(not os.path.isfile(os.path.join(CORE_BUILD, "ZeroGBridge.Core.dll")),
                                reason="core Release build not found")


@NEEDS_HARNESS
@NEEDS_CORE
def test_upload_core_puts_pdb_then_dll(tmp_path):
    process, port, scenario, mod_dir = start_harness(tmp_path)
    try:
        dll = copy_core(tmp_path)
        with ServerFilesSession(make_profile(port)) as session:
            reply = write_worker.upload_core(session, dll)
        assert reply["done"] is True and reply["pendingDrop"] is True
        assert (mod_dir / "Updates" / "ZeroGBridge.Core.dll").read_bytes() == open(dll, "rb").read()
        assert (mod_dir / "Updates" / "ZeroGBridge.Core.pdb").is_file()
    finally:
        process.kill()


@NEEDS_HARNESS
def test_core_upload_refuses_a_non_core(tmp_path):
    process, port, scenario, mod_dir = start_harness(tmp_path)
    try:
        fake = tmp_path / "ZeroGBridge.Core.dll"
        fake.write_bytes(b"MZ" + b"\0" * 200)
        with ServerFilesSession(make_profile(port)) as session:
            with pytest.raises(ServerFilesError) as caught:
                write_worker.upload_core(session, str(fake))
        assert caught.value.code == "bad_core"
        assert not (mod_dir / "Updates" / "ZeroGBridge.Core.dll").exists()
    finally:
        process.kill()


class LiveStub:
    ## Just enough of LiveDataSource for Browse: is_live and the profile.
    is_live = True

    def __init__(self, profile):
        self._profile = profile

    def profile(self):
        return self._profile


def build_portal(qapp, role):
    from features.zgb_portal import hot_reload_panel
    holder = FakeCockpit(role)
    KEEP_ALIVE.append(holder)
    panel = hot_reload_panel.HotReloadPanel(embedded=True, parent=holder)
    holder.setCentralWidget(panel)
    return hot_reload_panel, panel


@NEEDS_HARNESS
@NEEDS_CORE
def test_portal_browse_uploads_core_then_opens_reload(tmp_path, qapp, monkeypatch):
    process, port, scenario, mod_dir = start_harness(tmp_path)
    try:
        dll = copy_core(tmp_path)
        module, panel = build_portal(qapp, "developer")
        panel.source = LiveStub(make_profile(port))
        panel.state.connection = "Online"
        reloads = []
        monkeypatch.setattr(module.QFileDialog, "getOpenFileName", staticmethod(lambda *args, **kwargs: (dll, "")))
        monkeypatch.setattr(panel, "_confirm", lambda title, body, action: True)
        monkeypatch.setattr(panel, "_live_reload", lambda: reloads.append(True))
        monkeypatch.setattr(write_worker, "start_write_worker", lambda worker: worker.run())
        panel._live_browse()
        assert (mod_dir / "Updates" / "ZeroGBridge.Core.dll").is_file()
        assert reloads == [True] and panel._live_action is False
    finally:
        process.kill()


def test_portal_browse_is_developer_only(tmp_path, qapp, monkeypatch):
    module, panel = build_portal(qapp, "owner")
    panel.source = LiveStub(make_profile(1))
    panel.state.connection = "Online"
    picked = []
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", staticmethod(lambda *args, **kwargs: picked.append(1) or ("", "")))
    panel._live_browse()
    assert picked == []

# endregion


# region Settings LIVE MODE

@pytest.mark.parametrize("role, flag, enabled", [("developer", False, True), ("owner", False, True),
                                                 ("admin", False, False), ("admin", True, True)])
def test_live_mode_switch_gate(qapp, role, flag, enabled):
    cockpit = FakeCockpit(role, flag, True)
    page = settings_page.SettingsPage()
    cockpit.setCentralWidget(page)
    cockpit.show()
    qapp.processEvents()
    assert page.chk_live_mode.isEnabled() is enabled
    assert not page.chk_live_mode.isChecked()


@pytest.mark.parametrize("answer, expected", [(QMessageBox.StandardButton.Yes, True), (QMessageBox.StandardButton.No, False)])
def test_live_mode_asks_and_is_not_saved(qapp, monkeypatch, answer, expected):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: answer))
    cockpit = FakeCockpit("developer")
    page = settings_page.SettingsPage()
    cockpit.setCentralWidget(page)
    cockpit.show()
    qapp.processEvents()
    page.chk_live_mode.setChecked(True)
    assert cockpit.live_mode is expected and page.chk_live_mode.isChecked() is expected
    assert "live_mode" not in app_settings.load_app_settings()

# endregion
