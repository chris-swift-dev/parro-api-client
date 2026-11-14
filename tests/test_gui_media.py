"""0.13 in the desktop app: the chat layout, thumbnails, opening a file, the calendar's link.

Text and file names from other people must stay text; the only pictures are those the app
fetched itself; a click on a file names a message, never an address.
"""

import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QImage, QTextDocument  # noqa: E402

from parro import attachments, operations, summaries  # noqa: E402
from parro.api_client import ParroClient  # noqa: E402
from parro_gui import text as gui_text  # noqa: E402
from parro_gui import theme  # noqa: E402
from parro_gui import widgets as gui_widgets  # noqa: E402
from parro_gui.views import attachments as attachment_views  # noqa: E402
from parro_gui.views.agenda import agenda_html  # noqa: E402
from parro_gui.views.conversation import (  # noqa: E402
    Conversation,
    attachment_link,
    fitted,
    messages_html,
    thumbnail_name,
)
from parro_gui.window import SECTIONS, MainWindow  # noqa: E402
from tests import fakes  # noqa: E402
from tests.conftest import load_sample  # noqa: E402
from tests.gui_helpers import dispose, wait_until  # noqa: E402

ME, TOM = 2000000001, 3000000002
VIDEO_MESSAGE, PHOTO_MESSAGE = 8100000000, 8099999999
VIDEO_ATTACHMENT, PHOTO_ATTACHMENT = 8200000020, 8200000010


def jpeg(width: int = 30, height: int = 40) -> bytes:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#5a8f7b"))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "JPG")  # type: ignore[call-overload]  # PySide takes the name as text
    return bytes(data.data())


def text_message(message_id: int, author: int, when: str, text: str) -> dict[str, Any]:
    identity = {"id": author, "firstname": f"Person{author}", "surname": "Test"}
    return {"id": message_id, "identity": identity, "createdAt": when, "text": text}


def fixture_messages() -> list[dict[str, Any]]:
    raw = load_sample("listChatMessages.200.json")["items"]
    return [summaries.summarize_chat_message(message) for message in raw]


def remember(seen: list[str], value: str) -> bool:
    """Stands in for opening something: notes what would have been opened."""
    seen.append(value)
    return True


def plain(html: str) -> str:
    document = QTextDocument()
    document.setHtml(html)
    return document.toPlainText()


# ------------------------------------------------------------------------ the layout


def test_your_messages_are_on_the_right_and_the_others_on_the_left():
    messages = [
        text_message(1, TOM, "2026-11-02T19:00:00+01:00", "van Tom"),
        text_message(2, ME, "2026-11-02T19:05:00+01:00", "van mij"),
    ]

    html = messages_html(messages, Conversation(my_ids=frozenset({ME})))

    other, mine = html.split("van Tom")[0], html.split("van Tom")[1]
    assert 'class="other"' in other and 'align="left"' in other
    assert 'class="mine"' in mine and 'align="right"' in mine
    assert "Person2000000001" not in html, "your own name is not repeated on your messages"


def test_a_name_is_shown_once_per_run_of_messages():
    messages = [
        text_message(1, TOM, "2026-11-02T19:00:00+01:00", "een"),
        text_message(2, TOM, "2026-11-02T19:01:00+01:00", "twee"),
        text_message(3, ME, "2026-11-02T19:02:00+01:00", "ik"),
        text_message(4, TOM, "2026-11-02T19:03:00+01:00", "drie"),
        text_message(5, TOM, "2026-11-03T08:00:00+01:00", "vier"),
    ]

    text = plain(messages_html(messages, Conversation(my_ids=frozenset({ME}))))

    assert text.count(f"Person{TOM} Test") == 3, "at the start, after you, and on a new day"
    assert text.count("Mon 2 Nov 2026") == 1 and text.count("Tue 3 Nov 2026") == 1
    assert re.search(r"een\s+19:00", text), "the time is in the message, not a full date"


def test_a_chat_with_one_other_person_shows_no_names():
    messages = [text_message(1, TOM, "2026-11-02T19:00:00+01:00", "hallo")]

    text = plain(messages_html(messages, Conversation(show_names=False)))

    assert "Person" not in text and "hallo" in text


def test_the_same_person_always_gets_the_same_colour():
    messages = [
        text_message(1, TOM, "2026-11-02T19:00:00+01:00", "a"),
        text_message(2, 5, "2026-11-02T19:01:00+01:00", "b"),
        text_message(3, TOM, "2026-11-02T19:02:00+01:00", "c"),
    ]

    classes = re.findall(r'class="(name\d)"', messages_html(messages, Conversation()))

    assert classes[0] == classes[2] != classes[1]


