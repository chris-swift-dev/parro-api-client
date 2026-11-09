"""The desktop app's reading views, against the fake API. Reading must never change anything."""

import base64
import copy
import json
import os
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from parro import operations  # noqa: E402
from parro.api_client import ParroClient  # noqa: E402
from parro.errors import NotLoggedIn, ParroError  # noqa: E402
from parro_gui import text as gui_text  # noqa: E402
from parro_gui import widgets as gui_widgets  # noqa: E402
from parro_gui.views.attachments import ReadingDialog  # noqa: E402
from parro_gui.views.base import EMPTY, LOADING, LOG_IN_FIRST  # noqa: E402
from parro_gui.views.chats import conversation_html  # noqa: E402
from parro_gui.views.overview import unread_line  # noqa: E402
from parro_gui.window import SECTIONS, MainWindow  # noqa: E402
from parro_gui.worker import LOG_IN_AGAIN  # noqa: E402
from tests import fakes  # noqa: E402
from tests.conftest import load_sample  # noqa: E402
from tests.gui_helpers import dispose, wait_until  # noqa: E402

BEFORE_THE_TRIP = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)
ROOM = 8000000001


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
    return path


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
    assert view.notice.text() in ("", EMPTY), view.notice.text()
    return view


def rows_of(view: Any) -> list[str]:
    return [view.list.item(i).text() for i in range(view.list.count())]


def settle() -> None:
    for _ in range(20):
        QApplication.processEvents()
        time.sleep(0.002)


# ----------------------------------------------------------------------------- safe text


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("<script>alert(1)</script>", "&lt;script&gt;alert(1)&lt;/script&gt;"),
        ('<img src="https://x.example/a.png">', "&lt;img src=&quot;"),
        ("een\ntwee", "een<br>twee"),
        ("javascript:alert(1)", "javascript:alert(1)"),
        ("[klik](https://evil.example)", '[klik](<a href="https://evil.example">'),
    ],
)
def test_text_from_others_is_only_text(source, expected):
    assert expected in gui_text.safe_html(source)


def test_only_addresses_written_out_become_links():
    html = gui_text.safe_html("Zie https://school.example/a?x=1&y=2. En file:///etc/passwd")
    assert '<a href="https://school.example/a?x=1&amp;y=2">' in html
    assert "</a>. En file:///etc/passwd" in html


def test_none_is_empty():
    assert gui_text.safe_html(None) == "" and gui_text.paragraph(None) == ""


def test_the_browser_loads_nothing_by_itself(application):
    browser = gui_widgets.SafeTextBrowser()
    assert browser.loadResource(2, QUrl("https://x.example/a.png")) is None
    assert browser.loadResource(2, QUrl("file:///etc/passwd")) is None
    assert not browser.openLinks() and not browser.openExternalLinks()


def following(monkeypatch, answer: bool) -> tuple[list[str], list[str]]:
    asked: list[str] = []
    opened: list[str] = []

    def fake_ask(_parent: Any, question: str) -> bool:
        asked.append(question)
        return answer

    monkeypatch.setattr(gui_widgets, "ask", fake_ask)

    def fake_open(address: str) -> bool:
        opened.append(address)
        return True

    monkeypatch.setattr(gui_widgets, "open_url", fake_open)
    return asked, opened


def test_a_link_shows_the_address_before_opening(application, monkeypatch):
    asked, opened = following(monkeypatch, True)
    gui_widgets.SafeTextBrowser()._follow(QUrl("https://school.example/a"))
    assert "https://school.example/a" in asked[0] and opened == ["https://school.example/a"]


def test_saying_no_opens_nothing(application, monkeypatch):
    _asked, opened = following(monkeypatch, False)
    gui_widgets.SafeTextBrowser()._follow(QUrl("https://school.example/a"))
    assert opened == []


@pytest.mark.parametrize("address", ["file:///etc/passwd", "javascript:alert(1)", "smb://x/y"])
def test_other_kinds_of_link_never_open(application, monkeypatch, address):
    asked, opened = following(monkeypatch, True)
    gui_widgets.SafeTextBrowser()._follow(QUrl(address))
    assert asked == [] and opened == []


# ------------------------------------------------------------------------------- sections


def test_the_first_section_loads_after_login(window):
    view = window.views["Overview"]
    wait_until(lambda: view.loaded and view.notice.text() != LOADING)
    assert view.list.count() > 0


