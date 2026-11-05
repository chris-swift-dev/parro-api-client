"""The archive (`parro_cli.py sync`, PLAN-readable-output §3b).

First run, incremental runs, renames, removed items, photos, retries, and what must never end up
on disk.
"""

import copy
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

import parro_cli
from parro import operations
from parro.api_client import ParroClient
from parro.archive import file_stem, slugify
from parro.settings import Settings
from tests import fakes
from tests.conftest import load_sample

NEWSLETTER_PDF = b"%PDF-1.4 the newsletter"
FORM_DOCX = b"PK the form"


def attachment_urls(name: str, location: str = "attachments") -> list[str]:
    event = load_sample(name)
    holder = event["calendarItem"] if location == "calendar" else event
    return [a["entries"][0]["url"] for a in holder["attachments"]]


def make_api(load: Any = load_sample) -> fakes.FakeParroApi:
    """The fake API with every attachment downloadable."""
    api = fakes.FakeParroApi(load)
    feed = load_sample("listEvents_announcements-4000000001.200.json")["items"]
    feed += load_sample("listEvents_announcements-4000000003.200.json")["items"]
    for event in feed:
        for attachment in event["attachments"]:
            entry = attachment["entries"][0]
            body = NEWSLETTER_PDF if entry["filename"].endswith(".pdf") else FORM_DOCX
            if entry["contentType"].startswith("image/"):
                body = b"\xff\xd8 photo " + entry["filename"].encode()
            api.attachment_bodies[entry["url"]] = (entry["contentType"], body)
    route = load_sample("getEvent_calendar-7000000301.200.json")
    route_url = route["calendarItem"]["attachments"][0]["entries"][0]["url"]
    api.attachment_bodies[route_url] = ("image/jpeg", b"\xff\xd8 route")
    return api


def sync(tmp_path: Path, api: fakes.FakeParroApi, **options: Any) -> dict[str, Any]:
    client = ParroClient(
        Settings(role_override="GUARDIAN:1", data_dir=tmp_path / "data"), transport=api
    )
    client.token_store.save_token_response({"access_token": fakes.ACCESS_TOKEN})
    return operations.sync_archive(
        client, operations.SyncOptions(target=tmp_path / "archive", **options)
    )


