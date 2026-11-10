"""The desktop app's local data: the archive, the cache, the export and the secret links."""

import json
import logging
import os
import stat
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication  # noqa: E402

from parro import operations  # noqa: E402
from parro.api_client import ParroClient  # noqa: E402
from parro.errors import ParroError  # noqa: E402
from parro_gui import widgets as gui_widgets  # noqa: E402
from parro_gui.views import archive as archive_view  # noqa: E402
from parro_gui.views.base import LOADING  # noqa: E402
from parro_gui.window import SECTIONS, MainWindow  # noqa: E402
from tests import fakes  # noqa: E402
from tests.conftest import load_sample  # noqa: E402
from tests.gui_helpers import dispose, wait_until  # noqa: E402

BEFORE_THE_TRIP = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def environment(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("PARRO_"):
            monkeypatch.delenv(name)
    path = tmp_path / "tokens.json"
    path.write_text(
        json.dumps(
            {
                "access_token": fakes.ACCESS_TOKEN,
                "refresh_token": fakes.REFRESH_TOKEN,
                "expires_at": time.time() + 3000,
            }
        )
    )
    monkeypatch.setenv("PARRO_TOKEN_FILE", str(path))
    monkeypatch.setenv("PARRO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(operations, "current_time", lambda: BEFORE_THE_TRIP)


@pytest.fixture
def api() -> fakes.FakeParroApi:
    return fakes.FakeParroApi(load_sample)


@pytest.fixture
def make_client(api) -> Callable[[Any], ParroClient]:
    return lambda settings: ParroClient(settings, transport=api)


@pytest.fixture
def window(application, make_client):
    created = MainWindow(make_client)
    wait_until(lambda: created.logged_in)
    yield created
    dispose(created)


def open_section(window: MainWindow, name: str) -> Any:
    view = window.views[name]
    window.sections.setCurrentRow(SECTIONS.index(name))
    wait_until(lambda: view.loaded and view.notice.text() != LOADING)
    return view


def settle() -> None:
    for _ in range(30):
        QApplication.processEvents()
        time.sleep(0.002)


def answer(monkeypatch, value: bool) -> list[str]:
    questions: list[str] = []

    def fake_ask(_parent: Any, question: str) -> bool:
        questions.append(question)
        return value

    monkeypatch.setattr(gui_widgets, "ask", fake_ask)
    return questions


def archive_at(window: MainWindow, folder: Path, monkeypatch) -> Any:
    view = open_section(window, "Archive")
    monkeypatch.setattr(gui_widgets, "choose_folder", lambda _parent: str(folder))
    view.choose_button.click()
    return view


def synced(view: Any) -> None:
    wait_until(lambda: view.sync_button.isEnabled(), 15)
    settle()


# ------------------------------------------------------------------------------- the archive


def test_the_default_folder_is_the_same_as_the_cli(window, tmp_path):
    view = open_section(window, "Archive")
    settle()
    assert view.folder == str(tmp_path / "data" / "archive")


def test_sync_writes_the_archive_and_reports(window, tmp_path, monkeypatch, api):
    folder = tmp_path / "bewaard"
    view = archive_at(window, folder, monkeypatch)
    view.sync_button.click()
    assert not view.sync_button.isEnabled() and view.stop_button.isEnabled()
    synced(view)
    assert (folder / "index.md").exists()
    assert "Archive up to date" in view.report.toPlainText()
    assert "written" in view.report.toPlainText()
    assert api.writes() == [], "a sync only reads from Parro"


def test_progress_reaches_the_window(window, tmp_path, monkeypatch):
    view = archive_at(window, tmp_path / "bewaard", monkeypatch)
    seen: list[str] = []
    view.progress.connect(seen.append)
    view.sync_button.click()
    synced(view)
    assert any("Announcement 1 of" in text for text in seen)
    assert any("Reading the calendar" in text for text in seen)


def test_the_options_reach_the_sync(window, tmp_path, monkeypatch):
    received: list[Any] = []

    def fake_sync(_client: Any, options: Any, _report: Any) -> dict[str, Any]:
        received.append(options)
        return {"archive": str(options.target)}

    monkeypatch.setattr(operations, "sync_archive", fake_sync)
    view = archive_at(window, tmp_path / "x", monkeypatch)
    view.previous.setChecked(True)
    view.photos.setChecked(True)
    view.sync_button.click()
    synced(view)
    assert received[0].previous_year and received[0].photos


def test_stop_ends_the_run_and_marks_nothing_as_gone(window, tmp_path, monkeypatch):
    folder = tmp_path / "bewaard"
    view = archive_at(window, folder, monkeypatch)
    view.sync_button.click()
    synced(view)
    index_before = (folder / "index.md").read_text(encoding="utf-8")

    original = operations.sync_archive

    def stop_at_once(client: Any, options: Any, report: Any) -> Any:
        view._stop.set()
        return original(client, options, report)

    monkeypatch.setattr(operations, "sync_archive", stop_at_once)
    view.sync_button.click()
    synced(view)
    assert view.status.text() == archive_view.STOPPED
    assert (folder / "index.md").read_text(encoding="utf-8") == index_before


def test_a_failed_sync_is_shown_and_can_be_run_again(window, tmp_path, monkeypatch):
    def broken(_client: Any, _options: Any, _report: Any) -> None:
        raise ParroError("Parro did not answer.")

    monkeypatch.setattr(operations, "sync_archive", broken)
    view = archive_at(window, tmp_path / "x", monkeypatch)
    view.sync_button.click()
    synced(view)
    assert view.status.text() == "Parro did not answer."
    assert view.sync_button.isEnabled() and not view.stop_button.isEnabled()


def test_closing_the_window_stops_a_running_sync(application, make_client, tmp_path, monkeypatch):
    stopped: list[bool] = []

    def waits_for_stop(_client: Any, _options: Any, report: Any) -> None:
        for _ in range(500):
            try:
                report("working")
            except archive_view.SyncStopped:
                stopped.append(True)
                raise
            time.sleep(0.01)

    monkeypatch.setattr(operations, "sync_archive", waits_for_stop)
    window = MainWindow(make_client)
    wait_until(lambda: window.logged_in)
    view = archive_at(window, tmp_path / "x", monkeypatch)
    view.sync_button.click()
    settle()
    dispose(window)
    assert stopped == [True]


def test_a_cancelled_folder_choice_changes_nothing(window, monkeypatch):
    view = open_section(window, "Archive")
    settle()
    before = view.folder
    monkeypatch.setattr(gui_widgets, "choose_folder", lambda _parent: "")
    view.choose_button.click()
    assert view.folder == before


# --------------------------------------------------------------------------------- the cache


def test_the_cache_size_is_shown(window):
    view = open_section(window, "Archive")
    wait_until(lambda: view.cache_label.text().startswith("Cache:"))


def test_emptying_the_cache_asks_first(window, monkeypatch):
    questions = answer(monkeypatch, False)
    cleared: list[bool] = []
    monkeypatch.setattr(operations, "cache_clear", lambda _client: cleared.append(True))
    view = open_section(window, "Archive")
    view.clear_button.click()
    settle()
    assert len(questions) == 1 and cleared == []


def test_emptying_the_cache(window, monkeypatch):
    answer(monkeypatch, True)
    cleared: list[bool] = []

    def clear(_client: Any) -> dict[str, Any]:
        cleared.append(True)
        return {}

    monkeypatch.setattr(operations, "cache_clear", clear)
    view = open_section(window, "Archive")
    view.clear_button.click()
    wait_until(lambda: cleared == [True])


# -------------------------------------------------------------------------------- the export


def test_export_writes_a_private_calendar_file(window, tmp_path, monkeypatch, api):
    target = tmp_path / "agenda.ics"
    monkeypatch.setattr(gui_widgets, "choose_save_file", lambda *_args: str(target))
    view = open_section(window, "Calendar")
    settle()
    view.export_button.click()
    wait_until(lambda: "Exported" in view.notice.text())
    data = target.read_bytes()
    assert data.startswith(b"BEGIN:VCALENDAR\r\n"), "iCalendar lines end in CRLF"
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert api.writes() == []


def test_cancelling_the_export_writes_nothing(window, tmp_path, monkeypatch):
    monkeypatch.setattr(gui_widgets, "choose_save_file", lambda *_args: "")
    view = open_section(window, "Calendar")
    settle()
    view.export_button.click()
    settle()
    assert "Exported" not in view.notice.text()


# ---------------------------------------------------------------------------------- the links


def test_the_subscription_link_needs_a_yes(window, monkeypatch, api):
    questions = answer(monkeypatch, False)
    view = open_section(window, "Calendar")
    settle()
    before = len(api.requests)
    view.link_button.click()
    settle()
    assert "without logging in" in questions[0]
    assert len(api.requests) == before, "not even fetched"
    assert not hasattr(view, "secret_dialog")


def test_the_subscription_link_stays_in_its_dialog(window, monkeypatch, caplog):
    answer(monkeypatch, True)
    view = open_section(window, "Calendar")
    settle()
    with caplog.at_level(logging.DEBUG):
        view.link_button.click()
        wait_until(lambda: hasattr(view, "secret_dialog"))
    link = view.secret_dialog.link.text()
    assert link and link not in caplog.text
    assert link not in view.notice.text() and link not in window.statusBar().currentMessage()
    assert view.secret_dialog.link.isReadOnly()


def test_a_link_can_be_copied(window, monkeypatch, application):
    answer(monkeypatch, True)
    view = open_section(window, "Calendar")
    settle()
    view.link_button.click()
    wait_until(lambda: hasattr(view, "secret_dialog"))
    view.secret_dialog.copy_button.click()
    assert application.clipboard().text() == view.secret_dialog.link.text()


def test_the_privacy_link_is_per_child_and_needs_a_yes(window, monkeypatch, api):
    questions = answer(monkeypatch, True)
    view = open_section(window, "Family")
    wait_until(lambda: view.child.count() == 2)
    view.child.setCurrentIndex(1)
    view.link_button.click()
    wait_until(lambda: hasattr(view, "secret_dialog"))
    assert "without logging in" in questions[0]
    assert view.secret_dialog.link.text()
    assert api.writes() == []


def test_saying_no_to_the_privacy_link_fetches_nothing(window, monkeypatch, api):
    answer(monkeypatch, False)
    view = open_section(window, "Family")
    wait_until(lambda: view.child.count() == 2)
    before = len(api.requests)
    view.link_button.click()
    settle()
    assert len(api.requests) == before
