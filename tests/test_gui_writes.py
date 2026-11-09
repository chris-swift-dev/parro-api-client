"""Changing things from the desktop app, against the fake API.

These are mostly about when nothing happens: a change needs a deliberate click on Confirm.
"""

import json
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication  # noqa: E402

from parro import operations  # noqa: E402
from parro.api_client import ParroClient  # noqa: E402
from parro_gui import widgets as gui_widgets  # noqa: E402
from parro_gui.views.base import LOADING  # noqa: E402
from parro_gui.window import SECTIONS, MainWindow  # noqa: E402
from tests import fakes  # noqa: E402
from tests.conftest import load_sample  # noqa: E402
from tests.gui_helpers import wait_until  # noqa: E402

BEFORE_THE_TRIP = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)
AFTER_THE_TRIP = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
ROOM = 8000000001
ITEM = fakes.MUSEUM_TRIP_CALENDAR_ITEM
SLOT = fakes.MUSEUM_TRIP_SLOT
EVENT = fakes.MUSEUM_TRIP_ID
TEXT = "Ik kan rijden op de 12e"


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
    created.close()


@pytest.fixture
def asked(monkeypatch) -> list[str]:
    questions: list[str] = []

    def yes(_parent: Any, question: str) -> bool:
        questions.append(question)
        return True

    monkeypatch.setattr(gui_widgets, "ask", yes)
    return questions


def open_section(window: MainWindow, name: str) -> Any:
    view = window.views[name]
    window.sections.setCurrentRow(SECTIONS.index(name))
    wait_until(lambda: view.loaded and view.notice.text() != LOADING)
    return view


def settle() -> None:
    for _ in range(30):
        QApplication.processEvents()
        time.sleep(0.002)


def done_loading(view: Any) -> None:
    wait_until(lambda: view.notice.text() != LOADING)
    settle()


def dialog_of(view: Any) -> Any:
    wait_until(lambda: view.confirmation is not None and view.confirmation.isVisible())
    return view.confirmation


def agenda_on_the_trip(window: MainWindow) -> Any:
    view = open_section(window, "Calendar")
    row = next(i for i in range(view.list.count()) if "Natuurmuseum" in view.list.item(i).text())
    view.list.setCurrentRow(row)
    settle()
    return view


def chat(window: MainWindow) -> Any:
    view = open_section(window, "Chats")
    wait_until(lambda: view.send_button.isEnabled())
    return view


# ------------------------------------------------------------------------- the dialog itself


def preparing_message(window: MainWindow, text: str = TEXT) -> Any:
    view = chat(window)
    view.compose.setPlainText(text)
    view.send_button.click()
    return view, dialog_of(view)


def test_enter_does_not_confirm(window):
    _view, dialog = preparing_message(window)
    assert not dialog.confirm_button.isDefault() and not dialog.confirm_button.autoDefault()
    assert dialog.cancel_button.isDefault()


def test_cancel_writes_nothing(window, api):
    view, dialog = preparing_message(window)
    dialog.cancel_button.click()
    settle()
    assert api.writes() == [] and not dialog.isVisible()
    assert view.compose.toPlainText() == TEXT, "your text is still there"


# ----------------------------------------------------------------------------------- sending


def test_the_preview_shows_who_and_what(window, api):
    _view, dialog = preparing_message(window)
    text = dialog.preview.toPlainText()
    assert "Tom Smit" in text and TEXT in text and "cannot be taken back" in text
    assert api.writes() == [] and api.sent_messages == []


def test_confirm_sends_once(window, api):
    view, dialog = preparing_message(window)
    dialog.confirm_button.click()
    dialog.confirm_button.click()
    wait_until(lambda: not dialog.isVisible())
    done_loading(view)
    assert api.sent_messages == [(ROOM, TEXT)] and api.writes() == [
        f"POST /chatroom/{ROOM}/chatmessage"
    ]
    assert view.compose.toPlainText() == "" and view.notice.text() == "Sent."


def test_an_unknown_outcome_offers_no_retry(window, api):
    api.send_outcomes = ["lost"]
    view, dialog = preparing_message(window)
    dialog.confirm_button.click()
    wait_until(lambda: "may or may not" in dialog.message.text())
    assert not dialog.confirm_button.isEnabled() and dialog.cancel_button.text() == "Close"
    settle()
    assert len(api.writes()) == 1
    dialog.cancel_button.click()
    assert view.compose.toPlainText() == TEXT, "kept, so you can check before trying again"


def test_empty_text_is_refused_before_any_dialog(window, api):
    view = chat(window)
    view.compose.setPlainText("   ")
    view.send_button.click()
    wait_until(lambda: view.notice.text() != "")
    assert view.confirmation is None and api.writes() == []


