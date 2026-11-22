## ==========================================
## ZERO-G ADMIN HELPER - CHEAT CHECKER SETTINGS
## Local settings for the Alerts queue: which plys flags to watch, how watch words
## are matched, thresholds, suggest-only auto-actions, who may see alerts, the
## Alerts refresh interval, and how long a local alert log is kept.
## Saved in data/cheat_checker_settings.json. Missing or bad values fall back to
## the defaults, which keep the Alerts page behaving as it did before this page
## existed (both cheat flags on at Alert/CRITICAL, watch words case-insensitive
## substring at Warn/WARNING, no thresholds, no role filter, 15 s refresh, no
## persistent log). Kicks and bans are never sent from these settings.
## ==========================================

# region Imports

import json
import os
from datetime import datetime, timezone, timedelta

from features.paths import DATA_DIR
from features.shared.roles import has_role_at_least
from features.shared import server_actions

# endregion


# region Constants

## data/ is git-ignored, so these settings stay on this PC only.
SETTINGS_FILE = os.path.join(DATA_DIR, "cheat_checker_settings.json")

## Optional persistent ACK and alert log, used only when log_retention_days is above 0.
ACK_LOG_FILE = os.path.join(DATA_DIR, "cheat_checker_ack.json")
ALERT_LOG_FILE = os.path.join(DATA_DIR, "cheat_checker_log.json")

## Queue labels. Alert stays CRITICAL and Warn stays WARNING so the Alerts page
## looks the same when these defaults are in force.
SEVERITY_LEVELS = {"Info": "INFO", "Warn": "WARNING", "Alert": "CRITICAL"}
SEVERITY_RANK = {"Info": 0, "Warn": 1, "Alert": 2}
ALLOWED_SEVERITIES = ("Info", "Warn", "Alert")

## suggest = queue only. preview_ban = fill COMMAND PREVIEW (the admin still
## starts PREVIEW BAN). Nothing here sends a kick or a ban.
ALLOWED_ACTIONS = ("suggest", "preview_ban")

## The starting values match the Alerts page before this settings file existed.
DEFAULT_SETTINGS = {
    "detect_cheat": True,
    "detect_cheater": True,
    "cheat_severity": "Alert",
    "cheater_severity": "Alert",
    "detect_auto_ban_protection": False,
    "auto_ban_protection_severity": "Info",
    "watch_case_sensitive": False,
    "watch_whole_word": False,
    "watch_severity": "Warn",
    "watch_hit_count": 1,
    "watch_hit_minutes": 10,
    "flag_polls": 1,
    "on_info_action": "suggest",
    "on_warn_action": "suggest",
    "on_alert_action": "suggest",
    "min_alert_role": "",
    "poll_seconds": 15,
    "log_retention_days": 0,
}

# endregion


# region Load and Save

## True for a plain int (bool is a subclass of int in Python and must not count).
def _is_plain_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


## True when a saved value is a known, safe choice for that key.
def _value_allowed(key, value):
    if key in ("cheat_severity", "cheater_severity", "auto_ban_protection_severity", "watch_severity"):
        return value in ALLOWED_SEVERITIES
    if key in ("on_info_action", "on_warn_action", "on_alert_action"):
        return value in ALLOWED_ACTIONS
    if key == "min_alert_role":
        return value == "" or value in ("moderator", "admin", "owner", "developer")
    if key == "poll_seconds":
        return _is_plain_int(value) and 5 <= value <= 120
    if key == "watch_hit_count":
        return _is_plain_int(value) and 1 <= value <= 20
    if key == "watch_hit_minutes":
        return _is_plain_int(value) and 1 <= value <= 120
    if key == "flag_polls":
        return _is_plain_int(value) and 1 <= value <= 20
    if key == "log_retention_days":
        return _is_plain_int(value) and 0 <= value <= 90
    return True


