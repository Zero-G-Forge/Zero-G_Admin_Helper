## ==========================================
## ZERO-G ADMIN HELPER - ALERTS & ANTI-CHEAT PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Alerts_Anti-cheat.jpg:
## ALERT QUEUE on the left, the picked alert's details and EVIDENCE TIMELINE in the middle,
## COMMAND PREVIEW with the PREVIEW BAN button on the right.
## Layout only for now: there is no alert data source yet, so every panel shows "nothing yet".
## PREVIEW BAN stays greyed out; a ban is a real server action and gets its own step with Ray's OK.
## Wired (Nov 22, 2026): the queue is built here from two read-only sources: the plys cheat flags (CRITICAL) and
## chat watch-word hits from chat:recent (WARNING). ACK hides an alert on this PC. PREVIEW BAN fills COMMAND
## PREVIEW with con:ban and sends it only through the Safety Flow (admin and up).
## ==========================================

# region Imports

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QGridLayout, QPushButton,
                             QTableWidget, QHeaderView, QAbstractItemView, QPlainTextEdit, QListWidget,
                             QListWidgetItem, QTableWidgetItem, QInputDialog)

## Read-only bridge reads, the Safety Flow, chat watch-word hits, the cheat-flag rule and the ban lengths.
from features.shared import server_actions
from features.chat import chat_store
from features.dashboard.dashboard_page import is_flagged
from features.players.players_page import BAN_LENGTHS

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

# endregion


# region Constants

## Columns of the alert detail table, as in the mockup.
DETAIL_COLUMNS = ["ITEM", "BEFORE", "AFTER", "DELTA"]

## Seconds between refreshes while the page is open.
REFRESH_SEC = 15

## Alert keys acknowledged on this PC (kept while ZAH runs).
ACKNOWLEDGED = set()


## Builds the alert list: one CRITICAL per flagged player, one WARNING per chat hit. Newest hits first.
def build_alerts(players, hits):
    alerts = []
    for player in players:
        if isinstance(player, dict) and is_flagged(player):
            alerts.append({"key": f"cheat:{player.get('steamId') or player.get('name')}", "level": "CRITICAL",
                           "title": "CHEAT FLAG", "player": player, "entity_id": str(player.get("entityId", "")),
                           "name": str(player.get("name", "?"))})
    for word, message in hits:
        alerts.append({"key": f"chat:{message.get('seq')}", "level": "WARNING", "title": f"WATCH WORD: {word.upper()}",
                       "message": message, "entity_id": str(message.get("senderId", "")), "name": "", "word": word})
    return alerts

# endregion


# region AlertsPage Class

class AlertsPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("AlertsPage")

        ## Read players, and the alerts shown in the queue now.
        self.players = []
        self.alerts = []
        self.setup_widgets()
        self._wire_live_data()

    def setup_widgets(self):

        ## 3 columns: queue (narrow), details + timeline (wide), command preview (medium).
        ## The queue and command preview cards span both rows.
        page_grid = QGridLayout(self)
        page_grid.setContentsMargins(4, 4, 4, 4)
        page_grid.setHorizontalSpacing(14)
        page_grid.setVerticalSpacing(14)

        # region Alert Queue

        ## Each alert will be a row with a CRITICAL or WARNING badge and an ACK button.
        queue_card, queue_layout = make_card("ALERT QUEUE")
        self.lbl_queue_empty = QLabel("No alerts yet.")
        self.lbl_queue_empty.setObjectName("DashEmptyLabel")
        queue_layout.addWidget(self.lbl_queue_empty)
        self.lst_alerts = QListWidget()
        self.lst_alerts.setObjectName("AlertQueueList")
        self.lst_alerts.setStyleSheet("QListWidget#AlertQueueList { background: transparent; border: none; color: #d8e6f0; }")
        queue_layout.addWidget(self.lst_alerts, stretch=1)

        ## ACK hides the picked alert on this PC; it sends nothing to the server.
        self.btn_ack = QPushButton("ACK")
        self.btn_ack.setObjectName("DashActionButton")
        self.btn_ack.setEnabled(False)
        self.btn_ack.setToolTip("Pick an alert first.")
        queue_layout.addWidget(self.btn_ack)
        queue_layout.addStretch()
        page_grid.addWidget(queue_card, 0, 0, 2, 1)

        # endregion

        # region Alert Details

        ## The title becomes the alert's name (e.g. INVENTORY JUMP DETECTED) once one is picked.
        detail_card, detail_layout = make_card("NO ALERT SELECTED")
        self.lbl_detail_title = detail_card.findChild(QLabel, "DashCardTitle")
        self.lbl_detail_player = QLabel("PLAYER:  --")
        self.lbl_detail_player.setObjectName("AlertPlayerLabel")
        detail_layout.addWidget(self.lbl_detail_player)

        self.tbl_detail = QTableWidget(0, len(DETAIL_COLUMNS))
        self.tbl_detail.setObjectName("DashTable")
        self.tbl_detail.setHorizontalHeaderLabels(DETAIL_COLUMNS)
        self.tbl_detail.verticalHeader().setVisible(False)
        self.tbl_detail.setShowGrid(False)
        self.tbl_detail.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_detail.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tbl_detail.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        detail_layout.addWidget(self.tbl_detail)
        self.lbl_detail_empty = QLabel("Pick an alert to see its details.")
        self.lbl_detail_empty.setObjectName("DashEmptyLabel")
        detail_layout.addWidget(self.lbl_detail_empty)
        page_grid.addWidget(detail_card, 0, 1)

        # endregion

        # region Evidence Timeline

        ## The dots-on-a-line timeline is drawn here once an alert has evidence times.
        timeline_card, timeline_layout = make_card("EVIDENCE TIMELINE")
        self.lbl_timeline_empty = QLabel("No evidence yet.")
        self.lbl_timeline_empty.setObjectName("DashEmptyLabel")
        timeline_layout.addWidget(self.lbl_timeline_empty)
        self.lst_timeline = QListWidget()
        self.lst_timeline.setObjectName("AlertQueueList")
        self.lst_timeline.setStyleSheet("QListWidget#AlertQueueList { background: transparent; border: none; color: #ffb454; }")
        timeline_layout.addWidget(self.lst_timeline, stretch=1)
        timeline_layout.addStretch()
        page_grid.addWidget(timeline_card, 1, 1)

        # endregion

        # region Command Preview

        ## Read-only box: shows the exact command before anything is sent, so nothing is a surprise.
        preview_card, preview_layout = make_card("COMMAND PREVIEW")
        self.txt_command_preview = QPlainTextEdit()
        self.txt_command_preview.setObjectName("AlertPreviewBox")
        self.txt_command_preview.setReadOnly(True)
        self.txt_command_preview.setPlaceholderText("No command yet.")
        preview_layout.addWidget(self.txt_command_preview, stretch=1)

        ## Amber outlined button from the mockup, greyed out until bans get their own step.
        self.btn_preview_ban = QPushButton("PREVIEW BAN")
        self.btn_preview_ban.setObjectName("AlertBanButton")
        self.btn_preview_ban.setMinimumHeight(52)
        self.btn_preview_ban.setEnabled(False)
        self.btn_preview_ban.setToolTip("Pick an alert first.")
        spread_letters(self.btn_preview_ban, 2.0)
        preview_layout.addWidget(self.btn_preview_ban)
        page_grid.addWidget(preview_card, 0, 2, 2, 1)

        # endregion

        ## Column widths roughly match the mockup: 3 : 5 : 4.
        page_grid.setColumnStretch(0, 3)
        page_grid.setColumnStretch(1, 5)
        page_grid.setColumnStretch(2, 4)

        ## The details card is a bit shorter than the timeline below it.
        page_grid.setRowStretch(0, 2)
        page_grid.setRowStretch(1, 3)

    # endregion

    # region Live Data

    def _wire_live_data(self):
        try:
            self.lst_alerts.itemSelectionChanged.connect(self.show_detail)
            self.btn_ack.clicked.connect(self._on_ack_clicked)
            self.btn_preview_ban.clicked.connect(self._on_preview_ban_clicked)
            self.refresh_timer = QTimer(self)
            self.refresh_timer.setInterval(REFRESH_SEC * 1000)
            self.refresh_timer.timeout.connect(self.refresh_live)
        except Exception as e:
            print(f"[ERROR] AlertsPage: Could not wire live data: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        try:
            self.refresh_live()
            self.refresh_timer.start()
        except Exception as e:
            print(f"[ERROR] AlertsPage: Refresh on show failed: {e}")

    def hideEvent(self, event):
        super().hideEvent(event)
        try:
            self.refresh_timer.stop()
        except Exception:
            pass

    def refresh_live(self):
        try:
            if not server_actions.bridge_is_connected(self):
                self.lbl_queue_empty.setText("Connect to the server to see alerts.")
                return
            server_actions.read_bridge("plys", "PLAYER_CACHE", self._on_players_read,
                                       lambda message: print(f"[ERROR] AlertsPage: plys failed: {message}"))
            server_actions.read_bridge('chat:recent:{"since":%d}' % chat_store.LAST_SEQ["value"], ("CHAT_LOG", "ERROR", "RESPONSE"),
                                       self._on_chat_read, lambda message: None)
        except Exception as e:
            print(f"[ERROR] AlertsPage: Refresh failed: {e}")

    def _on_players_read(self, reply):
        try:
            self.players = [row for row in ((reply or {}).get("player_list") or []) if isinstance(row, dict)]
            self.show_alerts()
        except Exception as e:
            print(f"[ERROR] AlertsPage: Could not read players: {e}")

    def _on_chat_read(self, reply):
        try:
            if isinstance(reply, dict) and reply.get("type") == "CHAT_LOG":
                chat_store.add_messages(reply)
            self.show_alerts()
        except Exception as e:
            print(f"[ERROR] AlertsPage: Could not read chat: {e}")

    def player_name(self, entity_id):
        for row in self.players:
            if str(row.get("entityId")) == str(entity_id):
                return str(row.get("name", "?"))
        return f"id {entity_id}"

    def show_alerts(self):
        try:
            picked = self.selected_alert()
            self.alerts = [alert for alert in build_alerts(self.players, chat_store.find_hits()) if alert["key"] not in ACKNOWLEDGED]
            self.lst_alerts.blockSignals(True)
            self.lst_alerts.clear()
            for alert in self.alerts:
                if not alert["name"]:
                    alert["name"] = self.player_name(alert["entity_id"])
                item = QListWidgetItem(f"{alert['level']}   {alert['title']}\n{alert['name']}")
                item.setData(Qt.ItemDataRole.UserRole, alert["key"])
                self.lst_alerts.addItem(item)
                if picked is not None and alert["key"] == picked["key"]:
                    item.setSelected(True)
            self.lst_alerts.blockSignals(False)
            self.lbl_queue_empty.setVisible(not self.alerts)
            if not self.alerts:
                self.lbl_queue_empty.setText("No alerts yet.")
            cockpit = server_actions.find_cockpit(self)
            critical = sum(1 for alert in self.alerts if alert["level"] == "CRITICAL")
            if cockpit is not None and hasattr(cockpit, "update_alert_badge"):
                cockpit.update_alert_badge(critical)
            self.show_detail()
        except Exception as e:
            print(f"[ERROR] AlertsPage: Could not show alerts: {e}")

    def selected_alert(self):
        items = self.lst_alerts.selectedItems()
        if not items:
            return None
        key = items[0].data(Qt.ItemDataRole.UserRole)
        return next((alert for alert in self.alerts if alert["key"] == key), None)

    def ban_command(self, alert, length="1d"):
        entity_id = str((alert or {}).get("entity_id", ""))
        return f"con:ban {entity_id} {length}" if entity_id.isdigit() and int(entity_id) > 0 else None

    def show_detail(self):
        """Fills the detail table, the timeline and the command preview for the picked alert."""
        try:
            alert = self.selected_alert()
            self.tbl_detail.setRowCount(0)
            self.lst_timeline.clear()
            if alert is None:
                self.lbl_detail_title.setText("NO ALERT SELECTED")
                self.lbl_detail_player.setText("PLAYER:  --")
                self.lbl_detail_empty.setVisible(True)
                self.lbl_timeline_empty.setVisible(True)
                self.txt_command_preview.setPlainText("")
            else:
                self.lbl_detail_title.setText(alert["title"])
                self.lbl_detail_player.setText(f"PLAYER:  {alert['name']}   (id {alert['entity_id'] or '--'})")
                rows = []
                if alert["level"] == "CRITICAL":
                    player = alert["player"]

                    ## The game gives only the current flags, so BEFORE and DELTA stay "--".
                    for field in ("cheat", "cheater", "banned", "playfield", "faction"):
                        rows.append((field.upper(), "--", str(player.get(field, "--")), "--"))
                    self.lst_timeline.addItem(f"Last seen:  {player.get('last_seen', '--')}")
                    self.lst_timeline.addItem(f"Flags now:  cheat {player.get('cheat', '--')}, cheater {player.get('cheater', '--')}")
                else:
                    message = alert["message"]
                    rows.append(("WATCH WORD", "--", alert["word"], "--"))
                    rows.append(("CHANNEL", "--", str(message.get("channel", "--")), "--"))
                    for word, hit in chat_store.find_hits():
                        if str(hit.get("senderId")) == alert["entity_id"]:
                            self.lst_timeline.addItem(f"{str(hit.get('time', ''))[11:16]} UTC  \"{word}\"  {hit.get('text', '')}")
                for row_values in rows:
                    row_index = self.tbl_detail.rowCount()
                    self.tbl_detail.insertRow(row_index)
                    for column_index, value in enumerate(row_values):
                        self.tbl_detail.setItem(row_index, column_index, QTableWidgetItem(value))
                self.lbl_detail_empty.setVisible(False)
                self.lbl_timeline_empty.setVisible(self.lst_timeline.count() == 0)
                command = self.ban_command(alert)
                self.txt_command_preview.setPlainText(command or "This alert has no player id, so there is nothing to ban.")
            reason = server_actions.block_reason(self, "alert_ban")
            if not reason and (alert is None or self.ban_command(alert) is None):
                reason = "Pick an alert with a player first."
            self.btn_preview_ban.setEnabled(reason == "")
            self.btn_preview_ban.setToolTip(reason or "Picks a length, then bans through the Safety Flow.")
            self.btn_ack.setEnabled(alert is not None)
            self.btn_ack.setToolTip("Hides this alert on this PC." if alert is not None else "Pick an alert first.")
        except Exception as e:
            print(f"[ERROR] AlertsPage: Could not show detail: {e}")

    # endregion

    # region Actions

    def _on_ack_clicked(self):
        try:
            alert = self.selected_alert()
            if alert is not None:
                ACKNOWLEDGED.add(alert["key"])
                self.show_alerts()
        except Exception as e:
            print(f"[ERROR] AlertsPage: ACK failed: {e}")

    def _on_preview_ban_clicked(self):
        try:
            alert = self.selected_alert()
            if alert is None or self.ban_command(alert) is None:
                return
            length, accepted = QInputDialog.getItem(self, "Ban", f"Ban length for {alert['name']}:", BAN_LENGTHS, 1, False)
            if not accepted or length not in BAN_LENGTHS:
                return
            command = self.ban_command(alert, length)
            self.txt_command_preview.setPlainText(command)

            def done(ok, reply):
                print(f"[{'SUCCESS' if ok else 'ERROR'}] AlertsPage: Ban: {server_actions.reply_text(reply)}")
                if ok:
                    ACKNOWLEDGED.add(alert["key"])
                    self.refresh_live()
            server_actions.run_server_action(self, "alert_ban", "Ban from an alert", command, done,
                                             explanation=f"Bans {alert['name']} for {length} because of: {alert['title']}.")
        except Exception as e:
            print(f"[ERROR] AlertsPage: Ban failed: {e}")

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return AlertsPage()

# endregion
