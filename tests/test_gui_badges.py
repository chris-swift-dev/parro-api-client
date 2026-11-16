# ruff: noqa: F811
# (the fixtures of test_gui_writes are imported, and named again as the tests' arguments)
"""Unread counts beside the sidebar's sections (docs/PLAN-0.14-additions.md §4)."""

import os
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from parro import operations
from parro_gui import badges, theme
from parro_gui import window as window_module
from parro_gui.window import SECTIONS
from tests.gui_helpers import wait_until
from tests.test_attachments import make_client as core_client
from tests.test_gui_writes import (  # noqa: F401
    ROOM,
    api,
    chat,
    environment,
    make_client,
    open_section,
    settle,
    window,
)


def counts(window: Any) -> dict[str, int]:
    rows = (window.sections.item(row) for row in range(window.sections.count()))
    return {name: badges.unread_of(item) for name, item in zip(SECTIONS, rows, strict=True)}


def unread_requests(api: Any) -> int:
    return len([r for r in api.api_requests() if "/identity/unreadcounts" in r.url])


def started(window: Any) -> None:
    """Until the counts are shown and the first section has loaded. The Overview asks Parro for
    the unread counts too, for its own text: a test that counts those requests must not start
    while that one is still on its way (it did on Windows, in CI)."""
    wait_until(lambda: counts(window)["Chats"] == 1)
    open_section(window, "Overview")
    settle()


# --------------------------------------------------------------------------- the counts


def test_the_totals_add_up_every_identity(tmp_path, api):
    client = core_client(tmp_path, api)
    assert operations.unread_totals(client) == {"announcements": 2, "calendar": 1, "chats": 1}

    sample = api.load_sample

    def twice(name: str) -> Any:
        answer = sample(name)
        if name == "getUnreadCounts.200.json":
            odd = {**answer["items"][0], "numberOfUnreadChatRooms": None}
            return {"items": [answer["items"][0], odd]}
        return answer

    api.load_sample = twice
    assert operations.unread_totals(client) == {"announcements": 4, "calendar": 2, "chats": 1}


@pytest.mark.parametrize(
    ("count", "text"), [(0, ""), (-1, ""), (1, "1"), (99, "99"), (100, "99+"), (12345, "99+")]
)
def test_the_badge_shows_the_number_and_nothing_for_zero(count, text):
    assert badges.badge_text(count) == text


# ----------------------------------------------------------------------- in the window


def test_the_three_sections_with_something_to_read_get_their_count(window, api):
    wait_until(lambda: counts(window)["Chats"] == 1)

    assert counts(window) == {
        "Overview": 0,
        "Announcements": 2,
        "Calendar": 1,
        "Chats": 1,
        "Family": 0,
        "Archive": 0,
    }
    item = window.sections.item(SECTIONS.index("Announcements"))
    assert item.data(Qt.ItemDataRole.AccessibleTextRole) == "Announcements, 2 unread"
    assert item.toolTip() == "2 unread"
    assert window.sections.item(0).data(Qt.ItemDataRole.AccessibleTextRole) == "Overview"
    assert api.writes() == [], "looking at the counts changes nothing"


def test_the_count_is_drawn_and_only_where_there_is_one(window):
    wait_until(lambda: counts(window)["Chats"] == 1)
    window.resize(900, 600)
    window.show()
    settle()
    picture = window.sections.grab().toImage()
    accent = QColor(theme.current_colours().accent)

    def has_badge(name: str) -> bool:
        area = window.sections.visualItemRect(window.sections.item(SECTIONS.index(name)))
        ratio = picture.devicePixelRatio()
        y = int(area.center().y() * ratio)
        xs = range(int((area.right() - 40) * ratio), int(area.right() * ratio))
        return any(picture.pixelColor(x, y) == accent for x in xs)

    assert has_badge("Calendar") and has_badge("Chats")
    assert not has_badge("Family") and not has_badge("Archive")


def test_the_counts_follow_what_you_mark_as_read(window, api, monkeypatch):
    monkeypatch.setattr(window_module, "UNREAD_PAUSE_SECONDS", 0.0)
    wait_until(lambda: counts(window)["Chats"] == 1)
    sample = api.load_sample

    def after_reading(name: str) -> Any:
        answer = sample(name)
        if name == "getUnreadCounts.200.json" and api.read_chats:
            return {"items": [{**answer["items"][0], "numberOfUnreadChatRooms": 0}]}
        return answer

    api.load_sample = after_reading
    window.confirmations.set_skipped(frozenset({"mark_read"}))
    view = chat(window)

    view.mark_button.click()
    wait_until(lambda: view.notice.text() == "Marked as read.")
    wait_until(lambda: counts(window)["Chats"] == 0)

    assert api.read_chats == {ROOM} and counts(window)["Announcements"] == 2
    assert window.sections.item(SECTIONS.index("Chats")).toolTip() == ""


def test_a_burst_of_loading_asks_for_the_counts_once(window, api):
    started(window)
    before = unread_requests(api)

    for _ in range(5):
        window.refresh_unread()
    for name in ("Announcements", "Calendar", "Chats"):
        open_section(window, name)  # until it has loaded: each load asks for the counts
        settle()

    assert unread_requests(api) == before, "not again within ten seconds"
    assert window.unread_timer.isActive() and window.unread_timer.interval() == 5 * 60_000


def test_logged_out_or_without_an_answer_the_badges_go(window, api):
    started(window)

    window.show_unread({})
    assert set(counts(window).values()) == {0}

    window.logged_in = False
    before = unread_requests(api)
    window._unread_asked_at = None
    window.refresh_unread()
    settle()
    assert unread_requests(api) == before, "not asked while logged out"
    window.show_unread({"chats": 3})
    assert counts(window)["Chats"] == 0, "and never shown while logged out"