def test_joining_and_renaming_are_small_lines_not_empty_messages():
    text = plain(messages_html(fixture_messages(), Conversation()))

    assert "Sanne de Vries joined the chat" in text
    assert 'Tom Smit renamed the chat to "Excursie"' in text


def test_a_message_with_only_a_file_is_not_empty():
    html = messages_html(fixture_messages(), Conversation())

    assert "Video · IMG_0001.MOV · 12 MB" in plain(html)
    assert f'href="{attachment_link(VIDEO_MESSAGE)}"' in html
    assert "cloudfront" not in html, "no download address in the pane"
    assert "<img" not in html, "no picture before the app fetched one"


def test_a_thumbnail_is_shown_only_when_the_app_has_it_and_fits_the_box():
    view = Conversation(pictures={PHOTO_ATTACHMENT: (900, 1200)})

    html = messages_html(fixture_messages(), view)

    assert html.count("<img") == 1
    assert f'src="{thumbnail_name(PHOTO_ATTACHMENT)}" width="180" height="240"' in html
    assert fitted(100, 50) == (100, 50), "never enlarged"
    assert fitted(0, 0) == (240, 240)


def test_a_file_name_cannot_inject_markup_or_a_link():
    evil = text_message(7, TOM, "2026-11-02T19:00:00+01:00", "kijk")
    evil["attachment"] = {
        "attachment_id": '1"><img src=https://evil.example/a>',
        "filename": '<a href="https://evil.example">klik</a>',
        "media": "image",
        "size": 5,
    }
    view = Conversation(pictures={evil["attachment"]["attachment_id"]: (10, 10)})

    html = messages_html([evil], view)

    assert "evil.example/a>" not in html and '<a href="https://evil' not in html
    assert set(re.findall(r'href="([a-z-]+):', html)) == {"parro-attachment"}


@pytest.mark.parametrize("colours", [theme.LIGHT, theme.DARK])
def test_names_and_text_are_readable_on_both_kinds_of_message(colours):
    def luminance(colour: str) -> float:
        channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    def contrast(first: str, second: str) -> float:
        high, low = sorted((luminance(first), luminance(second)), reverse=True)
        return (high + 0.05) / (low + 0.05)

    assert len(colours.names) == theme.NAME_COLOUR_COUNT
    for name in colours.names:
        assert contrast(name, colours.other_message) >= 4.5, name
    for background in (colours.own_message, colours.other_message):
        assert contrast(colours.text, background) >= 7
        assert contrast(colours.muted, background) >= 4.5, "the time"
        assert contrast(colours.selected_text, background) >= 4.5, "a link"
    assert colours.own_message != colours.other_message
    assert {f.name for f in fields(colours)} >= {"own_message", "other_message", "names"}


# --------------------------------------------------------------------------- the pane


def test_the_pane_shows_only_pictures_the_app_handed_it(application):
    browser = gui_widgets.SafeTextBrowser()
    image = QImage.fromData(jpeg())
    browser.allow_image("parro-thumbnail:1", image)

    assert browser.loadResource(2, QUrl("parro-thumbnail:1")) == image
    assert browser.loadResource(2, QUrl("https://evil.example/a.png")) is None
    assert browser.loadResource(2, QUrl("file:///etc/passwd")) is None
    browser.clear()
    assert browser.loadResource(2, QUrl("parro-thumbnail:1")) is None
    dispose(browser)


