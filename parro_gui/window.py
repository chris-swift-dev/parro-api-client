"""The main window: a list of sections on the left, the chosen section on the right."""

import logging
import sys
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QListWidget,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QWidget,
)

from parro import __version__, operations
from parro.api_client import ParroClient
from parro.rendering import format_timestamp
from parro.settings import Settings

from .worker import Worker

APP_NAME = "Parro"
SECTIONS = ("Overview", "Announcements", "Calendar", "Chats", "Family", "Archive")
CHECKING_LOGIN = "Checking the login…"


def describe_login(status: dict[str, Any]) -> str:
    """One line for the status bar. `status` comes from operations.auth_status()."""
    if not (status.get("has_access_token") or status.get("has_refresh_token")):
        return "Not logged in"
    if status.get("error"):
        return str(status["error"])
    until = status.get("login_valid_until")
    if not until:
        return "Logged in"
    return f"Logged in until {format_timestamp(until)}"


class MainWindow(QMainWindow):
    def __init__(self, make_client: Callable[[Settings], ParroClient] = ParroClient) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1000, 680)
        self.worker = Worker(make_client, self)
        self.sections = QListWidget()
        self.sections.addItems(SECTIONS)
        self.sections.setMaximumWidth(220)
        self.pages = QStackedWidget()
        for name in SECTIONS:
            self.pages.addWidget(self._placeholder(name))
        self.sections.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sections.setCurrentRow(0)
        splitter = QSplitter()
        splitter.addWidget(self.sections)
        splitter.addWidget(self.pages)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)
        self.statusBar().showMessage(CHECKING_LOGIN)
        self.refresh_login()

    @staticmethod
    def _placeholder(name: str) -> QWidget:
        label = QLabel(f"{name}: not built yet.")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    def refresh_login(self) -> None:
        self.worker.submit(operations.auth_status, self._show_login, self.statusBar().showMessage)

    def _show_login(self, status: dict[str, Any]) -> None:
        self.statusBar().showMessage(describe_login(status))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt's name)
        self.worker.close()
        super().closeEvent(event)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.WARNING, format="[parro-gui] %(message)s", stream=sys.stderr)
    application = QApplication(argv)
    application.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    return application.exec()