def test_a_closed_chat_is_refused(window, api):
    api.room_overrides = {"archived": True}
    view = chat(window)
    view.compose.setPlainText(TEXT)
    view.send_button.click()
    wait_until(lambda: "Not sent" in view.notice.text())
    assert view.confirmation is None and api.writes() == []


def test_the_text_is_never_logged(window, caplog):
    secret = "Geheime tekst 8f3a"
    with caplog.at_level(logging.DEBUG):
        view, dialog = preparing_message(window, secret)
        dialog.confirm_button.click()
        wait_until(lambda: not dialog.isVisible())
        done_loading(view)
    assert secret not in caplog.text


# ------------------------------------------------------------------------------ marking read


def test_opening_never_marks_as_read(window, api):
    for name in ("Announcements", "Calendar", "Chats"):
        open_section(window, name)
        settle()
    assert api.writes() == []


def test_marking_asks_first_and_saying_no_marks_nothing(window, api, monkeypatch):
    monkeypatch.setattr(gui_widgets, "ask", lambda _parent, _question: False)
    view = open_section(window, "Announcements")
    settle()
    view.mark_button.click()
    settle()
    assert api.writes() == []


def test_marking_an_announcement(window, api, asked):
    view = open_section(window, "Announcements")
    settle()
    wanted = view.items[view.list.currentRow()]["announcement"]["id"]
    assert view.mark_button.isEnabled()
    view.mark_button.click()
    wait_until(lambda: view.notice.text() == "Marked as read.")
    assert api.writes() == [f"PUT /event/{wanted}/read"]
    assert "school can see" in asked[0]


def test_marking_a_chat(window, api, asked):
    view = chat(window)
    view.mark_button.click()
    wait_until(lambda: view.notice.text() == "Marked as read.")
    assert api.writes() == [f"PUT /chatroom/{ROOM}/read"]


def test_marking_a_calendar_item(window, api, asked):
    view = open_section(window, "Calendar")
    settle()
    row = next(i for i, item in enumerate(view.items) if item.get("read") is False)
    view.list.setCurrentRow(row)
    settle()
    wanted = view.items[row]["id"]
    view.mark_button.click()
    wait_until(lambda: view.notice.text() == "Marked as read.")
    assert api.writes() == [f"PUT /event/{wanted}/read"]


def test_a_read_item_has_nothing_to_mark(window):
    view = open_section(window, "Calendar")
    settle()
    row = next(i for i, item in enumerate(view.items) if item.get("read") is True)
    view.list.setCurrentRow(row)
    settle()
    assert not view.mark_button.isEnabled()


def group_with_unread(window: MainWindow) -> Any:
    view = open_section(window, "Announcements")
    settle()
    for index in range(1, view.source.count() - 1):
        view.source.setCurrentIndex(index)
        view.notice.clear()
        view.group_button.click()
        wait_until(lambda: view.confirmation is not None or view.notice.text() != "")
        if view.confirmation is not None:
            return view, view.source.currentData()
    raise AssertionError("no group with unread announcements in the fixtures")


def test_a_group_shows_the_count_first(window, api):
    view, _group = group_with_unread(window)
    assert "as read" in dialog_of(view).preview.toPlainText()
    assert api.writes() == []


def test_a_group_is_marked_only_on_confirm(window, api):
    view, group = group_with_unread(window)
    dialog = dialog_of(view)
    dialog.confirm_button.click()
    wait_until(lambda: not dialog.isVisible())
    assert api.writes() == [f"PUT /event/markannouncementsasread?group={group}"]


def test_all_groups_cannot_be_marked(window):
    view = open_section(window, "Announcements")
    view.source.setCurrentIndex(0)
    assert not view.group_button.isEnabled()


# ------------------------------------------------------------------------------------ helpers


def test_a_slot_needs_confirm(window, api):
    view = agenda_on_the_trip(window)
    _count, signup, _withdraw = view.action_bar.slot_rows[0]
    signup.click()
    dialog = dialog_of(view)
    assert "promise" in dialog.preview.toPlainText() and "1 of 2" in dialog.preview.toPlainText()
    assert api.writes() == []
    dialog.confirm_button.click()
    wait_until(lambda: not dialog.isVisible())
    done_loading(view)
    assert api.writes() == [f"POST /calendaritem/{ITEM}/resource/{SLOT}/commitment/"]
    assert view.notice.text() == "Signed up."


