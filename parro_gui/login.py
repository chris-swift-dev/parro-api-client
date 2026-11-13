"""Logging in: with a password typed here, or (under "Other ways to log in…") in the browser.

Most people log in with their password; the browser login is for when that does not work. It is
one click away, not a tab of its own, and the dialog opens on it only while a browser login that was
started has not been finished yet.

The login server locks an account after a few failed attempts, so one click is one password check.
Nothing retries, and the password is never stored: it goes straight to `operations.login`.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from parro import operations
from parro.api_client import ParroClient
from parro.errors import ParroError
from parro.settings import Settings
from parro.token_store import TokenStore

from . import widgets
from .auto_login import Remembered, password_file_problem, save_remembered
from .widgets import open_url
from .worker import Worker

LOCKOUT_WARNING = (
    "The login server locks your account after a few failed attempts. Each click is one attempt, "
    "and nothing is retried on its own."
)
PASSWORD_NOT_STORED = "Your password is not stored. A login lasts up to 8 hours."
REMEMBER = "Log in by itself next time, with the password in this file:"
REMEMBER_NOTE = (
    "Only the e-mail address and where the file is are remembered, not the password. The app "
    "then logs in by itself when the login has expired: one attempt, and none after a rejected "
    "password until you log in here again. The file must be private."
)
OTHER_WAYS = "Other ways to log in…"
BACK_TO_PASSWORD = "Log in with a password instead"
BROWSER_WHEN = (
    "Only if logging in with your password here does not work for you: you log in on Parro's own "
    "login page in your browser, and bring the result back here."
)
BROWSER_STEPS = (
    "1. Open the login page and log in there.\n"
    "2. You end up on talk.parro.com. Copy the whole address from the address bar right away: "
    "a code works only once.\n"
    "3. Paste it here."
)


def browser_login_pending(settings: Settings) -> bool:
    """A browser login was started (its code verifier is stored) and not finished yet."""
    try:
        return TokenStore(settings.token_file).get_pending_browser_login() is not None
    except (OSError, ValueError, ParroError):
        return False


def same_password(password_file: Path, typed: str) -> bool:
    """Read the file the way the core will, compare, and keep nothing."""
    try:
        return Settings(password_file=password_file).read_password() == typed
    except ParroError:
        return False


class LoginDialog(QDialog):
    logged_in = Signal(object)

    def __init__(
        self,
        worker: Worker,
        username: str | None,
        parent: QWidget | None = None,
        data_dir: Path | None = None,
        remembered: Remembered | None = None,
        browser_pending: bool = False,
    ) -> None:
        super().__init__(parent)
        self.data_dir = data_dir
        self.remember = QCheckBox(REMEMBER)
        self.remember.setChecked(remembered is not None)
        self.password_file = QLineEdit(str(remembered.password_file) if remembered else "")
        self.password_file.setPlaceholderText("A file with only your password in it")
        self.choose_button = QPushButton("Choose…")
        self.choose_button.clicked.connect(self.choose_password_file)
        if remembered is not None and not username:
            username = remembered.username
        self.setWindowTitle("Log in to Parro")
        self.setMinimumWidth(440)
        self.worker = worker
        self._browser_login_started = browser_pending  # Finish works for a login begun earlier
        self.username = QLineEdit(username or "")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.log_in_button = QPushButton("Log in")
        self.log_in_button.setDefault(True)
        self.open_button = QPushButton("Open the login page")
        self.address = QLineEdit()
        self.address.setPlaceholderText("https://talk.parro.com/oauth2?code=…")
        self.finish_button = QPushButton("Finish logging in")
        self.finish_button.setEnabled(False)
        self.message = QLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        self.log_in_button.clicked.connect(self.log_in_with_password)
        self.open_button.clicked.connect(self.open_login_page)
        self.finish_button.clicked.connect(self.finish_browser_login)
        self.password_part = self._password_tab()
        self.browser_part = self._browser_tab()
        self.other_ways_button = QPushButton(OTHER_WAYS)
        self.other_ways_button.setFlat(True)  # looks like a link: most people never need it
        self.other_ways_button.clicked.connect(self.toggle_browser_login)
        layout = QVBoxLayout(self)
        layout.addWidget(self.password_part)
        layout.addWidget(self.browser_part)
        layout.addWidget(self.message)
        layout.addWidget(self.other_ways_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.show_browser_login(browser_pending)
        self._set_busy(False)

    def show_browser_login(self, shown: bool) -> None:
        """The browser login in place of the password form, or back."""
        self.password_part.setVisible(not shown)
        self.browser_part.setVisible(shown)
        self.other_ways_button.setText(BACK_TO_PASSWORD if shown else OTHER_WAYS)
        self.message.clear()
        self.adjustSize()

    def toggle_browser_login(self) -> None:
        self.show_browser_login(self.password_part.isVisible())

    def _password_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.addRow("E-mail address", self.username)
        form.addRow("Password", self.password)
        for text in (LOCKOUT_WARNING, PASSWORD_NOT_STORED):
            note = QLabel(text)
            note.setWordWrap(True)
            form.addRow(note)
        if self.data_dir is not None:
            form.addRow(self.remember)
            row = QHBoxLayout()
            row.addWidget(self.password_file, 1)
            row.addWidget(self.choose_button)
            form.addRow(row)
            note = QLabel(REMEMBER_NOTE)
            note.setWordWrap(True)
            form.addRow(note)
        form.addRow(self.log_in_button)
        return tab

    def choose_password_file(self) -> None:
        chosen = widgets.choose_file(self, "Your password file")
        if chosen:
            self.password_file.setText(chosen)
            self.remember.setChecked(True)

    def _browser_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        when = QLabel(BROWSER_WHEN)
        when.setWordWrap(True)
        layout.addWidget(when)
        steps = QLabel(BROWSER_STEPS)
        steps.setWordWrap(True)
        layout.addWidget(steps)
        layout.addWidget(self.open_button)
        layout.addWidget(self.address)
        layout.addWidget(self.finish_button)
        return tab

    def _set_busy(self, busy: bool) -> None:
        for button in (self.log_in_button, self.open_button):
            button.setEnabled(not busy)
        self.finish_button.setEnabled(not busy and self._browser_login_started)

    def _run(self, task: Callable[[ParroClient], Any], done: Callable[[Any], None]) -> None:
        self._set_busy(True)
        self.message.setText("One moment…")

        def finished(value: Any) -> None:
            self._set_busy(False)
            done(value)

        self.worker.submit(task, finished, self._show_failure)

    def _show_failure(self, text: str) -> None:
        self._set_busy(False)
        self.message.setText(text)

    def _finish(self, status: dict[str, Any]) -> None:
        self.message.clear()
        self.logged_in.emit(status)
        self.accept()

    def log_in_with_password(self) -> None:
        username, password = self.username.text().strip(), self.password.text()
        if not username or not password:
            self.message.setText("Fill in your e-mail address and your password.")
            return
        remembering = self.data_dir is not None and self.remember.isChecked()
        password_file = Path(self.password_file.text().strip()).expanduser()
        if remembering:
            # Checked before the login: a refused file spends no password check.
            problem = (
                password_file_problem(password_file)
                if self.password_file.text().strip()
                else "Choose the file with your password, or untick the box."
            )
            if not problem and not same_password(password_file, password):
                # Caught now, not at the next automatic login, where it would stop all of them.
                problem = "The password in that file is not the one you typed. Nothing was sent."
            if problem:
                self.message.setText(problem)
                return
        self.password.clear()  # also after a failure: the next attempt is a deliberate one

        def task(client: ParroClient) -> dict[str, Any]:
            # Always the login form: one password check, where `auto` can spend two.
            return operations.login(
                client, method="login-form", username=username, password=password
            )

        chosen = Remembered(username, password_file) if remembering else None
        self._run(task, lambda status: self._logged_in_with_password(status, chosen))

    def _logged_in_with_password(self, status: dict[str, Any], chosen: Remembered | None) -> None:
        """Remember (or forget) only after a login that worked: the address is right then."""
        if self.data_dir is not None:
            save_remembered(self.data_dir, chosen)
        self._finish(status)

    def open_login_page(self) -> None:
        self._run(operations.login_url, self._show_login_page)

    def _show_login_page(self, result: dict[str, Any]) -> None:
        self._browser_login_started = True
        self.finish_button.setEnabled(True)
        if open_url(result["login_url"]):
            self.message.setText("Log in in your browser, then paste the address here.")
        else:
            self.message.setText(f"Could not open a browser. Open this page: {result['login_url']}")

    def finish_browser_login(self) -> None:
        address = self.address.text().strip()
        if not address:
            self.message.setText("Paste the address you ended up on.")
            return
        self.address.clear()  # the code works only once
        self._run(lambda client: operations.login_finish(client, address), self._finish)
