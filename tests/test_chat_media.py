"""0.13: photos, videos and status messages in a chat, and the link of a calendar item.

The shapes come from the live look of 2026-11-14 (docs/PLAN-media-and-chat-0.13.md): a message has
one `attachment` and then often no `text`; its entries come in any order; a video is never read.
"""

from typing import Any

import pytest

from parro import attachments, cli, operations, rendering, summaries
from parro.attachments import ReadOptions
from parro.errors import AttachmentError, ConfigurationError
from tests import fakes
from tests.conftest import load_sample
from tests.test_attachments import make_client

ROOM = 8000000001
VIDEO_MESSAGE, PHOTO_MESSAGE, TEXT_MESSAGE = 8100000000, 8099999999, 8100000001
VIDEO_ATTACHMENT, PHOTO_ATTACHMENT = 8200000020, 8200000010


def raw_message(message_id: int) -> dict[str, Any]:
    messages = load_sample("listChatMessages.200.json")["items"]
    return next(m for m in messages if m["links"][0]["id"] == message_id)


def entry_url(message_id: int, entry_type: str) -> str:
    entries = raw_message(message_id)["attachment"]["entries"]
    return str(next(e["url"] for e in entries if e["type"] == entry_type))


def conversation(tmp_path) -> dict[str, Any]:
    client = make_client(tmp_path, fakes.FakeParroApi(load_sample))
    result: dict[str, Any] = operations.list_chat_messages(client, ROOM, limit=30)
    return result


def message(result: dict[str, Any], message_id: int) -> dict[str, Any]:
    return next(m for m in result["messages"] if m["id"] == message_id)


# ------------------------------------------------------------------------------ finding


def test_a_message_s_single_attachment_is_found_and_its_entries_picked_by_type():
    photo = raw_message(PHOTO_MESSAGE)
    assert [e["type"] for e in photo["attachment"]["entries"]] == ["THUMBNAIL", "SOURCE"]

    (found,) = attachments.find_attachments(photo)
    described = attachments.describe_attachment(found)

    assert described.url == entry_url(PHOTO_MESSAGE, "SOURCE"), "not simply the first entry"
    assert described.thumbnail_url == entry_url(PHOTO_MESSAGE, "THUMBNAIL")
    assert described.content_type == "image/jpeg" and described.filename is None


@pytest.mark.parametrize(
    ("content_type", "filename", "expected"),
    [
        ("video/quicktime", "IMG_0001.MOV", "video"),
        ("audio/mp4", None, "audio"),
        ("application/octet-stream", "memo.m4a", "audio"),
        ("application/octet-stream", "film.mp4", "video"),
        ("image/jpg", None, "image"),
    ],
)
def test_video_and_audio_are_recognised(content_type, filename, expected):
    assert attachments.detect_format(content_type, filename) == expected
    assert not attachments.can_extract_text(content_type, filename)


# --------------------------------------------------------------------------- summaries


def test_a_message_gets_a_compact_attachment_with_a_made_up_name_for_a_photo(tmp_path):
    result = conversation(tmp_path)

    photo = message(result, PHOTO_MESSAGE)["attachment"]
    assert photo["filename"] == f"photo-{PHOTO_ATTACHMENT}.jpg"
    assert photo["media"] == "image" and photo["has_thumbnail"] is True
    assert "entries" not in photo
    video = message(result, VIDEO_MESSAGE)
    assert "text" not in video
    assert video["attachment"]["filename"] == "IMG_0001.MOV"
    assert video["attachment"]["media"] == "video" and video["attachment"]["readable"] is False
    assert "attachment" not in message(result, TEXT_MESSAGE)


def test_message_text_shows_the_text_and_then_the_file(tmp_path):
    result = conversation(tmp_path)

    assert rendering.message_text(message(result, VIDEO_MESSAGE)) == "[video] IMG_0001.MOV (12 MB)"
    assert rendering.message_text(message(result, PHOTO_MESSAGE)) == (
        "Kijk, zo ziet de route eruit: https://www.example.com/route\n"
        f"[photo] photo-{PHOTO_ATTACHMENT}.jpg (1.3 MB)"
    )