def files_in(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


# -------------------------------------------------------------------------- first run


def test_first_sync_writes_every_item_with_its_documents(tmp_path):
    result = sync(tmp_path, make_api())
    archive = tmp_path / "archive"
    assert result["announcement"]["written"] == 5
    assert result["calendar"]["written"] == 9, "each calendar item once, past and future"
    assert result["chat"]["written"] == 2
    assert result["files_saved"] == 2 and result["photos_not_saved"] == 4
    assert result["problems"] == []

    newsletter = archive / "announcements" / "2026-10-22-nieuwsbrief-nr-3-5000000101.md"
    text = newsletter.read_text(encoding="utf-8")
    assert text.startswith('---\nid: 5000000101\ntype: announcement\ntitle: "Nieuwsbrief nr. 3"\n')
    assert "[Nieuwsbrief-3.pdf](attachments/5000000101-6000000101-Nieuwsbrief-3.pdf)" in text
    saved_pdf = archive / "announcements/attachments/5000000101-6000000101-Nieuwsbrief-3.pdf"
    assert saved_pdf.read_bytes() == NEWSLETTER_PDF
    walk = (
        archive / "announcements" / "2026-10-31-fotos-herfstwandeling-5000000103.md"
    ).read_text()
    assert walk.count("not saved: run sync --photos") == 3

    chat = (archive / "chats" / "rijden-naar-het-natuurmuseum-8000000001.md").read_text()
    assert chat.index("Dag allemaal") < chat.index("Top, dan zijn we compleet"), "reading order"
    index = (archive / "index.md").read_text()
    assert index.index("Studiedag vrijdag 13 november") < index.index("Nieuwsbrief nr. 3")
    summary = json.loads(
        (archive / "calendar" / "2026-11-11-sint-maartenviering-7000000101.json").read_text()
    )
    assert summary["details"]["location"] == "Schoolplein"


def test_nothing_on_disk_holds_a_link_and_everything_is_private(tmp_path):
    sync(tmp_path, make_api(), photos=True)
    root = tmp_path / "archive"
    for name, data in files_in(root).items():
        assert b"https://" not in data and b"cloudfront" not in data, name
    if os.name == "posix":
        for path in root.rglob("*"):
            expected = 0o700 if path.is_dir() else 0o600
            assert stat.S_IMODE(path.stat().st_mode) == expected, path


# ---------------------------------------------------------------------- incremental


def test_a_second_sync_reads_only_the_lists_and_rewrites_nothing(tmp_path):
    sync(tmp_path, make_api())
    before = files_in(tmp_path / "archive")
    api = make_api()
    result = sync(tmp_path, api)
    assert result["announcement"] == {
        "written": 0,
        "unchanged": 5,
        "renamed": 0,
        "no_longer_in_parro": 0,
    }
    assert result["calendar"]["unchanged"] == 9 and result["chat"]["unchanged"] == 2
    detail_or_messages = [
        r.url for r in api.requests if "/event/" in r.url or "/chatmessage" in r.url
    ]
    assert detail_or_messages == [], "no details and no messages for unchanged items"
    assert not any("cloudfront" in r.url for r in api.requests), "no downloads"
    after = files_in(tmp_path / "archive")
    del before["index.md"], after["index.md"]  # carries the time of the last sync
    assert after == before


def test_lists_are_read_page_by_page(tmp_path, monkeypatch):
    monkeypatch.setattr(operations, "SYNC_PAGE_SIZE", 2)
    api = make_api()
    result = sync(tmp_path, api)
    assert result["calendar"]["written"] == 9
    schoolwide = [
        r
        for r in api.requests
        if "RCalendarItemEventPrimer" in r.url and "group=4000000001" in r.url
    ]
    assert len(schoolwide) == 7, "13 entries in pages of 2"


def test_an_edited_title_renames_the_files(tmp_path):
    sync(tmp_path, make_api())

    def renamed(name: str) -> Any:
        payload = load_sample(name)
        if name == "listEvents_announcements-4000000002.200.json":
            payload = copy.deepcopy(payload)
            gym = next(e for e in payload["items"] if e["links"][0]["id"] == 5000000201)
            gym["title"] = "Gym verplaatst naar dinsdag"
            gym["lastModifiedAt"] = "2026-11-04T09:00:00.000+01:00"
        return payload

    result = sync(tmp_path, make_api(renamed))
    announcements = tmp_path / "archive" / "announcements"
    assert result["announcement"]["renamed"] == 1 and result["announcement"]["written"] == 1
    assert not (announcements / "2026-10-29-gym-op-dinsdag-5000000201.md").exists()
    assert not (announcements / "2026-10-29-gym-op-dinsdag-5000000201.json").exists()
    renamed_file = announcements / "2026-10-29-gym-verplaatst-naar-dinsdag-5000000201.md"
    assert "Gym verplaatst naar dinsdag" in renamed_file.read_text()
    assert (
        "gym-verplaatst-naar-dinsdag-5000000201.md"
        in (tmp_path / "archive" / "index.md").read_text()
    )


def test_an_item_gone_from_parro_stays_and_is_marked(tmp_path):
    sync(tmp_path, make_api())

    def without_gym(name: str) -> Any:
        payload = load_sample(name)
        if name == "listEvents_announcements-4000000002.200.json":
            payload = {"items": [e for e in payload["items"] if e["links"][0]["id"] != 5000000201]}
        return payload

    result = sync(tmp_path, make_api(without_gym))
    assert result["announcement"]["no_longer_in_parro"] == 1
    assert (tmp_path / "archive/announcements/2026-10-29-gym-op-dinsdag-5000000201.md").exists()
    index_lines = (tmp_path / "archive/index.md").read_text().splitlines()
    gym_line = next(line for line in index_lines if "Gym" in line)
    assert gym_line.endswith("*(no longer in Parro)*")


def test_photos_later_and_a_failed_download_is_retried(tmp_path):
    api = make_api()
    pdf_url = attachment_urls("getEvent_announcement.200.json")[0]
    del api.attachment_bodies[pdf_url]  # the CDN fails for the newsletter
    first = sync(tmp_path, api)
    assert len(first["problems"]) == 1 and "Nieuwsbrief-3.pdf" in first["problems"][0]

    second = sync(tmp_path, make_api(), photos=True)
    archive = tmp_path / "archive"
    assert (archive / "announcements/attachments/5000000101-6000000101-Nieuwsbrief-3.pdf").exists()
    assert second["files_saved"] == 1 + 4, "the retried PDF and the four photos"
    walk = (archive / "announcements/2026-10-31-fotos-herfstwandeling-5000000103.md").read_text()
    assert "not saved" not in walk and walk.count("](attachments/5000000103-") == 3

    third = sync(tmp_path, make_api(), photos=True)
    assert third["files_saved"] == 0 and third["announcement"]["unchanged"] == 5


def test_files_come_from_the_cache_when_they_are_there(tmp_path):
    api = make_api()
    client = ParroClient(
        Settings(role_override="GUARDIAN:1", data_dir=tmp_path / "data"), transport=api
    )
    client.token_store.save_token_response({"access_token": fakes.ACCESS_TOKEN})
    operations.read_attachments(client, event_id=fakes.NEWSLETTER_ID)  # fills the cache
    requests_before = len(api.requests)
    operations.sync_archive(client, operations.SyncOptions(target=tmp_path / "archive"))
    newsletter_downloads = [r for r in api.requests[requests_before:] if r.url.endswith(".pdf")]
    assert newsletter_downloads == []


def test_previous_school_year_leaves_this_years_items_alone(tmp_path):
    sync(tmp_path, make_api())
    result = sync(tmp_path, make_api(), previous_year=True)
    assert result["school_year"] == "previous" and "chat" not in result
    index_lines = (tmp_path / "archive" / "index.md").read_text().splitlines()
    marked = [line for line in index_lines if line.endswith("*(no longer in Parro)*")]
    assert marked == [], "a previous-year run does not judge this year's items"


# ------------------------------------------------------------------------------- CLI


@pytest.fixture
def environment(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("PARRO_"):
            monkeypatch.delenv(name)
    token_file = tmp_path / "tokens.json"
    token_file.write_text(json.dumps({"access_token": fakes.ACCESS_TOKEN, "expires_at": 9e12}))
    monkeypatch.setenv("PARRO_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("PARRO_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_cli_sync_default_folder_and_report(environment, capsys):
    api = make_api()
    exit_code = parro_cli.main(
        ["sync", "--format", "markdown"], make_client=lambda s: ParroClient(s, transport=api)
    )
    out = capsys.readouterr().out
    assert exit_code == 0 and out.startswith("# Archive updated (this school year)")
    assert "- Announcements: 5 written · 0 unchanged" in out
    assert "Photos not saved: 4 (add --photos to save them)" in out
    assert (environment / "data" / "archive" / "index.md").exists()


def test_names():
    assert slugify("Foto's herfstwandeling!") == "fotos-herfstwandeling"
    assert slugify("Café — één") == "cafe-een"
    assert slugify("???") == "untitled"
    assert len(slugify("x" * 200)) == 50
    assert file_stem("2026-10-22T11:25:58+02:00", "Nieuwsbrief", 5) == "2026-10-22-nieuwsbrief-5"
    assert file_stem("", "Chat", 8) == "chat-8"
