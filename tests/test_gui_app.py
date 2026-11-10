"""The desktop app's window and background worker, offscreen, against the fake servers."""

import json
import os
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from parro.api_client import ParroClient  # noqa: E402
from parro.errors import ApiError, ConfigurationError  # noqa: E402
from parro_gui.window import (  # noqa: E402
    CHECKING_LOGIN,
    LOGIN_EXPIRED,
    LOGIN_HALTED,
    SECTIONS,
    MainWindow,
    describe_login,
)
from parro_gui.worker import Worker  # noqa: E402
from tests import fakes  # noqa: E402
from tests.conftest import load_sample  # noqa: E402
from tests.gui_helpers import dispose, wait_until  # noqa: E402


@pytest.fixture(autouse=True)
def environment(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("PARRO_"):
            monkeypatch.delenv(name)
    token_file = tmp_path / "tokens.json"
    monkeypatch.setenv("PARRO_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("PARRO_DATA_DIR", str(tmp_path / "data"))
    return token_file


@pytest.fixture
def logged_in(environment) -> None:
    environment.write_text(
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
def worker(application, make_client):
    created = Worker(make_client)
    yield created
    created.close()


def run_one(worker: Worker, task: Callable[[ParroClient], Any]) -> tuple[list[Any], list[str]]:
    results: list[Any] = []
    errors: list[str] = []
    worker.submit(task, results.append, errors.append)
    wait_until(lambda: bool(results or errors))
    return results, errors


# ------------------------------------------------------------------------------- the worker


def test_a_result_arrives_on_the_windows_thread(worker, application):
    threads: dict[str, Any] = {}

    def task(_client: ParroClient) -> str:
        threads["task"] = QThread.currentThread()
        return "klaar"

    def done(value: str) -> None:
        threads["done"] = QThread.currentThread()
        threads["value"] = value

    worker.submit(task, done, pytest.fail)
    wait_until(lambda: "done" in threads)
    assert threads["value"] == "klaar"
    assert threads["done"] == application.thread()
    assert threads["task"] != application.thread(), "the window must not wait for the network"


def test_the_window_keeps_running_while_a_task_waits(worker):
    release = threading.Event()
    results: list[str] = []

    def slow(_client: ParroClient) -> str:
        assert release.wait(5)
        return "klaar"

    worker.submit(slow, results.append, pytest.fail)
    QApplication.processEvents()
    assert results == [], "submit returned while the task is still running"
    release.set()
    wait_until(lambda: results == ["klaar"])


def test_tasks_run_one_at_a_time_and_in_order(worker):
    running, most = [0], [0]
    seen: list[int] = []

    def make(number: int) -> Callable[[ParroClient], int]:
        def task(_client: ParroClient) -> int:
            running[0] += 1
            most[0] = max(most[0], running[0])
            time.sleep(0.01)
            running[0] -= 1
            return number

        return task

    for number in range(6):
        worker.submit(make(number), seen.append, pytest.fail)
    wait_until(lambda: len(seen) == 6)
    assert seen == [0, 1, 2, 3, 4, 5] and most == [1]


def test_one_client_is_shared(worker, make_client):
    clients: list[ParroClient] = []
    run_one(worker, lambda client: clients.append(client))
    run_one(worker, lambda client: clients.append(client))
    assert clients[0] is clients[1]


def test_a_parro_error_reaches_the_window_as_its_message(worker):
    def task(_client: ParroClient) -> None:
        raise ApiError("Parro answered 500.", status=500)

    assert run_one(worker, task) == ([], ["Parro answered 500."])


def test_an_unexpected_error_shows_only_its_type(worker, caplog):
    secret = "access-token-in-an-error"

    def task(_client: ParroClient) -> None:
        raise ValueError(secret)

    _, errors = run_one(worker, task)
    assert errors == ["Something went wrong (ValueError)."]
    assert secret not in caplog.text


def test_it_keeps_working_after_a_failure(worker):
    def broken(_client: ParroClient) -> None:
        raise KeyError("x")

    run_one(worker, broken)
    assert run_one(worker, lambda _client: 1) == ([1], [])


def test_bad_settings_are_an_error_not_a_crash(worker, monkeypatch):
    monkeypatch.setenv("PARRO_LOGIN_METHOD", "nonsense")
    _, errors = run_one(worker, lambda _client: 1)
    assert "Unknown login method" in errors[0]


def test_nothing_is_delivered_after_closing(application, make_client):
    worker = Worker(make_client)
    results: list[int] = []
    worker.submit(lambda _client: 1, results.append, pytest.fail)
    worker.close()
    QApplication.processEvents()
    assert results == []
    worker.submit(lambda _client: 2, results.append, pytest.fail)
    QApplication.processEvents()
    assert results == []


# ------------------------------------------------------------------------------- the window


@pytest.fixture
def window(application, make_client):
    created = MainWindow(make_client)
    yield created
    dispose(created)


def status_of(window: MainWindow) -> str:
    wait_until(lambda: window.statusBar().currentMessage() != CHECKING_LOGIN)
    return window.statusBar().currentMessage()


def test_every_section_has_a_page(window):
    assert window.sections.count() == window.pages.count() == len(SECTIONS)
    assert window.pages.currentIndex() == 0


def test_choosing_a_section_shows_its_page(window):
    window.sections.setCurrentRow(2)
    assert window.pages.currentIndex() == 2


def test_the_title_names_the_version(window):
    from parro import __version__

    assert __version__ in window.windowTitle()


def test_without_a_login_it_says_so(window, api):
    assert status_of(window) == "Not logged in"
    assert api.requests == [], "no token, so nothing to ask Parro"


def test_with_a_login_it_shows_until_when(logged_in, window, api):
    assert status_of(window).startswith("Logged in")
    assert api.idp.credential_posts() == [], "starting the app never spends a password check"
    assert api.writes() == []


def test_closing_waits_for_the_worker(logged_in, application, make_client):
    window = MainWindow(make_client)
    dispose(window)
    QApplication.processEvents()
    assert window.worker._closed


@pytest.mark.parametrize(
    ("status", "line"),
    [
        ({}, "Not logged in"),
        ({"automatic_login_halted": "wrong password"}, LOGIN_HALTED),
        ({"has_refresh_token": True, "login_expires_in_seconds": 0}, LOGIN_EXPIRED),
        ({"has_access_token": True, "error": "Login halted."}, "Login halted."),
        ({"has_refresh_token": True}, "Logged in"),
        (
            {"has_access_token": True, "login_valid_until": "2026-11-09T14:32:00+01:00"},
            "Logged in until Mon 9 Nov 2026 14:32",
        ),
    ],
)
def test_describe_login(status, line):
    assert describe_login(status) == line


def test_a_configuration_error_is_shown(logged_in, application, monkeypatch):
    def refuses(_settings: Any) -> ParroClient:
        raise ConfigurationError("Bad settings.")

    window = MainWindow(refuses)
    assert status_of(window) == "Bad settings."
    dispose(window)
