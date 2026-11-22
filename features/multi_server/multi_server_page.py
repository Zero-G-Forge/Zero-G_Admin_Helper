## ==========================================
## ZERO-G ADMIN HELPER - MULTI-SERVER OVERVIEW PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Multi-Server_Overview.jpg:
## one card per connected server (players, CPU / RAM / TICK RATE rings, core, bridge, next restart),
## CROSS-SERVER ALERTS under them, and BROADCAST TO ALL SERVERS at the bottom.
## Its SERVERS nav button only shows while you are connected to 2 or more servers (MainCockpit.update_multi_server_nav).
## Layout only for now: no server stats are read yet, so every number shows "--".
## BROADCAST and RETRY change or contact the live servers, so they stay off until Ray OKs that step.
## Wired (Nov 22, 2026): the cockpit's ServerMonitor polls every saved server read-only (hot:status, plys,
## api:Request_Dedi_Stats) every 30 s, and show_results() fills the cards and CROSS-SERVER ALERTS.
## BROADCAST (one server) and BROADCAST TO ALL SERVERS send api:Request_InGameMessage_AllPlayers through the
## Safety Flow (admin and up). OPEN DASHBOARD makes that server the active one and reconnects.
## CPU stays "--": the game does not report it.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QFont
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QPushButton, QLineEdit, QInputDialog)

## The Safety Flow, and the uptime text shared with the dashboard.
from features.shared import server_actions
from features.dashboard.dashboard_page import format_uptime

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

# endregion


# region Constants

## Tooltip for every button that isn't wired up yet.
LATER_TIP = "Coming in a later step."

## Ring colours: dark track, and the fill colour for each ring.
RING_TRACK = QColor(60, 80, 98)
RING_COLORS = {"CPU": QColor("#33d17a"), "RAM": QColor("#2fa8e0"), "TICK RATE": QColor("#2fa8e0")}

