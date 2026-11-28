## ==========================================
## ZERO-G ADMIN HELPER - CHAT PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Chat.jpg:
## chat tabs (GLOBAL / FACTION / PRIVATE / DISCORD) over the message list and a REPLY AS SERVER box on the left,
## WATCH WORDS and RECENT HITS on the right.
## Layout only for now: there is no chat data source yet, so the lists show "nothing yet".
## SEND, WARN and MUTE stay greyed out; each one talks to the server and gets its own step with Ray's OK.
## Wired (Nov 22, 2026): messages from the bridge's read-only chat:recent (core 1.6.3), polled every 5 s while open,
## with names from plys. SEND (con:say / api:Request_InGameMessage_Faction / _SinglePlayer) and WARN go through the Safety Flow.
## WATCH WORDS are saved on this PC (chat_store.py). DISCORD and MUTE stay off (see DISCORD_TIP and MUTE_TIP).
## ==========================================

# region Imports

from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
                             QButtonGroup, QLineEdit, QListWidget, QListWidgetItem, QCheckBox, QInputDialog)
from PyQt6.QtCore import QTimer, Qt
from datetime import datetime

## Read-only bridge reads, the Safety Flow, and the shared chat history and watch words.
from features.shared import server_actions
from features.chat import chat_store
from features.cheat_checker.cheat_checker_settings import watch_match_kwargs

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

## Qt calls that may return None, wrapped once.
from features.shared.qt_types import layout_item_widget

# endregion


# region Constants

## Chat tabs in mockup order: (tab key, tab text). Message counts get added once there is data.
CHAT_TABS = [
    ("global", "GLOBAL"),
    ("faction", "FACTION"),
    ("private", "PRIVATE"),
    ("discord", "DISCORD"),
]

## Why DISCORD and MUTE stay off.
DISCORD_TIP = "Not connected: ZAH has no Discord bot or webhook set up yet."
MUTE_TIP = "Not possible from the server: the game has no mute command for the server console."

## Seconds between chat polls while the page is open.
POLL_SEC = 5

## Most message lines shown at once (the newest ones).
SHOWN_MESSAGES = 200

## Text WARN starts with (it can be changed before sending).
WARN_TEXT = "Warning from the server: please keep chat civil."

# endregion


# region ChatPage Class

class ChatPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("ChatPage")

        ## The tab shown now. GLOBAL is picked first, like the mockup.
        self.active_tab = "global"
        self.tab_buttons = {}

        ## entity id -> player name from plys, and the hits now shown in RECENT HITS.
        self.player_names = {}
        self.shown_hits = []
        self.setup_widgets()
        self._wire_live_data()

    def setup_widgets(self):

        ## 2 columns: the chat card (wide) and the right column with two cards stacked.
        page_grid = QGridLayout(self)
        page_grid.setContentsMargins(4, 4, 4, 4)
        page_grid.setHorizontalSpacing(14)
        page_grid.setVerticalSpacing(14)

        # region Chat Card

        chat_card, chat_layout = make_card()

        ## Tab row: checkable buttons in an exclusive group, so only one tab is lit at a time.
        tab_row = QHBoxLayout()
        tab_row.setSpacing(4)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        for tab_key, tab_text in CHAT_TABS:
            btn_tab = QPushButton(tab_text)
            btn_tab.setObjectName("ChatTabButton")
            btn_tab.setCheckable(True)
            btn_tab.setMinimumHeight(34)
            spread_letters(btn_tab, 1.5)

            ## The lambda passes this tab's key to _on_tab_clicked.
            btn_tab.clicked.connect(lambda checked, key=tab_key: self._on_tab_clicked(key))
            self.tab_group.addButton(btn_tab)
            self.tab_buttons[tab_key] = btn_tab
            tab_row.addWidget(btn_tab)
        self.tab_buttons[self.active_tab].setChecked(True)
        chat_layout.addLayout(tab_row)

        ## Message list: a dark inner box. Each message becomes one line with time, colour tag, name and text.
        self.messages_box = QFrame()
        self.messages_box.setObjectName("DashInnerBox")
        self.messages_box_layout = QVBoxLayout(self.messages_box)
        self.messages_box_layout.setContentsMargins(12, 8, 12, 8)
        self.messages_box_layout.setSpacing(4)
        self.lbl_messages_empty = QLabel("No chat messages yet.")
        self.lbl_messages_empty.setObjectName("DashEmptyLabel")
        self.messages_box_layout.addWidget(self.lbl_messages_empty)

        ## One row per message. Picking a row in FACTION or PRIVATE chooses who SEND answers.
        self.lst_messages = QListWidget()
        self.lst_messages.setObjectName("ChatMessageList")
        self.lst_messages.setStyleSheet("QListWidget#ChatMessageList { background: transparent; border: none; color: #d8e6f0; }")
        self.messages_box_layout.addWidget(self.lst_messages, stretch=1)
        self.messages_box_layout.addStretch()
        chat_layout.addWidget(self.messages_box, stretch=1)

        ## Reply row: text box and SEND. Both stay off until sending chat is built and approved.
        reply_row = QHBoxLayout()
        reply_row.setSpacing(10)
        self.txt_reply = QLineEdit()
        self.txt_reply.setObjectName("ChatReplyBox")
        self.txt_reply.setPlaceholderText("REPLY AS SERVER")
        self.txt_reply.setMinimumHeight(40)
        self.txt_reply.setEnabled(False)
        reply_row.addWidget(self.txt_reply, stretch=1)
        self.btn_send = QPushButton("SEND")
        self.btn_send.setObjectName("DashActionButton")
        self.btn_send.setMinimumSize(90, 40)
        self.btn_send.setEnabled(False)
        self.btn_send.setToolTip("Coming in a later step.")
        spread_letters(self.btn_send, 1.5)
        reply_row.addWidget(self.btn_send)
        chat_layout.addLayout(reply_row)
        page_grid.addWidget(chat_card, 0, 0, 2, 1)

        # endregion

        # region Watch Words

        ## Each watch word will be a row with its ON/OFF toggle, inside the dark inner box.
        watch_card, watch_layout = make_card("WATCH WORDS")
        self.watch_box = QFrame()
        self.watch_box.setObjectName("DashInnerBox")
        self.watch_box_layout = QVBoxLayout(self.watch_box)
        self.watch_box_layout.setContentsMargins(12, 8, 12, 8)
        self.watch_box_layout.setSpacing(4)
        self.lbl_watch_empty = QLabel("No watch words yet.")
        self.lbl_watch_empty.setObjectName("DashEmptyLabel")
        self.watch_box_layout.addWidget(self.lbl_watch_empty)

        ## Add a word, then switch each word ON/OFF with its box. Saved on this PC only.
        add_row = QHBoxLayout()
        self.txt_watch_word = QLineEdit()
        self.txt_watch_word.setObjectName("ChatReplyBox")
        self.txt_watch_word.setPlaceholderText("Add a watch word")
        self.btn_watch_add = QPushButton("ADD")
        self.btn_watch_add.setObjectName("DashActionButton")
        add_row.addWidget(self.txt_watch_word, stretch=1)
        add_row.addWidget(self.btn_watch_add)
        self.watch_box_layout.addLayout(add_row)
        self.watch_rows_layout = QVBoxLayout()
        self.watch_box_layout.addLayout(self.watch_rows_layout)
        self.watch_box_layout.addStretch()
        watch_layout.addWidget(self.watch_box, stretch=1)
        page_grid.addWidget(watch_card, 0, 1)

        # endregion

        # region Recent Hits

        ## WARN (red) and MUTE (grey) act on the player who hit a watch word. Off for now.
        hits_card, hits_layout = make_card("RECENT HITS")

        ## Newest hit first. WARN acts on the picked hit's player.
        self.lst_hits = QListWidget()
        self.lst_hits.setObjectName("ChatMessageList")
        self.lst_hits.setStyleSheet("QListWidget#ChatMessageList { background: transparent; border: none; color: #ffb454; }")
        self.lst_hits.setMaximumHeight(140)
        hits_layout.addWidget(self.lst_hits)
        hits_row = QHBoxLayout()
        hits_row.setSpacing(12)
        self.btn_warn = QPushButton("WARN")
        self.btn_warn.setObjectName("ChatWarnButton")
        self.btn_mute = QPushButton("MUTE")
        self.btn_mute.setObjectName("ChatMuteButton")
        for btn_hit in (self.btn_warn, self.btn_mute):
            btn_hit.setMinimumHeight(40)
            btn_hit.setEnabled(False)
            btn_hit.setToolTip("Coming in a later step.")
            spread_letters(btn_hit, 1.5)
            hits_row.addWidget(btn_hit)
        hits_layout.addLayout(hits_row)
        page_grid.addWidget(hits_card, 1, 1)

        # endregion

        ## Column widths roughly match the mockup: 2 : 1.
        page_grid.setColumnStretch(0, 2)
        page_grid.setColumnStretch(1, 1)

        ## WATCH WORDS takes most of the right column; RECENT HITS stays short.
        page_grid.setRowStretch(0, 1)
        page_grid.setRowStretch(1, 0)

    # endregion


    # region Tabs

    ## Lights the clicked tab. The message list will filter to that tab once there is chat data.
    def _on_tab_clicked(self, tab_key):
        self.active_tab = tab_key
        if tab_key in self.tab_buttons:
            self.tab_buttons[tab_key].setChecked(True)
        self.show_messages()

    # endregion

    # region Live Data

    def _wire_live_data(self):
        try:
            self.tab_buttons["discord"].setEnabled(False)
            self.tab_buttons["discord"].setToolTip(DISCORD_TIP)
            self.btn_mute.setToolTip(MUTE_TIP)
            self.btn_send.clicked.connect(self._on_send_clicked)
            self.txt_reply.returnPressed.connect(self._on_send_clicked)
            self.txt_reply.textChanged.connect(lambda text: self._refresh_buttons())
            self.lst_messages.itemSelectionChanged.connect(self._refresh_buttons)
            self.lst_hits.itemSelectionChanged.connect(self._refresh_buttons)
            self.btn_warn.clicked.connect(self._on_warn_clicked)
            self.btn_watch_add.clicked.connect(self._on_watch_add)
            self.txt_watch_word.returnPressed.connect(self._on_watch_add)
            self.poll_timer = QTimer(self)
            self.poll_timer.setInterval(POLL_SEC * 1000)
            self.poll_timer.timeout.connect(self.poll_chat)
            self.show_watch_words()
            self.show_messages()
        except Exception as e:
            print(f"[ERROR] ChatPage: Could not wire live data: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        try:
            self.poll_chat()
            self.poll_timer.start()
        except Exception as e:
            print(f"[ERROR] ChatPage: Poll on show failed: {e}")

    def hideEvent(self, event):
        super().hideEvent(event)
        try:
            self.poll_timer.stop()
        except Exception:
            pass

    def poll_chat(self):
        """Asks for new chat lines (read-only), and refreshes names now and then."""
        try:
            self._refresh_buttons()
            if not server_actions.bridge_is_connected(self):
                self.lbl_messages_empty.setText("Connect to the server to see chat.")
                return
            command = 'chat:recent:{"since":%d}' % chat_store.LAST_SEQ["value"]
            chat_items: list = [(command, ("CHAT_LOG", "ERROR", "RESPONSE"), self._on_chat_read,
                           lambda message: print(f"[ERROR] ChatPage: chat:recent failed: {message}"))]
            if not self.player_names or len(chat_store.CHAT_HISTORY) % 20 == 0:
                chat_items.append(("plys", "PLAYER_CACHE", self._on_players_read, lambda message: None))
            server_actions.read_bridge_many(chat_items)
        except Exception as e:
            print(f"[ERROR] ChatPage: Poll failed: {e}")

    def _on_chat_read(self, reply):
        try:
            if not isinstance(reply, dict) or reply.get("type") != "CHAT_LOG":
                self.lbl_messages_empty.setText("This server's bridge has no chat history yet (needs core 1.6.3).")
                self.lbl_messages_empty.setVisible(True)
                return
            if chat_store.add_messages(reply):
                self.show_messages()
        except Exception as e:
            print(f"[ERROR] ChatPage: Could not add chat lines: {e}")

    def _on_players_read(self, reply):
        try:
            for row in (reply or {}).get("player_list") or []:
                if isinstance(row, dict) and row.get("entityId") not in (None, "--"):
                    self.player_names[str(row.get("entityId"))] = str(row.get("name", "?"))
            self.show_messages()
        except Exception as e:
            print(f"[ERROR] ChatPage: Could not read names: {e}")

    def sender_name(self, message):
        if message.get("senderName"):
            return str(message["senderName"])
        if str(message.get("senderType")) != "Player":
            return "SERVER"
        return self.player_names.get(str(message.get("senderId")), f"id {message.get('senderId')}")

    def message_line(self, message):
        try:
            shown_time = datetime.fromisoformat(str(message.get("time")).replace("Z", "+00:00")).astimezone().strftime("%H:%M")
        except ValueError:
            shown_time = "--:--"
        return f"{shown_time}  [{message.get('channel', '?')}]  {self.sender_name(message)}:  {message.get('text', '')}"

    def show_messages(self):
        """Refills the list for the open tab, the tab counts, and RECENT HITS."""
        try:
            for tab_key, tab_text in CHAT_TABS:
                count = len(chat_store.messages_for_tab(tab_key)) if tab_key != "discord" else 0
                self.tab_buttons[tab_key].setText(f"{tab_text} ({count})" if count else tab_text)
            picked = self._picked_message()
            messages = chat_store.messages_for_tab(self.active_tab)[-SHOWN_MESSAGES:]
            self.lst_messages.blockSignals(True)
            self.lst_messages.clear()
            for message in messages:
                item = QListWidgetItem(self.message_line(message))
                item.setData(Qt.ItemDataRole.UserRole, message)
                self.lst_messages.addItem(item)
                if picked is not None and message.get("seq") == picked.get("seq"):
                    item.setSelected(True)
            self.lst_messages.blockSignals(False)
            self.lst_messages.scrollToBottom()
            self.lbl_messages_empty.setVisible(not messages)
            if not messages:
                self.lbl_messages_empty.setText("No chat messages yet.")
            self.shown_hits = chat_store.find_hits(**watch_match_kwargs())[:50]
            self.lst_hits.blockSignals(True)
            self.lst_hits.clear()
            for word, message in self.shown_hits:
                self.lst_hits.addItem(f"\"{word}\"  {self.message_line(message)}")
            self.lst_hits.blockSignals(False)
            self._refresh_buttons()
        except Exception as e:
            print(f"[ERROR] ChatPage: Could not show messages: {e}")

    def _picked_message(self):
        items = self.lst_messages.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else None

    def _picked_hit(self):
        row = self.lst_hits.currentRow()
        return self.shown_hits[row][1] if 0 <= row < len(self.shown_hits) and self.lst_hits.selectedItems() else None

    # endregion

    # region Sending

    def reply_command(self, text):
        """The command SEND would use for the open tab, or None when it needs a picked message."""
        text = text.strip().replace("'", "").replace("|", "/")
        if not text:
            return None
        if self.active_tab == "global":
            return f"con:say '{text}'"
        picked = self._picked_message()
        if picked is None:
            return None
        if self.active_tab == "faction" and int(picked.get("senderFactionId") or 0) > 0:
            return server_actions.message_faction_command(picked['senderFactionId'], text)
        if self.active_tab == "private" and int(picked.get("senderId") or 0) > 0:
            return server_actions.message_player_command(picked['senderId'], text)
        return None

    def _refresh_buttons(self):
        try:
            reason = server_actions.block_reason(self, "chat_send")
            self.txt_reply.setEnabled(reason == "")
            if not reason and self.reply_command(self.txt_reply.text() or "x") is None:
                reason = "Pick a message to answer first." if self.active_tab != "discord" else DISCORD_TIP
            if not reason and not self.txt_reply.text().strip():
                reason = "Type a message first."
            self.btn_send.setEnabled(reason == "")
            self.btn_send.setToolTip(reason or "Sends as the server (Safety Flow).")
            warn_reason = server_actions.block_reason(self, "chat_warn") or ("" if self._picked_hit() else "Pick a hit first.")
            self.btn_warn.setEnabled(warn_reason == "")
            self.btn_warn.setToolTip(warn_reason or "Private HUD warning to that player (Safety Flow).")
            self.btn_mute.setEnabled(False)
        except Exception as e:
            print(f"[ERROR] ChatPage: Could not refresh buttons: {e}")

    def _on_send_clicked(self):
        try:
            command = self.reply_command(self.txt_reply.text())
            if command is None or not self.btn_send.isEnabled():
                return

            def done(ok, reply):
                print(f"[{'SUCCESS' if ok else 'ERROR'}] ChatPage: Send: {server_actions.reply_text(reply)}")
                if ok:
                    self.txt_reply.clear()
            server_actions.run_server_action(self, "chat_send", "Send chat as the server", command, done)
        except Exception as e:
            print(f"[ERROR] ChatPage: Send failed: {e}")

    def _on_warn_clicked(self):
        try:
            hit = self._picked_hit()
            if hit is None or int(hit.get("senderId") or 0) <= 0:
                return
            text, accepted = QInputDialog.getText(self, "Warn", f"Warning for {self.sender_name(hit)}:", text=WARN_TEXT)
            text = text.strip().replace("|", "/")
            if not accepted or not text:
                return
            server_actions.run_server_action(self, "chat_warn", "Warn a player", server_actions.message_player_command(hit['senderId'], text),
                                             lambda ok, reply: print(f"[INFO] ChatPage: Warn ok={ok}"))
        except Exception as e:
            print(f"[ERROR] ChatPage: Warn failed: {e}")

    # endregion

    # region Watch Words

    def show_watch_words(self):
        try:
            while self.watch_rows_layout.count():
                old_item = self.watch_rows_layout.takeAt(0)
                old_widget = layout_item_widget(old_item)
                if old_widget is not None:
                    old_widget.deleteLater()
            rows = chat_store.load_watch_words()
            for index, row in enumerate(rows):
                chk_word = QCheckBox(row["word"])
                chk_word.setChecked(row["on"])
                chk_word.setToolTip("ON/OFF. Right-click removes the word.")
                chk_word.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                chk_word.toggled.connect(lambda checked, number=index: self._on_watch_toggled(number, checked))
                chk_word.customContextMenuRequested.connect(lambda point, number=index: self._on_watch_remove(number))
                self.watch_rows_layout.addWidget(chk_word)
            self.lbl_watch_empty.setVisible(not rows)
        except Exception as e:
            print(f"[ERROR] ChatPage: Could not show watch words: {e}")

    def _on_watch_add(self):
        try:
            word = self.txt_watch_word.text().strip()
            rows = chat_store.load_watch_words()
            if word and word.lower() not in [row["word"].lower() for row in rows]:
                rows.append({"word": word, "on": True})
                chat_store.save_watch_words(rows)
            self.txt_watch_word.clear()
            self.show_watch_words()
            self.show_messages()
        except Exception as e:
            print(f"[ERROR] ChatPage: Could not add a watch word: {e}")

    def _on_watch_toggled(self, number, checked):
        try:
            rows = chat_store.load_watch_words()
            if 0 <= number < len(rows):
                rows[number]["on"] = bool(checked)
                chat_store.save_watch_words(rows)
            self.show_messages()
        except Exception as e:
            print(f"[ERROR] ChatPage: Could not switch a watch word: {e}")

    def _on_watch_remove(self, number):
        try:
            rows = chat_store.load_watch_words()
            if 0 <= number < len(rows):
                rows.pop(number)
                chat_store.save_watch_words(rows)
            self.show_watch_words()
            self.show_messages()
        except Exception as e:
            print(f"[ERROR] ChatPage: Could not remove a watch word: {e}")

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return ChatPage()

# endregion