@pytest.mark.parametrize(
    ("status", "title", "expected"),
    [
        ("ENTER", None, "(joined the chat)"),
        ("LEAVE", None, "(left the chat)"),
        ("TITLE_CHANGED", "Excursie", '(renamed the chat to "Excursie")'),
        ("TITLE_CHANGED", None, "(renamed the chat)"),
        ("SOMETHING_NEW", None, "(something new)"),
    ],
)
def test_a_status_message_says_what_happened(status, title, expected):
    status_message = {"type": "ChatStatusMessage", "status": status, "title": title}
    assert rendering.message_text(status_message) == expected


def test_a_text_message_is_never_taken_for_a_status_message():
    assert rendering.message_text({"text": "hallo", "status": "ENTER"}) == "hallo"
    assert rendering.message_text({"deleted": True, "attachment": {"filename": "a"}}) == (
        "(message deleted)"
    )


def test_the_chat_list_shows_a_last_message_that_is_only_a_file():
    room = {**load_sample("listChatrooms.200.json")["items"][0]}
    room["lastMessage"] = raw_message(VIDEO_MESSAGE)

    summary = summaries.summarize_chatroom(room)
    text = rendering.chatroom_block(summary, rendering.RenderOptions())

    assert "[video] IMG_0001.MOV" in text
    assert "cloudfront" not in text


def test_the_conversation_names_the_message_id_and_how_to_read_the_file(tmp_path):
    text = rendering.render_conversation(conversation(tmp_path), rendering.RenderOptions())

    assert f"#{VIDEO_MESSAGE}" in text and f"#{TEXT_MESSAGE}" not in text
    assert f"attachment --chat {ROOM} --message <id>" in text
    assert "cloudfront" not in text, "no download link in what is shown"


# ----------------------------------------------------------------------------- reading


def test_a_chat_photo_comes_back_as_an_image(tmp_path):
    api = fakes.FakeParroApi(load_sample)
    api.attachment_bodies[entry_url(PHOTO_MESSAGE, "SOURCE")] = ("image/jpeg", b"\xff\xd8 photo")
    client = make_client(tmp_path, api)

    report = operations.read_attachments(client, chatroom_id=ROOM, message_id=PHOTO_MESSAGE)

    assert report.summary["returned_as"] == "image" and len(report.images) == 1
    assert report.summary["attachment_id"] == PHOTO_ATTACHMENT


def test_a_video_gives_its_thumbnail_and_the_film_is_never_fetched(tmp_path):
    api = fakes.FakeParroApi(load_sample)
    thumbnail = entry_url(VIDEO_MESSAGE, "THUMBNAIL")
    api.attachment_bodies[thumbnail] = ("image/jpg", b"\xff\xd8 small")
    client = make_client(tmp_path, api)

    report = operations.read_attachments(client, chatroom_id=ROOM, message_id=VIDEO_MESSAGE)

    assert report.summary["format"] == "video" and report.summary["bytes"] == 11_951_961
    assert report.summary["returned_as"].startswith("thumbnail image")
    assert len(report.images) == 1 and report.images[0].mime_type == "image/jpeg"
    fetched = [r.url for r in api.requests if "cloudfront" in r.url]
    assert fetched == [thumbnail], "the 12 MB film stays where it is"


def test_a_video_without_pictures_wanted_fetches_nothing_at_all(tmp_path):
    api = fakes.FakeParroApi(load_sample)
    client = make_client(tmp_path, api)

    report = operations.read_attachments(
        client,
        chatroom_id=ROOM,
        message_id=VIDEO_MESSAGE,
        options=ReadOptions(include_images=False),
    )

    assert report.summary["returned_as"] == "nothing (video; save it with --save-to)"
    assert not report.images and not [r for r in api.requests if "cloudfront" in r.url]


def test_saving_a_video_fetches_the_original_without_the_parro_token(tmp_path):
    api = fakes.FakeParroApi(load_sample)
    source = entry_url(VIDEO_MESSAGE, "SOURCE")
    api.attachment_bodies[source] = ("video/quicktime", b"moov film")
    client = make_client(tmp_path, api)
    options = ReadOptions(include_images=False, save_directory=tmp_path / "saved")

    report = operations.read_attachments(
        client, chatroom_id=ROOM, message_id=VIDEO_MESSAGE, options=options
    )

    assert (tmp_path / "saved" / "IMG_0001.MOV").read_bytes() == b"moov film"
    assert report.summary["format"] == "video" and "text" not in report.summary
    download = next(r for r in api.requests if r.url == source)
    assert "Authorization" not in download.headers


