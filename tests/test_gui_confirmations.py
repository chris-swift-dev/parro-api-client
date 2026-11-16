# ruff: noqa: F811
# (the fixtures of test_gui_writes are imported, and named again as the tests' arguments)
"""Settings → Confirmations… (docs/PLAN-0.14-additions.md §3): a change without its question.

Skipping the question skips nothing else: the app still reads first and refuses what it refused,
sends once, and says what happened. An action that is not unticked still asks.
"""

import os
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QUrl

from parro_gui import app_file, confirmations
from parro_gui import widgets as gui_widgets
from parro_gui.confirmations import ACTIONS, Confirmations, ConfirmationsDialog
from parro_gui.views.base import LOADING, Section
from tests.gui_helpers import dispose, wait_until
from tests.test_gui_writes import (  # noqa: F401
    EVENT,
    ITEM,
    ROOM,
    TEXT,
    agenda_on_the_trip,
    api,
    chat,
    dialog_of,
    done_loading,
    environment,
    make_client,
    open_section,
    settle,
    window,
)

OWN_MESSAGE = 8100000002


@pytest.fixture
def no_questions(monkeypatch) -> list[str]:
    """Any yes/no question fails the test: with the setting off, none may come."""
    asked: list[str] = []

    def ask(_parent: Any, question: str) -> bool:
        asked.append(question)
        return False

    monkeypatch.setattr(gui_widgets, "ask", ask)
    return asked


def skip(window: Any, *actions: str) -> None:
    window.confirmations.set_skipped(frozenset(actions))


# ------------------------------------------------------------------------- the setting


def test_at_first_every_action_asks(tmp_path):
    assert Confirmations(tmp_path).skipped() == frozenset()
    assert Confirmations(None).skipped() == frozenset(), "no data folder: always ask"
    assert not Section.__dict__.get("confirmations"), "each section gets its own default"


def test_the_choice_is_kept_and_anything_odd_in_the_file_means_ask(tmp_path):
    kept = Confirmations(tmp_path)
    kept.set_skipped(frozenset({"send_chat", "mark_read", "not-an-action"}))
    assert Confirmations(tmp_path).skipped() == {"send_chat", "mark_read"}
    assert app_file.read_part(tmp_path, confirmations.PART) == ["mark_read", "send_chat"]

    kept.set_skipped(frozenset())
    assert app_file.read_part(tmp_path, confirmations.PART) is None, "nothing kept when all ask"
    for odd in ("send_chat", {"send_chat": True}, [1, None, "delete_everything"], True):
        app_file.write_part(tmp_path, confirmations.PART, odd)
        assert Confirmations(tmp_path).skipped() == frozenset(), odd


def test_the_dialog_has_a_tick_per_action_and_saves_only_on_save(application, tmp_path):
    kept = Confirmations(tmp_path)
    kept.set_skipped(frozenset({"rsvp"}))
    dialog = ConfirmationsDialog(kept)
    assert list(dialog.boxes) == [name for name, _label in ACTIONS]
    assert not dialog.boxes["rsvp"].isChecked(), "unticked: not asked"
    assert all(box.isChecked() for name, box in dialog.boxes.items() if name != "rsvp")

    dialog.boxes["send_chat"].setChecked(False)
    dialog.reject()
    assert kept.skipped() == {"rsvp"}, "Cancel keeps what was"

    again = ConfirmationsDialog(kept)
    again.boxes["send_chat"].setChecked(False)
    again.boxes["rsvp"].setChecked(True)
    again.accept()
    assert kept.skipped() == {"send_chat"}
    dispose(dialog)
    dispose(again)


def test_the_window_has_the_menu_and_every_section_shares_the_setting(window):
    titles = [action.text() for action in window.menuBar().actions()]
    assert titles == ["&Settings", "&Help"]
    window.confirmations_action.trigger()
    assert window.confirmations_dialog is not None and window.confirmations_dialog.isVisible()
    window.confirmations_dialog.reject()
    assert all(view.confirmations is window.confirmations for view in window.views.values())


