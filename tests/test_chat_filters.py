"""Chat filters, chat members and the unread-only overview (PLAN-read-state-and-filters phase 4).

All against the fake API, which answers like the live probe of 2026-11-07: archived chats are left
out unless asked for, `archived` takes TRUE / FALSE / BOTH only, and only a chat room's `rel: self`
id opens it (the first link, `koppeling`, answers 403).
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from parro import cli as parro_cli
from parro import mcp_server as parro_mcp
from parro import operations, rendering
from parro.api_client import ParroClient
from parro.errors import ConfigurationError
from tests import fakes
from tests.conftest import load_sample

# Both fixture chats are CALENDAR chats (opened by a teacher for a calendar item).
GROUP_CHAT = 8000000001  # "Rijden naar het Natuurmuseum", one unread message
ARCHIVED_CHAT = 8000000002  # "Hulp bij het zomerfeest"


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
    except SystemExit as stop:  # argparse exits by itself on usage errors
        code = int(stop.code or 0)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def queries(api, path: str) -> list[dict[str, list[str]]]:
    """The query of every request the client sent to this API path."""
    return [
        parse_qs(urlsplit(r.url).query)
        for r in api.api_requests()
        if urlsplit(r.url).path.endswith(path)
    ]


def chat_ids(output: str) -> list[int]:
    return [room["id"] for room in json.loads(output)["chatrooms"]]


# ------------------------------------------------------------------------------- chatrooms


def test_chatrooms_leave_out_archived_chats_like_the_api(environment, api, capsys):
    code, out, _ = run(api, capsys, "chatrooms")
    assert code == 0 and chat_ids(out) == [GROUP_CHAT]
    assert queries(api, "/chatroom") == [{}], "no filter sent: the API's own default"


@pytest.mark.parametrize(
    ("choice", "sent", "ids"),
    [("only", "TRUE", [ARCHIVED_CHAT]), ("include", "BOTH", [GROUP_CHAT, ARCHIVED_CHAT])],
)
def test_chatrooms_archived_choices(environment, api, capsys, choice, sent, ids):
    code, out, _ = run(api, capsys, "chatrooms", "--archived", choice)
    assert code == 0 and sorted(chat_ids(out)) == sorted(ids)
    assert queries(api, "/chatroom") == [{"archived": [sent]}]


def test_chatrooms_type_unread_and_schoolyear_go_to_the_api(environment, api, capsys):
    code, out, _ = run(
        api, capsys, "chatrooms", "--type", "calendar", "--unread", "--schoolyear", "2026"
    )
    assert code == 0 and chat_ids(out) == [GROUP_CHAT]
    assert queries(api, "/chatroom") == [
        {"chatRoom.type": ["CALENDAR"], "read": ["false"], "chatRoom.createdInSchoolyear": ["2026"]}
    ]
    code, out, _ = run(api, capsys, "chatrooms", "--type", "single")
    assert code == 0 and chat_ids(out) == []


def test_unread_is_also_checked_locally(environment, api, capsys):
    """The live probe could not see `read=false` at work, so the client checks unreadCount too."""
    code, out, _ = run(api, capsys, "chatrooms", "--archived", "include", "--unread")
    assert code == 0 and chat_ids(out) == [GROUP_CHAT]


@pytest.mark.parametrize(
    "argv",
    [
        ["chatrooms", "--type", "GROUPS"],
        ["chatrooms", "--archived", "true"],
        ["chatrooms", "--schoolyear", "last"],
        ["chat-messages", str(GROUP_CHAT), "--since", "yesterday"],
        ["chat-members"],
    ],
    ids=" ".join,
)
def test_bad_filter_values_are_usage_errors(environment, api, capsys, argv):
    code, _, _ = run(api, capsys, *argv)
    assert code == 2 and api.api_requests() == []


def test_chat_filter_rejects_unknown_values_before_calling_the_api():
    for wrong in (operations.ChatFilter(archived="all"), operations.ChatFilter(chat_type="class")):
        with pytest.raises(ConfigurationError):
            wrong.as_params()
    assert operations.ChatFilter().as_params() == {}
    assert operations.ChatFilter(chat_type="Group").as_params() == {"chatRoom.type": "GROUP"}


def test_the_chat_id_shown_is_the_one_that_opens_the_chat(environment, api, capsys):
    room = load_sample("listChatrooms.200.json")["items"][0]
    assert room["links"][0]["rel"] == "koppeling", "the fixture keeps the API's trap"
    code, out, _ = run(api, capsys, "chatrooms")
    assert chat_ids(out) == [GROUP_CHAT] != [room["links"][0]["id"]]
    code, _, err = run(api, capsys, "chat-messages", str(room["links"][0]["id"]))
    assert code == 1 and "CHAT_NOT_ACTIVE_MEMBER" in err


# --------------------------------------------------------------------------- chat messages


def test_api_time_turns_dates_into_the_apis_utc_form():
    assert operations.api_time("2026-10-01T08:00:00+02:00") == "2026-10-01T06:00:00.000Z"
    assert operations.api_time("2026-10-01T06:00Z") == "2026-10-01T06:00:00.000Z"
    local_midnight = datetime(2026, 10, 1).astimezone().astimezone(timezone.utc)
    assert operations.api_time("2026-10-01") == local_midnight.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    with pytest.raises(ConfigurationError):
        operations.api_time("1 October")


def test_chat_messages_since(environment, api, capsys):
    code, out, _ = run(api, capsys, "chat-messages", str(GROUP_CHAT))
    everything = json.loads(out)["messages"]
    newest = max(message["createdAt"] for message in everything)
    code, out, _ = run(api, capsys, "chat-messages", str(GROUP_CHAT), "--since", newest)
    result = json.loads(out)
    assert code == 0 and 0 < len(result["messages"]) < len(everything)
    assert result["since"].endswith(".000Z")
    assert queries(api, "/chatmessage")[-1]["createdSince"] == [result["since"]]


# ---------------------------------------------------------------------------- chat members


def test_chat_members_markdown(environment, api, capsys):
    code, out, _ = run(api, capsys, "chat-members", str(GROUP_CHAT), "--format", "markdown")
    assert code == 0
    assert out.startswith(f"# Members of chat #{GROUP_CHAT} (4)\n")
    assert "- Tom Smit · teacher · admin" in out
    assert "- Sanne de Vries · parent of Daan" in out
    assert "Kees" not in out, "members who left only with --former"
    assert queries(api, "/chatroommember") == [{"isActive": ["true"]}]


def test_chat_members_former(environment, api, capsys):
    code, out, _ = run(api, capsys, "chat-members", str(GROUP_CHAT), "--former")
    members = json.loads(out)["members"]
    assert code == 0 and len(members) == 5
    kees = next(member for member in members if member["name"].startswith("Kees"))
    assert kees == {
        "id": kees["id"],
        "name": "Kees Visser",
        "role": "parent",
        "children": ["Lotte"],
        "admin": False,
        "active": False,
    }
    assert queries(api, "/chatroommember") == [{}]


def test_mcp_chat_members(environment, api):
    server = parro_mcp.McpServer(make_client=lambda s: ParroClient(s, transport=api))
    answer = server.call_tool("parro_chat_members", {"chatroom_id": GROUP_CHAT})
    result = json.loads(answer.content[0]["text"])
    assert result["total"] == 4 and {m["role"] for m in result["members"]} == {"teacher", "parent"}


# -------------------------------------------------------------------------------- overview


def test_overview_lists_only_what_is_unread_unless_all(environment, api, capsys):
    code, out, _ = run(api, capsys, "overview", "--format", "markdown")
    assert code == 0 and "## Unread announcements" in out and "## New in the calendar" in out
    assert "Nieuwsbrief nr. 3" not in out, "read announcement"
    code, out, _ = run(api, capsys, "overview", "--all", "--format", "markdown")
    assert code == 0 and "## Latest announcements" in out and "Nieuwsbrief nr. 3" in out


def test_overview_says_so_when_nothing_is_unread():
    options = rendering.RenderOptions()
    announcements = rendering.overview_announcements({"announcements": []}, options, True)
    assert announcements.startswith("## Unread announcements\nNothing unread.")
    assert "overview --all" in announcements
    calendar = rendering.overview_calendar({"items": []}, options, True)
    assert calendar.startswith("## New in the calendar\nNothing new.")


def test_mcp_overview_all(environment, api):
    server = parro_mcp.McpServer(make_client=lambda s: ParroClient(s, transport=api))
    unread = json.loads(server.call_tool("parro_overview", {}).content[0]["text"])
    everything = json.loads(server.call_tool("parro_overview", {"all": True}).content[0]["text"])
    assert unread["unread_only"] is True and everything["unread_only"] is False
    assert 0 < announcement_count(unread) < announcement_count(everything)


def announcement_count(overview: dict[str, Any]) -> int:
    return len(overview["announcements"]["announcements"])
