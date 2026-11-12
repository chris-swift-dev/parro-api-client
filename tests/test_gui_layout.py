"""The detail side of Announcements and Calendar fits in the window, however much an item holds.

Invented items, shown offscreen in a window of the default size: the text and the lower panel
share the height, both scroll, and the action row (Mark as read) stays inside the window.
"""

import json
import os
import time
from collections.abc import Callable
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from parro.api_client import ParroClient  # noqa: E402
from parro_gui.views.base import LOADING  # noqa: E402
from parro_gui.window import SECTIONS, MainWindow  # noqa: E402
from tests import fakes  # noqa: E402
from tests.conftest import load_sample  # noqa: E402
from tests.gui_helpers import dispose, wait_until  # noqa: E402

WIDTH, HEIGHT = 1000, 680
LONG_TEXT = "\n\n".join(f"Paragraph {n}: bring a packed lunch and a raincoat." for n in range(80))


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
def window(application) -> Any:
    api = fakes.FakeParroApi(load_sample)
    make_client: Callable[[Any], ParroClient] = lambda s: ParroClient(s, transport=api)  # noqa: E731
    created = MainWindow(make_client)
    created.resize(WIDTH, HEIGHT)
    created.show()
    wait_until(lambda: created.logged_in)
    yield created
    dispose(created)


def settle() -> None:
    for _ in range(30):
        QApplication.processEvents()
        time.sleep(0.002)


def attachments(count: int) -> list[dict[str, Any]]:
    return [
        {"attachment_id": 100 + n, "filename": f"worksheet-{n}.pdf", "size": 20_000 + n}
        for n in range(count)
    ]


def calendar_item(attachment_count: int, slot_count: int) -> dict[str, Any]:
    slots = [
        {"id": 200 + n, "title": f"Helper task {n}", "wanted": 2, "signed_up": 0}
        for n in range(slot_count)
    ]
    return {
        "id": 9000,
        "read": False,
        "calendarItem": {
            "title": "Sports day",
            "startDate": "2026-11-20T09:00:00+01:00",
            "rsvpRequired": True,
        },
        "details": {
            "description": LONG_TEXT,
            "helpers": slots,
            "attachments": attachments(attachment_count),
        },
    }


def show(window: MainWindow, name: str) -> Any:
    view = window.views[name]
    window.sections.setCurrentRow(SECTIONS.index(name))
    wait_until(lambda: view.loaded and view.notice.text() != LOADING)
    settle()
    return view


def in_window(window: MainWindow, widget: QWidget) -> bool:
    corner = widget.mapTo(window, QPoint(0, 0))
    return window.rect().contains(QRect(corner, widget.size()))


def assert_fits(window: MainWindow, view: Any) -> None:
    assert view.mark_button.isVisible()
    assert in_window(window, view.mark_button), "Mark as read can be reached"
    assert in_window(window, view.lower_part), "nothing falls off the bottom"
    assert view.minimumSizeHint().height() <= window.pages.height(), "never taller than the window"
    text, lower = view.detail_splitter.sizes()
    assert lower <= (text + lower) // 2 + 1, "the lower part takes at most half"


def test_a_full_calendar_item_fits(window):
    view = show(window, "Calendar")
    view.show_item(calendar_item(attachment_count=30, slot_count=10))
    settle()
    assert_fits(window, view)
    assert len(view.attachments.read_buttons) == 30 and len(view.action_bar.slot_rows) == 10
    assert view.panel.verticalScrollBar().maximum() > 0, "the panel scrolls"
    assert view.detail.verticalScrollBar().maximum() > 0, "the text scrolls"
    assert view.detail.height() >= view.detail.minimumHeight()


def test_the_action_row_sits_above_the_panel(window):
    view = show(window, "Calendar")
    view.show_item(calendar_item(attachment_count=30, slot_count=10))
    settle()
    button = view.mark_button.mapTo(view, QPoint(0, 0)).y()
    assert button < view.panel.mapTo(view, QPoint(0, 0)).y()
    assert button > view.detail.mapTo(view, QPoint(0, 0)).y()


def test_a_small_item_gets_what_it_needs(window):
    view = show(window, "Calendar")
    view.show_item(calendar_item(attachment_count=1, slot_count=0))
    settle()
    assert_fits(window, view)
    assert view.panel.verticalScrollBar().maximum() == 0, "one attachment needs no scrolling"
    _text, lower = view.detail_splitter.sizes()
    assert lower < view.detail_splitter.height() // 2


def test_without_attachments_only_the_action_row_is_left(window):
    view = show(window, "Announcements")
    view._show_full({"id": 1, "title": "No files", "contents": LONG_TEXT, "attachments": []})
    settle()
    assert view.panel.isHidden()
    assert in_window(window, view.mark_button)
    _text, lower = view.detail_splitter.sizes()
    assert lower <= view.action_row.sizeHint().height() + 1


def test_many_announcement_attachments_fit(window):
    view = show(window, "Announcements")
    full = {"id": 1, "title": "Many files", "contents": LONG_TEXT, "attachments": attachments(30)}
    view._show_full(full)
    settle()
    assert_fits(window, view)
    assert view.panel.verticalScrollBar().maximum() > 0


def test_a_dragged_splitter_stays_until_the_next_item(window):
    view = show(window, "Calendar")
    view.show_item(calendar_item(attachment_count=30, slot_count=10))
    settle()
    total = sum(view.detail_splitter.sizes())
    view.detail_splitter.setSizes([total - 300, 300])
    view._dragged(0, 1)
    window.resize(WIDTH + 40, HEIGHT + 20)
    settle()
    assert abs(view.detail_splitter.sizes()[1] - 300) <= 25, "a resize keeps what you chose"
    view.show_item(calendar_item(attachment_count=2, slot_count=0))
    settle()
    assert not view._user_dragged, "other content: it gets the height it needs again"
    assert view.detail_splitter.sizes()[1] == view.lower_height_needed() < 300
