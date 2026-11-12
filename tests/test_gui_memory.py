"""The app's short memory: a kept answer within 5 minutes, a new load after it, and Refresh, every
change and logging in or out drop what was kept. Nothing of it is written to disk."""

import json
import os
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from parro.api_client import ParroClient  # noqa: E402
from parro_gui import widgets as gui_widgets  # noqa: E402
from parro_gui.memory import KEEP_SECONDS, Memory  # noqa: E402
from parro_gui.views.base import LOADING  # noqa: E402
from parro_gui.window import SECTIONS, MainWindow  # noqa: E402
from tests import fakes  # noqa: E402
from tests.conftest import load_sample  # noqa: E402
from tests.gui_helpers import dispose, wait_until  # noqa: E402

AT_NINE = datetime(2026, 11, 12, 9, 0)


class Clock:
    def __init__(self) -> None:
        self.seconds = 1000.0

    def __call__(self) -> float:
        return self.seconds


# ----------------------------------------------------------------------------- the memory


def test_an_answer_is_kept_for_five_minutes():
    clock = Clock()
    memory = Memory(clock, lambda: AT_NINE)
    memory.put("key", {"items": [1]})
    clock.seconds += KEEP_SECONDS - 1
    kept = memory.get("key")
    assert kept is not None and kept.result == {"items": [1]} and kept.fetched_at == AT_NINE
    clock.seconds += 1
    assert memory.get("key") is None and len(memory) == 0


def test_what_a_view_does_with_an_answer_does_not_change_the_kept_one():
    memory = Memory(Clock(), lambda: AT_NINE)
    shown = memory.put("key", {"items": [1]}).result
    shown["items"].append(2)
    again = memory.get("key")
    assert again is not None
    again.result["items"].append(3)
    assert memory.get("key").result == {"items": [1]}  # type: ignore[union-attr]


def test_forget_drops_everything():
    memory = Memory(Clock(), lambda: AT_NINE)
    memory.put("a", 1)
    memory.put("b", 2)
    memory.forget()
    assert memory.get("a") is None and memory.get("b") is None


# ----------------------------------------------------------------------------- the window


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


@pytest.fixture
def api() -> fakes.FakeParroApi:
    return fakes.FakeParroApi(load_sample)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def window(application, api, clock) -> Any:
    make_client: Callable[[Any], ParroClient] = lambda s: ParroClient(s, transport=api)  # noqa: E731
    created = MainWindow(make_client)
    created.memory.clock = clock
    created.memory.wall_clock = lambda: AT_NINE
    wait_until(lambda: created.logged_in)
    yield created
    dispose(created)


def settled(view: Any) -> Any:
    wait_until(lambda: view.loaded and view.notice.text() != LOADING)
    return view


def go_to(window: MainWindow, name: str) -> Any:
    window.sections.setCurrentRow(SECTIONS.index(name))
    return settled(window.views[name])


def announcement_lists(api: fakes.FakeParroApi) -> int:
    return sum(1 for r in api.api_requests() if "/announcement" in r.url and "/event/" not in r.url)


def requests(api: fakes.FakeParroApi) -> int:
    return len(api.api_requests())


def test_going_back_to_a_filter_choice_shows_what_was_kept(window, api):
    view = go_to(window, "Announcements")
    assert view.fetched.text() == "Fetched at 09:00"
    view.unread_only.setChecked(True)
    settled(view)
    before = requests(api)
    view.unread_only.setChecked(False)
    settled(view)
    assert requests(api) == before, "no request: the answer from a moment ago"
    assert view.list.count() > 0 and view.fetched.text() == "Fetched at 09:00"


def test_switching_sections_within_five_minutes_loads_nothing(window, api, clock):
    go_to(window, "Announcements")
    go_to(window, "Calendar")
    before = requests(api)
    clock.seconds += KEEP_SECONDS - 1
    go_to(window, "Announcements")
    assert requests(api) == before


def test_after_five_minutes_coming_back_loads_again(window, api, clock):
    go_to(window, "Announcements")
    go_to(window, "Calendar")
    before = requests(api)
    clock.seconds += KEEP_SECONDS
    view = go_to(window, "Announcements")
    wait_until(lambda: requests(api) > before)
    settled(view)


def test_refresh_always_fetches(window, api):
    view = go_to(window, "Announcements")
    before = requests(api)
    view.refresh_button.click()
    settled(view)
    assert requests(api) > before


def test_an_announcement_is_kept_too(window, api):
    view = go_to(window, "Announcements")
    wait_until(lambda: "Fetched at 09:00" in view.detail.toPlainText())
    first = view.list.currentRow()
    view.list.setCurrentRow(first + 1)
    wait_until(lambda: "Fetched at 09:00" in view.detail.toPlainText())
    before = requests(api)
    view.list.setCurrentRow(first)
    assert requests(api) == before and "Fetched at 09:00" in view.detail.toPlainText()


def test_a_change_drops_everything_that_was_kept(window, api, monkeypatch):
    go_to(window, "Overview")
    view = go_to(window, "Announcements")
    row = next(i for i, item in enumerate(view.items) if item["announcement"].get("read") is False)
    view.list.setCurrentRow(row)
    wait_until(view.mark_button.isEnabled)
    monkeypatch.setattr(gui_widgets, "ask", lambda *_args: True)
    view.mark_button.click()
    wait_until(lambda: view.notice.text() == "Marked as read.")
    assert len(api.writes()) == 1
    before = requests(api)
    go_to(window, "Overview")
    wait_until(lambda: requests(api) > before)


def test_logging_out_forgets_everything(window, monkeypatch):
    go_to(window, "Announcements")
    assert len(window.memory) > 0
    monkeypatch.setattr("parro_gui.window.ask", lambda *_args: True)
    window.account_button.click()
    wait_until(lambda: not window.logged_in)
    assert len(window.memory) == 0
    assert window.views["Announcements"].fetched.text() == ""


def test_the_archive_is_never_kept(window, api):
    view = go_to(window, "Archive")
    assert view.fetched.text() == ""
    assert not any(key[0] == "ArchiveSection" for key in window.memory._kept)


def test_nothing_is_written_to_disk(window, tmp_path):
    """The disk cache may hold calendar details and files; the lists stay in memory only."""
    go_to(window, "Overview")
    go_to(window, "Announcements")
    go_to(window, "Chats")
    data = tmp_path / "data"
    written = [p for p in data.rglob("*") if p.is_file()] if data.exists() else []
    for path in written:
        text = path.read_bytes()
        assert b"announcements" not in text and b"chatrooms" not in text, path
