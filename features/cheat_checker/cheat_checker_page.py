## ==========================================
## ZERO-G ADMIN HELPER - CHEAT CHECKER SETTINGS PAGE
## Local settings that feed the Alerts & Anti-Cheat queue. SAVE writes
## data/cheat_checker_settings.json. Watch words still live in
## data/chat_watch_words.json (the same list the Chat page uses) and are
## written when SAVE is pressed. Inventory jump, speed or position delta,
## and uncommanded god mode stay off because the server does not send that
## data. Nothing on this page sends a kick or a ban.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QPushButton, QCheckBox, QComboBox, QSpinBox, QLineEdit, QScrollArea,
                             QFileDialog)

from features.chat import chat_store
from features.cheat_checker.cheat_checker_settings import (
    DEFAULT_SETTINGS, load_cheat_checker_settings, save_cheat_checker_settings,
    export_cheat_checker_settings, ALLOWED_SEVERITIES, ALLOWED_ACTIONS,
)
from features.dashboard.dashboard_page import make_card

# endregion


# region Helpers

ACTION_LABELS = [("suggest", "Suggest only"), ("preview_ban", "Suggest PREVIEW BAN")]
ROLE_LABELS = [("", "No extra filter"), ("moderator", "Moderator"),
               ("admin", "Admin"), ("owner", "Owner"), ("developer", "Developer")]

DISABLED_DETECTIONS = (
    ("Inventory jump", "Not available: the server does not send inventory-jump data."),
    ("Speed / position delta", "Not available: the server does not send speed or position-delta data."),
    ("Uncommanded god mode", "Not available: plys has no god-mode flag, and ZAH does not poll the godmode console command."),
)


def make_note(text):
    label = QLabel(text)
    label.setObjectName("SettingsNote")
    label.setWordWrap(True)
    label.setStyleSheet("QLabel#SettingsNote { color: #8fa6b8; font-size: 12px; }")
    return label


def make_severity(current="Alert"):
    combo = QComboBox()
    combo.setObjectName("EcfFileCombo")
    combo.addItems(list(ALLOWED_SEVERITIES))
    if current in ALLOWED_SEVERITIES:
        combo.setCurrentText(current)
    combo.setFixedWidth(110)
    combo.setFixedHeight(32)
    return combo


def make_action(current="suggest"):
    combo = QComboBox()
    combo.setObjectName("EcfFileCombo")
    for key, label in ACTION_LABELS:
        combo.addItem(label, key)
    index = combo.findData(current if current in ALLOWED_ACTIONS else "suggest")
    combo.setCurrentIndex(index if index >= 0 else 0)
    combo.setMinimumWidth(200)
    combo.setFixedHeight(32)
    return combo


def make_spin(value, minimum, maximum, suffix="", width=100):
    box = QSpinBox()
    box.setObjectName("LibraryQuantityBox")
    box.setRange(minimum, maximum)
    box.setValue(value)
    if suffix:
        box.setSuffix(suffix)
    box.setFixedWidth(width)
    box.setFixedHeight(32)
    return box


def field_label(text):
    label = QLabel(text)
    label.setStyleSheet("QLabel { color: #dcebf5; font-size: 13px; }")
    return label


def labeled_row(*widgets, stretch_index=None):
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(8)
    for index, widget in enumerate(widgets):
        layout.addWidget(widget, stretch=1 if stretch_index == index else 0)
    layout.addStretch()
    return row

# endregion


# region CheatCheckerPage Class

class CheatCheckerPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("CheatCheckerPage")
        self.setup_widgets()
        self.load_into_widgets(load_cheat_checker_settings())

    def setup_widgets(self):
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(10)

        scroll = QScrollArea()
        scroll.setObjectName("CheatCheckerScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("CheatCheckerInner")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 8, 0)
        inner_layout.setSpacing(14)

        # region Detection

        detect_card, detect_layout = make_card("DETECTION TOGGLES")
        detect_layout.addWidget(make_note(
            "The only cheat flags ZAH can read today are the plys fields cheat (On/Off) and cheater (Yes/No). "
            "Alerts already treats either one as CRITICAL when this page has no saved settings. "
            "api:Request_Dedi_Stats is fps, memory, and uptime only, and does not carry cheat flags."
        ))
        self.chk_detect_cheat = QCheckBox("cheat  (On / Off)")
        self.chk_detect_cheat.setObjectName("SettingsCheckBox")
        self.cmb_cheat_severity = make_severity("Alert")
        detect_layout.addWidget(labeled_row(
            self.chk_detect_cheat, field_label("from plys"), self.cmb_cheat_severity, stretch_index=0
        ))
        self.chk_detect_cheater = QCheckBox("cheater  (Yes / No)")
        self.chk_detect_cheater.setObjectName("SettingsCheckBox")
        self.cmb_cheater_severity = make_severity("Alert")
        detect_layout.addWidget(labeled_row(
            self.chk_detect_cheater, field_label("from plys"), self.cmb_cheater_severity, stretch_index=0
        ))
        self.chk_detect_auto_ban = QCheckBox("auto_ban_protection  (alert when not Active)")
        self.chk_detect_auto_ban.setObjectName("SettingsCheckBox")
        self.cmb_auto_ban_severity = make_severity("Info")
        detect_layout.addWidget(labeled_row(
            self.chk_detect_auto_ban, field_label("plys field, off by default"),
            self.cmb_auto_ban_severity, stretch_index=0
        ))
        for title, reason in DISABLED_DETECTIONS:
            box = QCheckBox(title)
            box.setObjectName("SettingsCheckBox")
            box.setEnabled(False)
            box.setToolTip(reason)
            detect_layout.addWidget(labeled_row(box, make_note(reason), stretch_index=1))
        inner_layout.addWidget(detect_card)

        # endregion

        mid = QWidget()
        mid_grid = QGridLayout(mid)
        mid_grid.setContentsMargins(0, 0, 0, 0)
        mid_grid.setHorizontalSpacing(14)
        mid_grid.setVerticalSpacing(14)

        # region Watch Words

        watch_card, watch_layout = make_card("WATCH WORDS")
        watch_layout.addWidget(make_note(
            "The on/off list is the same file the Chat page uses (data/chat_watch_words.json). "
            "It is written when you press SAVE. With no saved matching options, a hit is still "
            "a case-insensitive substring, shown as WARNING."
        ))
        self.watch_boxes = QWidget()
        self.watch_boxes_layout = QVBoxLayout(self.watch_boxes)
        self.watch_boxes_layout.setContentsMargins(0, 0, 0, 0)
        self.watch_boxes_layout.setSpacing(4)
        watch_layout.addWidget(self.watch_boxes)
        self.lbl_watch_empty = QLabel("No watch words yet.")
        self.lbl_watch_empty.setObjectName("DashEmptyLabel")
        watch_layout.addWidget(self.lbl_watch_empty)
        add_row = QWidget()
        add_layout = QHBoxLayout(add_row)
        add_layout.setContentsMargins(0, 0, 0, 0)
        add_layout.setSpacing(8)
        self.txt_watch_word = QLineEdit()
        self.txt_watch_word.setObjectName("ChatReplyBox")
        self.txt_watch_word.setPlaceholderText("Add a watch word")
        self.btn_watch_add = QPushButton("ADD")
        self.btn_watch_add.setObjectName("DashActionButton")
        self.btn_watch_add.setFixedWidth(80)
        self.btn_watch_add.setFixedHeight(32)
        self.btn_watch_add.clicked.connect(self._on_watch_add)
        self.txt_watch_word.returnPressed.connect(self._on_watch_add)
        add_layout.addWidget(self.txt_watch_word, stretch=1)
        add_layout.addWidget(self.btn_watch_add)
        watch_layout.addWidget(add_row)
        self.chk_case_sensitive = QCheckBox("Case sensitive")
        self.chk_case_sensitive.setObjectName("SettingsCheckBox")
        watch_layout.addWidget(self.chk_case_sensitive)
        self.chk_whole_word = QCheckBox("Whole-word matching")
        self.chk_whole_word.setObjectName("SettingsCheckBox")
        watch_layout.addWidget(self.chk_whole_word)
        self.cmb_watch_severity = make_severity("Warn")
        watch_layout.addWidget(labeled_row(field_label("Watch-word hit severity"), self.cmb_watch_severity))
        mid_grid.addWidget(watch_card, 0, 0)

        # endregion

        # region Thresholds

        thresh_card, thresh_layout = make_card("THRESHOLDS")
        thresh_layout.addWidget(make_note(
            "With the defaults (1 hit, 1 poll) Alerts still fires on the first cheat flag or the "
            "first watch-word hit. A watch-word count above 1 raises that player's later hits to Alert. "
            "A poll count above 1 waits that many plys refreshes before a flag is queued."
        ))
        self.spn_watch_hits = make_spin(1, 1, 20, " hits", 100)
        self.spn_watch_minutes = make_spin(10, 1, 120, " min", 100)
        thresh_layout.addWidget(labeled_row(
            field_label("Watch-word hits"), self.spn_watch_hits,
            field_label("within"), self.spn_watch_minutes
        ))
        self.spn_flag_polls = make_spin(1, 1, 20, " polls", 100)
        thresh_layout.addWidget(labeled_row(
            field_label("Cheat flag still on after"), self.spn_flag_polls
        ))
        mid_grid.addWidget(thresh_card, 0, 1)
        mid_grid.setColumnStretch(0, 1)
        mid_grid.setColumnStretch(1, 1)
        inner_layout.addWidget(mid)

        # endregion

        # region Auto-actions

        auto_card, auto_layout = make_card("AUTO-ACTIONS  ·  SUGGEST ONLY")
        auto_layout.addWidget(make_note(
            "A hit always shows in the Alerts queue. Suggest PREVIEW BAN fills the command preview "
            "on the Alerts page; the admin still starts PREVIEW BAN. ZAH never sends a kick or a ban "
            "from these settings."
        ))
        self.cmb_on_info = make_action("suggest")
        self.cmb_on_warn = make_action("suggest")
        self.cmb_on_alert = make_action("suggest")
        auto_layout.addWidget(labeled_row(field_label("On Info"), self.cmb_on_info))
        auto_layout.addWidget(labeled_row(field_label("On Warn"), self.cmb_on_warn))
        auto_layout.addWidget(labeled_row(field_label("On Alert"), self.cmb_on_alert))
        safety = QFrame()
        safety.setObjectName("SafetyNoteBox")
        safety.setStyleSheet(
            "QFrame#SafetyNoteBox { background-color: rgba(60, 40, 8, 180); "
            "border: 1px solid #f5a623; border-radius: 6px; }"
        )
        safety_layout = QVBoxLayout(safety)
        safety_layout.setContentsMargins(12, 8, 12, 8)
        safety_label = QLabel(
            "KICK and BAN always go through the Safety Flow: command preview, type CONFIRM, "
            "a 15 second delay with Cancel, then an audit log entry. No automatic kicks or bans. "
            "PREVIEW BAN and ACK already work this way on the Alerts page (ACK hides the alert on this PC only)."
        )
        safety_label.setObjectName("BackupHintLabel")
        safety_label.setWordWrap(True)
        safety_label.setStyleSheet("QLabel#BackupHintLabel { color: #ffc04d; font-size: 12px; }")
        safety_layout.addWidget(safety_label)
        auto_layout.addWidget(safety)
        inner_layout.addWidget(auto_card)

        # endregion

        # region Who, polling, retention

        bottom = QWidget()
        bottom_grid = QGridLayout(bottom)
        bottom_grid.setContentsMargins(0, 0, 0, 0)
        bottom_grid.setHorizontalSpacing(14)

        who_card, who_layout = make_card("WHO GETS ALERTED")
        who_layout.addWidget(make_note(
            "Role order is already moderator < admin < owner < developer. "
            "No extra filter keeps the Alerts queue visible to every signed-in role, as it is today. "
            "Bans stay admin and up; kicks stay moderator and up."
        ))
        self.cmb_min_role = QComboBox()
        self.cmb_min_role.setObjectName("EcfFileCombo")
        for key, label in ROLE_LABELS:
            self.cmb_min_role.addItem(label, key)
        self.cmb_min_role.setFixedWidth(180)
        self.cmb_min_role.setFixedHeight(32)
        who_layout.addWidget(labeled_row(field_label("Minimum role"), self.cmb_min_role))
        bottom_grid.addWidget(who_card, 0, 0)

        poll_card, poll_layout = make_card("POLLING INTERVAL")
        poll_layout.addWidget(make_note(
            "Alerts already refreshes plys and chat:recent every 15 seconds while the page is open. "
            "Changing this interval does not add a new bridge command."
        ))
        self.spn_poll_seconds = make_spin(15, 5, 120, " sec", 100)
        poll_layout.addWidget(labeled_row(field_label("Refresh every"), self.spn_poll_seconds))
        bottom_grid.addWidget(poll_card, 0, 1)

        retain_card, retain_layout = make_card("LOG RETENTION")
        retain_layout.addWidget(make_note(
            "0 days keeps ACK and the alert log in memory only, and they are dropped when ZAH restarts "
            "(today's behaviour). A value above 0 keeps a local log on this PC; nothing is sent to the server."
        ))
        self.spn_retention_days = make_spin(0, 0, 90, " days", 100)
        retain_layout.addWidget(labeled_row(field_label("Keep alert log"), self.spn_retention_days))
        bottom_grid.addWidget(retain_card, 0, 2)
        bottom_grid.setColumnStretch(0, 1)
        bottom_grid.setColumnStretch(1, 1)
        bottom_grid.setColumnStretch(2, 1)
        inner_layout.addWidget(bottom)

        # endregion

        inner_layout.addStretch()
        scroll.setWidget(inner)
        page_layout.addWidget(scroll, stretch=1)

        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("SettingsNote")
        self.lbl_status.setStyleSheet("QLabel#SettingsNote { color: #8fa6b8; font-size: 12px; }")
        self.lbl_status.setWordWrap(True)
        page_layout.addWidget(self.lbl_status)

        button_row = QWidget()
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(10)
        self.btn_save = QPushButton("SAVE")
        self.btn_reset = QPushButton("RESET TO DEFAULTS")
        self.btn_export = QPushButton("EXPORT")
        for button in (self.btn_save, self.btn_reset, self.btn_export):
            button.setObjectName("DashActionButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumWidth(160)
            button_layout.addWidget(button)
        button_layout.addStretch()
        self.btn_save.clicked.connect(self._on_save)
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_export.clicked.connect(self._on_export)
        page_layout.addWidget(button_row)

    # endregion

    # region Load and Save

    def load_into_widgets(self, settings):
        try:
            self.chk_detect_cheat.setChecked(settings["detect_cheat"])
            self.chk_detect_cheater.setChecked(settings["detect_cheater"])
            self.cmb_cheat_severity.setCurrentText(settings["cheat_severity"])
            self.cmb_cheater_severity.setCurrentText(settings["cheater_severity"])
            self.chk_detect_auto_ban.setChecked(settings["detect_auto_ban_protection"])
            self.cmb_auto_ban_severity.setCurrentText(settings["auto_ban_protection_severity"])
            self.chk_case_sensitive.setChecked(settings["watch_case_sensitive"])
            self.chk_whole_word.setChecked(settings["watch_whole_word"])
            self.cmb_watch_severity.setCurrentText(settings["watch_severity"])
            self.spn_watch_hits.setValue(settings["watch_hit_count"])
            self.spn_watch_minutes.setValue(settings["watch_hit_minutes"])
            self.spn_flag_polls.setValue(settings["flag_polls"])
            self._set_action(self.cmb_on_info, settings["on_info_action"])
            self._set_action(self.cmb_on_warn, settings["on_warn_action"])
            self._set_action(self.cmb_on_alert, settings["on_alert_action"])
            role_index = self.cmb_min_role.findData(settings["min_alert_role"])
            self.cmb_min_role.setCurrentIndex(role_index if role_index >= 0 else 0)
            self.spn_poll_seconds.setValue(settings["poll_seconds"])
            self.spn_retention_days.setValue(settings["log_retention_days"])
            self._fill_watch_words(chat_store.load_watch_words())
        except Exception as e:
            print(f"[ERROR] CheatCheckerPage: Could not load settings into the page: {e}")

    def _set_action(self, combo, key):
        index = combo.findData(key if key in ALLOWED_ACTIONS else "suggest")
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _fill_watch_words(self, rows):
        while self.watch_boxes_layout.count():
            item = self.watch_boxes_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for row in rows:
            box = QCheckBox(str(row.get("word", "")))
            box.setObjectName("SettingsCheckBox")
            box.setChecked(row.get("on") is not False)
            self.watch_boxes_layout.addWidget(box)
        self.lbl_watch_empty.setVisible(self.watch_boxes_layout.count() == 0)

    def _watch_rows_from_widgets(self):
        rows = []
        for index in range(self.watch_boxes_layout.count()):
            box = self.watch_boxes_layout.itemAt(index).widget()
            if isinstance(box, QCheckBox) and box.text().strip():
                rows.append({"word": box.text().strip(), "on": box.isChecked()})
        return rows

    def settings_from_widgets(self):
        return {
            "detect_cheat": self.chk_detect_cheat.isChecked(),
            "detect_cheater": self.chk_detect_cheater.isChecked(),
            "cheat_severity": self.cmb_cheat_severity.currentText(),
            "cheater_severity": self.cmb_cheater_severity.currentText(),
            "detect_auto_ban_protection": self.chk_detect_auto_ban.isChecked(),
            "auto_ban_protection_severity": self.cmb_auto_ban_severity.currentText(),
            "watch_case_sensitive": self.chk_case_sensitive.isChecked(),
            "watch_whole_word": self.chk_whole_word.isChecked(),
            "watch_severity": self.cmb_watch_severity.currentText(),
            "watch_hit_count": self.spn_watch_hits.value(),
            "watch_hit_minutes": self.spn_watch_minutes.value(),
            "flag_polls": self.spn_flag_polls.value(),
            "on_info_action": self.cmb_on_info.currentData() or "suggest",
            "on_warn_action": self.cmb_on_warn.currentData() or "suggest",
            "on_alert_action": self.cmb_on_alert.currentData() or "suggest",
            "min_alert_role": self.cmb_min_role.currentData() or "",
            "poll_seconds": self.spn_poll_seconds.value(),
            "log_retention_days": self.spn_retention_days.value(),
        }

    def _on_watch_add(self):
        try:
            word = self.txt_watch_word.text().strip()
            if not word:
                return
            for row in self._watch_rows_from_widgets():
                if row["word"].lower() == word.lower():
                    self.lbl_status.setText("That watch word is already on the list.")
                    return
            box = QCheckBox(word)
            box.setObjectName("SettingsCheckBox")
            box.setChecked(True)
            self.watch_boxes_layout.addWidget(box)
            self.lbl_watch_empty.setVisible(False)
            self.txt_watch_word.clear()
        except Exception as e:
            print(f"[ERROR] CheatCheckerPage: Could not add a watch word: {e}")

    def _on_save(self):
        try:
            if not save_cheat_checker_settings(self.settings_from_widgets()):
                self.lbl_status.setText("Could not save the settings.")
                return
            chat_store.save_watch_words(self._watch_rows_from_widgets())
            self.lbl_status.setText("Saved on this PC. The Alerts page will use these settings on its next refresh.")
        except Exception as e:
            print(f"[ERROR] CheatCheckerPage: Save failed: {e}")
            self.lbl_status.setText("Could not save the settings.")

    def _on_reset(self):
        try:
            self.load_into_widgets(dict(DEFAULT_SETTINGS))
            if not save_cheat_checker_settings(DEFAULT_SETTINGS):
                self.lbl_status.setText("Could not write the default settings.")
                return

            ## Watch words are left as they are: they are a list the admin built, not a default of this page.
            self.lbl_status.setText(
                "Restored the default cheat-checker settings (Alerts behaves as it did before this page). "
                "The watch-word list was not cleared."
            )
        except Exception as e:
            print(f"[ERROR] CheatCheckerPage: Reset failed: {e}")

    def _on_export(self):
        try:
            path, _filter = QFileDialog.getSaveFileName(
                self, "Export cheat checker settings", "cheat_checker_settings.json", "JSON files (*.json)"
            )
            if not path:
                return
            if export_cheat_checker_settings(path, self._watch_rows_from_widgets()):
                self.lbl_status.setText(f"Exported to {path}.")
            else:
                self.lbl_status.setText("Could not export the settings.")
        except Exception as e:
            print(f"[ERROR] CheatCheckerPage: Export failed: {e}")
            self.lbl_status.setText("Could not export the settings.")

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return CheatCheckerPage()

# endregion