def test_a_message_without_a_file_and_a_half_given_pair_are_refused(tmp_path):
    client = make_client(tmp_path, fakes.FakeParroApi(load_sample))

    with pytest.raises(AttachmentError, match="no attachments"):
        operations.read_attachments(client, chatroom_id=ROOM, message_id=TEXT_MESSAGE)
    with pytest.raises(ConfigurationError, match="message id"):
        operations.read_attachments(client, chatroom_id=ROOM)
    with pytest.raises(ConfigurationError, match="not both"):
        operations.read_attachments(client, event_id=1, chatroom_id=ROOM, message_id=2)


def test_the_cli_reads_a_chat_message_s_file(tmp_path):
    api = fakes.FakeParroApi(load_sample)
    api.attachment_bodies[entry_url(VIDEO_MESSAGE, "SOURCE")] = ("video/quicktime", b"film")
    client = make_client(tmp_path, api)
    arguments = ["attachment", "--chat", str(ROOM), "--message", str(VIDEO_MESSAGE)]
    args = cli.build_parser().parse_args([*arguments, "--save-to", str(tmp_path / "out")])

    summary = cli.run_attachment(client, args)

    assert summary["saved_to"].endswith("IMG_0001.MOV")


# -------------------------------------------------------------------------- thumbnails


def test_thumbnails_of_a_chat_are_fetched_once_and_then_come_from_the_cache(tmp_path):
    api = fakes.FakeParroApi(load_sample)
    for message_id in (PHOTO_MESSAGE, VIDEO_MESSAGE):
        api.attachment_bodies[entry_url(message_id, "THUMBNAIL")] = ("image/jpg", b"\xff\xd8 t")
    client = make_client(tmp_path, api)

    first = operations.load_thumbnails(client, chatroom_id=ROOM)
    downloads = len([r for r in api.requests if "cloudfront" in r.url])
    second = operations.load_thumbnails(client, chatroom_id=ROOM)

    assert first == {PHOTO_ATTACHMENT: b"\xff\xd8 t", VIDEO_ATTACHMENT: b"\xff\xd8 t"}
    assert second == first
    assert downloads == 2 == len([r for r in api.requests if "cloudfront" in r.url])
    assert all("/thumbnail/" in r.url for r in api.requests if "cloudfront" in r.url)


def test_a_thumbnail_that_fails_is_left_out(tmp_path):
    api = fakes.FakeParroApi(load_sample)
    api.attachment_bodies[entry_url(PHOTO_MESSAGE, "THUMBNAIL")] = ("image/jpg", b"\xff\xd8 t")
    client = make_client(tmp_path, api)

    assert list(operations.load_thumbnails(client, chatroom_id=ROOM)) == [PHOTO_ATTACHMENT]


def test_thumbnails_of_a_calendar_item(tmp_path):
    api = fakes.FakeParroApi(load_sample, calendar_event_ids={fakes.MUSEUM_TRIP_ID})
    event = load_sample(f"getEvent_calendar-{fakes.MUSEUM_TRIP_ID}.200.json")
    entries = event["calendarItem"]["attachments"][0]["entries"]
    api.attachment_bodies[entries[1]["url"]] = ("image/jpg", b"\xff\xd8 route")
    client = make_client(tmp_path, api)

    assert operations.load_thumbnails(client, event_id=fakes.MUSEUM_TRIP_ID) == {
        6000000401: b"\xff\xd8 route"
    }


# ------------------------------------------------------------------- the calendar link


def test_a_calendar_item_s_own_link_is_in_its_details():
    event = load_sample(f"getEvent_calendar-{fakes.MUSEUM_TRIP_ID}.200.json")

    details = summaries.summarize_calendar_details(event)

    assert details["link"] == "https://www.example.com/natuurmuseum"
    assert "url" not in details["attachments"][0], "a file's download link is still left out"


@pytest.mark.parametrize("address", ["javascript:alert(1)", "file:///etc/passwd", "", None, 7])
def test_only_a_web_address_is_passed_on_as_the_link(address):
    event = {"calendarItem": {"description": "x", "url": address}}

    assert "link" not in summaries.summarize_calendar_details(event)
