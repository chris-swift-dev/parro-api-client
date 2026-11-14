"""Every MCP tool states all four hints, and they match what its handler does.

EXPECTED is written out here on purpose, separately from parro/mcp_server.py: changing a hint then
takes a deliberate change in both places. The tests below it run the handlers against the fake
servers, so a hint that stops being true fails.
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import pytest

from parro import mcp_server as parro_mcp
from parro import operations
from parro.api_client import ParroClient
from tests import fakes
from tests.conftest import load_sample

CHAT = 8000000001
UNREAD_ANNOUNCEMENT = 5000000102
BEFORE_THE_TRIP = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)
HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")

READ = (True, False, True, True)
EXPECTED = {
    "parro_auth_status": READ,
    "parro_login": (False, True, False, True),
    "parro_login_url": (False, False, False, False),
    "parro_login_finish": (False, False, False, True),
    "parro_logout": (False, True, True, True),
    "parro_me": READ,
    "parro_children": READ,
    "parro_groups": READ,
    "parro_announcements": READ,
    "parro_announcement": READ,
    "parro_attachment": READ,
    "parro_calendar": READ,
    "parro_chatrooms": READ,
    "parro_chat_messages": READ,
    "parro_chat_members": READ,
    "parro_unread": READ,
    "parro_get": READ,
    "parro_overview": READ,
    "parro_calendar_link": READ,
    "parro_privacy": READ,
    "parro_mark_read": (False, False, True, True),
    "parro_send_chat_message": (False, True, False, True),
    "parro_delete_chat_message": (False, True, True, True),
    "parro_helper_signup": (False, False, True, True),
    "parro_helper_withdraw": (False, True, True, True),
    "parro_rsvp": (False, True, True, True),
}

READ_CALLS: dict[str, dict[str, Any]] = {
    "parro_auth_status": {},
    "parro_me": {},
    "parro_children": {},
    "parro_groups": {},
    "parro_announcements": {},
    "parro_announcement": {"id": UNREAD_ANNOUNCEMENT},
    "parro_attachment": {"announcement_id": fakes.NEWSLETTER_ID},
    "parro_calendar": {"details": True},
    "parro_chatrooms": {},
    "parro_chat_messages": {"chatroom_id": CHAT},
    "parro_chat_members": {"chatroom_id": CHAT},
    "parro_unread": {},
    "parro_get": {"path": "/accountsettings"},
    "parro_overview": {},
    "parro_calendar_link": {},
    "parro_privacy": {},
}


@pytest.fixture
def token_file(tmp_path, monkeypatch):
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
    return path


@pytest.fixture
def api() -> fakes.FakeParroApi:
    return fakes.FakeParroApi(load_sample)


@pytest.fixture
def server(api, token_file) -> parro_mcp.McpServer:
    return parro_mcp.McpServer(make_client=lambda s: ParroClient(s, transport=api))


def result_of(answer: Any) -> Any:
    assert not answer.is_error, answer.content[0]["text"]
    return json.loads(answer.content[0]["text"])


def all_tools() -> list[dict[str, Any]]:
    return [
        *parro_mcp.TOOL_DEFINITIONS,
        parro_mcp.MARK_READ_TOOL,
        parro_mcp.SEND_CHAT_TOOL,
        parro_mcp.DELETE_CHAT_TOOL,
        parro_mcp.HELPER_SIGNUP_TOOL,
        parro_mcp.HELPER_WITHDRAW_TOOL,
        parro_mcp.RSVP_TOOL,
    ]


def test_the_expected_table_covers_every_tool():
    assert {t["name"] for t in all_tools()} == set(EXPECTED) == set(parro_mcp.TOOL_FUNCTIONS)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_tool_states_all_four_hints_as_booleans(name):
    tool = next(t for t in all_tools() if t["name"] == name)
    annotations = tool["annotations"]
    assert all(type(annotations[hint]) is bool for hint in HINTS), annotations
    assert tuple(annotations[hint] for hint in HINTS) == EXPECTED[name]


def test_the_hints_reach_clients_through_tools_list(server, monkeypatch):
    monkeypatch.setenv("PARRO_ALLOW_MARK_READ", "1")
    monkeypatch.setenv("PARRO_ALLOW_SEND_CHAT", "1")
    monkeypatch.setenv("PARRO_ALLOW_DELETE_CHAT", "1")
    monkeypatch.setenv("PARRO_ALLOW_HELPER_SIGNUP", "1")
    monkeypatch.setenv("PARRO_ALLOW_RSVP", "1")
    listed = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    tools = {tool["name"]: tool["annotations"] for tool in listed["result"]["tools"]}
    assert set(tools) == set(EXPECTED)
    assert tools["parro_send_chat_message"]["title"] == "Send a chat message"
    assert all(tuple(tools[n][h] for h in HINTS) == v for n, v in EXPECTED.items())
    titles = {tool["name"]: tool.get("title") for tool in listed["result"]["tools"]}
    assert all(titles[name] == tools[name]["title"] for name in EXPECTED), "a title for every tool"


@pytest.mark.parametrize("name", sorted(READ_CALLS))
def test_a_read_only_tool_changes_nothing(api, server, token_file, name):
    assert EXPECTED[name][0] is True
    before = token_file.read_bytes()
    server.call_tool(name, READ_CALLS[name])
    server.call_tool(name, READ_CALLS[name])
    assert api.writes() == [], "nothing but GET reaches the Parro API"
    assert api.idp.credential_posts() == [], "no password check"
    assert token_file.read_bytes() == before, "the login is untouched"


def test_every_read_only_tool_has_a_behaviour_test():
    assert set(READ_CALLS) == {name for name, hint in EXPECTED.items() if hint[0] is True}


def test_parro_get_cannot_write(api, server):
    answer = server.call_tool("parro_get", {"path": "/event/1/read"})
    assert answer.is_error, "a GET on a write-only path; no PUT is sent"
    assert api.writes() == []


def test_read_only_tools_reach_the_api(api, token_file):
    """openWorldHint true: the answer comes from Parro, not from this process."""
    for name, arguments in READ_CALLS.items():
        fresh = parro_mcp.McpServer(make_client=lambda s: ParroClient(s, transport=api))
        count = len(api.api_requests())
        fresh.call_tool(name, arguments)
        assert len(api.api_requests()) > count, name


def test_login_spends_a_password_check_on_every_call(api, server, token_file, monkeypatch):
    monkeypatch.setenv("PARRO_USERNAME", fakes.USERNAME)
    monkeypatch.setenv("PARRO_PASSWORD", fakes.CORRECT_PASSWORD)
    result_of(server.call_tool("parro_login", {}))
    result_of(server.call_tool("parro_login", {}))
    assert len(api.idp.credential_posts()) == 2, "not idempotent"


def test_login_url_is_local_and_changes_on_every_call(api, server, token_file):
    before = token_file.read_bytes()
    first = result_of(server.call_tool("parro_login_url", {}))["login_url"]
    stored = token_file.read_bytes()
    second = result_of(server.call_tool("parro_login_url", {}))["login_url"]
    assert api.requests == [], "no network: openWorldHint false"
    assert stored != before, "it writes the unfinished login: not read-only"
    assert fakes.query_of(first)["state"] != fakes.query_of(second)["state"], "not idempotent"
    assert json.loads(token_file.read_text())["access_token"] == fakes.ACCESS_TOKEN, (
        "not destructive"
    )


def test_login_finish_works_only_once(api, server):
    started = result_of(server.call_tool("parro_login_url", {}))["login_url"]
    state = fakes.query_of(started)["state"]
    redirect = f"https://talk.parro.com/oauth2?code={fakes.AUTHORIZATION_CODE}&state={state}"
    result_of(server.call_tool("parro_login_finish", {"url": redirect}))
    assert api.requests != [], "it talks to the login server: openWorldHint true"
    assert server.call_tool("parro_login_finish", {"url": redirect}).is_error, "not idempotent"


def test_logout_forgets_the_login_and_can_be_repeated(api, server, token_file):
    result_of(server.call_tool("parro_logout", {}))
    assert not token_file.exists(), "destructive: the tokens are gone"
    count = len(api.requests)
    assert count > 0, "it revokes at the login server: openWorldHint true"
    result_of(server.call_tool("parro_logout", {}))
    assert len(api.requests) == count, "idempotent: nothing left to revoke"


def test_mark_read_can_be_repeated(api, server, monkeypatch):
    monkeypatch.setenv("PARRO_ALLOW_MARK_READ", "1")
    arguments = {"kind": "announcement", "id": UNREAD_ANNOUNCEMENT}
    assert result_of(server.call_tool("parro_mark_read", arguments))["marked_read"] is True
    assert result_of(server.call_tool("parro_mark_read", arguments))["marked_read"] is False
    assert len(api.writes()) == 1


def test_send_is_not_idempotent(api, server, monkeypatch):
    monkeypatch.setenv("PARRO_ALLOW_SEND_CHAT", "1")
    monkeypatch.setenv("PARRO_ALLOW_DELETE_CHAT", "1")
    arguments = {"chatroom_id": CHAT, "text": "Tekst", "confirm": True}
    result_of(server.call_tool("parro_send_chat_message", arguments))
    result_of(server.call_tool("parro_send_chat_message", arguments))
    assert api.sent_messages == [(CHAT, "Tekst"), (CHAT, "Tekst")]


def test_helper_tools_do_nothing_more_when_repeated(api, server, monkeypatch):
    """idempotentHint true: a repeat is refused before it writes (more in test_helper_signup.py)."""
    monkeypatch.setenv("PARRO_ALLOW_HELPER_SIGNUP", "1")
    monkeypatch.setattr(operations, "current_time", lambda: BEFORE_THE_TRIP)
    arguments = {"event_id": fakes.MUSEUM_TRIP_ID, "confirm": True}
    for name, writes in (("parro_helper_signup", 1), ("parro_helper_withdraw", 2)):
        result_of(server.call_tool(name, arguments))
        assert server.call_tool(name, arguments).is_error
        assert len(api.writes()) == writes


def test_the_same_rsvp_answer_again_writes_nothing(api, server, monkeypatch):
    """idempotentHint true: more in test_rsvp.py."""
    monkeypatch.setenv("PARRO_ALLOW_RSVP", "1")
    monkeypatch.setattr(operations, "current_time", lambda: BEFORE_THE_TRIP)
    arguments = {"event_id": fakes.MUSEUM_TRIP_ID, "answer": "accept", "confirm": True}
    assert result_of(server.call_tool("parro_rsvp", arguments))["changed"] is True
    assert result_of(server.call_tool("parro_rsvp", arguments))["changed"] is False
    assert len(api.writes()) == 1
