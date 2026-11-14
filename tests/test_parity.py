"""Behaviour comparison: the original MCP server and the new core, on the same fake responses.

This compares *output*, never code (PLAN-api-client §0b, §7). The original is only executed, with
its HTTP function replaced by the fake transport. Differences are allowed only where §4 lists a
fix; each one is spelled out next to its case in CASES below.

Skipped when legacy/parro_mcp_original.py is absent (it is never committed).
"""

import importlib.util
import json
import os
import time
from collections.abc import Callable
from typing import Any

import pytest

from parro import mcp_server as parro_mcp
from parro.api_client import ParroClient
from parro.http import HttpRequest
from tests import fakes, test_mcp
from tests.conftest import PROJECT_ROOT, load_sample

LEGACY_SERVER = PROJECT_ROOT / "legacy" / "parro_mcp_original.py"

pytestmark = pytest.mark.skipif(not LEGACY_SERVER.exists(), reason="legacy/ not present")


def without(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key not in keys}


# Fields the new feed adds (PLAN-readable-output phase 3); the original never had them.
ADDED_ANNOUNCEMENT_FIELDS = ("author", "pinned", "groups")
# 0.13: what kind of media an attachment is, and whether it has a small picture.
ADDED_ATTACHMENT_FIELDS = ("media", "has_thumbnail")


def without_added_fields(item: dict[str, Any]) -> dict[str, Any]:
    stripped = without(item, *ADDED_ANNOUNCEMENT_FIELDS)
    if "attachments" in stripped:
        stripped["attachments"] = [
            without(a, *ADDED_ATTACHMENT_FIELDS) for a in stripped["attachments"]
        ]
    return stripped


def without_attachments(result: dict[str, Any], *keys: str) -> dict[str, Any]:
    """0.13: a message's attachment is compact, as an event's is; the original passed the raw
    object on. The messages themselves must still be the same."""
    # Also 0.13: `yours` marks the messages you wrote, the ones you can delete.
    messages = [without(message, "attachment", "yours") for message in result["messages"]]
    return {**without(result, *keys), "messages": messages}


def merged_feed(old: Any, new: Any) -> tuple[Any, Any]:
    """The original lists an announcement once per group; the new feed once (phase 3).

    Merge the original's duplicates, ignore the added fields, and compare as many items as the
    merged original has left (the new feed fills the freed places with older items).
    """
    seen: set[Any] = set()
    old_items = []
    for item in old["announcements"]:
        if item["id"] not in seen:
            seen.add(item["id"])
            old_items.append(item)
    new_items = [without_added_fields(item) for item in new["announcements"][: len(old_items)]]
    return old_items, new_items


def single_group_feed(old: Any, new: Any) -> tuple[Any, Any]:
    stripped = [without_added_fields(item) for item in new["announcements"]]
    return old, {**new, "announcements": stripped}


# Each entry: (tool, arguments, how old and new may differ). None = must be identical.
Adjust = Callable[[Any, Any], tuple[Any, Any]] | None
CASES: list[tuple[str, dict[str, Any], Adjust]] = [
    (
        # New: login_method is reported. The expiry is computed from the clock: may differ by 1 s.
        "parro_auth_status",
        {},
        lambda old, new: (
            without(old, "access_token_expires_in_seconds"),
            without(new, "access_token_expires_in_seconds", "login_method"),
        ),
    ),
    ("parro_me", {}, None),
    ("parro_me", {"raw": True}, None),
    ("parro_children", {}, None),
    ("parro_children", {"limit": 1}, None),
    ("parro_groups", {}, None),
    ("parro_groups", {"scope": "previous"}, None),
    ("parro_unread", {}, None),
    ("parro_announcements", {"limit": 3}, merged_feed),
    ("parro_announcements", {"limit": 20}, merged_feed),
    ("parro_announcements", {"group_id": fakes.GROUP_3, "limit": 2}, single_group_feed),
    ("parro_announcements", {"group_id": fakes.GROUP_3, "unread_only": True}, single_group_feed),
    # parro_calendar is not compared: the original sorted the API's first page, which holds the
    # furthest-future items (seen live 2026-11-05), so it never showed the coming weeks. The new
    # client pages to today (PLAN-readable-output, live look). Covered by test_calendar_*.
    ("parro_chatrooms", {}, None),
    ("parro_chatrooms", {"limit": 1}, None),
    # New: the messages name their chatroom (PLAN-readable-output phase 4).
    (
        "parro_chat_messages",
        {"chatroom_id": 8000000001},
        lambda old, new: (without_attachments(old), without_attachments(new, "chatroom_id")),
    ),
    ("parro_get", {"path": "/accountsettings"}, None),
    ("parro_get", {"path": "/systemnews", "limit": 2}, None),
    ("parro_get", {"path": "/absence/setting"}, None),
    ("parro_get", {"path": "/organisation/400100", "raw": True}, None),
]


def seed_tokens(path) -> None:
    path.write_text(
        json.dumps(
            {
                "access_token": fakes.ACCESS_TOKEN,
                "refresh_token": fakes.REFRESH_TOKEN,
                "expires_at": time.time() + 3000,
                "obtained_at": time.time(),
            }
        )
    )


