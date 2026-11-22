## ==========================================
## ZERO-G ADMIN HELPER - CHAT PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Chat.jpg:
## chat tabs (GLOBAL / FACTION / PRIVATE / DISCORD) over the message list and a REPLY AS SERVER box on the left,
## WATCH WORDS and RECENT HITS on the right.
## Layout only for now: there is no chat data source yet, so the lists show "nothing yet".
## SEND, WARN and MUTE stay greyed out; each one talks to the server and gets its own step with Ray's OK.
## ==========================================

# region Imports

from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
                             QButtonGroup, QLineEdit)

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

# endregion


# region Constants

## Chat tabs in mockup order: (tab key, tab text). Message counts get added once there is data.
CHAT_TABS = [
    ("global", "GLOBAL"),
    ("faction", "FACTION"),
    ("private", "PRIVATE"),
    ("discord", "DISCORD"),
]

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
        self.setup_widgets()

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
        self.watch_box_layout.addStretch()
        watch_layout.addWidget(self.watch_box, stretch=1)
        page_grid.addWidget(watch_card, 0, 1)

        # endregion

        # region Recent Hits

        ## WARN (red) and MUTE (grey) act on the player who hit a watch word. Off for now.
        hits_card, hits_layout = make_card("RECENT HITS")
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

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return ChatPage()

# endregion
