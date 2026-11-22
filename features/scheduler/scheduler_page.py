## ==========================================
## ZERO-G ADMIN HELPER - SCHEDULER PAGE
## Layout follows .scratchpad/.conceptual/Concept_11-17/Scheduler.jpg:
## TASKS on the left, CHAIN EDITOR (the steps of the picked task and its trigger) in the middle,
## RUN HISTORY on the right.
## Layout only for now: there are no scheduled tasks yet, so every panel shows "nothing yet".
## Scheduled tasks will run real server actions (restart, save, backup), so each one gets its own step with Ray's OK.
## ==========================================

# region Imports

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout)

## The card and letter-spacing helpers are shared with the dashboard, so every page looks the same.
from features.dashboard.dashboard_page import make_card, spread_letters

# endregion


# region SchedulerPage Class

class SchedulerPage(QWidget):

    # region Setup

    def __init__(self, parent=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the page.
        self.setObjectName("SchedulerPage")
        self.setup_widgets()

    def setup_widgets(self):

        ## 3 columns: tasks (narrow), chain editor (wide), run history (narrow).
        page_grid = QGridLayout(self)
        page_grid.setContentsMargins(4, 4, 4, 4)
        page_grid.setHorizontalSpacing(14)
        page_grid.setVerticalSpacing(14)

        # region Tasks

        ## Each task will be a row with its name, NEXT RUN time and an on/off switch.
        tasks_card, tasks_layout = make_card("TASKS")
        self.lbl_tasks_empty = QLabel("No scheduled tasks yet.")
        self.lbl_tasks_empty.setObjectName("DashEmptyLabel")
        tasks_layout.addWidget(self.lbl_tasks_empty)
        tasks_layout.addStretch()
        page_grid.addWidget(tasks_card, 0, 0)

        # endregion

        # region Chain Editor

        ## The picked task's steps show as boxes joined by arrows, e.g. WARN PLAYERS > SAVE > BACKUP > RESTART.
        chain_card, chain_layout = make_card("CHAIN EDITOR")
        chain_title = chain_card.findChild(QLabel, "DashCardTitle")
        if chain_title is not None:
            chain_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chain_layout.addStretch(1)
        self.chain_row = QHBoxLayout()
        self.chain_row.setSpacing(10)
        self.lbl_chain_empty = QLabel("Pick a task to see its steps.")
        self.lbl_chain_empty.setObjectName("DashEmptyLabel")
        self.lbl_chain_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chain_row.addWidget(self.lbl_chain_empty)
        chain_layout.addLayout(self.chain_row)
        chain_layout.addStretch(2)

        ## Trigger box at the bottom, e.g. "TRIGGER: DAILY 04:00 CST".
        trigger_row = QHBoxLayout()
        trigger_row.addStretch(1)
        self.trigger_box = QFrame()
        self.trigger_box.setObjectName("DashInnerBox")
        trigger_box_layout = QVBoxLayout(self.trigger_box)
        trigger_box_layout.setContentsMargins(40, 12, 40, 12)
        self.lbl_trigger = QLabel("TRIGGER:  --")
        self.lbl_trigger.setObjectName("SchedTriggerLabel")
        self.lbl_trigger.setAlignment(Qt.AlignmentFlag.AlignCenter)
        spread_letters(self.lbl_trigger, 1.5)
        trigger_box_layout.addWidget(self.lbl_trigger)
        trigger_row.addWidget(self.trigger_box, stretch=3)
        trigger_row.addStretch(1)
        chain_layout.addLayout(trigger_row)
        chain_layout.addStretch(1)
        page_grid.addWidget(chain_card, 0, 1)

        # endregion

        # region Run History

        ## Each run will be a line with a SUCCESS or FAILED badge, the time and what happened.
        history_card, history_layout = make_card("RUN HISTORY")
        self.lbl_history_empty = QLabel("No runs yet.")
        self.lbl_history_empty.setObjectName("DashEmptyLabel")
        history_layout.addWidget(self.lbl_history_empty)
        history_layout.addStretch()
        page_grid.addWidget(history_card, 0, 2)

        # endregion

        ## Column widths roughly match the mockup: 3 : 6 : 4.
        page_grid.setColumnStretch(0, 3)
        page_grid.setColumnStretch(1, 6)
        page_grid.setColumnStretch(2, 4)

    # endregion

# endregion


# region Page Factory

## page_loader calls this to build the page.
def create_page():
    return SchedulerPage()

# endregion
