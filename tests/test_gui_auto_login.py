"""Logging in by itself, against the fake login server: one password check at most, and the latch
decides. The tests count password checks, because the login server locks an account after a few
failed ones."""

import json
import logging
import os
import stat
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication  # noqa: E402

from parro.api_client import ParroClient  # noqa: E402
from parro_gui import auto_login  # noqa: E402
from parro_gui import widgets as gui_widgets  # noqa: E402
from parro_gui import window as window_module  # noqa: E402
from parro_gui.auto_login import Remembered, app_settings, save_remembered  # noqa: E402
from parro_gui.window import LOGIN_HALTED, MainWindow  # noqa: E402
from tests import fakes  # noqa: E402
from tests.conftest import load_sample  # noqa: E402
from tests.gui_helpers import dispose, wait_until  # noqa: E402

WRONG_PASSWORD = "not-the-password-8f3a"
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="file permissions are POSIX")


@pytest.fixture(autouse=True)
def token_file(tmp_path, monkeypatch) -> Path:
    for name in list(os.environ):
        if name.startswith("PARRO_"):
            monkeypatch.delenv(name)
    path = Path(tmp_path) / "tokens.json"
    monkeypatch.setenv("PARRO_TOKEN_FILE", str(path))
    monkeypatch.setenv("PARRO_DATA_DIR", str(tmp_path / "data"))
    return path


@pytest.fixture
def data_dir(tmp_path) -> Path:
    return Path(tmp_path) / "data"