## Returns every cheat-checker setting. Missing keys, a missing file, or a wrong
## type all fall back to the default, so the Alerts page keeps its old behaviour.
def load_cheat_checker_settings():
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as file_handle:
            saved = json.load(file_handle)
        if not isinstance(saved, dict):
            print("[ERROR] CheatCheckerSettings: Settings file was not a dictionary, using defaults")
            return settings
        for key, default_value in DEFAULT_SETTINGS.items():
            value = saved.get(key)
            if isinstance(value, type(default_value)) and not (
                _is_plain_int(default_value) and isinstance(value, bool)
            ) and _value_allowed(key, value):
                settings[key] = value
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[ERROR] CheatCheckerSettings: Could not read settings, using defaults: {e}")
    return settings


## Writes the known settings after checking types. Returns True if it saved.
def save_cheat_checker_settings(values):
    settings = dict(DEFAULT_SETTINGS)
    if not isinstance(values, dict):
        print("[ERROR] CheatCheckerSettings: Refused save, values were not a dictionary")
        return False
    for key, default_value in DEFAULT_SETTINGS.items():
        value = values.get(key, default_value)
        if not isinstance(value, type(default_value)) or (
            _is_plain_int(default_value) and isinstance(value, bool)
        ) or not _value_allowed(key, value):
            print(f"[ERROR] CheatCheckerSettings: Refused unknown or wrong-type setting '{key}', using default")
            value = default_value
        settings[key] = value
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        part = SETTINGS_FILE + ".part"
        with open(part, "w", encoding="utf-8") as file_handle:
            json.dump(settings, file_handle, indent=2)
        os.replace(part, SETTINGS_FILE)
        print("[SUCCESS] CheatCheckerSettings: Saved cheat checker settings")
        return True
    except Exception as e:
        print(f"[ERROR] CheatCheckerSettings: Could not save settings: {e}")
        return False


