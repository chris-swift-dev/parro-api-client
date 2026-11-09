"""Logging in and out in the desktop app, against the fake login server.

The login server locks an account after a few failed logins, so these tests count password checks.
"""

import json
import logging
import os
import time
from collections.abc import Callable
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from parro.api_client import ParroClient  # noqa: E402
from parro_gui import login as login_module  # noqa: E402
from parro_gui import window as window_module  # noqa: E402
from parro_gui.login import LoginDialog  # noqa: E402
from parro_gui.window import LOGIN_HALTED, MainWindow  # noqa: E402
from tests import fakes  # noqa: E402
from tests.conftest import load_sample  # noqa: E402
from tests.gui_helpers import dispose, wait_until  # noqa: E402

WRONG_PASSWORD = "not-the-password-8f3a"


@pytest.fixture(autouse=True)
def token_file(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("PARRO_"):
            monkeypatch.delenv(name)
    path = tmp_path / "tokens.json"
    monkeypatch.setenv("PARRO_TOKEN_FILE", str(path))
    monkeypatch.setenv("PARRO_DATA_DIR", str(tmp_path / "data"))
    return path


@pytest.fixture
def logged_in(token_file) -> None:
    token_file.write_text(
        json.dumps(
            {
                "access_token": fakes.ACCESS_TOKEN,
                "refresh_token": fakes.REFRESH_TOKEN,
                "expires_at": time.time() + 3000,
            }
        )
    )


@pytest.fixture
def api() -> fakes.FakeParroApi:
    return fakes.FakeParroApi(load_sample)


@pytest.fixture
def make_client(api) -> Callable[[Any], ParroClient]:
    return lambda settings: ParroClient(settings, transport=api)


@pytest.fixture
def window(application, make_client):
    created = MainWindow(make_client)
    yield created
    dispose(created)


def status_of(window: MainWindow) -> str:
    return window.statusBar().currentMessage()


def dialog_of(window: MainWindow) -> LoginDialog:
    wait_until(lambda: window.login_dialog is not None and window.login_dialog.isVisible())
    assert window.login_dialog is not None
    return window.login_dialog


def attempt(dialog: LoginDialog, password: str = fakes.CORRECT_PASSWORD) -> None:
    dialog.username.setText(fakes.USERNAME)
    dialog.password.setText(password)
    dialog.log_in_button.click()


def finished(dialog: LoginDialog) -> bool:
    return dialog.log_in_button.isEnabled()


# ------------------------------------------------------------------------ with a password


def test_it_offers_to_log_in_when_there_is_no_login(window, api):
    assert dialog_of(window).password.echoMode() == QLineEdit.EchoMode.Password
    assert api.idp.credential_posts() == [], "showing the dialog spends nothing"


def test_it_does_not_ask_when_there_is_a_login(logged_in, window):
    wait_until(lambda: window.logged_in)
    assert window.login_dialog is None and window.account_button.text() == "Log out"


def test_a_good_password_logs_in_with_one_check(window, api, token_file):
    dialog = dialog_of(window)
    attempt(dialog)
    wait_until(lambda: window.logged_in)
    assert len(api.idp.credential_posts()) == 1
    assert not dialog.isVisible() and status_of(window).startswith("Logged in")
    assert window.account_button.text() == "Log out"
    assert fakes.CORRECT_PASSWORD not in token_file.read_text(), "the password is never stored"


def test_a_wrong_password_is_one_check_and_is_not_retried(window, api):
    dialog = dialog_of(window)
    attempt(dialog, WRONG_PASSWORD)
    wait_until(lambda: finished(dialog))
    for _ in range(30):
        QApplication.processEvents()
    assert len(api.idp.credential_posts()) == 1
    assert dialog.isVisible() and "rejected" in dialog.message.text().lower()
    assert dialog.password.text() == "", "the next attempt is a deliberate one"


def test_another_click_is_one_more_check_and_no_more(window, api):
    dialog = dialog_of(window)
    attempt(dialog, WRONG_PASSWORD)
    wait_until(lambda: finished(dialog))
    attempt(dialog)
    wait_until(lambda: window.logged_in)
    assert len(api.idp.credential_posts()) == 2


def test_clicking_twice_is_one_attempt(window, api):
    dialog = dialog_of(window)
    attempt(dialog, WRONG_PASSWORD)
    dialog.log_in_button.click()
    wait_until(lambda: finished(dialog))
    assert len(api.idp.credential_posts()) == 1


@pytest.mark.parametrize(("username", "password"), [("", "x"), ("a@example.com", ""), (" ", "x")])
def test_empty_fields_spend_nothing(window, api, username, password):
    dialog = dialog_of(window)
    dialog.username.setText(username)
    dialog.password.setText(password)
    dialog.log_in_button.click()
    QApplication.processEvents()
    assert "Fill in" in dialog.message.text() and api.idp.requests == []


def test_it_never_uses_auto_which_can_spend_two_checks(window, api, monkeypatch):
    monkeypatch.setenv("PARRO_LOGIN_METHOD", "auto")
    dialog = dialog_of(window)
    attempt(dialog, WRONG_PASSWORD)
    wait_until(lambda: finished(dialog))
    assert len(api.idp.credential_posts()) == 1


def test_the_password_never_reaches_a_log_or_the_screen(window, api, caplog):
    dialog = dialog_of(window)
    with caplog.at_level(logging.DEBUG):
        attempt(dialog, WRONG_PASSWORD)
        wait_until(lambda: finished(dialog))
    assert WRONG_PASSWORD not in caplog.text
    assert WRONG_PASSWORD not in dialog.message.text()


def test_the_configured_username_is_filled_in(application, make_client, monkeypatch):
    monkeypatch.setenv("PARRO_USERNAME", fakes.USERNAME)
    window = MainWindow(make_client)
    assert dialog_of(window).username.text() == fakes.USERNAME
    dispose(window)


def test_the_warning_about_the_lockout_is_shown(window):
    dialog = dialog_of(window)
    labels = [label.text() for label in dialog.findChildren(QtWidgets.QLabel)]
    assert login_module.LOCKOUT_WARNING in labels


# ---------------------------------------------------------------------------- the lockout


def test_a_rejected_password_shows_that_login_stopped(window, api, token_file):
    dialog = dialog_of(window)
    attempt(dialog, WRONG_PASSWORD)
    wait_until(lambda: finished(dialog))
    window.refresh_login()
    wait_until(lambda: status_of(window) == LOGIN_HALTED)
    assert window.account_button.text() == "Log in"


def test_the_periodic_check_never_spends_a_password(application, make_client, api, monkeypatch):
    monkeypatch.setenv("PARRO_USERNAME", fakes.USERNAME)
    monkeypatch.setenv("PARRO_PASSWORD", fakes.CORRECT_PASSWORD)
    window = MainWindow(make_client)
    wait_until(lambda: status_of(window) == "Not logged in")
    for _ in range(3):
        window.refresh_login()
        QApplication.processEvents()
    time.sleep(0.05)
    for _ in range(30):
        QApplication.processEvents()
    assert api.idp.credential_posts() == []
    dispose(window)


# ----------------------------------------------------------------------------- the browser


def browser_login(window: MainWindow, opened: list[str]) -> LoginDialog:
    dialog = dialog_of(window)
    dialog.open_button.click()
    wait_until(lambda: bool(opened))
    return dialog


@pytest.fixture
def opened(monkeypatch) -> list[str]:
    addresses: list[str] = []

    def fake_open(address: str) -> bool:
        addresses.append(address)
        return True

    monkeypatch.setattr(login_module, "open_url", fake_open)
    return addresses


def test_the_browser_login_opens_the_login_page(window, api, opened):
    dialog = browser_login(window, opened)
    assert opened[0].startswith(fakes.IDP) and "code_challenge" in opened[0]
    assert api.idp.credential_posts() == []
    assert dialog.finish_button.isEnabled()


def test_finish_is_only_possible_after_starting(window):
    assert not dialog_of(window).finish_button.isEnabled()


def test_the_browser_login_finishes_without_a_password(window, api, opened):
    dialog = browser_login(window, opened)
    state = fakes.query_of(opened[0])["state"]
    dialog.address.setText(
        f"https://talk.parro.com/oauth2?code={fakes.AUTHORIZATION_CODE}&state={state}"
    )
    dialog.finish_button.click()
    wait_until(lambda: window.logged_in)
    assert api.idp.credential_posts() == [] and not dialog.isVisible()


def test_a_wrong_address_is_shown_and_can_be_retried(window, opened):
    dialog = browser_login(window, opened)
    dialog.address.setText("https://talk.parro.com/oauth2?code=x&state=other")
    dialog.finish_button.click()
    wait_until(lambda: dialog.message.text() not in ("", "One moment…"))
    assert dialog.isVisible() and dialog.address.text() == ""


def test_without_a_browser_it_shows_the_address(window, monkeypatch):
    monkeypatch.setattr(login_module, "open_url", lambda _address: False)
    dialog = dialog_of(window)
    dialog.open_button.click()
    wait_until(lambda: "Could not open a browser" in dialog.message.text())
    assert fakes.IDP in dialog.message.text()


# ---------------------------------------------------------------------------- logging out


def test_logging_out_asks_first(logged_in, window, api, token_file, monkeypatch):
    asked: list[str] = []

    def no(_parent: Any, question: str) -> bool:
        asked.append(question)
        return False

    monkeypatch.setattr(window_module, "ask", no)
    wait_until(lambda: window.logged_in)
    window.account_button.click()
    QApplication.processEvents()
    assert len(asked) == 1 and token_file.exists() and window.logged_in


def test_logging_out_forgets_the_login(logged_in, window, api, token_file, monkeypatch):
    monkeypatch.setattr(window_module, "ask", lambda _parent, _question: True)
    wait_until(lambda: window.logged_in)
    window.account_button.click()
    wait_until(lambda: not window.logged_in)
    assert status_of(window) == "Not logged in" and window.account_button.text() == "Log in"
    assert api.idp.requests != [], "the tokens are revoked at the login server"
    assert api.idp.credential_posts() == []


def test_the_login_button_opens_the_dialog_again(window):
    dialog = dialog_of(window)
    dialog.reject()
    QApplication.processEvents()
    window.account_button.click()
    wait_until(dialog.isVisible)
