## ==========================================
## ZERO-G ADMIN HELPER - MULTI-SERVER OVERVIEW PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Multi-Server_Overview.jpg:
## one card per connected server (players, CPU / RAM / TICK RATE rings, core, bridge, next restart),
## CROSS-SERVER ALERTS under them, and BROADCAST TO ALL SERVERS at the bottom.
## Its SERVERS nav button only shows while you are connected to 2 or more servers (MainCockpit.update_multi_server_nav).
## Layout only for now: no server stats are read yet, so every number shows "--".
## BROADCAST and RETRY change or contact the live servers, so they stay off until Ray OKs that step.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QFont
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QPushButton, QLineEdit)

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

# endregion


# region Constants

## Tooltip for every button that isn't wired up yet.
LATER_TIP = "Coming in a later step."

## Ring colours: dark track, and the fill colour for each ring.
RING_TRACK = QColor(60, 80, 98)
RING_COLORS = {"CPU": QColor("#33d17a"), "RAM": QColor("#2fa8e0"), "TICK RATE": QColor("#2fa8e0")}

# endregion


# region RingGauge Class

class RingGauge(QWidget):
    """A round gauge: a dark ring, a coloured arc for the value, and the number in the middle.
    With no value yet it shows only the dark ring and "--"."""

    def __init__(self, ring_color, parent=None):
        super().__init__(parent)
        self.ring_color = ring_color
        self.ring_value = None
        self.ring_text = "--"
        self.setFixedSize(92, 92)

    def set_value(self, percent, text):
        """percent is 0-100 (or None for no data); text is what shows in the middle, e.g. '23%'."""
        self.ring_value = percent
        self.ring_text = text
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            ## The ring sits 6px inside the widget so the thick pen isn't cut off at the edges.
            ring_rect = QRectF(6, 6, self.width() - 12, self.height() - 12)
            painter.setPen(QPen(RING_TRACK, 7))
            painter.drawEllipse(ring_rect)

            ## Qt angles are in 1/16 of a degree. 90 degrees is the top; a negative span goes clockwise.
            if self.ring_value is not None:
                fill_pen = QPen(self.ring_color, 7)
                fill_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(fill_pen)
                span = int(-360 * 16 * max(0, min(100, self.ring_value)) / 100)
                painter.drawArc(ring_rect, 90 * 16, span)

            ## The number in the middle.
            painter.setPen(QColor("#ffffff"))
            text_font = QFont(self.font())
            text_font.setPixelSize(20)
            text_font.setBold(True)
            painter.setFont(text_font)
            painter.drawText(ring_rect, Qt.AlignmentFlag.AlignCenter, self.ring_text)

        ## finally: always runs, so the painter is closed even if drawing fails.
        finally:
            painter.end()

# endregion


# region MultiServerPage Class

class MultiServerPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("MultiServerPage")
        self.server_cards = {}
        self.setup_widgets()

    def setup_widgets(self):

        ## Rows: server cards (tall), cross-server alerts, broadcast.
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(4, 4, 4, 4)
        page_layout.setSpacing(14)

        # region Server Cards

        ## One card per connected server, side by side. set_servers() fills this row.
        self.servers_row = QHBoxLayout()
        self.servers_row.setSpacing(14)
        self.lbl_servers_empty = QLabel("Connect to two or more servers to see them side by side here.")
        self.lbl_servers_empty.setObjectName("DashEmptyLabel")
        self.lbl_servers_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.servers_row.addWidget(self.lbl_servers_empty)
        page_layout.addLayout(self.servers_row, stretch=3)

        # endregion

        # region Cross-Server Alerts

        ## Alerts from every server in one list, each tagged CRITICAL or WARNING.
        alerts_card, alerts_layout = make_card("CROSS-SERVER ALERTS")
        self.alerts_box = QFrame()
        self.alerts_box.setObjectName("DashInnerBox")
        alerts_box_layout = QVBoxLayout(self.alerts_box)
        alerts_box_layout.setContentsMargins(12, 8, 12, 8)
        self.lbl_alerts_empty = QLabel("No alerts yet.")
        self.lbl_alerts_empty.setObjectName("DashEmptyLabel")
        alerts_box_layout.addWidget(self.lbl_alerts_empty)
        alerts_layout.addWidget(self.alerts_box)
        page_layout.addWidget(alerts_card, stretch=1)

        # endregion

        # region Broadcast

        ## One message sent to every connected server's chat. Off until sending is built and approved.
        broadcast_card, broadcast_layout = make_card("BROADCAST TO ALL SERVERS")
        broadcast_row = QHBoxLayout()
        broadcast_row.setSpacing(14)
        lbl_broadcast_hint = QLabel("Example: Server restart in 15 minutes")
        lbl_broadcast_hint.setObjectName("BackupHintLabel")
        broadcast_row.addWidget(lbl_broadcast_hint, stretch=1)
        self.txt_broadcast = QLineEdit()
        self.txt_broadcast.setObjectName("ChatReplyBox")
        self.txt_broadcast.setFixedHeight(34)
        self.txt_broadcast.setEnabled(False)
        self.txt_broadcast.setToolTip(LATER_TIP)
        broadcast_row.addWidget(self.txt_broadcast, stretch=1)
        self.btn_broadcast_send = QPushButton("SEND")
        self.btn_broadcast_send.setObjectName("DashActionButton")
        self.btn_broadcast_send.setFixedSize(90, 34)
        self.btn_broadcast_send.setEnabled(False)
        self.btn_broadcast_send.setToolTip(LATER_TIP)
        broadcast_row.addWidget(self.btn_broadcast_send)
        broadcast_layout.addLayout(broadcast_row)
        page_layout.addWidget(broadcast_card)

        # endregion

    # endregion

    # region Server Cards

    def set_servers(self, server_names):
        """Rebuilds the row of server cards, one per name. An empty list shows the 'connect to two or more' note."""
        try:

            ## Take the old cards out first.
            for old_card in self.server_cards.values():
                self.servers_row.removeWidget(old_card)
                old_card.deleteLater()
            self.server_cards = {}
            for server_name in server_names:
                server_card = self._make_server_card(server_name)
                self.server_cards[server_name] = server_card
                self.servers_row.addWidget(server_card, stretch=1)
            self.lbl_servers_empty.setVisible(len(self.server_cards) == 0)
        except Exception as e:
            print(f"[ERROR] MultiServerPage: Failed to build server cards: {e}")

    def _make_server_card(self, server_name):
        """Builds one server card: name and status, players, 3 rings, an info row and 2 buttons."""
        server_card, card_layout = make_card(str(server_name).upper())

        ## Status on the right of the title, e.g. ONLINE (green) or RECONNECTING (amber). "--" until it is read.
        card_title = server_card.findChild(QLabel, "DashCardTitle")
        lbl_status = QLabel("--")
        lbl_status.setObjectName("PlayerInfoLabel")
        if card_title is not None:
            title_row = QHBoxLayout()
            card_layout.replaceWidget(card_title, QWidget())
            title_row.addWidget(card_title)
            title_row.addStretch()
            title_row.addWidget(lbl_status)
            card_layout.insertLayout(0, title_row)

        ## Inner box: PLAYERS, the 3 rings, then CORE / BRIDGE / NEXT RESTART.
        stats_box = QFrame()
        stats_box.setObjectName("DashInnerBox")
        stats_layout = QVBoxLayout(stats_box)
        stats_layout.setContentsMargins(14, 12, 14, 12)
        stats_layout.setSpacing(10)
        lbl_players = QLabel("PLAYERS  --")
        lbl_players.setObjectName("BackupCompareTitle")
        stats_layout.addWidget(lbl_players)
        rings_row = QHBoxLayout()
        for ring_name in ("CPU", "RAM", "TICK RATE"):
            ring_column = QVBoxLayout()
            ring_column.setSpacing(6)
            lbl_ring = QLabel(ring_name)
            lbl_ring.setObjectName("PlayerInfoLabel")
            lbl_ring.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ring_column.addWidget(lbl_ring)
            ring_column.addWidget(RingGauge(RING_COLORS[ring_name]), alignment=Qt.AlignmentFlag.AlignHCenter)
            rings_row.addLayout(ring_column)
        stats_layout.addLayout(rings_row)
        info_row = QHBoxLayout()
        for info_text in ("CORE\n--", "BRIDGE\n--", "NEXT RESTART\n--"):
            lbl_info = QLabel(info_text)
            lbl_info.setObjectName("PlayerInfoLabel")
            lbl_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
            info_row.addWidget(lbl_info, stretch=1)
        stats_layout.addLayout(info_row)
        card_layout.addWidget(stats_box, stretch=1)

        ## OPEN DASHBOARD switches the cockpit to this server; BROADCAST talks to this server only.
        button_row = QHBoxLayout()
        button_row.setSpacing(14)
        for button_text in ("OPEN DASHBOARD", "BROADCAST"):
            btn_server = QPushButton(button_text)
            btn_server.setObjectName("DashActionButton")
            btn_server.setFixedHeight(34)
            btn_server.setEnabled(False)
            btn_server.setToolTip(LATER_TIP)
            button_row.addWidget(btn_server)
        card_layout.addLayout(button_row)
        return server_card

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return MultiServerPage()

# endregion
