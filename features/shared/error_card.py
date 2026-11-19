## ==========================================
## ZERO-G ADMIN HELPER - ERROR CARD
## Shown in place of a page that failed to load.
## Has a title, the error text, and a Retry button.
## ==========================================

## region: Imports

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

## endregion


## region: ErrorCard Class

class ErrorCard(QFrame):
    ## Fires when Retry is clicked, sends the page name along
    retry_requested = pyqtSignal(str)

    ## region: Setup

    def __init__(self, page_name, error_text, parent=None):
        super().__init__(parent)
        ## Keep the page name and message on the card so other methods can read them.
        self.page_name = page_name
        self.error_text = error_text
        ## Name that ZAH_main.css can use to style the card.
        self.setObjectName("ErrorCard")
        ## Build the title, the message and the Retry button.
        self.setup_widgets()

    def setup_widgets(self):
        ## Top-to-bottom stack: 24 px margins at the edges, 12 px between items.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        ## Title, e.g. 'PLAYERS FAILED TO LOAD'.
        self.lbl_title = QLabel(f"{self.page_name.upper()} FAILED TO LOAD")
        self.lbl_title.setObjectName("ErrorCardTitle")

        ## Error message. Word wrap stops long messages from running off the card.
        self.lbl_error = QLabel(self.error_text)
        self.lbl_error.setObjectName("ErrorCardText")
        self.lbl_error.setWordWrap(True)

        ## Retry button. A click runs _on_retry_clicked.
        self.btn_retry = QPushButton("RETRY")
        self.btn_retry.setObjectName("ErrorCardRetry")
        self.btn_retry.clicked.connect(self._on_retry_clicked)

        ## Add the pieces in order. The stretch at the end keeps them at the top.
        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_error)
        layout.addWidget(self.btn_retry, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()

    ## endregion

    ## region: Click Handlers

    def _on_retry_clicked(self):
        print(f"[INFO] ErrorCard: Retry clicked for {self.page_name}")
        ## Announce the retry so the page loader can try this page again.
        self.retry_requested.emit(self.page_name)

    ## endregion

## endregion