def test_an_internal_link_is_passed_on_and_never_opened(application, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(gui_widgets, "open_url", lambda address: remember(opened, address))
    monkeypatch.setattr(gui_widgets, "ask", lambda *_: True)
    browser = gui_widgets.SafeTextBrowser()
    browser.internal_schemes = ("parro-attachment",)
    seen: list[str] = []
    browser.internal_link.connect(seen.append)

    browser._follow(QUrl("parro-attachment:12"))
    plain_browser = gui_widgets.SafeTextBrowser()
    plain_browser._follow(QUrl("parro-attachment:12"))

    assert seen == ["parro-attachment:12"] and opened == []
    dispose(browser)
    dispose(plain_browser)


def test_new_pictures_do_not_move_a_reader_who_scrolled_up(application):
    browser = gui_widgets.SafeTextBrowser()
    browser.resize(300, 200)
    browser.show()
    long_text = "".join(f"<p>regel {number}</p>" for number in range(200))
    browser.show_at_end(long_text)
    wait_until(lambda: browser.verticalScrollBar().maximum() > 0)
    bar = browser.verticalScrollBar()

    browser.replace_keeping_place(long_text + "<p>erbij</p>")
    assert bar.value() == bar.maximum(), "at the end: stays at the end"

    bar.setValue(bar.maximum() // 2)
    place = bar.value()
    browser.replace_keeping_place(long_text + "<p>nog een</p>")
    assert bar.value() == place
    dispose(browser)


# ------------------------------------------------------------------------ whole window


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
    monkeypatch.setattr(attachment_views, "_media_folder", tmp_path / "media")
    (tmp_path / "media").mkdir()


def entry_url(message_id: int, entry_type: str) -> str:
    messages = load_sample("listChatMessages.200.json")["items"]
    message = next(m for m in messages if m["links"][0]["id"] == message_id)
    return str(next(e["url"] for e in message["attachment"]["entries"] if e["type"] == entry_type))


@pytest.fixture
def api() -> fakes.FakeParroApi:
    created = fakes.FakeParroApi(load_sample, calendar_event_ids={fakes.MUSEUM_TRIP_ID})
    for message_id in (PHOTO_MESSAGE, VIDEO_MESSAGE):
        created.attachment_bodies[entry_url(message_id, "THUMBNAIL")] = ("image/jpg", jpeg())
    created.attachment_bodies[entry_url(PHOTO_MESSAGE, "SOURCE")] = ("image/jpeg", jpeg(60, 80))
    created.attachment_bodies[entry_url(VIDEO_MESSAGE, "SOURCE")] = ("video/quicktime", b"film")
    return created


@pytest.fixture
def window(application, api):
    make_client: Callable[[Any], ParroClient] = lambda settings: ParroClient(  # noqa: E731
        settings, transport=api
    )
    created = MainWindow(make_client)
    created.show()
    wait_until(lambda: created.logged_in)
    yield created
    dispose(created)


def open_chat(window: MainWindow) -> Any:
    window.sections.setCurrentRow(SECTIONS.index("Chats"))
    view: Any = window.views["Chats"]
    wait_until(lambda: view.list.count() > 0)
    view.list.setCurrentRow(0)
    wait_until(lambda: "<img" in view.detail._html)
    return view


def cdn_requests(api: fakes.FakeParroApi) -> list[str]:
    return [request.url for request in api.requests if "cloudfront" in request.url]


def test_a_chat_shows_its_thumbnails_and_fetches_only_those(window, api):
    view = open_chat(window)

    assert view.detail._html.count("<img") == 2
    assert all("/thumbnail/" in url for url in cdn_requests(api)), "no film, no full photo"
    assert "Sanne de Vries joined the chat" in view.detail.toPlainText()
    assert not api.writes(), "looking at a chat changes nothing"


def test_a_click_on_a_photo_shows_it(window, api):
    view = open_chat(window)

    view.detail._follow(QUrl(attachment_link(PHOTO_MESSAGE)))
    wait_until(lambda: view.opener.dialog is not None)

    assert not view.opener.dialog.picture.pixmap().isNull()
    assert view.opener.dialog.save_button.isVisible() or not view.opener.dialog.isVisible()
    view.opener.dialog.close()


def test_a_video_is_fetched_only_after_you_choose_to_open_it(window, api, monkeypatch):
    asked: list[str] = []
    opened: list[str] = []

    def choose(_parent: Any, question: str, options: list[str]) -> str | None:
        asked.append(question)
        return options[0]

    monkeypatch.setattr(gui_widgets, "choose", choose)
    monkeypatch.setattr(gui_widgets, "open_file", lambda path: remember(opened, path))
    view = open_chat(window)
    source = entry_url(VIDEO_MESSAGE, "SOURCE")
    assert source not in cdn_requests(api)

    view.detail._follow(QUrl(attachment_link(VIDEO_MESSAGE)))
    wait_until(lambda: bool(opened))

    assert "IMG_0001.MOV (12 MB)" in asked[0]
    assert Path(opened[0]).read_bytes() == b"film" and Path(opened[0]).name == "IMG_0001.MOV"
    assert "Handed IMG_0001.MOV to your computer to open" in view.notice.text()

    view.detail._follow(QUrl(attachment_link(VIDEO_MESSAGE)))
    wait_until(lambda: len(opened) == 2)
    assert cdn_requests(api).count(source) == 1, "the second time it is not fetched again"


def test_in_a_flatpak_a_fetched_file_is_kept_where_the_desktop_can_reach_it(tmp_path, monkeypatch):
    """Live check of 0.13.0: in the Flatpak, Open did nothing. Its /tmp exists only inside the
    sandbox, so the desktop could not find the file it was asked to open."""
    cache = tmp_path / "cache"
    leftover = cache / "parro-media" / "old" / "film.mov"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(b"left behind by a killed app")
    monkeypatch.setenv("FLATPAK_ID", "io.github.chrisswiftdev.parro-gui")
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.setattr(attachment_views, "_media_folder", None)

    folder = attachment_views.media_folder()

    assert folder == cache / "parro-media" and folder.is_dir()
    assert not leftover.exists(), "emptied at first use"
    assert attachment_views.media_folder() == folder, "made once"
    if os.name == "posix":
        assert folder.stat().st_mode & 0o077 == 0, "only for you"


def test_outside_a_flatpak_the_system_s_temporary_folder_is_used(monkeypatch):
    monkeypatch.delenv("FLATPAK_ID", raising=False)

    assert attachment_views.flatpak_media_folder(os.environ) is None
    assert attachment_views.flatpak_media_folder({"FLATPAK_ID": "x"}) == (
        Path.home() / ".cache" / "parro-media"
    )


def test_cancelling_the_question_fetches_nothing(window, api, monkeypatch):
    monkeypatch.setattr(gui_widgets, "choose", lambda *_: None)
    view = open_chat(window)

    view.detail._follow(QUrl(attachment_link(VIDEO_MESSAGE)))
    view.detail._follow(QUrl("parro-attachment:999"))
    view.detail._follow(QUrl("parro-attachment:https://evil.example/x"))

    assert entry_url(VIDEO_MESSAGE, "SOURCE") not in cdn_requests(api)
    assert view.opener.dialog is None


def test_a_calendar_item_shows_its_photo_as_a_picture_and_its_link(window, api):
    event = load_sample(f"getEvent_calendar-{fakes.MUSEUM_TRIP_ID}.200.json")
    thumbnail = event["calendarItem"]["attachments"][0]["entries"][1]["url"]
    api.attachment_bodies[thumbnail] = ("image/jpg", jpeg())
    window.sections.setCurrentRow(SECTIONS.index("Calendar"))
    view: Any = window.views["Calendar"]
    wait_until(lambda: view.list.count() > 0)
    row = next(i for i in range(view.list.count()) if "Natuurmuseum" in view.list.item(i).text())
    view.list.setCurrentRow(row)
    wait_until(lambda: bool(view.attachments.photo_buttons))
    (button,) = view.attachments.photo_buttons.values()
    wait_until(lambda: not button.icon().isNull())

    assert "Link: https://www.example.com/natuurmuseum" in view.detail.toPlainText()
    assert 'href="https://www.example.com/natuurmuseum"' in view.detail._html
    assert button.toolTip().startswith("Route.jpg")
    assert not view.attachments.save_buttons, "a photo has no row of its own"
    assert view.attachments.save_all_button.isEnabled()


def test_a_video_on_an_announcement_gets_open_instead_of_read(application, tmp_path):
    bar = attachment_views.AttachmentBar(None, lambda *_: None)  # type: ignore[arg-type]
    video = {"attachment_id": 1, "filename": "film.mp4", "size": 2_000_000, "media": "video"}
    letter = {"attachment_id": 2, "filename": "brief.pdf", "size": 1000, "readable": True}

    bar.show_attachments(7, [video, letter])

    assert [button.text() for button in bar.read_buttons] == ["Open", "Read"]
    assert len(bar.save_buttons) == 2 and not bar.photo_buttons
    dispose(bar)


def test_the_calendar_text_shows_the_link_only_when_there_is_one():
    item = {"calendarItem": {"title": "Uitje"}, "details": {"description": "Tot dan"}}

    assert "Link:" not in agenda_html(item)
    item["details"]["link"] = "https://www.example.com/x"
    assert '<a href="https://www.example.com/x">' in agenda_html(item)


# ------------------------------------------------------------------------------- links


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("Kijk op www.school.nl/agenda voor meer", "https://www.school.nl/agenda"),
        ("www.school.nl.", "https://www.school.nl"),
        ("(www.school.nl)", "https://www.school.nl"),
    ],
)
def test_an_address_without_its_scheme_is_a_link_to_https(source, target):
    assert f'<a href="{target}">' in gui_text.safe_html(source)


@pytest.mark.parametrize(
    "source",
    ["mail naar info@www.school.nl", "https://www.school.nl", "awww.nl", "www.", "x/www.a.nl"],
)
def test_what_only_looks_like_www_is_left_alone(source):
    html = gui_text.safe_html(source)

    assert html.count("<a ") == (1 if source.startswith("https://") else 0)
    assert 'href="https://https' not in html


def test_a_link_in_html_keeps_its_address():
    html = (
        '<p>Zie <a href="https://www.example.com/film">dit filmpje</a> en '
        '<a href="https://www.example.com/a">https://www.example.com/a</a>.</p>'
        '<p><a href="javascript:alert(1)">klik</a> <a href="mailto:x@example.com">mail</a></p>'
    )

    text = attachments.extract_html_text(html)

    assert "dit filmpje (https://www.example.com/film)" in text
    assert text.count("https://www.example.com/a") == 1, "not repeated when it is the text"
    assert "javascript" not in text and "mailto" not in text


def test_own_identity_ids_come_from_the_account(api, tmp_path):
    from tests.test_attachments import make_client

    client = make_client(tmp_path, api)

    assert ME in operations.own_identity_ids(client)