def test_a_section_loads_only_when_opened(window, api):
    wait_until(lambda: window.views["Overview"].notice.text() != LOADING)
    assert not window.views["Family"].loaded


def test_overview_shows_counts_and_what_is_new(window):
    view = open_section(window, "Overview")
    assert view.counts.text() == unread_line([{"announcements": 2, "calendar": 1, "chats": 1}])
    assert len(rows_of(view)) == 4


def test_overview_can_show_everything(window):
    view = open_section(window, "Overview")
    unread_rows = view.list.count()
    view.everything.setChecked(True)
    wait_until(lambda: view.notice.text() != LOADING and view.list.count() > unread_rows)


def test_announcements_list_and_detail(window):
    view = open_section(window, "Announcements")
    assert any("●" in row for row in rows_of(view))
    wait_until(lambda: "Beste ouders" in view.detail.toPlainText())


def test_groups_appear_in_the_filter_once(window):
    view = open_section(window, "Announcements")
    count = view.source.count()
    assert count > 2
    view.load()
    wait_until(lambda: view.notice.text() != LOADING)
    assert view.source.count() == count


def test_news_from_parro_has_no_html_left(window):
    view = open_section(window, "Announcements")
    view.source.setCurrentIndex(view.source.count() - 1)
    view.load()
    wait_until(lambda: view.notice.text() != LOADING and view.list.count() > 0)
    assert "<p>" not in view.detail.toPlainText()
    assert "donkere modus" in view.detail.toPlainText()


def test_unread_only_filters(window):
    view = open_section(window, "Announcements")
    everything = view.list.count()
    view.unread_only.setChecked(True)
    wait_until(lambda: view.notice.text() != LOADING and view.list.count() < everything)
    assert all("●" in row for row in rows_of(view))


def test_calendar_shows_your_answer_and_details(window, api):
    api.rsvp_answers[fakes.MUSEUM_TRIP_CALENDAR_ITEM] = "ACCEPT"
    view = open_section(window, "Calendar")
    row = next(i for i, text in enumerate(rows_of(view)) if "Natuurmuseum" in text)
    assert "RSVP: accepted" in rows_of(view)[row]
    view.list.setCurrentRow(row)
    settle()
    assert "Natuurmuseum Voorbeeldstad" in view.detail.toPlainText()
    assert "signed up" in view.detail.toPlainText()


def test_chats_show_a_conversation_oldest_first(window):
    view = open_section(window, "Chats")
    wait_until(lambda: "Tot de 12e" in view.detail.toPlainText())
    text = view.detail.toPlainText()
    assert "Tom Smit" in text
    assert text.rindex("Tot de 12e") > len(text) / 2, "the newest message comes last"


def test_a_deleted_message_says_so():
    html = conversation_html(
        {"title": "Chat"},
        {"messages": [{"deleted": True, "text": "weg", "createdAt": "2026-11-03T16:00:00+01:00"}]},
        {"members": []},
    )
    assert "(message deleted)" in html and "weg" not in html


def test_a_chat_message_cannot_inject_markup():
    html = conversation_html(
        {"title": "<b>x</b>"},
        {"messages": [{"text": "<img src=https://evil.example/a>", "createdAt": "2026"}]},
        {"members": []},
    )
    assert "<img" not in html and "<b>x" not in html


def test_family_shows_children_groups_and_privacy(window):
    view = open_section(window, "Family")
    wait_until(lambda: "Mila de Vries" in view.page.toPlainText())
    text = view.page.toPlainText()
    assert "Sanne de Vries" in text and "Basisschool De Linde" in text
    assert "can be changed now" in text


def test_reading_everything_changes_nothing(window, api):
    for name in window.views:
        view = open_section(window, name)
        if hasattr(view, "list"):
            for row in range(view.list.count()):
                view.list.setCurrentRow(row)
                settle()
    assert api.writes() == [], "nothing is marked as read by opening it"
    assert api.idp.credential_posts() == []


def test_nothing_reads_the_list_of_respondents(window, api):
    for name in window.views:
        open_section(window, name)
    settle()
    assert [r for r in api.api_requests() if "calendaritemrsvp" in r.url] == []


# ------------------------------------------------------------------------- loading and errors