## Why CPU stays empty, and the frame rate that fills the TICK RATE ring.
CPU_TIP = "The game does not report CPU use."
FULL_FPS = 60

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

        ## Latest poll results, and whether the page listens to the cockpit's monitor yet.
        self.results = []
        self.monitor_linked = False
        self.setup_widgets()
        self._wire_live_data()

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
        self.alerts_rows_layout = QVBoxLayout()
        alerts_box_layout.addLayout(self.alerts_rows_layout)
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

        ## Kept on the card so show_results() can fill it.
        server_card.lbl_status = lbl_status
        server_card.rings = {}
        server_card.info_labels = []

        ## Inner box: PLAYERS, the 3 rings, then CORE / BRIDGE / NEXT RESTART.
        stats_box = QFrame()
        stats_box.setObjectName("DashInnerBox")
        stats_layout = QVBoxLayout(stats_box)
        stats_layout.setContentsMargins(14, 12, 14, 12)
        stats_layout.setSpacing(10)
        lbl_players = QLabel("PLAYERS  --")
        lbl_players.setObjectName("BackupCompareTitle")
        stats_layout.addWidget(lbl_players)
        server_card.lbl_players = lbl_players
        rings_row = QHBoxLayout()
        for ring_name in ("CPU", "RAM", "TICK RATE"):
            ring_column = QVBoxLayout()
            ring_column.setSpacing(6)
            lbl_ring = QLabel(ring_name)
            lbl_ring.setObjectName("PlayerInfoLabel")
            lbl_ring.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ring_column.addWidget(lbl_ring)
            ring_gauge = RingGauge(RING_COLORS[ring_name])
            server_card.rings[ring_name] = ring_gauge
            ring_column.addWidget(ring_gauge, alignment=Qt.AlignmentFlag.AlignHCenter)
            rings_row.addLayout(ring_column)
        stats_layout.addLayout(rings_row)
        info_row = QHBoxLayout()
        for info_text in ("CORE\n--", "BRIDGE\n--", "NEXT RESTART\n--"):
            lbl_info = QLabel(info_text)
            lbl_info.setObjectName("PlayerInfoLabel")
            lbl_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
            info_row.addWidget(lbl_info, stretch=1)
            server_card.info_labels.append(lbl_info)
        stats_layout.addLayout(info_row)
        card_layout.addWidget(stats_box, stretch=1)

        ## OPEN DASHBOARD switches the cockpit to this server; BROADCAST talks to this server only.
        button_row = QHBoxLayout()
        button_row.setSpacing(14)
        server_card.buttons = {}
        for button_text in ("OPEN DASHBOARD", "BROADCAST"):
            btn_server = QPushButton(button_text)
            btn_server.setObjectName("DashActionButton")
            btn_server.setFixedHeight(34)
            btn_server.setEnabled(False)
            btn_server.setToolTip(LATER_TIP)
            button_row.addWidget(btn_server)
            server_card.buttons[button_text] = btn_server
        server_card.buttons["OPEN DASHBOARD"].clicked.connect(lambda checked, name=server_name: self._on_open_dashboard(name))
        server_card.buttons["BROADCAST"].clicked.connect(lambda checked, name=server_name: self._on_broadcast_one(name))
        card_layout.addLayout(button_row)
        return server_card

    # endregion

    # region Live Data

    def _wire_live_data(self):
        try:
            self.btn_broadcast_send.clicked.connect(self._on_broadcast_all)
            self.txt_broadcast.returnPressed.connect(self._on_broadcast_all)
            self.txt_broadcast.textChanged.connect(lambda text: self._refresh_buttons())
            self._refresh_buttons()
        except Exception as e:
            print(f"[ERROR] MultiServerPage: Could not wire live data: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        try:
            cockpit = server_actions.find_cockpit(self)
            monitor = getattr(cockpit, "server_monitor", None) if cockpit is not None else None
            if monitor is not None and not self.monitor_linked:
                monitor.servers_updated.connect(self.show_results)
                self.monitor_linked = True
            if monitor is not None:
                self.show_results(monitor.results)
                monitor.poll_now()
        except Exception as e:
            print(f"[ERROR] MultiServerPage: Could not link the server monitor: {e}")

    def show_results(self, results):
        """Draws one card per saved server from a ServerMonitor poll, plus the cross-server alerts."""
        try:
            self.results = list(results or [])
            names = [result["name"] for result in self.results]
            if names != list(self.server_cards):
                self.set_servers(names)
            for result in self.results:
                server_card = self.server_cards.get(result["name"])
                if server_card is None:
                    continue
                online = bool(result.get("online"))
                server_card.lbl_status.setText("ONLINE" if online else "OFFLINE")
                if result.get("players_online") is None:
                    server_card.lbl_players.setText("PLAYERS  --")
                else:
                    server_card.lbl_players.setText(f"PLAYERS  {result['players_online']} / {result['players_total']}")
                server_card.rings["CPU"].set_value(None, "--")
                server_card.rings["CPU"].setToolTip(CPU_TIP)
                mem = result.get("mem")
                server_card.rings["RAM"].set_value(None, "--" if mem is None else f"{int(mem)}")
                server_card.rings["RAM"].setToolTip("Server memory in MB, as the game reports it.")
                fps = result.get("fps")
                server_card.rings["TICK RATE"].set_value(None if fps is None else 100 * min(fps, FULL_FPS) / FULL_FPS,
                                                         "--" if fps is None else f"{int(fps)}")
                server_card.rings["TICK RATE"].setToolTip("Server frames per second.")
                uptime = result.get("uptime")
                server_card.info_labels[0].setText(f"CORE\n{result.get('core', '--')}")
                server_card.info_labels[1].setText(f"BRIDGE\n{'ONLINE' if online else 'OFFLINE'}")
                server_card.info_labels[2].setText("UPTIME\n" + ("--" if uptime is None else format_uptime(uptime)))
            self.show_alerts()
            self._refresh_buttons()
        except Exception as e:
            print(f"[ERROR] MultiServerPage: Could not show results: {e}")

    def show_alerts(self):
        try:
            while self.alerts_rows_layout.count():
                old_item = self.alerts_rows_layout.takeAt(0)
                if old_item.widget() is not None:
                    old_item.widget().deleteLater()
            lines = []
            for result in self.results:
                if not result.get("online"):
                    lines.append(f"WARNING   {result['name']}: the bridge does not answer")
                for name in result.get("flagged") or []:
                    lines.append(f"CRITICAL   {result['name']}: {name} has a cheat flag")
            for line in lines:
                lbl_alert = QLabel(line)
                lbl_alert.setObjectName("PlayerInfoLabel")
                self.alerts_rows_layout.addWidget(lbl_alert)
            self.lbl_alerts_empty.setVisible(not lines)
        except Exception as e:
            print(f"[ERROR] MultiServerPage: Could not show alerts: {e}")

    def online_profiles(self):
        return [result["profile"] for result in self.results if result.get("online") and isinstance(result.get("profile"), dict)]

    def _refresh_buttons(self):
        try:

            ## Each server gets its own connection, so only the role matters here, not the main bridge.
            reason = "" if server_actions.user_may(self, "multi_broadcast") else "Needs the admin role or higher."
            for result in self.results:
                server_card = self.server_cards.get(result["name"])
                if server_card is None:
                    continue
                online = bool(result.get("online"))
                open_reason = "" if online else "This server does not answer."
                server_card.buttons["OPEN DASHBOARD"].setEnabled(open_reason == "")
                server_card.buttons["OPEN DASHBOARD"].setToolTip(open_reason or "Makes this the active server and reconnects.")
                one_reason = reason or open_reason
                server_card.buttons["BROADCAST"].setEnabled(one_reason == "")
                server_card.buttons["BROADCAST"].setToolTip(one_reason or "HUD message to everyone on this server (Safety Flow).")
            all_reason = reason or ("" if self.online_profiles() else "No server answers.")
            self.txt_broadcast.setEnabled(all_reason == "")
            self.txt_broadcast.setToolTip(all_reason or "Message for every server that answers.")
            if not all_reason and not self.txt_broadcast.text().strip():
                all_reason = "Type a message first."
            self.btn_broadcast_send.setEnabled(all_reason == "")
            self.btn_broadcast_send.setToolTip(all_reason or "Sends to every server that answers (Safety Flow).")
        except Exception as e:
            print(f"[ERROR] MultiServerPage: Could not refresh buttons: {e}")

    # endregion

    # region Actions

    def _result_named(self, server_name):
        return next((result for result in self.results if result["name"] == server_name), None)

    def _on_open_dashboard(self, server_name):
        try:
            names = [result["name"] for result in self.results]
            cockpit = server_actions.find_cockpit(self)
            if server_name in names and cockpit is not None and hasattr(cockpit, "switch_server"):
                cockpit.switch_server(names.index(server_name))
        except Exception as e:
            print(f"[ERROR] MultiServerPage: Open dashboard failed: {e}")

    def _on_broadcast_one(self, server_name):
        try:
            result = self._result_named(server_name)
            if result is None or not result.get("online"):
                return
            text, accepted = QInputDialog.getText(self, "Broadcast", f"HUD message to everyone on {server_name}:")
            text = text.strip()
            if not accepted or not text:
                return
            server_actions.run_server_action(self, "multi_broadcast", f"Broadcast on {server_name}",
                                             server_actions.message_all_command(text),
                                             lambda ok, reply: print(f"[INFO] MultiServerPage: Broadcast on {server_name} ok={ok}"),
                                             profile=result["profile"],
                                             explanation=f"Shows this on the screen of everyone on {server_name}.")
        except Exception as e:
            print(f"[ERROR] MultiServerPage: Broadcast failed: {e}")

    def _on_broadcast_all(self):
        try:
            text = self.txt_broadcast.text().strip()
            profiles = self.online_profiles()
            if not text or not profiles or not self.btn_broadcast_send.isEnabled():
                return
            names = ", ".join(str(profile.get("server_name", "?")) for profile in profiles)

            def done(ok, results):
                print(f"[{'SUCCESS' if ok else 'WARN'}] MultiServerPage: Broadcast to all: "
                      + "; ".join(f"{name} {'ok' if server_actions.reply_ok(reply) else 'failed'}" for name, reply in (results if isinstance(results, list) else [])))
                if ok:
                    self.txt_broadcast.clear()
            server_actions.run_server_action(self, "multi_broadcast", "Broadcast to all servers",
                                             server_actions.message_all_command(text), done, profiles=profiles,
                                             explanation=f"Shows this on the screen of everyone on: {names}.")
        except Exception as e:
            print(f"[ERROR] MultiServerPage: Broadcast to all failed: {e}")

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return MultiServerPage()

# endregion
