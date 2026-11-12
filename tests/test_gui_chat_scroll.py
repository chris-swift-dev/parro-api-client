"""A chat opens at its newest message, like other chat apps, and stays there until you scroll up."""

import copy
import json
import os
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from parro.api_client import ParroClient  # noqa: E402
from parro_gui.views.base import LOADING  # noqa: E402
from parro_gui.widgets import SafeTextBrowser  # noqa: E402
from parro_gui.window import SECTIONS, MainWindow  # noqa: E402
from tests import fakes  # noqa: E402
from tests.conftest import load_sample  # noqa: E402
from tests.gui_helpers import dispose, wait_until  # noqa: E402

FIRST = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)
MESSAGES = 60
NEWEST = f"Bericht nummer {MESSAGES}"


def long_chat(file_name: str) -> Any:
    """The fixtures, with 60 invented messages in the chat; the API gives the newest first."""
    sample = load_sample(file_name)
    if file_name != "listChatMessages.200.json":
        return sample
    template = sample["items"][0]
    items = []
    for number in range(MESSAGES, 0, -1):
        message = copy.deepcopy(template)
        message["text"] = f"Bericht nummer {number}"
        message["createdAt"] = (FIRST + timedelta(minutes=number)).isoformat()
        items.append(message)
    return {**sample, "items": items}


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
    return fakes.FakeParroApi(long_chat)


@pytest.fixture
def window(application, api) -> Any:
    make_client: Callable[[Any], ParroClient] = lambda s: ParroClient(s, transport=api)  # noqa: E731
    created = MainWindow(make_client)
    created.resize(1000, 680)
    created.show()
    wait_until(lambda: created.logged_in)
    yield created
    dispose(created)


def open_chat(window: MainWindow) -> Any:
    view: Any = window.views["Chats"]
    window.sections.setCurrentRow(SECTIONS.index("Chats"))
    wait_until(lambda: view.loaded and view.notice.text() != LOADING)
    view.list.setCurrentRow(0)
    wait_until(lambda: NEWEST in view.detail.toPlainText())
    wait_until(lambda: at_end(view.detail))
    return view


def at_end(browser: SafeTextBrowser) -> bool:
    bar = browser.verticalScrollBar()
    return bar.maximum() > 0 and bar.value() == bar.maximum()


def newest_in_view(browser: SafeTextBrowser) -> bool:
    found = browser.document().find(NEWEST)
    return browser.viewport().rect().contains(browser.cursorRect(found).center())


def test_a_long_chat_opens_at_the_newest_message(window):
    view = open_chat(window)
    assert newest_in_view(view.detail)
    text = view.detail.toPlainText()
    assert text.index("Bericht nummer 1\n") < text.index(NEWEST), "still oldest to newest"


def test_it_stays_at_the_end_while_the_size_changes(window):
    view = open_chat(window)
    window.resize(700, 600)
    wait_until(lambda: at_end(view.detail))
    window.resize(1200, 800)
    wait_until(lambda: at_end(view.detail))


def test_after_scrolling_up_it_stays_where_you_are(window):
    view = open_chat(window)
    bar = view.detail.verticalScrollBar()
    bar.setValue(bar.maximum() // 3)
    window.resize(700, 600)
    QtWidgets.QApplication.processEvents()
    assert bar.value() < bar.maximum(), "not pulled back to the end"
    bar.setValue(bar.maximum())
    window.resize(1200, 800)
    wait_until(lambda: at_end(view.detail))


def test_after_sending_it_is_at_the_end_again(window, api):
    view = open_chat(window)
    bar = view.detail.verticalScrollBar()
    bar.setValue(0)
    view.compose.setPlainText("Tot morgen")
    view.send_button.click()
    wait_until(lambda: view.confirmation is not None and view.confirmation.isVisible())
    view.confirmation.confirm_button.click()
    wait_until(lambda: view.notice.text() == "Sent.")
    wait_until(lambda: NEWEST in view.detail.toPlainText() and at_end(view.detail))
    assert len(api.sent_messages) == 1


def test_announcements_still_open_at_the_top(application):
    browser = SafeTextBrowser()
    browser.resize(400, 200)
    browser.show()
    browser.setHtml("".join(f"<p>Regel {n}</p>" for n in range(80)))
    QtWidgets.QApplication.processEvents()
    assert browser.verticalScrollBar().value() == 0
    browser.show_at_end("<p>kort</p>")
    QtWidgets.QApplication.processEvents()
    assert browser.verticalScrollBar().maximum() == 0, "a short chat needs no scrolling"
    dispose(browser)
