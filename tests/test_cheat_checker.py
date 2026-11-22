## =====================================================================
## TEST: tests/test_cheat_checker.py
## Cheat checker settings: fail-closed defaults match the original Alerts behaviour,
## matching options, thresholds, the role filter, SAVE / RESET / EXPORT, and the
## guarantee that these settings never send a kick or a ban. The fake bridge is used;
## no network is used.
## =====================================================================

# region Imports

import json

import pytest

from tests.page_helpers import get_qapp, host, install, settle
from features.chat import chat_store
from features.cheat_checker import cheat_checker_settings as ccs
from features.alerts import alerts_page

# endregion


@pytest.fixture(scope="session")
def qapp():
    return get_qapp()


# region Settings File

def use_temp_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(ccs, "SETTINGS_FILE", str(tmp_path / "cheat_checker_settings.json"))
    monkeypatch.setattr(ccs, "ACK_LOG_FILE", str(tmp_path / "cheat_checker_ack.json"))
    monkeypatch.setattr(ccs, "ALERT_LOG_FILE", str(tmp_path / "cheat_checker_log.json"))
    monkeypatch.setattr(chat_store, "WATCH_WORDS_FILE", str(tmp_path / "words.json"))
    monkeypatch.setattr(chat_store, "CHAT_HISTORY", [])
    monkeypatch.setattr(chat_store, "LAST_SEQ", {"value": 0})
    monkeypatch.setattr(alerts_page, "ACKNOWLEDGED", set())


def test_missing_file_returns_defaults(tmp_path, monkeypatch):
    use_temp_settings(monkeypatch, tmp_path)
    settings = ccs.load_cheat_checker_settings()
    assert settings == ccs.DEFAULT_SETTINGS
    assert settings["detect_cheat"] is True and settings["detect_cheater"] is True
    assert settings["cheat_severity"] == "Alert" and settings["watch_severity"] == "Warn"
    assert settings["watch_case_sensitive"] is False and settings["watch_whole_word"] is False
    assert settings["watch_hit_count"] == 1 and settings["flag_polls"] == 1
    assert settings["on_alert_action"] == "suggest" and settings["min_alert_role"] == ""
    assert settings["poll_seconds"] == 15 and settings["log_retention_days"] == 0
    assert settings["detect_auto_ban_protection"] is False


def test_bad_types_and_unknown_keys_are_ignored(tmp_path, monkeypatch):
    use_temp_settings(monkeypatch, tmp_path)
    with open(ccs.SETTINGS_FILE, "w", encoding="utf-8") as file_handle:
        json.dump({
            "detect_cheat": "yes",
            "poll_seconds": 3,
            "min_alert_role": "superuser",
            "on_alert_action": "auto_ban",
            "log_retention_days": True,
            "not_a_real_key": 1,
            "cheat_severity": "Alert",
        }, file_handle)
    settings = ccs.load_cheat_checker_settings()
    assert settings["detect_cheat"] is True
    assert settings["poll_seconds"] == 15
    assert settings["min_alert_role"] == ""
    assert settings["on_alert_action"] == "suggest"
    assert settings["log_retention_days"] == 0
    assert settings["cheat_severity"] == "Alert"
    assert "not_a_real_key" not in settings


def test_save_roundtrip(tmp_path, monkeypatch):
    use_temp_settings(monkeypatch, tmp_path)
    values = dict(ccs.DEFAULT_SETTINGS)
    values["detect_cheat"] = False
    values["poll_seconds"] = 30
    values["min_alert_role"] = "admin"
    values["on_alert_action"] = "preview_ban"
    assert ccs.save_cheat_checker_settings(values) is True
    loaded = ccs.load_cheat_checker_settings()
    assert loaded["detect_cheat"] is False
    assert loaded["poll_seconds"] == 30
    assert loaded["min_alert_role"] == "admin"
    assert loaded["on_alert_action"] == "preview_ban"
    assert loaded["detect_cheater"] is True

# endregion


# region Matching and Alerts

def test_watch_word_matching_defaults_and_options():
    assert chat_store.text_has_watch_word("please cheat now", "cheat") is True
    assert chat_store.text_has_watch_word("cheater", "cheat") is True
    assert chat_store.text_has_watch_word("cheater", "cheat", whole_word=True) is False
    assert chat_store.text_has_watch_word("the cheat is on", "cheat", whole_word=True) is True
    assert chat_store.text_has_watch_word("use Cheat codes", "Cheat", case_sensitive=True) is True
    assert chat_store.text_has_watch_word("use cheat codes", "Cheat", case_sensitive=True) is False