# --------------------------------------------------------------- without the question


def test_a_message_is_sent_at_once_and_only_once(window, api):
    skip(window, "send_chat")
    view = chat(window)
    view.compose.setPlainText(TEXT)

    view.send_button.click()
    view.send_button.click()
    wait_until(lambda: view.notice.text() == "Sent.")

    assert api.sent_messages == [(ROOM, TEXT)], "one click, one message"
    assert view.confirmation is None and view.compose.toPlainText() == ""


def test_what_was_refused_before_is_still_refused(window, api):
    skip(window, "send_chat", "delete_chat")
    view = chat(window)
    view.compose.setPlainText("   ")

    view.send_button.click()
    wait_until(lambda: view.notice.text() == "Not sent: the message is empty.")
    assert api.writes() == [], "an empty message is refused before anything is sent"

    wait_until(lambda: "joined the chat" in view.detail.toPlainText())
    view.detail._follow(QUrl("parro-delete:8100000001"))  # the teacher's message
    wait_until(lambda: "wrote yourself" in view.notice.text())
    assert api.writes() == []


def test_an_unknown_outcome_is_said_in_the_message_line_and_not_tried_again(window, api):
    skip(window, "send_chat")
    api.send_outcomes = ["lost"]
    view = chat(window)
    view.compose.setPlainText(TEXT)

    view.send_button.click()
    wait_until(lambda: "may or may not" in view.notice.text())
    settle()

    assert len([w for w in api.writes() if w.startswith("POST")]) == 1
    assert view.compose.toPlainText() == TEXT, "your text is still there"


def test_a_message_of_your_own_is_deleted_at_once(window, api):
    skip(window, "delete_chat")
    view = chat(window)
    wait_until(lambda: "plek voor drie" in view.detail.toPlainText())

    view.detail._follow(QUrl(f"parro-delete:{OWN_MESSAGE}"))
    wait_until(lambda: view.notice.text() == "Deleted.")

    assert api.writes() == [f"DELETE /chatroom/{ROOM}/chatmessage/{OWN_MESSAGE}"]
    assert view.confirmation is None


def test_marking_as_read_asks_nothing(window, api, no_questions):
    skip(window, "mark_read")
    view = chat(window)

    view.mark_button.click()
    wait_until(lambda: view.notice.text() == "Marked as read.")

    assert api.writes() == [f"PUT /chatroom/{ROOM}/read"] and no_questions == []


def test_a_group_is_marked_at_once(window, api):
    skip(window, "mark_group_read")
    view = open_section(window, "Announcements")
    settle()
    for index in range(1, view.source.count() - 1):
        view.source.setCurrentIndex(index)
        done_loading(view)
        view.notice.clear()
        view.group_button.click()
        wait_until(lambda: view.notice.text() not in ("", "One moment…", LOADING))
        if api.writes():
            break
    group = view.source.currentData()

    assert api.writes() == [f"PUT /event/markannouncementsasread?group={group}"]
    assert view.confirmation is None, "counted first, then marked, without the dialog"


def test_an_answer_and_a_sign_up_go_at_once(window, api):
    skip(window, "rsvp", "helper")
    view = agenda_on_the_trip(window)

    view.action_bar.rsvp_buttons["ACCEPT"].click()
    wait_until(lambda: view.notice.text() == "Answered: Accept.")
    done_loading(view)
    assert api.rsvp_answers == {ITEM: "ACCEPT"} and view.confirmation is None


# ------------------------------------------------------------------- still asking


def test_an_action_that_is_not_unticked_still_asks(window, api, no_questions):
    skip(window, "send_chat")
    view = chat(window)

    view.mark_button.click()
    settle()
    assert len(no_questions) == 1 and api.writes() == [], "mark as read: asked, answered no"

    agenda = agenda_on_the_trip(window)
    agenda.action_bar.rsvp_buttons["ACCEPT"].click()
    dialog = dialog_of(agenda)
    assert api.writes() == [], "an answer still shows its dialog"
    dialog.cancel_button.click()
