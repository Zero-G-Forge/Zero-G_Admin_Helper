## ==========================================
## ZERO-G ADMIN HELPER - BACKUPS PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Backups.jpg:
## SNAPSHOTS on the left, RESTORE SCOPE (what to restore, snapshot vs current, PREVIEW / RESTORE) in the middle,
## BACKUP SCHEDULE and DISK USAGE on the right.
## Layout only for now: no snapshots are read yet, so every panel shows "nothing yet".
## RESTORE SELECTED changes the live server, so it stays locked until Ray OKs that step.
## Checked (Nov 22, 2026): the bridge has no snapshot, backup or restore command (save and backup answer
## not_available), and a consistent copy or restore of a save needs the server stopped, which is a restart.
## So PREVIEW and RESTORE stay off with RESTORE_TIP, and the panels say why (see NO_SNAPSHOTS_TEXT).
## ==========================================

# region Imports

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QPushButton, QButtonGroup, QProgressBar)

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

# endregion


# region Constants

## What a restore can cover. FULL SERVER is drawn red because it rolls back everything.
RESTORE_SCOPES = ["PLAYER", "STRUCTURE", "PLAYFIELD", "FULL SERVER"]

## Tooltip for every button that isn't wired up yet.
LATER_TIP = "Coming in a later step."

## Why PREVIEW and RESTORE stay off, and what the empty panels say.
RESTORE_TIP = ("Not possible while the server runs: the bridge has no snapshot or restore command, and restoring "
               "a save needs the server stopped (a restart).")
NO_SNAPSHOTS_TEXT = "No snapshots: the bridge cannot list or make server backups while the server runs."
NO_SCHEDULE_TEXT = "No backup schedule: backups are made on the server machine, outside ZAH."

# endregion


# region BackupsPage Class

class BackupsPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("BackupsPage")
        self.setup_widgets()

    def setup_widgets(self):

        ## 3 columns: snapshots (narrow), restore scope (wide), backup schedule (narrow).
        page_grid = QGridLayout(self)
        page_grid.setContentsMargins(4, 4, 4, 4)
        page_grid.setHorizontalSpacing(14)
        page_grid.setVerticalSpacing(14)

        # region Snapshots

        ## Each snapshot will be a row with its date, size, a FULL or PARTIAL tag and VERIFIED.
        snapshots_card, snapshots_layout = make_card("SNAPSHOTS")
        self.lbl_snapshots_empty = QLabel(NO_SNAPSHOTS_TEXT)
        self.lbl_snapshots_empty.setWordWrap(True)
        self.lbl_snapshots_empty.setObjectName("DashEmptyLabel")
        snapshots_layout.addWidget(self.lbl_snapshots_empty)
        snapshots_layout.addStretch()
        page_grid.addWidget(snapshots_card, 0, 0)

        # endregion

        # region Restore Scope

        restore_card, restore_layout = make_card("RESTORE SCOPE")

        ## Scope tabs: only one can be picked at a time, like the chat tabs.
        scope_row = QHBoxLayout()
        scope_row.setSpacing(8)
        self.scope_group = QButtonGroup(self)
        self.scope_group.setExclusive(True)
        self.scope_buttons = {}
        for scope_name in RESTORE_SCOPES:
            btn_scope = QPushButton(scope_name)
            btn_scope.setObjectName("BackupFullScopeButton" if scope_name == "FULL SERVER" else "StructFilterButton")
            btn_scope.setCheckable(True)
            btn_scope.setFixedHeight(32)
            btn_scope.setCursor(Qt.CursorShape.PointingHandCursor)
            self.scope_group.addButton(btn_scope)
            self.scope_buttons[scope_name] = btn_scope
            scope_row.addWidget(btn_scope)
        self.scope_buttons["STRUCTURE"].setChecked(True)
        scope_row.addStretch()
        restore_layout.addLayout(scope_row)

        ## What will be restored, e.g. "ISS VANGUARD (10432)". Filled in once a snapshot and a target are picked.
        self.target_box = QFrame()
        self.target_box.setObjectName("DashInnerBox")
        target_box_layout = QVBoxLayout(self.target_box)
        target_box_layout.setContentsMargins(12, 10, 12, 10)
        self.lbl_target = QLabel("Pick a snapshot first.")
        self.lbl_target.setObjectName("DashEmptyLabel")
        target_box_layout.addWidget(self.lbl_target)
        restore_layout.addWidget(self.target_box)

        ## Snapshot vs current: how the picked thing looked in the snapshot compared to now.
        self.compare_box = QFrame()
        self.compare_box.setObjectName("DashInnerBox")
        compare_box_layout = QVBoxLayout(self.compare_box)
        compare_box_layout.setContentsMargins(12, 12, 12, 12)
        compare_box_layout.setSpacing(10)
        lbl_compare_title = QLabel("SNAPSHOT VS CURRENT")
        lbl_compare_title.setObjectName("BackupCompareTitle")
        spread_letters(lbl_compare_title, 1.0)
        compare_box_layout.addWidget(lbl_compare_title)
        self.lbl_compare_blocks = QLabel("BLOCKS:  --")
        self.lbl_compare_owner = QLabel("OWNER:  --")
        self.lbl_compare_location = QLabel("LOCATION:  --")
        for lbl_compare in (self.lbl_compare_blocks, self.lbl_compare_owner, self.lbl_compare_location):
            lbl_compare.setObjectName("PlayerInfoLabel")
            compare_box_layout.addWidget(lbl_compare)

        ## Stretch at the bottom keeps the lines together at the top instead of spread out.
        compare_box_layout.addStretch()
        restore_layout.addWidget(self.compare_box, stretch=1)

        ## PREVIEW shows what would change; RESTORE SELECTED does it (amber, server change).
        button_row = QHBoxLayout()
        button_row.setSpacing(14)
        self.btn_preview = QPushButton("PREVIEW")
        self.btn_preview.setObjectName("DashActionButton")
        self.btn_restore = QPushButton("RESTORE SELECTED")
        self.btn_restore.setObjectName("AlertBanButton")
        for restore_button in (self.btn_preview, self.btn_restore):
            restore_button.setFixedHeight(40)
            restore_button.setEnabled(False)
            restore_button.setToolTip(RESTORE_TIP)
        button_row.addWidget(self.btn_preview, stretch=2)
        button_row.addWidget(self.btn_restore, stretch=3)
        restore_layout.addLayout(button_row)

        ## Safety reminder: a restore will need CONFIRM typed in, then waits 15 seconds before it is sent.
        self.lbl_restore_hint = QLabel("Type CONFIRM - 15s send delay")
        self.lbl_restore_hint.setObjectName("BackupHintLabel")
        self.lbl_restore_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        restore_layout.addWidget(self.lbl_restore_hint)
        page_grid.addWidget(restore_card, 0, 1)

        # endregion

        # region Backup Schedule

        schedule_card, schedule_layout = make_card("BACKUP SCHEDULE")

        ## The schedule, e.g. "Daily 03:00 full", "hourly partial", "keep 14 days".
        self.schedule_box = QFrame()
        self.schedule_box.setObjectName("DashInnerBox")
        schedule_box_layout = QVBoxLayout(self.schedule_box)
        schedule_box_layout.setContentsMargins(12, 12, 12, 12)
        schedule_box_layout.setSpacing(10)
        self.lbl_schedule_empty = QLabel(NO_SCHEDULE_TEXT)
        self.lbl_schedule_empty.setWordWrap(True)
        self.lbl_schedule_empty.setObjectName("DashEmptyLabel")
        schedule_box_layout.addWidget(self.lbl_schedule_empty)

        ## Thin line between the schedule and the disk usage.
        schedule_line = QFrame()
        schedule_line.setObjectName("BackupDivider")
        schedule_line.setFixedHeight(1)
        schedule_box_layout.addWidget(schedule_line)

        ## DISK USAGE: how full the backup disk is. The bar stays empty and the number "--" until it is read.
        lbl_disk_title = QLabel("DISK USAGE")
        lbl_disk_title.setObjectName("PlayerInfoLabel")
        schedule_box_layout.addWidget(lbl_disk_title)
        disk_row = QHBoxLayout()
        disk_row.setSpacing(10)
        self.bar_disk = QProgressBar()
        self.bar_disk.setObjectName("BackupDiskBar")
        self.bar_disk.setRange(0, 100)
        self.bar_disk.setValue(0)
        self.bar_disk.setTextVisible(False)
        self.bar_disk.setFixedHeight(8)
        disk_row.addWidget(self.bar_disk, stretch=1)
        self.lbl_disk_percent = QLabel("--")
        self.lbl_disk_percent.setObjectName("PlayerInfoLabel")
        disk_row.addWidget(self.lbl_disk_percent)
        schedule_box_layout.addLayout(disk_row)
        schedule_layout.addWidget(self.schedule_box)
        schedule_layout.addStretch()
        page_grid.addWidget(schedule_card, 0, 2)

        # endregion

        ## Column widths roughly match the mockup: 3 : 5 : 3.
        page_grid.setColumnStretch(0, 3)
        page_grid.setColumnStretch(1, 5)
        page_grid.setColumnStretch(2, 3)

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return BackupsPage()

# endregion