def test_defaults_build_the_original_alerts(tmp_path, monkeypatch):
    use_temp_settings(monkeypatch, tmp_path)
    players = [
        {"entityId": "1001", "steamId": "s1", "name": "Alice", "cheat": "On", "cheater": "No"},
        {"entityId": "1002", "steamId": "s2", "name": "Bob", "cheat": "Off", "cheater": "No"},
    ]
    hits = [("cheat", {"seq": 9, "senderId": "1002", "text": "let us cheat"})]
    alerts = alerts_page.build_alerts(players, hits)
    assert len(alerts) == 2
    assert alerts[0]["level"] == "CRITICAL" and alerts[0]["title"] == "CHEAT FLAG" and alerts[0]["name"] == "Alice"
    assert alerts[1]["level"] == "WARNING" and alerts[1]["word"] == "cheat" and alerts[1]["key"] == "chat:9"


def test_detect_toggles_and_severity(tmp_path, monkeypatch):
    use_temp_settings(monkeypatch, tmp_path)
    players = [
        {"entityId": "1", "steamId": "s1", "name": "A", "cheat": "On", "cheater": "No"},
        {"entityId": "2", "steamId": "s2", "name": "B", "cheat": "Off", "cheater": "Yes"},
    ]
    settings = dict(ccs.DEFAULT_SETTINGS)
    settings["detect_cheat"] = False
    settings["detect_cheater"] = True
    settings["cheater_severity"] = "Warn"
    alerts, _counts = ccs.build_configured_alerts(players, [], settings=settings)
    assert len(alerts) == 1 and alerts[0]["name"] == "B" and alerts[0]["level"] == "WARNING"


def test_auto_ban_protection_is_off_by_default(tmp_path, monkeypatch):
    use_temp_settings(monkeypatch, tmp_path)
    players = [
        {"entityId": "1", "steamId": "s1", "name": "A", "cheat": "Off", "cheater": "No",
         "auto_ban_protection": "Inactive"},
    ]
    alerts, _counts = ccs.build_configured_alerts(players, [])
    assert alerts == []
    settings = dict(ccs.DEFAULT_SETTINGS)
    settings["detect_auto_ban_protection"] = True
    settings["auto_ban_protection_severity"] = "Info"
    alerts, _counts = ccs.build_configured_alerts(players, [], settings=settings)
    assert len(alerts) == 1 and alerts[0]["level"] == "INFO" and alerts[0]["name"] == "A"


def test_flag_poll_threshold(tmp_path, monkeypatch):
    use_temp_settings(monkeypatch, tmp_path)
    player = {"entityId": "1", "steamId": "s1", "name": "A", "cheat": "On", "cheater": "No"}
    settings = dict(ccs.DEFAULT_SETTINGS)
    settings["flag_polls"] = 2
    first, counts = ccs.build_configured_alerts([player], [], settings=settings, flag_poll_counts={})
    assert first == [] and counts["cheat:s1"] == 1
    second, counts = ccs.build_configured_alerts([player], [], settings=settings, flag_poll_counts=counts)
    assert len(second) == 1 and second[0]["name"] == "A" and counts["cheat:s1"] == 2


def test_watch_hit_threshold_raises_to_alert(tmp_path, monkeypatch):
    use_temp_settings(monkeypatch, tmp_path)
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)
    settings = dict(ccs.DEFAULT_SETTINGS)
    settings["watch_hit_count"] = 3
    settings["watch_hit_minutes"] = 10
    hits = [
        ("spam", {"seq": 1, "senderId": "7", "text": "spam", "time": (now - timedelta(minutes=1)).isoformat()}),
        ("spam", {"seq": 2, "senderId": "7", "text": "spam", "time": (now - timedelta(minutes=2)).isoformat()}),
        ("spam", {"seq": 3, "senderId": "7", "text": "spam", "time": (now - timedelta(minutes=3)).isoformat()}),
        ("spam", {"seq": 4, "senderId": "8", "text": "spam", "time": now.isoformat()}),
    ]
    alerts, _counts = ccs.build_configured_alerts([], hits, settings=settings, now=now)
    by_key = {alert["key"]: alert["level"] for alert in alerts}
    assert by_key["chat:1"] == "CRITICAL" and by_key["chat:4"] == "WARNING"


def test_min_role_hides_alerts_for_a_moderator(qapp, monkeypatch, tmp_path):
    use_temp_settings(monkeypatch, tmp_path)
    values = dict(ccs.DEFAULT_SETTINGS)
    values["min_alert_role"] = "admin"
    assert ccs.save_cheat_checker_settings(values) is True
    players = {"type": "PLAYER_CACHE", "player_list": [
        {"entityId": "7", "name": "Z", "cheat": "On", "steamId": "s7"}
    ]}
    install(monkeypatch, tmp_path, {"plys": players, "chat:recent": {"type": "CHAT_LOG", "messages": []}})
    page = alerts_page.create_page()
    cockpit = host(page, role="moderator")
    settle(qapp)
    assert page.lst_alerts.count() == 0
    assert "cannot see" in page.lbl_queue_empty.text()
    cockpit.close()


