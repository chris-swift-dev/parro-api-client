"""The main window: a list of sections on the left, the chosen section on the right."""

import logging
import sys
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QSize, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QListWidget,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
)

from parro import __version__, operations
from parro.api_client import ParroClient
from parro.errors import ParroError
from parro.rendering import format_timestamp
from parro.settings import Settings

from .icons import ICON_SIZE, section_icon
from .login import LoginDialog
from .theme import apply_theme, current_colours
from .views.agenda import AgendaSection
from .views.archive import ArchiveSection
from .views.base import LOG_IN_FIRST, Section
from .views.chats import ChatsSection
from .views.family import FamilySection
from .views.news import NewsSection
from .views.overview import OverviewSection
from .widgets import APP_NAME, ask
from .worker import Worker

SECTIONS = ("Overview", "Announcements", "Calendar", "Chats", "Family", "Archive")
SECTION_ROW_HEIGHT = 36
CHECKING_LOGIN = "Checking the login…"
LOGIN_HALTED = "Login stopped after a rejected password. Check it, then log in."
LOGIN_EXPIRED = "Your login has expired. A login lasts up to 8 hours."
LOGIN_CHECK_INTERVAL_MS = 60_000


def describe_login(status: dict[str, Any]) -> str:
    """One line for the status bar. `status` comes from operations.auth_status()."""
    if status.get("automatic_login_halted"):
        return LOGIN_HALTED
    if not (status.get("has_access_token") or status.get("has_refresh_token")):
        return "Not logged in"
    left = status.get("login_expires_in_seconds")
    if isinstance(left, (int, float)) and left <= 0:
        return LOGIN_EXPIRED
    if status.get("error"):
        return str(status["error"])
    until = status.get("login_valid_until")
    if not until:
        return "Logged in"
    return f"Logged in until {format_timestamp(until)}"


def is_logged_in(status: dict[str, Any]) -> bool:
    """Whether the button should offer logging out rather than logging in."""
    return describe_login(status).startswith("Logged in")


class MainWindow(QMainWindow):
    def __init__(self, make_client: Callable[[Settings], ParroClient] = ParroClient) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1000, 680)
        self.worker = Worker(make_client, self)
        self.logged_in = False
        self.sections = QListWidget()
        self.sections.setObjectName("sections")
        self.sections.addItems(SECTIONS)
        self.sections.setFixedWidth(190)
        self.sections.setSpacing(1)
        self.sections.setIconSize(ICON_SIZE)
        for row in range(self.sections.count()):
            self.sections.item(row).setSizeHint(QSize(0, SECTION_ROW_HEIGHT))
        self.restyle()
        self.pages = QStackedWidget()
        self.views: dict[str, Section] = {
            "Overview": OverviewSection(self.worker),
            "Announcements": NewsSection(self.worker),
            "Calendar": AgendaSection(self.worker),
            "Chats": ChatsSection(self.worker),
            "Family": FamilySection(self.worker),
            "Archive": ArchiveSection(self.worker),
        }
        for name in SECTIONS:
            self.pages.addWidget(self.views[name])
        for view in self.views.values():
            view.reset(LOG_IN_FIRST)
        self.sections.currentRowChanged.connect(self._section_chosen)
        self.sections.setCurrentRow(0)
        splitter = QSplitter()
        splitter.addWidget(self.sections)
        splitter.addWidget(self.pages)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)
        self.login_dialog: LoginDialog | None = None
        self._offered_login = False
        self.account_button = QPushButton("Log in")
        self.account_button.clicked.connect(self._log_in_or_out)
        self.statusBar().addPermanentWidget(self.account_button)
        self.statusBar().showMessage(CHECKING_LOGIN)
        self.login_timer = QTimer(self)
        self.login_timer.setInterval(LOGIN_CHECK_INTERVAL_MS)
        self.login_timer.timeout.connect(self.refresh_login)
        self.login_timer.start()
        self.refresh_login()

    def restyle(self) -> None:
        """The theme changed: draw the icons in the new colours."""
        colours = current_colours()
        for row, name in enumerate(SECTIONS):
            self.sections.item(row).setIcon(section_icon(name, colours))

    def _section_chosen(self, row: int) -> None:
        self.pages.setCurrentIndex(row)
        self._load_current()

    def _load_current(self) -> None:
        view = self.views.get(SECTIONS[self.pages.currentIndex()])
        if view is not None and self.logged_in:
            view.ensure_loaded()

    def refresh_login(self) -> None:
        self.worker.submit(operations.auth_status, self._show_login, self.statusBar().showMessage)

    def _show_login(self, status: dict[str, Any]) -> None:
        self.statusBar().showMessage(describe_login(status))
        was_logged_in, self.logged_in = self.logged_in, is_logged_in(status)
        if self.logged_in != was_logged_in:
            for view in self.views.values():
                view.reset("" if self.logged_in else LOG_IN_FIRST)
            self._load_current()
        self.account_button.setText("Log out" if self.logged_in else "Log in")
        if not self.logged_in and not self._offered_login:
            self._offered_login = True
            self.show_login_dialog()

    def _configured_username(self) -> str | None:
        try:
            return Settings.from_environment().username
        except ParroError:
            return None

    def show_login_dialog(self) -> None:
        if self.login_dialog is None:
            self.login_dialog = LoginDialog(self.worker, self._configured_username(), self)
            self.login_dialog.logged_in.connect(self._show_login)
        self.login_dialog.open()

    def _log_in_or_out(self) -> None:
        if not self.logged_in:
            self.show_login_dialog()
        elif ask(self, "Log out of Parro on this computer?"):
            self.account_button.setEnabled(False)
            self.worker.submit(operations.logout, self._logged_out, self._logout_failed)

    def _logged_out(self, _result: dict[str, Any]) -> None:
        self.account_button.setEnabled(True)
        self.refresh_login()

    def _logout_failed(self, text: str) -> None:
        self.account_button.setEnabled(True)
        self.statusBar().showMessage(text)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt's name)
        for view in self.views.values():
            view.stop()
        self.worker.close()
        super().closeEvent(event)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.WARNING, format="[parro-gui] %(message)s", stream=sys.stderr)
    application = QApplication(argv)
    application.setApplicationName(APP_NAME)
    apply_theme(application)
    window = MainWindow()
    window.show()
    code = application.exec()
    # Everything Qt owns goes before Python starts its own cleanup.
    window.close()
    del window
    application.shutdown()
    return code
