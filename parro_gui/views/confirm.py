"""The dialog in front of every change: it shows what would happen, and only Confirm does it.

After a failure the Confirm button stays off. A write that may have arrived is never repeated from
here (PLAN-desktop-app §4): to try again, start over, which reads the current state first.
"""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from parro.api_client import ParroClient

from ..widgets import SafeTextBrowser
from ..worker import Worker


class ConfirmDialog(QDialog):
    def __init__(
        self,
        worker: Worker,
        title: str,
        preview_html: str,
        confirm_label: str,
        task: Callable[[ParroClient], Any],
        on_done: Callable[[Any], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(480, 320)
        self.worker, self.task, self.on_done = worker, task, on_done
        self.preview = SafeTextBrowser()
        self.preview.setHtml(preview_html)
        self.message = QLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        self.confirm_button = QPushButton(confirm_label)
        self.cancel_button = QPushButton("Cancel")
        # Enter must not do it: only a deliberate click on Confirm does.
        self.confirm_button.setAutoDefault(False)
        self.cancel_button.setDefault(True)
        self.confirm_button.clicked.connect(self.confirm)
        self.cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.confirm_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.preview, 1)
        layout.addWidget(self.message)
        layout.addLayout(buttons)

    def confirm(self) -> None:
        self.confirm_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.message.setText("One moment…")
        self.worker.submit(self.task, self._done, self._failed)

    def _done(self, result: Any) -> None:
        self.accept()
        self.on_done(result)

    def _failed(self, text: str) -> None:
        self.message.setText(text)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Close")

    def reject(self) -> None:
        if self.cancel_button.isEnabled():  # not while a write is on its way
            super().reject()