def test_alerts_page_unchanged_without_saved_settings(qapp, monkeypatch, tmp_path):
    use_temp_settings(monkeypatch, tmp_path)
    chat_store.save_watch_words([{"word": "cheat", "on": True}])
    players = {"type": "PLAYER_CACHE", "player_list": [
        {"entityId": "1001", "steamId": "s1", "name": "Alice", "cheat": "On", "cheater": "No", "status": "Online"},
        {"entityId": "1002", "steamId": "s2", "name": "Bob", "cheat": "Off", "cheater": "No", "status": "Online"}]}
    install(monkeypatch, tmp_path, {"plys": players, "chat:recent": {
        "type": "CHAT_LOG", "last_seq": 1,
        "messages": [{"seq": 1, "channel": "Global", "senderId": "1002", "senderName": "Bob",
                      "text": "let us cheat", "time": "2026-11-22T18:00:00+00:00"}]
    }})
    page = alerts_page.create_page()
    cockpit = host(page, role="admin")
    settle(qapp)
    assert page.lst_alerts.count() == 2
    assert page.lst_alerts.item(0).text().startswith("CRITICAL")
    assert "Bob" in page.lst_alerts.item(1).text()
    cockpit.close()

# endregion


# region Page

def test_page_save_reset_export_and_disabled_detections(qapp, monkeypatch, tmp_path):
    use_temp_settings(monkeypatch, tmp_path)
    from features.cheat_checker import cheat_checker_page
    page = cheat_checker_page.create_page()
    cockpit = host(page, role="developer")
    assert page.chk_detect_cheat.isChecked() and page.spn_poll_seconds.value() == 15
    assert page.spn_retention_days.value() == 0 and page.cmb_min_role.currentData() == ""
    disabled = []
    for box in page.findChildren(cheat_checker_page.QCheckBox):
        if not box.isEnabled():
            disabled.append((box.text(), box.toolTip()))
    titles = [row[0] for row in disabled]
    assert "Inventory jump" in titles
    assert "Speed / position delta" in titles
    assert "Uncommanded god mode" in titles
    for _title, tip in disabled:
        assert "does not" in tip.lower() or "no god-mode" in tip.lower() or "does not send" in tip.lower()
    page.chk_detect_cheat.setChecked(False)
    page.spn_poll_seconds.setValue(45)
    page._on_save()
    saved = ccs.load_cheat_checker_settings()
    assert saved["detect_cheat"] is False and saved["poll_seconds"] == 45
    export_path = str(tmp_path / "export.json")
    assert ccs.export_cheat_checker_settings(export_path, [{"word": "dupe", "on": True}]) is True
    payload = json.loads(open(export_path, encoding="utf-8").read())
    assert payload["cheat_checker_settings"]["poll_seconds"] == 45
    assert payload["watch_words"][0]["word"] == "dupe"
    page._on_reset()
    reset = ccs.load_cheat_checker_settings()
    assert reset == ccs.DEFAULT_SETTINGS
    source = open(cheat_checker_page.__file__, encoding="utf-8").read()
    settings_source = open(ccs.__file__, encoding="utf-8").read()
    for banned in ("con:kick", "con:ban", "run_server_action"):
        assert banned not in source
        assert banned not in settings_source
    cockpit.close()


def test_nav_lists_cheat_checker_after_alerts():
    from features.dashboard import main_cockpit
    from features.shared.page_loader import PAGE_MODULES
    keys = [key for key, _title in main_cockpit.NAV_PAGES]
    assert keys[keys.index("alerts") + 1] == "cheat_checker"
    _title, _page, children = main_cockpit.NAV_GROUPS["settings"]
    assert children[children.index("alerts") + 1] == "cheat_checker"
    assert PAGE_MODULES["cheat_checker"] == "features.cheat_checker.cheat_checker_page"


def test_poll_interval_is_read_from_settings(qapp, monkeypatch, tmp_path):
    use_temp_settings(monkeypatch, tmp_path)
    values = dict(ccs.DEFAULT_SETTINGS)
    values["poll_seconds"] = 40
    assert ccs.save_cheat_checker_settings(values) is True
    assert ccs.poll_interval_ms() == 40000
    install(monkeypatch, tmp_path, {"plys": {"type": "PLAYER_CACHE", "player_list": []},
                                    "chat:recent": {"type": "CHAT_LOG", "messages": []}})
    page = alerts_page.create_page()
    cockpit = host(page, role="admin")
    settle(qapp)
    assert page.refresh_timer.interval() == 40000
    cockpit.close()


def test_persisted_ack_only_when_retention_is_on(tmp_path, monkeypatch):
    use_temp_settings(monkeypatch, tmp_path)
    ccs.persist_ack("cheat:s1")
    assert ccs.load_persisted_acks() == set()
    values = dict(ccs.DEFAULT_SETTINGS)
    values["log_retention_days"] = 7
    assert ccs.save_cheat_checker_settings(values) is True
    ccs.persist_ack("cheat:s1")
    assert "cheat:s1" in ccs.load_persisted_acks()

# endregion