def password_file(tmp_path: Path, password: str = fakes.CORRECT_PASSWORD) -> Path:
    path = tmp_path / "password.txt"
    path.write_text(password + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.fixture
def remembered(tmp_path, data_dir) -> Path:
    """What the dialog stores after ticking the box: the address and the file's path."""
    path = password_file(tmp_path)
    save_remembered(data_dir, Remembered(fakes.USERNAME, path))
    return path


@pytest.fixture
def api() -> fakes.FakeParroApi:
    return fakes.FakeParroApi(load_sample)


@pytest.fixture
def make_client(api) -> Callable[[Any], ParroClient]:
    return lambda settings: ParroClient(settings, transport=api)


@pytest.fixture
def start(application, make_client) -> Any:
    """Start the app as often as a test likes; every window is closed at the end."""
    started: list[MainWindow] = []

    def new_window() -> MainWindow:
        created = MainWindow(make_client)
        started.append(created)
        return created

    yield new_window
    for created in started:
        dispose(created)


def checks(api: fakes.FakeParroApi) -> int:
    return len(api.idp.credential_posts())


def status_of(window: MainWindow) -> str:
    return window.statusBar().currentMessage()


def settle() -> None:
    time.sleep(0.05)
    for _ in range(30):
        QApplication.processEvents()


def valid_login(token_file: Path) -> None:
    token_file.write_text(
        json.dumps(
            {
                "access_token": fakes.ACCESS_TOKEN,
                "refresh_token": fakes.REFRESH_TOKEN,
                "expires_at": time.time() + 3000,
            }
        )
    )


# ------------------------------------------------------------------------------ at start


def test_it_logs_in_by_itself_with_one_check(start, api, remembered):
    window = start()
    wait_until(lambda: window.logged_in)
    assert checks(api) == 1
    assert "logged in by itself at" in status_of(window)
    assert window.login_dialog is None, "no dialog: nothing to type"


def test_a_valid_login_spends_nothing(start, api, remembered, token_file):
    valid_login(token_file)
    window = start()
    wait_until(lambda: window.logged_in)
    settle()
    assert checks(api) == 0


def test_without_a_password_file_it_offers_the_dialog(start, api):
    window = start()
    wait_until(lambda: window.login_dialog is not None)
    assert checks(api) == 0


def test_the_variables_work_as_in_the_cli(start, api, tmp_path, monkeypatch):
    monkeypatch.setenv("PARRO_USERNAME", fakes.USERNAME)
    monkeypatch.setenv("PARRO_PASSWORD_FILE", str(password_file(tmp_path)))
    window = start()
    wait_until(lambda: window.logged_in)
    assert checks(api) == 1


def test_it_always_uses_the_login_form(monkeypatch, remembered):
    """`auto` can spend two checks; the app spends one."""
    monkeypatch.setenv("PARRO_LOGIN_METHOD", "auto")
    assert app_settings().login_method == "login-form"


def test_the_variables_win_over_what_was_remembered(monkeypatch, remembered, tmp_path):
    other = tmp_path / "other.txt"
    monkeypatch.setenv("PARRO_USERNAME", "someone@example.com")
    monkeypatch.setenv("PARRO_PASSWORD_FILE", str(other))
    settings = app_settings()
    assert settings.username == "someone@example.com" and settings.password_file == other


# ----------------------------------------------------------------------------- the latch


def test_a_rejected_password_is_one_check_also_after_a_restart(start, api, data_dir, tmp_path):
    path = password_file(tmp_path, WRONG_PASSWORD)
    save_remembered(data_dir, Remembered(fakes.USERNAME, path))
    first = start()
    wait_until(lambda: first.login_dialog is not None)
    for _ in range(3):
        first.refresh_login()
        settle()
    assert checks(api) == 1, "never two in one start"
    second = start()
    wait_until(lambda: status_of(second) == LOGIN_HALTED)
    settle()
    assert checks(api) == 1, "the latch holds across a restart"


def test_logging_in_by_hand_clears_the_latch_and_it_works_again(start, api, data_dir, tmp_path):
    path = password_file(tmp_path, WRONG_PASSWORD)
    save_remembered(data_dir, Remembered(fakes.USERNAME, path))
    window = start()
    wait_until(lambda: window.login_dialog is not None and window.login_dialog.isVisible())
    path.write_text(fakes.CORRECT_PASSWORD, encoding="utf-8")
    dialog = window.login_dialog
    assert dialog is not None and dialog.remember.isChecked()
    dialog.password.setText(fakes.CORRECT_PASSWORD)
    dialog.log_in_button.click()
    wait_until(lambda: window.logged_in)
    assert checks(api) == 2


# ------------------------------------------------------------------- while the app is open


def test_when_the_login_expires_it_logs_in_by_itself_once_more(start, api, remembered, token_file):
    window = start()
    wait_until(lambda: window.logged_in)
    token_file.unlink()  # the login is gone, as after 8 hours
    window.refresh_login()
    wait_until(lambda: checks(api) == 2)
    wait_until(lambda: window.logged_in)
    window.refresh_login()
    settle()
    assert checks(api) == 2


def test_after_logging_out_it_does_not_log_in_by_itself(start, api, remembered, monkeypatch):
    window = start()
    wait_until(lambda: window.logged_in)
    monkeypatch.setattr(window_module, "ask", lambda *_args: True)
    window.account_button.click()
    wait_until(lambda: not window.logged_in)
    for _ in range(3):
        window.refresh_login()
        settle()
    assert checks(api) == 1 and not window.logged_in


# ------------------------------------------------------------------------ the file itself


@POSIX_ONLY
def test_a_file_others_can_read_is_not_used(start, api, remembered):
    remembered.chmod(0o644)
    window = start()
    wait_until(lambda: "Others on this computer can read" in status_of(window))
    settle()
    assert checks(api) == 0


def test_a_missing_file_is_named_and_spends_nothing(start, api, remembered):
    remembered.unlink()
    window = start()
    wait_until(lambda: "cannot be read" in status_of(window))
    assert checks(api) == 0


def test_the_password_is_never_written_or_logged(start, api, remembered, data_dir, caplog):
    with caplog.at_level(logging.DEBUG):
        window = start()
        wait_until(lambda: window.logged_in)
    stored = (data_dir / auto_login.FILE_NAME).read_text(encoding="utf-8")
    assert fakes.CORRECT_PASSWORD not in stored and str(remembered) in stored
    assert fakes.CORRECT_PASSWORD not in caplog.text
    if os.name != "nt":
        assert stat.S_IMODE((data_dir / auto_login.FILE_NAME).stat().st_mode) == 0o600


# ------------------------------------------------------------------------------ the dialog


def dialog_with_box(start, tmp_path, typed: str, in_file: str) -> Any:
    window = start()
    wait_until(lambda: window.login_dialog is not None and window.login_dialog.isVisible())
    dialog = window.login_dialog
    dialog.username.setText(fakes.USERNAME)
    dialog.password.setText(typed)
    dialog.remember.setChecked(True)
    dialog.password_file.setText(str(password_file(tmp_path, in_file)))
    return window, dialog


def test_ticking_the_box_remembers_the_address_and_the_path(start, api, tmp_path, data_dir):
    window, dialog = dialog_with_box(start, tmp_path, *[fakes.CORRECT_PASSWORD] * 2)
    dialog.log_in_button.click()
    wait_until(lambda: window.logged_in)
    kept = auto_login.load_remembered(data_dir)
    assert kept == Remembered(fakes.USERNAME, tmp_path / "password.txt")
    assert checks(api) == 1


def test_a_file_with_another_password_is_refused_before_sending(start, api, tmp_path, data_dir):
    _window, dialog = dialog_with_box(start, tmp_path, fakes.CORRECT_PASSWORD, WRONG_PASSWORD)
    dialog.log_in_button.click()
    assert "not the one you typed" in dialog.message.text()
    settle()
    assert checks(api) == 0 and auto_login.load_remembered(data_dir) is None


@POSIX_ONLY
def test_the_dialog_refuses_a_file_others_can_read(start, api, tmp_path):
    _window, dialog = dialog_with_box(start, tmp_path, *[fakes.CORRECT_PASSWORD] * 2)
    (tmp_path / "password.txt").chmod(0o640)
    dialog.log_in_button.click()
    assert "Others on this computer" in dialog.message.text()
    settle()
    assert checks(api) == 0


def test_unticking_the_box_forgets(start, api, tmp_path, data_dir, monkeypatch):
    path = password_file(tmp_path, WRONG_PASSWORD)  # rejected: so the dialog opens
    save_remembered(data_dir, Remembered(fakes.USERNAME, path))
    window = start()
    wait_until(lambda: window.login_dialog is not None and window.login_dialog.isVisible())
    dialog = window.login_dialog
    dialog.remember.setChecked(False)
    dialog.password.setText(fakes.CORRECT_PASSWORD)
    dialog.log_in_button.click()
    wait_until(lambda: window.logged_in)
    assert auto_login.load_remembered(data_dir) is None


def test_choosing_a_file_ticks_the_box(start, tmp_path, monkeypatch):
    path = password_file(tmp_path)
    monkeypatch.setattr(gui_widgets, "choose_file", lambda *_args: str(path))
    window = start()
    wait_until(lambda: window.login_dialog is not None)
    dialog = window.login_dialog
    dialog.choose_button.click()
    assert dialog.password_file.text() == str(path) and dialog.remember.isChecked()