def run_old_tool(
    tmp_path, monkeypatch, api: fakes.FakeParroApi, tool: str, args: dict[str, Any]
) -> Any:
    token_file = tmp_path / "tokens.json"  # same path as the new run: it is part of the output
    seed_tokens(token_file)
    for name in list(os.environ):
        if name.startswith("PARRO_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("PARRO_TOKEN_FILE", str(token_file))
    spec = importlib.util.spec_from_file_location("parro_mcp_original", LEGACY_SERVER)
    assert spec and spec.loader
    old_server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old_server)

    def fake_request(method, url, headers=None, body=None, opener=None, redirect=True):
        answer = api.send(HttpRequest(method, url, dict(headers or {}), body, redirect))
        # Real servers send e.g. 'Content-Type'; the fake stores lower case. Restore the case.
        headers = {name.title(): value for name, value in answer.headers.items()}
        return answer.status, headers, answer.body

    monkeypatch.setattr(old_server, "_request", fake_request)
    result = old_server.call_tool(tool, args)
    return result if result.startswith("ERROR:") else json.loads(result)


def run_new_tool(
    tmp_path, monkeypatch, api: fakes.FakeParroApi, tool: str, args: dict[str, Any]
) -> Any:
    """Call the tool through the new MCP server (parro_mcp.McpServer), like a client would."""
    token_file = tmp_path / "tokens.json"
    seed_tokens(token_file)
    monkeypatch.setenv("PARRO_TOKEN_FILE", str(token_file))
    server = parro_mcp.McpServer(make_client=lambda s: ParroClient(s, transport=api))
    outcome = server.call_tool(tool, args)
    text = outcome.content[0]["text"]
    return text if outcome.is_error else json.loads(text)


@pytest.mark.parametrize(("tool", "args", "adjust"), CASES, ids=lambda v: str(v)[:40])
def test_old_and_new_give_the_same_output(tmp_path, monkeypatch, tool, args, adjust):
    old = run_old_tool(tmp_path, monkeypatch, fakes.FakeParroApi(load_sample), tool, args)
    new = run_new_tool(tmp_path, monkeypatch, fakes.FakeParroApi(load_sample), tool, args)
    if adjust is not None:
        old, new = adjust(old, new)
    assert new == old


def test_fix_2_and_3_single_announcement_works_where_the_original_failed(tmp_path, monkeypatch):
    old_api = fakes.FakeParroApi(load_sample)
    old = run_old_tool(
        tmp_path, monkeypatch, old_api, "parro_announcement", {"id": fakes.NEWSLETTER_ID}
    )
    assert isinstance(old, str) and old.startswith("ERROR:")
    assert not (tmp_path / "tokens.json").exists(), "the original deleted the token file"

    new = run_new_tool(
        tmp_path, monkeypatch, fakes.FakeParroApi(load_sample), "parro_announcement", {"id": 1}
    )
    assert new["title"].startswith("Nieuwsbrief") and new["author"] == "Lotte Bakker"
    assert json.loads((tmp_path / "tokens.json").read_text())["refresh_token"]


ATTACHMENT_BODIES = {
    "https://cdn.example/brief.txt": ("text/plain", b"Beste ouders,\r\n\r\n\r\nTot  ziens"),
    "https://cdn.example/page.html": ("text/html", b"<p>Hallo &amp; welkom</p><p>Doei</p>"),
}


@pytest.mark.parametrize(
    "args",
    [
        {"url": "https://cdn.example/brief.txt"},
        {"url": "https://cdn.example/brief.txt", "max_chars": 5},
        {"url": "https://cdn.example/page.html", "filename": "nieuws.html"},
    ],
    ids=["text", "text-truncated", "html"],
)
def test_attachment_by_url_matches(tmp_path, monkeypatch, args):
    def api_with_files() -> fakes.FakeParroApi:
        return fakes.FakeParroApi(load_sample, attachment_bodies=dict(ATTACHMENT_BODIES))

    old = run_old_tool(tmp_path, monkeypatch, api_with_files(), "parro_attachment", args)
    new = run_new_tool(tmp_path, monkeypatch, api_with_files(), "parro_attachment", args)
    assert new == old


def test_tools_list_matches_the_original_plus_the_login_method(tmp_path, monkeypatch):
    run_old_tool(tmp_path, monkeypatch, fakes.FakeParroApi(load_sample), "parro_unread", {})
    spec = importlib.util.spec_from_file_location("parro_mcp_original", LEGACY_SERVER)
    assert spec and spec.loader
    old_server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old_server)
    old_tools = old_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    old_interface = test_mcp.interface_of(old_tools["result"]["tools"])
    new_interface = test_mcp.interface_of(parro_mcp.McpServer().list_tools())
    method = new_interface["parro_login"]["properties"].pop("method")
    assert method["enum"] == ["login-form", "password-grant", "auto"]
    for tool in new_interface.values():  # PLAN-readable-output: optional `format` everywhere
        assert tool["properties"].pop("format")["default"] == "json"
    assert new_interface["parro_calendar"]["properties"].pop("details")["type"] == "boolean"
    assert new_interface["parro_calendar"]["properties"].pop("past")["type"] == "boolean"
    chatrooms = new_interface["parro_chatrooms"]["properties"]
    assert {chatrooms.pop(k)["type"] for k in ("unread", "archived", "type", "schoolyear")} == {
        "boolean",
        "string",
        "integer",
    }
    assert new_interface["parro_chat_messages"]["properties"].pop("since")["type"] == "string"
    attachment = new_interface["parro_attachment"]["properties"]  # 0.13: a chat message's file
    assert {attachment.pop(k)["type"] for k in ("chatroom_id", "message_id")} == {"integer"}
    assert new_interface.pop("parro_overview") == {"properties": {"all": {"type": "boolean"}}}
    assert new_interface.pop("parro_calendar_link") == {"properties": {}}
    assert set(new_interface.pop("parro_privacy")["properties"]) == {"child_id", "link", "raw"}
    assert set(new_interface.pop("parro_chat_members")["properties"]) == {
        "chatroom_id",
        "include_former",
        "raw",
    }
    assert new_interface == old_interface
    assert list(new_interface) == list(old_interface), "same tools, same order"
