"""Readable output (PLAN-readable-output): markdown views, the format switches, kept ids.

Snapshot tests: each view is rendered from the invented fixtures and compared with a committed file
in tests/snapshots/, so a layout change shows up as a readable diff. After an intended change:

    UPDATE_SNAPSHOTS=1 .venv/bin/pytest tests/test_rendering.py
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import parro_cli
import parro_mcp
from parro import operations, rendering
from parro.api_client import ParroClient
from parro.errors import ConfigurationError
from parro.settings import Settings
from tests import fakes
from tests.conftest import load_sample

SNAPSHOTS = Path(__file__).resolve().parent / "snapshots"


@pytest.fixture
def environment(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("PARRO_"):
            monkeypatch.delenv(name)
    token_file = tmp_path / "tokens.json"
    token_file.write_text(
        json.dumps(
            {
                "access_token": fakes.ACCESS_TOKEN,
                "refresh_token": fakes.REFRESH_TOKEN,
                "expires_at": time.time() + 3000,
            }
        )
    )
    monkeypatch.setenv("PARRO_TOKEN_FILE", str(token_file))
    return token_file


def run_cli(capsys, *argv: str) -> tuple[int, str, str]:
    api = fakes.FakeParroApi(load_sample)
    exit_code = parro_cli.main(list(argv), make_client=lambda s: ParroClient(s, transport=api))
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def matches_snapshot(name: str, text: str) -> None:
    path = SNAPSHOTS / f"{name}.md"
    if os.environ.get("UPDATE_SNAPSHOTS") or not path.exists():
        SNAPSHOTS.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert text == path.read_text(encoding="utf-8"), f"differs from {path}"


def ids_that_must_show(view: str, data: Any) -> set[int]:
    """The ids a reader needs for a follow-up command, per view."""
    lists = {
        "children": ("children", "id"),
        "groups": ("groups", "id"),
        "announcements": ("announcements", "id"),
        "calendar": ("items", "id"),
        "chatrooms": ("chatrooms", "id"),
        "system_news": ("items", "id"),
    }
    if view in lists:
        key, id_key = lists[view]
        return {item[id_key] for item in data.get(key, []) if item.get(id_key)}
    if view == "announcement":
        return {data["id"], *(a["attachment_id"] for a in data.get("attachments", []))}
    if view == "account":
        return {data["organisation"]["id"]}
    return set()


# Command line → (snapshot name, view). Later phases add the richer views here.
CLI_CASES = [
    (["me"], "me", "account"),
    (["children"], "children", "children"),
    (["groups"], "groups", "groups"),
    (["groups", "--previous"], "groups-previous", "groups"),
    (["unread"], "unread", "unread"),
    (["system-news"], "system-news", "system_news"),
    (["system-news", "--full"], "system-news-full", "system_news"),
    (["get", "/accountsettings"], "get-accountsettings", "get"),
    (["announcements"], "announcements", "announcements"),
    (["announcements", "--full", "--limit", "2"], "announcements-full", "announcements"),
    (["announcements", "--unread-only"], "announcements-unread", "announcements"),
    (["announcements", "--group", str(fakes.GROUP_6)], "announcements-group-6", "announcements"),
    (["announcement", str(fakes.NEWSLETTER_ID)], "announcement", "announcement"),
    (["calendar"], "calendar", "calendar"),
    (["calendar", "--details"], "calendar-details", "calendar"),
    (["chatrooms"], "chatrooms", "chatrooms"),
    (["chat-messages", "8000000001"], "chat-messages", "chat_messages"),
]


@pytest.mark.parametrize(("argv", "snapshot", "view"), CLI_CASES, ids=[c[1] for c in CLI_CASES])
def test_cli_markdown_view(environment, capsys, argv, snapshot, view):
    exit_code, markdown, err = run_cli(capsys, *argv, "--format", "markdown")
    assert exit_code == 0, err
    matches_snapshot(snapshot, markdown)
    exit_code, as_json, _ = run_cli(capsys, *argv, "--format", "json")
    for needed in ids_that_must_show(view, json.loads(as_json)):
        assert f"#{needed}" in markdown, f"id {needed} missing from the {view} view"


def test_status_view_from_a_fixed_status():
    status = {
        "token_file": "/home/someone/.parro-mcp/tokens.json",
        "has_access_token": True,
        "has_refresh_token": True,
        "credentials_in_env": True,
        "login_method": "login-form",
        "access_token_expires_in_seconds": 3480,
        "access_token_valid": True,
        "automatic_login_halted": "password grant rejected",
        "how_to_resume": "Fix the password first, then log in explicitly.",
        "logged_in_as": {
            "name": "Sanne de Vries",
            "email": "sanne@example.com",
            "accountType": "GUARDIAN",
            "organisation": "Basisschool De Linde",
            "role_header": "GUARDIAN:2000000001",
        },
    }
    matches_snapshot("status", rendering.render("status", status))


# ------------------------------------------------------------------------------ switches


def test_auto_is_json_when_piped_and_markdown_at_a_terminal(environment, capsys, monkeypatch):
    _, out, _ = run_cli(capsys, "children")
    json.loads(out)  # capsys is not a terminal
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    _, out, _ = run_cli(capsys, "children")
    assert out.startswith("# Children")


def test_parro_format_and_the_flag(environment, capsys, monkeypatch):
    monkeypatch.setenv("PARRO_FORMAT", "markdown")
    _, out, _ = run_cli(capsys, "children")
    assert out.startswith("# Children")
    _, out, _ = run_cli(capsys, "children", "--format", "json")
    json.loads(out)


def test_raw_cannot_be_markdown(environment, capsys, monkeypatch):
    exit_code, out, err = run_cli(capsys, "me", "--raw", "--format", "markdown")
    assert exit_code == 2 and out == "" and "--raw" in err
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    _, out, _ = run_cli(capsys, "me", "--raw")
    assert json.loads(out)["dtype"] == "auth.RAccount", "auto + --raw stays JSON"


def test_choose_format_and_parse_errors():
    assert rendering.choose_format("auto", raw=False, stdout_is_terminal=True) == "markdown"
    assert rendering.choose_format("auto", raw=False, stdout_is_terminal=False) == "json"
    assert rendering.choose_format("markdown", raw=False, stdout_is_terminal=False) == "markdown"
    with pytest.raises(ConfigurationError):
        rendering.choose_format("markdown", raw=True, stdout_is_terminal=True)
    with pytest.raises(ConfigurationError, match="Unknown output format"):
        Settings.from_environment({"PARRO_FORMAT": "html"})


def test_mcp_markdown_on_request_json_by_default(environment):
    api = fakes.FakeParroApi(load_sample)
    server = parro_mcp.McpServer(make_client=lambda s: ParroClient(s, transport=api))
    default = server.call_tool("parro_groups", {})
    json.loads(default.content[0]["text"])
    readable = server.call_tool("parro_groups", {"format": "markdown"})
    assert readable.content[0]["text"].startswith("# Groups, this school year (3)")
    for arguments, expected in (
        ({"format": "html"}, "`format`"),
        ({"format": "markdown", "raw": True}, "`raw`"),
    ):
        refused = server.call_tool("parro_groups", arguments)
        assert refused.is_error and expected in refused.content[0]["text"]


# ------------------------------------------------------------------------------- helpers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-11-02T12:28:51.57+01:00", "Mon 2 Nov 2026 12:28"),  # 2 fraction digits (3.10!)
        ("2026-11-02T12:28:51+01:00", "Mon 2 Nov 2026 12:28"),
        ("2026-11-02T12:28:51.227123456+01:00", "Mon 2 Nov 2026 12:28"),
        ("2026-11-02T23:30:00Z", "Mon 2 Nov 2026 23:30"),  # shown as sent, not converted
        ("not a date", "not a date"),
    ],
)
def test_format_timestamp(text, expected):
    assert rendering.format_timestamp(text) == expected


def test_small_helpers():
    assert rendering.format_date("2022-08-29") == "Mon 29 Aug 2022"
    assert rendering.format_size(1_500_108) == "1.5 MB"
    assert rendering.format_size(24_576) == "25 KB"
    assert rendering.format_size(512) == "512 bytes"
    assert rendering.plural(1, "photo") == "1 photo"
    assert rendering.plural(3, "child", "children") == "3 children"
    assert rendering.preview("a\n\n b \nc\nd") == "a\nb\nc …"
    assert rendering.quote("one\n\ntwo") == "> one\n>\n> two"
    assert rendering.join_parts(["a", "", None, "b"]) == "a · b"


# ------------------------------------------------------------------------ announcements


def test_feed_lists_an_announcement_sent_to_two_groups_once(environment, capsys):
    _, out, _ = run_cli(capsys, "announcements", "--format", "json")
    feed = json.loads(out)
    ids = [item["id"] for item in feed["announcements"]]
    assert len(ids) == len(set(ids)) == feed["count"] == 5
    study_day = next(item for item in feed["announcements"] if item["id"] == 5000000102)
    assert study_day["groups"] == ["Basisschool De Linde", "Groep 3 - juf Eva"]
    assert study_day["from"] == "Basisschool De Linde", "`from` keeps its old meaning"
    assert study_day["pinned"] is True and study_day["author"] == "Lotte Bakker"
    newsletter = next(item for item in feed["announcements"] if item["id"] == fakes.NEWSLETTER_ID)
    assert "groups" not in newsletter and "pinned" not in newsletter


def test_feed_limit_counts_announcements_not_copies(environment, capsys):
    _, out, _ = run_cli(capsys, "announcements", "--limit", "2", "--format", "json")
    assert [item["id"] for item in json.loads(out)["announcements"]] == [5000000102, 5000000103]


def test_pinned_announcements_come_first_in_markdown():
    feed = {
        "count": 2,
        "announcements": [
            {"id": 1, "title": "Newest", "date": "2026-11-03T10:00:00+01:00", "read": True},
            {"id": 2, "title": "Pinned", "date": "2026-11-01T10:00:00+01:00", "pinned": True},
        ],
    }
    markdown = rendering.render("announcements", feed)
    assert markdown.index("📌 Pinned") < markdown.index("## Newest")


def test_mcp_markdown_names_the_tools_and_shows_whole_texts(environment):
    api = fakes.FakeParroApi(load_sample)
    server = parro_mcp.McpServer(make_client=lambda s: ParroClient(s, transport=api))
    result = server.call_tool("parro_announcements", {"format": "markdown"})
    text = result.content[0]["text"]
    assert "parro_attachment(announcement_id=5000000101)" in text
    assert "parro_cli.py" not in text
    assert "Lotte Bakker\nadministratie" in text, "MCP gets the whole text, not a preview"


# --------------------------------------------------------------------- calendar and chats


def test_calendar_details_cost_one_request_per_item(environment, capsys):
    api = fakes.FakeParroApi(load_sample)

    def make_client(settings: Settings) -> ParroClient:
        return ParroClient(settings, transport=api)

    parro_cli.main(["calendar", "--format", "json"], make_client=make_client)
    capsys.readouterr()
    requests_without_details = len(api.api_requests())
    parro_cli.main(["calendar", "--details", "--format", "json"], make_client=make_client)
    agenda = json.loads(capsys.readouterr().out)
    extra = api.api_requests()[requests_without_details:]
    detail_calls = [r for r in extra if "/event/" in r.url]
    assert len(detail_calls) == agenda["count"] == 4
    assert agenda["items"][1]["details"]["location"] == "Natuurmuseum Voorbeeldstad"
    assert agenda["items"][3]["details"] == {}, "a holiday has no details"


def test_conversation_is_in_reading_order_whatever_the_api_order():
    messages = load_sample("listChatMessages.200.json")["items"]
    newest_first = {"chatroom_id": 1, "total": 3, "messages": messages}
    oldest_first = {"chatroom_id": 1, "total": 3, "messages": list(reversed(messages))}
    rendered = rendering.render("chat_messages", newest_first)
    assert rendered == rendering.render("chat_messages", oldest_first)
    assert rendered.index("Dag allemaal") < rendered.index("Ik kan rijden") < rendered.index("Top")


def test_agenda_time_spans():
    def span(start: str, end: str, days: int = 1) -> str:
        item = {"calendarItem": {"startDate": start, "endDate": end}, "numberOfDays": days}
        return rendering.time_span(item)

    assert span("2026-11-11T17:30:00+01:00", "2026-11-11T19:00:00+01:00") == "17:30-19:00"
    assert span("2026-11-12T00:00:00+01:00", "2026-11-12T00:00:00+01:00") == "all day"
    assert span("2026-11-12T09:00:00+01:00", "2026-11-12T09:00:00+01:00") == "09:00"
    assert span("2026-12-21T00:00:00+01:00", "2027-01-01T00:00:00+01:00", 12).startswith(
        "all day, 12 days until Fri 1 Jan 2027"
    )


ATTACHMENT_TEXT = {
    "filename": "Nieuwsbrief-3.pdf",
    "contentType": "application/pdf",
    "bytes": 1_500_108,
    "chars": 30,
    "format": "pdf",
    "pages": 9,
    "engine": "pypdf",
    "truncated": True,
    "shown_chars": 30,
    "hint": "Raise `max_chars` to read the rest.",
    "text": "Beste ouders,\nIn deze nieuwsbr",
    "attachment_id": 6000000101,
    "announcement": "Nieuwsbrief nr. 3",
}


def test_attachment_views():
    matches_snapshot("attachment-text", rendering.render("attachment", ATTACHMENT_TEXT))
    several = {
        "announcement": "Foto's herfstwandeling",
        "attachments": [
            {"filename": "herfst-1.jpg", "contentType": "image/jpeg", "bytes": 1_333_337,
             "returned_as": "image", "attachment_id": 6000000201},
            {"filename": "herfst-2.jpg", "error": "Downloading the attachment failed (HTTP 403).",
             "attachment_id": 6000000211},
        ],
    }  # fmt: skip
    matches_snapshot("attachment-several", rendering.render("attachment", several))
    choose = {
        "announcement": "Foto's herfstwandeling",
        "message": "This event has several attachments. Ask for one with its attachment id.",
        "attachments": [{"attachment_id": 6000000201, "filename": "herfst-1.jpg",
                         "contentType": "image/jpeg", "size": 1_333_337}],
    }  # fmt: skip
    rendered = rendering.render("attachment", choose)
    assert "several attachments" in rendered and "#6000000201" in rendered


# -------------------------------------------------------------------------------- overview

FIXED_NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone(timedelta(hours=1)))


def overview(now: datetime = FIXED_NOW) -> tuple[dict[str, Any], fakes.FakeParroApi]:
    api = fakes.FakeParroApi(load_sample)
    client = ParroClient(Settings(role_override="GUARDIAN:1"), transport=api)
    client.token_store.save_token_response({"access_token": fakes.ACCESS_TOKEN})
    return operations.show_overview(client, now=now), api


def test_overview_view(environment):
    result, api = overview()
    matches_snapshot("overview", rendering.render("overview", result))
    assert sum("/group" in r.url for r in api.api_requests()) == 1, "groups fetched once"
    assert result["chats"]["total"] == 1 and result["unread"][0]["announcements"] == 2


@pytest.mark.parametrize(
    ("today", "first_upcoming", "count"),
    [
        ("2026-11-05", 7000000101, 4),  # everything is still ahead
        ("2026-11-12", 7000000301, 3),  # Sint-Maarten (11 Nov) is over, the trip is today
        ("2026-12-24", 7000000102, 1),  # the 5-day holiday is still running
        ("2026-12-26", None, 0),
    ],
)
def test_overview_coming_up_depends_on_today(environment, today, first_upcoming, count):
    now = datetime.fromisoformat(f"{today}T08:00:00+01:00")
    items = overview(now)[0]["calendar"]["items"]
    assert len(items) == count
    assert (items[0]["id"] if items else None) == first_upcoming


def test_cli_and_mcp_overview(environment, capsys):
    exit_code, out, _ = run_cli(capsys, "overview", "--format", "markdown")
    assert exit_code == 0 and out.startswith("# Overview\n\n## Unread")
    api = fakes.FakeParroApi(load_sample)
    server = parro_mcp.McpServer(make_client=lambda s: ParroClient(s, transport=api))
    result = server.call_tool("parro_overview", {"format": "markdown"})
    assert not result.is_error and "parro_calendar(details=true)" in result.content[0]["text"]
