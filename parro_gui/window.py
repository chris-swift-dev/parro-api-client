"""The main window: a list of sections on the left, the chosen section on the right."""

import logging
import os
import sys
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QSize, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QWidget,
)

from parro import __version__, operations
from parro.api_client import ParroClient
from parro.errors import ParroError
from parro.rendering import format_timestamp
from parro.settings import Settings

from . import auto_login
from .desktop_font import use_desktop_font
from .icons import ICON_SIZE, app_icon, section_icon
from .login import LoginDialog
from .memory import Memory
from .theme import apply_theme, current_colours
from .updates import Updates, data_dir_of
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
LOGGING_IN_BY_ITSELF = "Logging in by itself, with the password file…"


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


MINIMUM_SIZE = (760, 520)


class MainWindow(QMainWindow):
    def __init__(self, make_client: Callable[[Settings], ParroClient] = ParroClient) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1000, 680)
        # Measured (0.12.0): every section's buttons and filters fit from Qt's own 710 x 415, but
        # the list and the text are cramped there. Below this the window does not go.
        self.setMinimumSize(*MINIMUM_SIZE)
        self.worker = Worker(make_client, self, settings=self.settings)
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
        self.memory = Memory()  # one for all sections: a change in one makes all of it doubtful
        for name in SECTIONS:
            self.pages.addWidget(self.views[name])
            self.views[name].memory = self.memory
        for name, view in self.views.items():
            view.set_title(name)
            view.reset(LOG_IN_FIRST)
        self.sections.currentRowChanged.connect(self._section_chosen)
        self.sections.setCurrentRow(0)
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sections)
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(central)
        self.login_dialog: LoginDialog | None = None
        self._offered_login = False
        # One automatic login per expiry: allowed again only after a login that worked, and not
        # after logging out on purpose.
        self._may_log_in_by_itself = True
        self._logged_in_by_itself = ""
        self.first_login_check_done = False
        self.updates = Updates(self, data_dir_of(self.settings), ready=self._quiet_moment)
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
        self.worker.submit(operations.auth_status, self._show_login, self._login_check_failed)

    def _login_check_failed(self, text: str) -> None:
        self.first_login_check_done = True
        self.statusBar().showMessage(text)

    def _quiet_moment(self) -> bool:
        """For a question at start: the login is known, and no other dialog is open."""
        return self.first_login_check_done and QApplication.activeModalWidget() is None

    @staticmethod
    def settings() -> Settings:
        return auto_login.app_settings()

    def _show_login(self, status: dict[str, Any]) -> None:
        self.first_login_check_done = True
        line = describe_login(status)
        if self._logged_in_by_itself and is_logged_in(status):
            line = f"{line} · {self._logged_in_by_itself}"
        self.statusBar().showMessage(line)
        was_logged_in, self.logged_in = self.logged_in, is_logged_in(status)
        if self.logged_in:
            self._may_log_in_by_itself = True
        elif self._can_log_in_by_itself(status):
            self._log_in_by_itself()
            return
        if self.logged_in != was_logged_in:
            self.memory.forget()
            for view in self.views.values():
                view.reset("" if self.logged_in else LOG_IN_FIRST)
            self._load_current()
        self.account_button.setText("Log out" if self.logged_in else "Log in")
        if not self.logged_in and not self._offered_login:
            self._offered_login = True
            self.show_login_dialog()

    def _can_log_in_by_itself(self, status: dict[str, Any]) -> bool:
        if not self._may_log_in_by_itself or status.get("automatic_login_halted"):
            return False
        try:
            return self.settings().has_credentials()
        except ParroError:
            return False

    def _log_in_by_itself(self) -> None:
        """One attempt; the core refuses it while the latch is set, and never clears it."""
        self._may_log_in_by_itself = False
        self.statusBar().showMessage(LOGGING_IN_BY_ITSELF)
        self.worker.submit(auto_login.log_in, self._logged_in_itself, self._not_logged_in_itself)

    def _logged_in_itself(self, status: dict[str, Any]) -> None:
        self._logged_in_by_itself = (
            f"logged in by itself at {operations.current_time().astimezone():%H:%M}"
        )
        self._show_login(status)

    def _not_logged_in_itself(self, text: str) -> None:
        self._logged_in_by_itself = ""
        self.statusBar().showMessage(text)
        if not self._offered_login:
            self._offered_login = True
            self.show_login_dialog()

    def _configured_username(self) -> str | None:
        try:
            return Settings.from_environment().username
        except ParroError:
            return None

    def show_login_dialog(self) -> None:
        if self.login_dialog is None:
            try:
                data_dir = Settings.from_environment().data_dir
            except ParroError:
                data_dir = None
            remembered = auto_login.load_remembered(data_dir) if data_dir else None
            self.login_dialog = LoginDialog(
                self.worker, self._configured_username(), self, data_dir, remembered
            )
            self.login_dialog.logged_in.connect(self._logged_in_by_hand)
        self.login_dialog.open()

    def _logged_in_by_hand(self, status: dict[str, Any]) -> None:
        self._logged_in_by_itself = ""
        self._show_login(status)

    def _log_in_or_out(self) -> None:
        if not self.logged_in:
            self.show_login_dialog()
        elif ask(self, "Log out of Parro on this computer?"):
            self.account_button.setEnabled(False)
            self.worker.submit(operations.logout, self._logged_out, self._logout_failed)

    def _logged_out(self, _result: dict[str, Any]) -> None:
        # Logged out on purpose: no logging in by itself until a login by hand.
        self._may_log_in_by_itself = False
        self._logged_in_by_itself = ""
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
    application.setWindowIcon(app_icon())
    flatpak_id = os.environ.get("FLATPAK_ID")
    if flatpak_id:  # on Wayland, the dock finds the menu entry and the icon by this name
        application.setDesktopFileName(flatpak_id)
    apply_theme(application)
    use_desktop_font(application)
    window = MainWindow()
    window.show()
    QTimer.singleShot(0, window.updates.at_start)  # asks once; tests' windows never ask
    code = application.exec()
    # Everything Qt owns goes before Python starts its own cleanup.
    window.close()
    del window
    application.shutdown()
    return code