def test_the_count_reaches_the_request(window, api):
    api.calendar_item_overrides = {
        "resources": [
            {
                "dtype": "calendar.RCalendarItemVolunteerResource",
                "links": [{"id": SLOT, "rel": "self", "type": "x"}],
                "title": "Kinderen meenemen",
                "type": "VOLUNTEER",
                "amount": 8,
                "amountCommitted": 2,
                "commitedByMe": 0,
                "commitments": [],
            }
        ]
    }
    view = agenda_on_the_trip(window)
    count, signup, _withdraw = view.action_bar.slot_rows[0]
    count.setValue(3)
    signup.click()
    dialog = dialog_of(view)
    assert "Your count: 3" in dialog.preview.toPlainText()
    dialog.confirm_button.click()
    wait_until(lambda: not dialog.isVisible())
    assert api.commitments[SLOT][0]["amount"] == 3


def test_a_count_that_does_not_fit_is_refused(window, api):
    view = agenda_on_the_trip(window)
    count, signup, _withdraw = view.action_bar.slot_rows[0]
    count.setValue(2)
    signup.click()
    wait_until(lambda: "places are left" in view.notice.text())
    assert view.confirmation is None and api.writes() == []


def test_withdraw_is_only_possible_where_you_signed_up(window, api):
    view = agenda_on_the_trip(window)
    _count, signup, withdraw = view.action_bar.slot_rows[0]
    assert signup.isEnabled() and not withdraw.isEnabled()


def test_withdrawing(window, api):
    api.commitments[SLOT] = [{"id": 8500000099, "amount": 1}]
    view = agenda_on_the_trip(window)
    _count, signup, withdraw = view.action_bar.slot_rows[0]
    assert withdraw.isEnabled() and not signup.isEnabled()
    withdraw.click()
    dialog = dialog_of(view)
    assert "Your place becomes free" in dialog.preview.toPlainText()
    dialog.confirm_button.click()
    wait_until(lambda: not dialog.isVisible())
    assert api.commitments[SLOT] == []


def test_a_past_item_is_refused(window, api, monkeypatch):
    view = agenda_on_the_trip(window)
    monkeypatch.setattr(operations, "current_time", lambda: AFTER_THE_TRIP)
    view.action_bar.slot_rows[0][1].click()
    wait_until(lambda: "in the past" in view.notice.text())
    assert api.writes() == []


# ---------------------------------------------------------------------------------- answering


def test_an_answer_needs_confirm_and_shows_both(window, api):
    api.rsvp_answers[ITEM] = "ACCEPT"
    view = agenda_on_the_trip(window)
    view.action_bar.rsvp_buttons["DECLINE"].click()
    dialog = dialog_of(view)
    text = dialog.preview.toPlainText()
    assert "Your answer now: Accept" in text and "New answer: Decline" in text
    assert "not remove it" in text and api.writes() == []
    dialog.confirm_button.click()
    wait_until(lambda: not dialog.isVisible())
    done_loading(view)
    assert api.rsvp_answers == {ITEM: "DECLINE"}
    assert api.writes() == [f"POST /calendaritem/{ITEM}/calendaritemrsvp"]
    assert view.notice.text() == "Answered: Decline."


def test_the_same_answer_sends_and_asks_nothing(window, api):
    api.rsvp_answers[ITEM] = "ACCEPT"
    view = agenda_on_the_trip(window)
    view.action_bar.rsvp_buttons["ACCEPT"].click()
    wait_until(lambda: view.notice.text() == "Already answered: Accept.")
    assert view.confirmation is None and api.writes() == []


def test_an_item_that_asks_nothing_has_no_answer_buttons(window):
    view = open_section(window, "Calendar")
    settle()
    row = next(
        i for i, item in enumerate(view.items) if not item["calendarItem"].get("rsvpRequired")
    )
    view.list.setCurrentRow(row)
    settle()
    assert view.action_bar.rsvp_buttons == {}


def test_an_unknown_outcome_of_an_answer_offers_no_retry(window, api):
    api.send_outcomes = ["lost"]
    view = agenda_on_the_trip(window)
    view.action_bar.rsvp_buttons["ACCEPT"].click()
    dialog = dialog_of(view)
    dialog.confirm_button.click()
    wait_until(lambda: "may or may not" in dialog.message.text())
    assert not dialog.confirm_button.isEnabled() and len(api.writes()) == 1


def test_after_a_change_the_same_item_stays_chosen(window, api):
    view = agenda_on_the_trip(window)
    row = view.list.currentRow()
    view.action_bar.rsvp_buttons["TENTATIVE"].click()
    dialog = dialog_of(view)
    dialog.confirm_button.click()
    wait_until(lambda: not dialog.isVisible())
    done_loading(view)
    assert view.list.currentRow() == row
    assert "RSVP: tentative" in view.list.item(row).text()


# --------------------------------------------------------------------------------- the filter


def test_the_calendar_can_be_filtered_by_group(window, api):
    view = open_section(window, "Calendar")
    settle()
    assert view.group.count() > 1
    view.group.setCurrentIndex(1)
    before = len(api.requests)
    view.load()
    done_loading(view)
    assert len(api.requests) > before