## Writes the settings (and the current watch-word list) to a chosen path. Returns True if it wrote.
def export_cheat_checker_settings(path, watch_words=None):
    try:
        payload = {
            "cheat_checker_settings": load_cheat_checker_settings(),
            "watch_words": list(watch_words) if watch_words is not None else [],
        }
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        part = str(path) + ".part"
        with open(part, "w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle, indent=2)
        os.replace(part, path)
        print(f"[SUCCESS] CheatCheckerSettings: Exported settings to {path}")
        return True
    except Exception as e:
        print(f"[ERROR] CheatCheckerSettings: Could not export settings: {e}")
        return False

# endregion


# region Flag and Watch Helpers

## True when plys marks this player's cheat flag as on (same rule as dashboard is_flagged for cheat).
def cheat_is_on(player):
    return str(player.get("cheat", "Off")).lower() not in ("off", "", "--")


## True when plys marks this player as a cheater (same rule as dashboard is_flagged for cheater).
def cheater_is_yes(player):
    return str(player.get("cheater", "No")).lower() == "yes"


## True when auto_ban_protection is present and is not Active. An empty or missing
## value is treated as Active (the PlayerRecord default), so nobody is flagged by accident.
def auto_ban_protection_is_off(player):
    return str(player.get("auto_ban_protection", "Active")).lower() not in (
        "active", "on", "yes", "true", "",
    )


## The higher of two Info/Warn/Alert names, or the one that is not None.
def higher_severity(left, right):
    if left is None:
        return right
    if right is None:
        return left
    if SEVERITY_RANK.get(right, -1) > SEVERITY_RANK.get(left, -1):
        return right
    return left


## The Info/Warn/Alert name for a player under the current detection toggles, or None.
def detection_severity(player, settings=None):
    if not isinstance(player, dict):
        return None
    settings = settings if settings is not None else load_cheat_checker_settings()
    best = None
    if settings["detect_cheat"] and cheat_is_on(player):
        best = higher_severity(best, settings["cheat_severity"])
    if settings["detect_cheater"] and cheater_is_yes(player):
        best = higher_severity(best, settings["cheater_severity"])
    if settings["detect_auto_ban_protection"] and auto_ban_protection_is_off(player):
        best = higher_severity(best, settings["auto_ban_protection_severity"])
    return best


## kwargs for chat_store.find_hits so Chat and Alerts share the same matching rules.
def watch_match_kwargs(settings=None):
    settings = settings if settings is not None else load_cheat_checker_settings()
    return {
        "case_sensitive": bool(settings["watch_case_sensitive"]),
        "whole_word": bool(settings["watch_whole_word"]),
    }


## Queue level text (INFO, WARNING, CRITICAL) for an Info/Warn/Alert setting.
def level_for_severity(severity):
    return SEVERITY_LEVELS.get(severity, "WARNING")


## Action key for a queue level: suggest or preview_ban.
def action_for_level(level, settings=None):
    settings = settings if settings is not None else load_cheat_checker_settings()
    if level == "INFO":
        return settings["on_info_action"]
    if level == "CRITICAL":
        return settings["on_alert_action"]
    return settings["on_warn_action"]


## True when the signed-in role may see the Alerts queue. An empty minimum means
## no extra filter (the behaviour before this setting existed).
def user_may_see_alerts(widget, settings=None):
    settings = settings if settings is not None else load_cheat_checker_settings()
    needed = settings.get("min_alert_role") or ""
    if needed == "":
        return True
    cockpit = server_actions.find_cockpit(widget)
    if cockpit is None or not hasattr(cockpit, "user_has_role"):
        print("[ERROR] CheatCheckerSettings: No cockpit for the role check, hiding alerts")
        return False
    try:
        return bool(cockpit.user_has_role(needed))
    except Exception as e:
        print(f"[ERROR] CheatCheckerSettings: Role check failed, hiding alerts: {e}")
        return False


## Refresh interval in milliseconds, always at least 5 seconds.
def poll_interval_ms(settings=None):
    settings = settings if settings is not None else load_cheat_checker_settings()
    seconds = settings.get("poll_seconds", 15)
    if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 5:
        seconds = 15
    return seconds * 1000

# endregion


# region Alert Building

## One player's stable key, matching the Alerts page cheat: key.
def player_alert_key(player):
    return f"cheat:{player.get('steamId') or player.get('name')}"


## Parses a chat message time (ISO text, or anything datetime.fromisoformat accepts).
def _message_time(message, now):
    raw = str(message.get("time", "")).strip()
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return now


## True when this message is one of at least N hits from the same sender in the window.
def _hits_meet_threshold(message, hits, settings, now):
    needed = settings["watch_hit_count"]
    if needed <= 1:
        return False
    sender = str(message.get("senderId", ""))
    window = timedelta(minutes=settings["watch_hit_minutes"])
    count = 0
    for _word, hit in hits:
        if str(hit.get("senderId", "")) != sender:
            continue
        if now - _message_time(hit, now) <= window:
            count += 1
    return count >= needed


## Updates consecutive-flag counts and returns (new counts, keys that have reached the poll threshold).
def update_flag_poll_counts(players, settings, previous_counts):
    settings = settings if settings is not None else load_cheat_checker_settings()
    needed = settings["flag_polls"]
    if not isinstance(needed, int) or needed < 1:
        needed = 1
    previous_counts = previous_counts if isinstance(previous_counts, dict) else {}
    new_counts = {}
    ready = set()
    for player in players:
        if not isinstance(player, dict) or detection_severity(player, settings) is None:
            continue
        key = player_alert_key(player)
        count = previous_counts.get(key, 0) + 1
        new_counts[key] = count
        if count >= needed:
            ready.add(key)
    return new_counts, ready


## Builds the alert list from plys rows and watch-word hits, using the saved settings.
## Defaults produce one CRITICAL CHEAT FLAG per flagged player and one WARNING per
## chat hit, which is what Alerts did before this file existed.
def build_configured_alerts(players, hits, settings=None, flag_poll_counts=None, now=None):
    settings = settings if settings is not None else load_cheat_checker_settings()
    now = now if now is not None else datetime.now(timezone.utc)
    flag_poll_counts, ready_keys = update_flag_poll_counts(players, settings, flag_poll_counts)
    alerts = []
    for player in players:
        if not isinstance(player, dict):
            continue
        severity = detection_severity(player, settings)
        if severity is None:
            continue
        key = player_alert_key(player)
        if key not in ready_keys:
            continue
        alerts.append({
            "key": key,
            "level": level_for_severity(severity),
            "title": "CHEAT FLAG",
            "player": player,
            "entity_id": str(player.get("entityId", "")),
            "name": str(player.get("name", "?")),
            "action": action_for_level(level_for_severity(severity), settings),
        })
    for word, message in hits:
        level = level_for_severity(settings["watch_severity"])
        if _hits_meet_threshold(message, hits, settings, now):
            level = "CRITICAL"
        alerts.append({
            "key": f"chat:{message.get('seq')}",
            "level": level,
            "title": f"WATCH WORD: {str(word).upper()}",
            "message": message,
            "entity_id": str(message.get("senderId", "")),
            "name": "",
            "word": word,
            "action": action_for_level(level, settings),
        })
    return alerts, flag_poll_counts

# endregion


# region Persistent Log

## Loads a JSON list from a local file, or an empty list if it is missing or bad.
def _load_json_list(path):
    try:
        with open(path, "r", encoding="utf-8") as file_handle:
            rows = json.load(file_handle)
        if isinstance(rows, list):
            return rows
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[ERROR] CheatCheckerSettings: Could not read {path}: {e}")
    return []


## Writes a JSON list atomically.
def _save_json_list(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    part = path + ".part"
    with open(part, "w", encoding="utf-8") as file_handle:
        json.dump(rows, file_handle, indent=2)
    os.replace(part, path)


## Drops rows older than retention days. A missing or bad "at" field is dropped.
def _prune_rows(rows, days, now):
    cutoff = now - timedelta(days=days)
    kept = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            stamp = datetime.fromisoformat(str(row.get("at", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if stamp >= cutoff:
            kept.append(row)
    return kept


## ACK keys still within the retention window. An empty set when retention is 0
## (ACK then stays in memory only, as it did before this setting existed).
def load_persisted_acks(now=None):
    settings = load_cheat_checker_settings()
    days = settings["log_retention_days"]
    if not isinstance(days, int) or days <= 0:
        return set()
    now = now if now is not None else datetime.now(timezone.utc)
    rows = _prune_rows(_load_json_list(ACK_LOG_FILE), days, now)
    return {str(row.get("key")) for row in rows if row.get("key")}


## Saves one ACK when retention is on. Does nothing when retention is 0.
def persist_ack(alert_key, now=None):
    settings = load_cheat_checker_settings()
    days = settings["log_retention_days"]
    if not isinstance(days, int) or days <= 0 or not alert_key:
        return
    now = now if now is not None else datetime.now(timezone.utc)
    rows = _prune_rows(_load_json_list(ACK_LOG_FILE), days, now)
    rows.append({"key": str(alert_key), "at": now.isoformat()})
    try:
        _save_json_list(ACK_LOG_FILE, rows)
    except Exception as e:
        print(f"[ERROR] CheatCheckerSettings: Could not persist ACK: {e}")


## Appends a local alert-log row when retention is on. Never sent to the server.
def append_alert_log(alert, now=None):
    settings = load_cheat_checker_settings()
    days = settings["log_retention_days"]
    if not isinstance(days, int) or days <= 0 or not isinstance(alert, dict):
        return
    now = now if now is not None else datetime.now(timezone.utc)
    rows = _prune_rows(_load_json_list(ALERT_LOG_FILE), days, now)
    key = str(alert.get("key", ""))
    if key and any(isinstance(row, dict) and str(row.get("key")) == key for row in rows):
        return
    rows.append({
        "key": str(alert.get("key", "")),
        "level": str(alert.get("level", "")),
        "title": str(alert.get("title", "")),
        "name": str(alert.get("name", "")),
        "at": now.isoformat(),
    })
    try:
        _save_json_list(ALERT_LOG_FILE, _prune_rows(rows, days, now))
    except Exception as e:
        print(f"[ERROR] CheatCheckerSettings: Could not write the alert log: {e}")

# endregion
