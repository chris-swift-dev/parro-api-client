"""Marking as read: the only writes (PLAN-read-state-and-filters §2, phase 5).

The fake API raises ForbiddenWrite for any request to the API that is not a GET or one of the
three allowed PUTs, so every test in this suite checks the allowlist. The tests here check that
writes happen only when asked, only once, and only after the item was found.
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import pytest

from parro import api_client, operations
from parro import cli as parro_cli
from parro import mcp_server as parro_mcp
from parro.api_client import READ_STATE_WRITES, ParroClient
from parro.errors import ConfigurationError
from parro.http import HttpRequest
from parro.settings import Settings
from tests import fakes
from tests.conftest import load_sample
from tests.test_cli import COMMANDS_WITH_JSON_OUTPUT

ROOT = Path(__file__).resolve().parent.parent
UNREAD_ANNOUNCEMENT = 5000000102  # "Studiedag vrijdag 13 november", group 3
READ_ANNOUNCEMENT = fakes.NEWSLETTER_ID
UNREAD_CALENDAR_ITEM = 7000000201  # "Oudergesprekken groep 3"
CHAT = 8000000001  # one unread message
CHAT_MEMBERSHIP_ID = 8000000501  # the chat's first link (`koppeling`): 403


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


@pytest.fixture
def api() -> fakes.FakeParroApi:
    return fakes.FakeParroApi(load_sample)


def run(api, capsys, *argv: str) -> tuple[int, str, str]:
    try:
        code = parro_cli.main(list(argv), make_client=lambda s: ParroClient(s, transport=api))
    except SystemExit as stop:
        code = int(stop.code or 0)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def client_for(api) -> ParroClient:
    client = ParroClient(Settings(role_override="GUARDIAN:1"), transport=api)
    client.token_store.save_token_response({"access_token": fakes.ACCESS_TOKEN})
    return client


# ------------------------------------------------------------------------ the one write


def test_the_allowlist_is_exactly_the_three_captured_calls():
    assert READ_STATE_WRITES == {
        "announcement": ("/event/{id}/read", None),
        "calendar": ("/event/{id}/read", None),
        "chat": ("/chatroom/{id}/read", None),
        "group-announcements": ("/event/markannouncementsasread", "group"),
    }


def test_mark_read_sends_an_empty_put_with_the_usual_headers(api):
    client_for(api).mark_read("chat", CHAT)
    (request,) = api.api_requests()
    assert request.method == "PUT" and request.body == b""
    assert request.url == f"{fakes.API}/rest/v2/chatroom/{CHAT}/read"
    assert request.headers["Authorization"] == f"Bearer {fakes.ACCESS_TOKEN}"
    assert request.headers["parro-authorization-role"] == "GUARDIAN:1"
    assert "Range" not in request.headers


def test_group_marking_puts_the_group_in_the_query(api):
    client_for(api).mark_read("group-announcements", fakes.GROUP_3)
    assert api.writes() == [f"PUT /event/markannouncementsasread?group={fakes.GROUP_3}"]


@pytest.mark.parametrize(
    ("kind", "object_id"),
    [("event", 1), ("announcement", 0), ("chat", -5), ("chat", True), ("announcement", "1")],
)
def test_mark_read_refuses_anything_else_before_sending(api, kind, object_id):
    with pytest.raises(ConfigurationError):
        client_for(api).mark_read(kind, object_id)
    assert api.api_requests() == []


def test_only_the_client_core_builds_api_requests():
    """No module but api_client talks to the API, and it only builds GET and PUT requests."""
    for path in sorted((ROOT / "parro").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        methods = set(re.findall(r'HttpRequest\(\s*"([A-Z]+)"', text))
        if path.name == "login_methods.py":  # the IdP only: token, revoke, login form
            assert methods <= {"GET", "POST"} and "api_root" not in text
        elif path.name == "attachments.py":  # downloads from the CDN
            assert methods == {"GET"}
        elif path.name == "release_check.py":  # the desktop app's update check: GitHub only
            assert methods == {"GET"} and "api_root" not in text
            assert "https://api.github.com/repos/" in text and "Authorization" not in text
        elif path.name == "api_client.py":
            assert methods == set(), "_send passes the method on; it is GET, PUT or POST"
            assert 'Literal["GET", "PUT", "POST", "DELETE"]' in text
            assert text.count('method="PUT"') == 1 and text.count('method="POST"') == 1
            assert text.count('"POST", body, (200, 201)') == 2, "helper sign-up and RSVP"
            assert text.count('"DELETE", None, (200, 204)') == 1
        else:
            assert "HttpRequest(" not in text, path.name


def test_the_fake_refuses_every_other_write(api):
    client = client_for(api)
    headers = {"Authorization": f"Bearer {fakes.ACCESS_TOKEN}"}
    for method, path, body in [
        ("POST", f"/chatroom/{CHAT}/chatmessage", b"{}"),
        ("DELETE", f"/event/{READ_ANNOUNCEMENT}", None),
        ("PUT", f"/event/{READ_ANNOUNCEMENT}", b""),
        ("PUT", f"/chatroom/{CHAT}/read", b'{"x": 1}'),
    ]:
        request = HttpRequest(method, client.build_api_url(path), headers, body)
        with pytest.raises(fakes.ForbiddenWrite):
            api.send(request)


# ---------------------------------------------------------------------- never on its own


@pytest.mark.parametrize(
    "argv",
    [
        *COMMANDS_WITH_JSON_OUTPUT,
        ["overview"],
        ["overview", "--all"],
        ["announcement", str(UNREAD_ANNOUNCEMENT)],
        ["chat-messages", str(CHAT)],
        ["chatrooms", "--unread"],
        ["mark-read", "group", str(fakes.GROUP_3)],  # without --yes: only the count
    ],
    ids=" ".join,
)
def test_no_command_writes_unless_asked(environment, api, capsys, argv):
    run(api, capsys, *argv)
    assert api.writes() == []


def test_no_mcp_tool_writes_but_mark_read(environment, api, monkeypatch):
    monkeypatch.setenv("PARRO_ALLOW_MARK_READ", "1")
    server = parro_mcp.McpServer(make_client=lambda s: ParroClient(s, transport=api))
    arguments: dict[str, dict[str, Any]] = {
        "parro_announcement": {"announcement_id": UNREAD_ANNOUNCEMENT},
        "parro_chat_messages": {"chatroom_id": CHAT},
        "parro_chat_members": {"chatroom_id": CHAT},
        "parro_attachment": {"announcement_id": READ_ANNOUNCEMENT},
        "parro_get": {"path": "/accountsettings"},
    }
    skipped = {"parro_login", "parro_logout", "parro_login_url", "parro_login_finish"}
    for tool in parro_mcp.TOOL_DEFINITIONS:
        if tool["name"] not in skipped:
            server.call_tool(tool["name"], arguments.get(tool["name"], {}))
    assert api.writes() == []


# ------------------------------------------------------------------------------ the CLI


def test_mark_read_announcement_once(environment, api, capsys):
    code, out, _ = run(
        api, capsys, "mark-read", "announcement", str(UNREAD_ANNOUNCEMENT), "--format", "markdown"
    )
    assert code == 0 and out.startswith("# Marked as read: Studiedag vrijdag 13 november\n")
    assert "The school sees this" in out
    assert api.writes() == [f"PUT /event/{UNREAD_ANNOUNCEMENT}/read"]

    code, out, _ = run(api, capsys, "mark-read", "announcement", str(UNREAD_ANNOUNCEMENT))
    assert code == 0 and json.loads(out)["already_read"] is True
    assert len(api.writes()) == 1, "already read: no second write"


def test_an_announcement_that_is_read_is_left_alone(environment, api, capsys):
    code, out, _ = run(
        api, capsys, "mark-read", "announcement", str(READ_ANNOUNCEMENT), "--format", "markdown"
    )
    assert code == 0 and out.startswith("# Already read: Nieuwsbrief nr. 3\n")
    assert api.writes() == []


def test_the_overview_no_longer_lists_what_was_marked(environment, api, capsys):
    _, before, _ = run(api, capsys, "overview", "--format", "markdown")
    assert "Studiedag vrijdag 13 november" in before
    run(api, capsys, "mark-read", "announcement", str(UNREAD_ANNOUNCEMENT))
    _, after, _ = run(api, capsys, "overview", "--format", "markdown")
    assert "Studiedag vrijdag 13 november" not in after and "Gym op dinsdag" in after


def test_mark_read_calendar_item(environment, api, capsys):
    code, out, _ = run(api, capsys, "mark-read", "calendar", str(UNREAD_CALENDAR_ITEM))
    result = json.loads(out)
    assert code == 0 and result["marked_read"] is True
    assert result["title"] == "Oudergesprekken groep 3"
    assert api.writes() == [f"PUT /event/{UNREAD_CALENDAR_ITEM}/read"]


def test_the_wrong_kind_of_id_is_an_error_and_no_write(environment, api, capsys):
    code, _, err = run(api, capsys, "mark-read", "announcement", str(UNREAD_CALENDAR_ITEM))
    assert code == 1 and "406" in err
    code, _, err = run(api, capsys, "mark-read", "chat", str(CHAT_MEMBERSHIP_ID))
    assert code == 1 and "CHAT_NOT_ACTIVE_MEMBER" in err
    code, _, _ = run(api, capsys, "mark-read", "event", "1")
    assert code == 2
    assert api.writes() == []


def test_mark_read_chat(environment, api, capsys):
    code, out, _ = run(api, capsys, "mark-read", "chat", str(CHAT), "--format", "markdown")
    assert code == 0 and out.startswith("# Marked as read: Rijden naar het Natuurmuseum\n")
    assert api.writes() == [f"PUT /chatroom/{CHAT}/read"]
    _, out, _ = run(api, capsys, "chatrooms", "--unread")
    assert json.loads(out)["chatrooms"] == []


def test_announcement_mark_read_shows_it_first(environment, api, capsys):
    code, out, _ = run(
        api,
        capsys,
        "announcement",
        str(UNREAD_ANNOUNCEMENT),
        "--mark-read",
        "--format",
        "markdown",
    )
    assert code == 0 and out.startswith("# ")
    assert out.rstrip().endswith("✓ Marked as read. The school can see that you read it.")
    assert api.writes() == [f"PUT /event/{UNREAD_ANNOUNCEMENT}/read"]
    methods = [r.method for r in api.api_requests() if f"/event/{UNREAD_ANNOUNCEMENT}" in r.url]
    assert methods == ["GET", "PUT"], "fetched first, then marked"


def test_chat_messages_mark_read(environment, api, capsys):
    code, out, _ = run(api, capsys, "chat-messages", str(CHAT), "--mark-read")
    assert code == 0 and json.loads(out)["marked_read"] is True
    code, out, _ = run(api, capsys, "chat-messages", str(CHAT), "--mark-read")
    assert json.loads(out)["marked_read"] is False
    assert api.writes() == [f"PUT /chatroom/{CHAT}/read"]


def test_group_marking_counts_first_and_needs_yes(environment, api, capsys):
    group = str(fakes.GROUP_3)
    code, out, _ = run(api, capsys, "mark-read", "group", group, "--format", "markdown")
    assert code == 0 and out.startswith("# 2 unread announcements in ")
    assert "- Studiedag vrijdag 13 november\n- Gym op dinsdag" in out
    assert "Nothing marked yet." in out and f"mark-read group {group} --yes" in out
    assert api.writes() == []

    code, out, _ = run(api, capsys, "mark-read", "group", group, "--yes", "--format", "markdown")
    assert code == 0 and out.startswith("# Marked as read: 2 unread announcements in ")
    assert api.writes() == [f"PUT /event/markannouncementsasread?group={group}"]

    code, out, _ = run(api, capsys, "mark-read", "group", group, "--yes", "--format", "markdown")
    assert out.startswith("# No unread announcements in ") and len(api.writes()) == 1


def test_group_marking_only_for_your_own_groups(environment, api, capsys):
    code, _, err = run(api, capsys, "mark-read", "group", "123", "--yes")
    assert code == 2 and "not one of your current groups" in err
    assert api.writes() == []


# ------------------------------------------------------------------------------- MCP


def test_mcp_mark_read_is_off_by_default(environment, api):
    server = parro_mcp.McpServer(make_client=lambda s: ParroClient(s, transport=api))
    names = [tool["name"] for tool in server.list_tools()]
    assert "parro_mark_read" not in names and len(names) == 20
    answer = server.call_tool("parro_mark_read", {"kind": "chat", "id": CHAT})
    assert answer.is_error and "PARRO_ALLOW_MARK_READ=1" in answer.content[0]["text"]
    assert api.api_requests() == []


def test_mcp_mark_read_when_switched_on(environment, api, monkeypatch):
    monkeypatch.setenv("PARRO_ALLOW_MARK_READ", "1")
    server = parro_mcp.McpServer(make_client=lambda s: ParroClient(s, transport=api))
    tool = next(t for t in server.list_tools() if t["name"] == "parro_mark_read")
    assert tool["annotations"]["readOnlyHint"] is False
    assert "the school sees it" in tool["description"]
    answer = server.call_tool("parro_mark_read", {"kind": "chat", "id": CHAT})
    assert not answer.is_error and json.loads(answer.content[0]["text"])["marked_read"] is True
    answer = server.call_tool("parro_mark_read", {"kind": "group-announcements", "id": 1})
    assert answer.is_error, "bulk marking is CLI only"
    assert api.writes() == [f"PUT /chatroom/{CHAT}/read"]


@pytest.mark.parametrize(("value", "allowed"), [("1", True), ("yes", True), ("0", False)])
def test_the_switch(value, allowed):
    settings = Settings.from_environment({"PARRO_ALLOW_MARK_READ": value})
    assert settings.allow_mark_read is allowed
    assert Settings.from_environment({}).allow_mark_read is False


def test_mark_read_kinds_match_the_allowlist():
    single = set(READ_STATE_WRITES) - {"group-announcements"}
    assert set(api_client.READ_STATE_WRITES) >= single
    assert set(operations.MARK_READ_KINDS) == single