def test_an_old_answer_is_dropped(window):
    view = open_section(window, "Family")
    shown: list[Any] = []
    view.show_result = shown.append
    view.load()
    view.load()
    wait_until(lambda: len(shown) >= 1)
    settle()
    assert len(shown) == 1, "only the newest request counts"


def test_an_error_is_shown_in_the_section(window, monkeypatch):
    view = window.views["Family"]

    def broken(_client: ParroClient) -> Any:
        raise ParroError("Parro did not answer.")

    monkeypatch.setattr(operations, "show_account", broken)
    window.sections.setCurrentRow(SECTIONS.index("Family"))
    wait_until(lambda: view.notice.text() == "Parro did not answer.")


def test_a_lost_login_points_to_the_button_not_the_cli(window, monkeypatch):
    view = window.views["Family"]

    def lost(_client: ParroClient) -> Any:
        raise NotLoggedIn("Run `parro-client login`.")

    monkeypatch.setattr(operations, "show_account", lost)
    window.sections.setCurrentRow(SECTIONS.index("Family"))
    wait_until(lambda: view.notice.text() == LOG_IN_AGAIN)


def test_without_a_login_nothing_is_fetched(application, make_client, api, environment):
    environment.unlink()
    window = MainWindow(make_client)
    wait_until(lambda: window.login_dialog is not None)
    assert window.views["Overview"].notice.text() == LOG_IN_FIRST
    window.sections.setCurrentRow(SECTIONS.index("Chats"))
    settle()
    assert not window.views["Chats"].loaded and api.api_requests() == []
    dispose(window)


# ---------------------------------------------------------------------------- attachments


@pytest.fixture
def newsletter(api) -> dict[str, Any]:
    sample = copy.deepcopy(load_sample("getEvent_announcement.200.json"))
    entry = sample["attachments"][0]["entries"][0]
    entry["contentType"] = "text/plain"

    def with_text_newsletter(name: str) -> Any:
        return sample if name == "getEvent_announcement.200.json" else load_sample(name)

    api.load_sample = with_text_newsletter
    api.attachment_bodies[entry["url"]] = ("text/plain", b"Beste ouders, dit is de nieuwsbrief.")
    return {"url": entry["url"]}


def bar(window: MainWindow) -> Any:
    view = open_section(window, "Announcements")
    row = next(i for i, text in enumerate(rows_of(view)) if "Nieuwsbrief" in text)
    view.list.setCurrentRow(row)
    wait_until(lambda: bool(view.attachments.read_buttons))
    return view.attachments


def test_an_attachment_can_be_read(window, newsletter):
    attachments = bar(window)
    attachments.read_buttons[0].click()
    wait_until(lambda: attachments.dialog is not None)
    assert "dit is de nieuwsbrief" in attachments.dialog.text.toPlainText()


def test_the_download_address_is_not_shown(window, newsletter):
    attachments = bar(window)
    labels = [label.text() for label in attachments.findChildren(QtWidgets.QLabel)]
    assert not any(newsletter["url"] in text for text in labels)
    assert labels and "Nieuwsbrief" in labels[0]


def test_a_photo_is_shown_as_a_picture(application):
    png = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5E"
        "rkJggg=="
    )
    report = type(
        "Report",
        (),
        {
            "summary": {"filename": "a.png"},
            "images": [type("Image", (), {"base64_data": png, "mime_type": "image/png"})()],
        },
    )()
    assert base64.b64decode(png)
    dialog = ReadingDialog(report)
    assert not dialog.picture.pixmap().isNull()


def test_saving_writes_the_file_to_the_chosen_folder(window, newsletter, tmp_path, monkeypatch):
    target = tmp_path / "bewaard"
    target.mkdir()
    monkeypatch.setattr(gui_widgets, "choose_folder", lambda _parent: str(target))
    attachments = bar(window)
    attachments.save_buttons[0].click()
    wait_until(lambda: any(Path(target).iterdir()))
    view = window.views["Announcements"]
    wait_until(lambda: "Saved in" in view.notice.text())


def test_cancelling_the_folder_saves_nothing(window, newsletter, api, monkeypatch):
    monkeypatch.setattr(gui_widgets, "choose_folder", lambda _parent: "")
    attachments = bar(window)
    before = len(api.requests)
    attachments.save_buttons[0].click()
    settle()
    assert len(api.requests) == before
