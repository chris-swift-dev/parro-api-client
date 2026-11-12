"""A quick second click does nothing: every button that starts a request stays off until the answer
is in, and a section runs one action at a time. Before this, two clicks on Send… opened two
previews, and confirming both sent the message twice."""

# ruff: noqa: F811 (the fixtures of test_gui_writes are imported and then requested by name)

import time
from typing import Any

import pytest

from tests.test_gui_writes import (  # noqa: F401 (fixtures)
    TEXT,
    agenda_on_the_trip,
    api,
    asked,
    chat,
    environment,
    make_client,
    open_section,
    settle,
    window,
)

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from parro_gui import widgets as gui_widgets  # noqa: E402
from parro_gui.views.confirm import ConfirmDialog  # noqa: E402
from tests.gui_helpers import wait_until  # noqa: E402
from tests.test_gui_views import newsletter  # noqa: E402, F401 (a fixture)


def previews(view: Any) -> list[ConfirmDialog]:
    return [dialog for dialog in view.findChildren(ConfirmDialog) if dialog.isVisible()]


def let_it_finish() -> None:
    time.sleep(0.1)
    settle()


def test_two_clicks_on_send_open_one_preview_and_send_once(window, api):
    view = chat(window)
    view.compose.setPlainText(TEXT)
    view.send_button.click()
    assert not view.send_button.isEnabled(), "off while the preview is prepared"
    view.send_button.click()
    wait_until(lambda: len(previews(view)) == 1)
    let_it_finish()
    assert len(previews(view)) == 1
    dialog = previews(view)[0]
    dialog.confirm_button.click()
    wait_until(lambda: not dialog.isVisible())
    let_it_finish()
    assert len(api.sent_messages) == 1


def test_two_answers_in_a_row_open_one_preview(window):
    view = agenda_on_the_trip(window)
    view.action_bar.rsvp_buttons["DECLINE"].click()
    view.action_bar.rsvp_buttons["TENTATIVE"].click()  # another action of the same section
    wait_until(lambda: len(previews(view)) == 1)
    let_it_finish()
    assert len(previews(view)) == 1


def test_two_clicks_on_sign_up_open_one_preview(window):
    view = agenda_on_the_trip(window)
    _count, signup, _withdraw = view.action_bar.slot_rows[0]
    signup.click()
    signup.click()
    wait_until(lambda: len(previews(view)) == 1)
    let_it_finish()
    assert len(previews(view)) == 1


def test_mark_as_read_asks_once(window, api, asked):
    view = open_section(window, "Announcements")
    settle()
    view.mark_button.click()
    assert not view.mark_button.isEnabled()
    view.mark_button.click()
    wait_until(lambda: view.notice.text() == "Marked as read.")
    assert len(asked) == 1 and len(api.writes()) == 1


def test_mark_as_read_is_on_again_after_a_failure(window, api, asked, monkeypatch):
    from parro import operations
    from parro.errors import ParroError

    def broken(*_args: Any) -> Any:
        raise ParroError("Parro did not answer.")

    monkeypatch.setattr(operations, "mark_read", broken)
    view = open_section(window, "Announcements")
    settle()
    view.mark_button.click()
    wait_until(lambda: view.notice.text() == "Parro did not answer.")
    assert view.mark_button.isEnabled(), "a failure leaves it on, to try again"


def test_refresh_is_off_while_it_loads(window, api):
    view = open_section(window, "Announcements")
    count = len(api.api_requests())
    view.refresh_button.click()
    assert not view.refresh_button.isEnabled()
    view.refresh_button.click()
    view.refresh_button.click()
    wait_until(view.refresh_button.isEnabled)
    one_load = len(api.api_requests()) - count
    view.refresh_button.click()
    wait_until(view.refresh_button.isEnabled)
    assert len(api.api_requests()) - count == 2 * one_load, "three clicks were one load"


def test_the_subscription_link_opens_once(window, monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(gui_widgets, "ask", lambda *_args: True)
    monkeypatch.setattr(
        "parro_gui.views.agenda.show_secret", lambda _parent, title, *_rest: shown.append(title)
    )
    view = open_section(window, "Calendar")
    view.link_button.click()
    view.link_button.click()
    wait_until(lambda: bool(shown))
    let_it_finish()
    assert len(shown) == 1 and view.link_button.isEnabled()


def test_an_attachment_opens_once(window, api, newsletter):
    view = open_section(window, "Announcements")
    row = next(i for i in range(view.list.count()) if "Nieuwsbrief" in view.list.item(i).text())
    view.list.setCurrentRow(row)
    wait_until(lambda: bool(view.attachments.read_buttons))
    button = view.attachments.read_buttons[0]
    count = len(api.requests)
    button.click()
    assert not button.isEnabled()
    button.click()
    wait_until(button.isEnabled)
    downloads = [r for r in api.requests[count:] if r.url == newsletter["url"]]
    assert len(downloads) == 1
