## =====================================================================
## MODULE: features/chat/chat_store.py
## DESCRIPTION: Chat history and watch words shared by the Chat page and the Alerts page.
## The history comes from the bridge's read-only chat:recent (core 1.6.3) and lives in memory only, so it
## survives page switches but not a ZAH restart. Watch words are saved in data/chat_watch_words.json.
## =====================================================================

# region Imports

import json
import os
import re

from features.paths import DATA_DIR

# endregion


# region Constants

## Watch words file. Each row is {"word": text, "on": True/False}.
WATCH_WORDS_FILE = os.path.join(DATA_DIR, "chat_watch_words.json")

## Most messages kept in memory (the bridge keeps 500 too).
MAX_MESSAGES = 500

## Which chat:recent channels each tab shows.
TAB_CHANNELS = {"global": ("Global", "Server"), "faction": ("Faction", "Alliance"), "private": ("SinglePlayer",)}

# endregion


# region History

## Messages in arrival order, and the newest seq seen (the next poll asks for "since" this number).
CHAT_HISTORY = []
LAST_SEQ = {"value": 0}


## Adds the messages from one CHAT_LOG reply, skipping any already kept. Returns the new ones.
def add_messages(reply):
    messages = reply.get("messages") if isinstance(reply, dict) else None
    if not isinstance(messages, list):
        return []
    known = {message.get("seq") for message in CHAT_HISTORY}
    added = [message for message in messages if isinstance(message, dict) and message.get("seq") not in known]
    CHAT_HISTORY.extend(added)
    del CHAT_HISTORY[:-MAX_MESSAGES]
    if added:
        LAST_SEQ["value"] = max(LAST_SEQ["value"], max(int(message.get("seq") or 0) for message in added))

    ## A reloaded bridge starts counting again from 1: start over so nothing is missed.
    last_seq = reply.get("last_seq")
    if isinstance(last_seq, int) and last_seq < LAST_SEQ["value"]:
        LAST_SEQ["value"] = last_seq
    return added


## The messages for one tab, oldest first.
def messages_for_tab(tab_key):
    channels = TAB_CHANNELS.get(tab_key, ())
    return [message for message in CHAT_HISTORY if message.get("channel") in channels]

# endregion


# region Watch Words

def load_watch_words():
    try:
        with open(WATCH_WORDS_FILE, encoding="utf-8") as file_handle:
            rows = json.load(file_handle)
        return [{"word": str(row["word"]), "on": row.get("on") is not False}
                for row in rows if isinstance(row, dict) and str(row.get("word", "")).strip()]
    except (OSError, ValueError, TypeError):
        return []


def save_watch_words(rows):
    os.makedirs(os.path.dirname(WATCH_WORDS_FILE), exist_ok=True)
    part = WATCH_WORDS_FILE + ".part"
    with open(part, "w", encoding="utf-8") as file_handle:
        json.dump(rows, file_handle, indent=2)
    os.replace(part, WATCH_WORDS_FILE)


## True when text contains word, using the given matching rules.
## The defaults (case-insensitive, substring) are the original find_hits behaviour.
def text_has_watch_word(text, word, case_sensitive=False, whole_word=False):
    if not word:
        return False
    haystack = text if case_sensitive else str(text).lower()
    needle = word if case_sensitive else str(word).lower()
    if not whole_word:
        return needle in haystack
    return re.search(r"\b" + re.escape(needle) + r"\b", haystack) is not None


## Messages that contain a switched-on watch word. Newest first, as (word, message).
## case_sensitive and whole_word default to off, so a missing call still does a
## case-insensitive substring match (the original behaviour).
def find_hits(messages=None, rows=None, case_sensitive=False, whole_word=False):
    rows = rows if rows is not None else load_watch_words()
    hits = []
    for message in reversed(messages if messages is not None else CHAT_HISTORY):
        text = str(message.get("text", ""))
        for row in rows:
            if not row.get("on"):
                continue
            word = str(row.get("word", ""))
            if text_has_watch_word(text, word, case_sensitive, whole_word):
                hits.append((word if case_sensitive else word.lower(), message))
                break
    return hits

# endregion
