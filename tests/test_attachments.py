"""Phase 4: attachments (fixes 4, 6 and 7 of PLAN-api-client §4)."""

import base64
import builtins
import copy
import io
import json
import logging
import zipfile

import pytest

from parro import attachments, operations
from parro.api_client import ParroClient
from parro.attachments import ReadOptions
from parro.errors import AttachmentError, ConfigurationError
from parro.settings import Settings
from parro.token_store import TokenStore
from tests import fakes
from tests.conftest import load_sample

PDF_URL_IN_SAMPLE_PREFIX = "https://d3jdv0f7ba4m2l.cloudfront.net/application/"


def make_pdf(text: str) -> bytes:
    """A minimal valid one-page PDF containing `text` (Helvetica, built by hand)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    output, offsets = io.BytesIO(), []
    output.write(b"%PDF-1.4\n")
    for number, body in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref_position = output.tell()
    output.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        output.write(b"%010d 00000 n \n" % offset)
    output.write(b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1))
    output.write(b"startxref\n%d\n%%%%EOF\n" % xref_position)
    return output.getvalue()


def make_docx(paragraphs: list[str]) -> bytes:
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = (
        f'<?xml version="1.0"?><w:document xmlns:w="{namespace}">'
        f"<w:body>{body}</w:body></w:document>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return output.getvalue()


def make_client(tmp_path, api: fakes.FakeParroApi, **settings_changes) -> ParroClient:
    settings = Settings(
        token_file=tmp_path / "tokens.json", role_override="GUARDIAN:1", **settings_changes
    )
    store = TokenStore(settings.token_file)
    store.save_token_response(
        {"access_token": fakes.ACCESS_TOKEN, "refresh_token": fakes.REFRESH_TOKEN}
    )
    return ParroClient(settings, transport=api, token_store=store)


def pdf_url_of_announcement_sample() -> str:
    event = load_sample("getEvent_announcement.200.json")
    return str(event["attachments"][0]["entries"][0]["url"])


def image_url_of_calendar_sample() -> str:
    event = load_sample("getEvent_attachment.200.json")
    return str(event["calendarItem"]["attachments"][0]["entries"][0]["url"])


# ------------------------------------------------------------------- finding and choosing


def test_calendar_item_attachments_are_found():  # fix 4
    event = load_sample("getEvent_attachment.200.json")
    (found,) = attachments.find_attachments(event)
    described = attachments.describe_attachment(found)
    assert described.kind == "IMAGE"
    assert described.filename == "Screenshot.jpg", "the SOURCE entry, not the thumbnail"
    announcement = load_sample("getEvent_announcement.200.json")
    assert (
        attachments.describe_attachment(attachments.find_attachments(announcement)[0]).kind == "PDF"
    )


def test_source_entry_falls_back_to_the_first_entry():
    assert attachments.pick_source_entry({"entries": [{"type": "THUMBNAIL", "url": "u"}]}) == {
        "type": "THUMBNAIL",
        "url": "u",
    }
    assert attachments.pick_source_entry({}) == {}


@pytest.mark.parametrize(
    ("content_type", "filename", "expected"),
    [
        ("image/jpeg", "Screenshot.jpg", "image"),
        ("image/jpg", None, "image"),  # fix 6: the non-standard type seen in the samples
        ("application/pdf", "brief.PDF", "pdf"),
        ("application/pdf", "photo.jpg", "pdf"),  # the content type wins over the name
        ("application/octet-stream", "brief.pdf", "pdf"),  # generic type: the name decides
        (None, "notes.docx", "docx"),
        ("text/html; charset=utf-8", None, "html"),
        ("text/csv", None, "text"),
        ("application/zip", "x.pdf", None),
        (None, None, None),
    ],
)
def test_format_is_chosen_by_content_type_first(content_type, filename, expected):
    assert attachments.detect_format(content_type, filename) == expected


def test_a_photo_source_entry_with_a_document_dtype_is_read_as_an_image():  # fix 6
    event = load_sample("getEvent_attachment.200.json")
    entry = attachments.pick_source_entry(event["calendarItem"]["attachments"][0])
    assert entry["dtype"] == "attachment.RAttachmentDocumentEntry"
    assert attachments.detect_format(entry["contentType"], entry["filename"]) == "image"


# ------------------------------------------------------------------------------ extraction


def test_pdf_text_extraction():
    pytest.importorskip("pypdf")
    extracted = attachments.extract_text(make_pdf("Nieuwsbrief nummer 3"), "application/pdf", None)
    assert "Nieuwsbrief nummer 3" in extracted.text
    assert extracted.details["format"] == "pdf" and extracted.details["pages"] == 1


def test_missing_pdf_libraries_give_an_install_hint(monkeypatch):
    real_import = builtins.__import__

    def without_pdf_libraries(name, *args, **kwargs):
        if name in ("fitz", "pypdf"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_pdf_libraries)
    with pytest.raises(AttachmentError, match="pip install pymupdf"):
        attachments.extract_text(b"%PDF-1.4", "application/pdf", None)


def test_docx_html_and_text_extraction():
    docx = attachments.extract_text(make_docx(["Eerste alinea", "Tweede  alinea"]), None, "a.docx")
    assert docx.text == "Eerste alinea\nTweede alinea"
    html = "<html><head><style>p{}</style></head><body><p>Hallo &amp; welkom</p><p>Tot  ziens</p>"
    assert attachments.extract_text(html.encode(), "text/html", None).text == (
        "Hallo & welkom\nTot ziens"
    )
    text = attachments.extract_text("﻿a\r\n\r\n\r\n\tb  c ".encode(), "text/plain", None)
    assert text.text == "a\n\nb c"


def test_images_and_unknown_types_are_refused_with_a_reason():
    with pytest.raises(AttachmentError, match="image"):
        attachments.extract_text(b"\xff\xd8", "image/jpeg", None)
    with pytest.raises(AttachmentError, match="No text reader"):
        attachments.extract_text(b"PK", "application/zip", "x.zip")
    with pytest.raises(AttachmentError, match="could not be read"):
        attachments.extract_text(b"not a zip", None, "x.docx")


def test_large_images_are_downscaled_and_small_ones_kept():
    image_module = pytest.importorskip("PIL.Image")
    large = io.BytesIO()
    image_module.new("RGB", (3000, 2000), "white").save(large, format="PNG")
    data, mime_type = attachments.shrink_image(large.getvalue(), "image/png", 1400)
    assert mime_type == "image/jpeg"
    assert image_module.open(io.BytesIO(data)).size == (1400, 933)
    small = io.BytesIO()
    image_module.new("RGB", (100, 50)).save(small, format="PNG")
    assert attachments.shrink_image(small.getvalue(), "image/png", 1400) == (
        small.getvalue(),
        "image/png",
    )


# ------------------------------------------------------------------------ whole operation


def test_reading_the_announcement_pdf_downloads_without_the_parro_token(tmp_path, caplog):
    pytest.importorskip("pypdf")
    caplog.set_level(logging.DEBUG)
    api = fakes.FakeParroApi(load_sample)
    pdf_url = pdf_url_of_announcement_sample()
    api.attachment_bodies[pdf_url] = ("application/pdf", make_pdf("Beste ouders"))
    client = make_client(tmp_path, api)

    report = operations.read_attachments(client, event_id=11000000000)

    assert report.summary["announcement"].startswith("Nieuwsbrief")
    assert "Beste ouders" in report.summary["text"]
    assert report.summary["format"] == "pdf" and report.summary["attachment_id"] == 11000000000
    download = next(r for r in api.requests if r.url == pdf_url)
    assert "Authorization" not in download.headers, "never send the Parro token to the CDN"
    assert not any(h.lower().startswith("parro-") for h in download.headers)
    assert pdf_url not in caplog.text, "fix 7: full attachment URLs are never logged"
    assert pdf_url.split("/application/")[1] not in caplog.text
    assert "d3jdv0f7ba4m2l.cloudfront.net" in caplog.text, "the host alone is fine"


def test_calendar_item_photo_comes_back_as_an_image(tmp_path):  # fix 4 end to end
    api = fakes.FakeParroApi(load_sample, calendar_event_ids={11000000000})
    image_url = image_url_of_calendar_sample()
    api.attachment_bodies[image_url] = ("image/jpeg", b"\xff\xd8 tiny jpeg")
    client = make_client(tmp_path, api)

    report = operations.read_attachments(client, event_id=11000000000)

    assert report.summary["returned_as"] == "image"
    assert report.summary["announcement"].startswith("Culturele muziekavond")
    (image,) = report.images
    assert base64.b64decode(image.base64_data).startswith(b"\xff\xd8")
    probe, calendar = [r for r in api.api_requests() if "/event/" in r.url]
    assert "RAnnouncementEventPrimer" in probe.url and "RCalendarItemEvent" in calendar.url


def test_images_are_left_out_when_not_wanted_and_can_be_saved(tmp_path):
    api = fakes.FakeParroApi(load_sample, calendar_event_ids={11000000000})
    api.attachment_bodies[image_url_of_calendar_sample()] = ("image/jpeg", b"\xff\xd8")
    client = make_client(tmp_path, api)
    options = ReadOptions(include_images=False, save_directory=tmp_path / "saved")
    report = operations.read_attachments(client, event_id=11000000000, options=options)
    assert report.images == []
    assert (tmp_path / "saved" / "Screenshot.jpg").read_bytes() == b"\xff\xd8"
    again = operations.read_attachments(client, event_id=11000000000, options=options)
    assert again.summary["saved_to"].endswith("Screenshot (2).jpg"), "never overwrite"


def test_several_attachments_need_a_choice(tmp_path):
    api = fakes.FakeParroApi(load_sample)
    event = load_sample("getEvent_announcement.200.json")
    second = copy.deepcopy(event["attachments"][0])
    second["links"][0]["id"] = 222
    second["entries"][0]["url"] = "https://d3jdv0f7ba4m2l.cloudfront.net/application/x/2.txt"
    second["entries"][0]["contentType"] = "text/plain"
    event["attachments"].append(second)

    def sample_with_two_attachments(name):
        return event if name == "getEvent_announcement.200.json" else load_sample(name)

    api.load_sample = sample_with_two_attachments
    api.attachment_bodies[second["entries"][0]["url"]] = ("text/plain", b"second file")
    client = make_client(tmp_path, api)

    listing = operations.read_attachments(client, event_id=1)
    assert len(listing.summary["attachments"]) == 2 and "several" in listing.summary["message"]
    chosen = operations.read_attachments(client, event_id=1, attachment_id=222)
    assert chosen.summary["text"] == "second file"
    every = operations.read_attachments(client, event_id=1, read_all=True)
    first_result, second_result = every.summary["attachments"]
    assert "error" in first_result, "the PDF download fails (fake CDN has no body): reported"
    assert second_result["text"] == "second file"
    with pytest.raises(AttachmentError, match="not on this event"):
        operations.read_attachments(client, event_id=1, attachment_id=999)


def test_text_is_truncated_at_max_chars_and_empty_text_warns(tmp_path):
    api = fakes.FakeParroApi(load_sample)
    api.attachment_bodies["https://cdn.example/a.txt"] = ("text/plain", b"x" * 50)
    api.attachment_bodies["https://cdn.example/empty.txt"] = ("text/plain", b"  ")
    client = make_client(tmp_path, api)
    options = ReadOptions(max_chars=10)
    truncated = operations.read_attachments(
        client, url="https://cdn.example/a.txt", options=options
    )
    assert truncated.summary["truncated"] is True and len(truncated.summary["text"]) == 10
    empty = operations.read_attachments(client, url="https://cdn.example/empty.txt")
    assert "OCR" in empty.summary["warning"]


def test_download_limits_and_url_checks(tmp_path):
    api = fakes.FakeParroApi(load_sample)
    client = make_client(tmp_path, api, max_download_bytes=10)
    with pytest.raises(AttachmentError, match="limit"):
        attachments.download_attachment(client, "https://cdn.example/big.pdf", 11, None)
    api.attachment_bodies["https://cdn.example/b.txt"] = ("text/plain", b"x" * 11)
    with pytest.raises(AttachmentError, match="larger"):
        attachments.download_attachment(client, "https://cdn.example/b.txt", None, None)
    with pytest.raises(AttachmentError, match="http"):
        attachments.download_attachment(client, "file:///etc/passwd", None, None)
    with pytest.raises(ConfigurationError):
        operations.read_attachments(client)


def test_api_host_files_do_get_the_parro_headers(tmp_path):
    api = fakes.FakeParroApi(load_sample)
    url = "https://rest-v2.parro.com/rest/v2/accountsettings"
    client = make_client(tmp_path, api)
    downloaded = attachments.download_attachment(client, url, None, "application/json")
    assert json.loads(downloaded.data)["dtype"] == "auth.RAccountSettings"
    assert api.requests[-1].headers["Authorization"] == f"Bearer {fakes.ACCESS_TOKEN}"


def test_filename_from_url():
    assert attachments.filename_from_url("https://x/a/b/1-%20x.pdf?q=1") == "1- x.pdf"
    assert attachments.filename_from_url(None) is None
