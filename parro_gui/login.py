"""Logging in: with a password typed here, or in the browser.

The login server locks an account after a few failed attempts, so one click is one password check.
Nothing retries, and the password is never stored: it goes straight to `operations.login`.
"""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from parro import operations
from parro.api_client import ParroClient

from .widgets import open_url
from .worker import Worker

LOCKOUT_WARNING = (
    "The login server locks your account after a few failed attempts. Each click is one attempt, "
    "and nothing is retried on its own."
)
PASSWORD_NOT_STORED = "Your password is not stored. A login lasts up to 8 hours."
BROWSER_STEPS = (
    "1. Open the login page and log in there.\n"
    "2. You end up on talk.parro.com. Copy the whole address from the address bar right away: "
    "a code works only once.\n"
    "3. Paste it here."
)


class LoginDialog(QDialog):
    logged_in = Signal(object)

    def __init__(self, worker: Worker, username: str | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Log in to Parro")
        self.setMinimumWidth(440)
        self.worker = worker
        self._browser_login_started = False
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
        tabs = QTabWidget()
        tabs.addTab(self._password_tab(), "With a password")
        tabs.addTab(self._browser_tab(), "In the browser")
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(self.message)

    def _password_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.addRow("E-mail address", self.username)
        form.addRow("Password", self.password)
        for text in (LOCKOUT_WARNING, PASSWORD_NOT_STORED):
            note = QLabel(text)
            note.setWordWrap(True)
            form.addRow(note)
        form.addRow(self.log_in_button)
        return tab

    def _browser_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
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
        self.password.clear()  # also after a failure: the next attempt is a deliberate one

        def task(client: ParroClient) -> dict[str, Any]:
            # Always the login form: one password check, where `auto` can spend two.
            return operations.login(
                client, method="login-form", username=username, password=password
            )

        self._run(task, self._finish)

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
