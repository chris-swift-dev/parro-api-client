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

import parro_mcp
from parro.api_client import ParroClient
from parro.http import HttpRequest
from tests import fakes, test_mcp
from tests.conftest import PROJECT_ROOT, load_sample

LEGACY_SERVER = PROJECT_ROOT / "legacy" / "parro_mcp_original.py"

pytestmark = pytest.mark.skipif(not LEGACY_SERVER.exists(), reason="legacy/ not present")


def without(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key not in keys}


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
    ("parro_announcements", {"limit": 3}, None),
    ("parro_announcements", {"limit": 20}, None),
    ("parro_announcements", {"group_id": 10000000000, "limit": 2}, None),
    ("parro_announcements", {"group_id": 10000000000, "unread_only": True}, None),
    (
        # Fix 8 (§4): `count` is the number of items shown, not the number fetched.
        "parro_calendar",
        {"limit": 2},
        lambda old, new: (without(old, "count"), without(new, "count")),
    ),
    ("parro_calendar", {"group_id": 10000000000}, None),
    ("parro_chatrooms", {}, None),
    ("parro_chatrooms", {"limit": 1}, None),
    ("parro_chat_messages", {"chatroom_id": 5}, None),
    ("parro_get", {"path": "/accountsettings"}, None),
    ("parro_get", {"path": "/systemnews", "limit": 2}, None),
    ("parro_get", {"path": "/absence/setting"}, None),
    ("parro_get", {"path": "/organisation/100000", "raw": True}, None),
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
    old = run_old_tool(tmp_path, monkeypatch, old_api, "parro_announcement", {"id": 11000000000})
    assert isinstance(old, str) and old.startswith("ERROR:")
    assert not (tmp_path / "tokens.json").exists(), "the original deleted the token file"

    new = run_new_tool(
        tmp_path, monkeypatch, fakes.FakeParroApi(load_sample), "parro_announcement", {"id": 1}
    )
    assert new["title"].startswith("Nieuwsbrief") and new["author"] == "Voorbeeld City"
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
    assert new_interface == old_interface
    assert list(new_interface) == list(old_interface), "same tools, same order"
