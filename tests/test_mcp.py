"""Phase 6: the MCP server: tool list compatibility, JSON-RPC handling, every tool, stdio."""

import json
import os
import subprocess
import sys
import time
from typing import Any

import pytest

from parro import mcp_server as parro_mcp
from parro.api_client import ParroClient
from tests import fakes
from tests.conftest import PROJECT_ROOT, load_sample

# The original server's tool interface (names and argument schemas, descriptions left out).
# Existing MCP clients depend on it, so it must not change; parro_login only gains `method`.
ORIGINAL_TOOL_INTERFACE: dict[str, dict[str, Any]] = {
    "parro_auth_status": {"properties": {}},
    "parro_login": {"properties": {}},
    "parro_login_url": {"properties": {}},
    "parro_login_finish": {"properties": {"url": {"type": "string"}}},
    "parro_logout": {"properties": {}},
    "parro_me": {"properties": {"raw": {"type": "boolean"}}},
    "parro_children": {
        "properties": {"limit": {"type": "integer", "default": 20}, "raw": {"type": "boolean"}}
    },
    "parro_groups": {
        "properties": {
            "scope": {"type": "string", "enum": ["current", "previous"], "default": "current"},
            "limit": {"type": "integer", "default": 50},
            "raw": {"type": "boolean"},
        }
    },
    "parro_announcements": {
        "properties": {
            "group_id": {"type": "integer"},
            "limit": {"type": "integer", "default": 20},
            "unread_only": {"type": "boolean"},
            "raw": {"type": "boolean"},
        }
    },
    "parro_announcement": {
        "properties": {"id": {"type": "integer"}, "raw": {"type": "boolean"}},
        "required": ["id"],
    },
    "parro_attachment": {
        "properties": {
            "announcement_id": {"type": "integer"},
            "attachment_id": {"type": "integer"},
            "all": {"type": "boolean"},
            "url": {"type": "string"},
            "filename": {"type": "string"},
            "content_type": {"type": "string"},
            "max_chars": {"type": "integer", "default": 40000},
            "no_images": {"type": "boolean"},
        }
    },
    "parro_calendar": {
        "properties": {
            "group_id": {"type": "integer"},
            "limit": {"type": "integer", "default": 20},
            "dtype": {"type": "string"},
            "raw": {"type": "boolean"},
        }
    },
    "parro_chatrooms": {
        "properties": {"limit": {"type": "integer", "default": 25}, "raw": {"type": "boolean"}}
    },
    "parro_chat_messages": {
        "properties": {
            "chatroom_id": {"type": "integer"},
            "limit": {"type": "integer", "default": 30},
            "raw": {"type": "boolean"},
        },
        "required": ["chatroom_id"],
    },
    "parro_unread": {"properties": {"raw": {"type": "boolean"}}},
    "parro_get": {
        "properties": {
            "path": {"type": "string"},
            "params": {"type": "object"},
            "limit": {"type": "integer"},
            "offset": {"type": "integer", "default": 0},
            "raw": {"type": "boolean"},
        },
        "required": ["path"],
    },
}


def interface_of(tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Tool name → inputSchema without descriptions (the part clients depend on)."""

    def without_descriptions(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: without_descriptions(v) for k, v in value.items() if k != "description"}
        return value

    return {
        tool["name"]: without(without_descriptions(tool["inputSchema"]), "type") for tool in tools
    }


def without(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k not in keys}


@pytest.fixture
def server(tmp_path, monkeypatch) -> tuple[parro_mcp.McpServer, fakes.FakeParroApi]:
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
    api = fakes.FakeParroApi(load_sample)
    return parro_mcp.McpServer(make_client=lambda s: ParroClient(s, transport=api)), api


# ------------------------------------------------------------------------- tool interface


FORMAT_ARGUMENT = {"type": "string", "enum": ["json", "markdown"], "default": "json"}


def test_tool_interface_only_gains_optional_arguments():
    """The original, plus `method` (parro_login), `details` (parro_calendar), `format` (all),
    and three new tools at the end."""
    expected = json.loads(json.dumps(ORIGINAL_TOOL_INTERFACE))
    expected["parro_login"]["properties"]["method"] = {
        "type": "string",
        "enum": ["login-form", "password-grant", "auto"],
    }
    expected["parro_calendar"]["properties"]["details"] = {"type": "boolean"}
    expected["parro_calendar"]["properties"]["past"] = {"type": "boolean"}
    expected["parro_chatrooms"]["properties"].update(
        unread={"type": "boolean"},
        archived={"type": "string", "enum": ["exclude", "only", "include"], "default": "exclude"},
        type={"type": "string", "enum": ["single", "bot", "calendar", "group", "family"]},
        schoolyear={"type": "integer"},
    )
    expected["parro_chat_messages"]["properties"]["since"] = {"type": "string"}
    expected["parro_attachment"]["properties"].update(
        chatroom_id={"type": "integer"}, message_id={"type": "integer"}
    )
    expected["parro_overview"] = {
        "properties": {"all": {"type": "boolean"}}
    }  # new tools, at the end
    expected["parro_calendar_link"] = {"properties": {}}
    expected["parro_privacy"] = {
        "properties": {
            "child_id": {"type": "integer"},
            "link": {"type": "boolean", "default": False},
            "raw": {"type": "boolean"},
        }
    }
    expected["parro_chat_members"] = {
        "properties": {
            "chatroom_id": {"type": "integer"},
            "include_former": {"type": "boolean"},
            "raw": {"type": "boolean"},
        },
        "required": ["chatroom_id"],
    }
    for tool in expected.values():
        tool["properties"]["format"] = FORMAT_ARGUMENT
    assert interface_of(parro_mcp.TOOL_DEFINITIONS) == expected
    names = list(interface_of(parro_mcp.TOOL_DEFINITIONS))
    assert names[: len(ORIGINAL_TOOL_INTERFACE)] == list(ORIGINAL_TOOL_INTERFACE), "same order"


def test_every_tool_has_an_implementation_and_a_description():
    every_tool = [
        *parro_mcp.TOOL_DEFINITIONS,
        parro_mcp.MARK_READ_TOOL,
        parro_mcp.SEND_CHAT_TOOL,
        parro_mcp.DELETE_CHAT_TOOL,
        parro_mcp.HELPER_SIGNUP_TOOL,
        parro_mcp.HELPER_WITHDRAW_TOOL,
        parro_mcp.RSVP_TOOL,
    ]
    assert set(parro_mcp.TOOL_FUNCTIONS) == {t["name"] for t in every_tool}
    for tool in every_tool:
        assert len(tool["description"]) > 30


def test_login_tool_carries_the_lockout_warning_and_method_hint():
    login = next(t for t in parro_mcp.TOOL_DEFINITIONS if t["name"] == "parro_login")
    assert "locks the account" in login["description"]
    assert "login-form" in login["description"]


# ----------------------------------------------------------------------------- JSON-RPC


def test_initialize_ping_and_notifications(server):
    mcp, _ = server
    answer = mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
    )
    assert answer is not None
    assert answer["result"]["protocolVersion"] == "2024-11-05"
    assert answer["result"]["serverInfo"]["name"] == "parro"
    assert mcp.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert mcp.handle_request({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {}
    unknown = mcp.handle_request({"jsonrpc": "2.0", "id": 3, "method": "bogus"})
    assert unknown["error"]["code"] == -32601
    assert mcp.handle_request({"jsonrpc": "2.0", "id": 4, "method": "prompts/list"})["result"] == {
        "prompts": []
    }


def call(
    mcp: parro_mcp.McpServer, name: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    answer = mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    assert answer is not None
    result: dict[str, Any] = answer["result"]
    return result


TOOL_CALLS = [
    ("parro_auth_status", {}),
    ("parro_me", {}),
    ("parro_children", {"limit": "2"}),
    ("parro_groups", {"scope": "previous"}),
    ("parro_announcements", {"limit": 2, "unread_only": True}),
    ("parro_announcement", {"id": fakes.NEWSLETTER_ID}),
    ("parro_calendar", {"limit": 1, "raw": True}),
    ("parro_chatrooms", {}),
    ("parro_chat_messages", {"chatroom_id": 8000000001}),
    ("parro_unread", {}),
    ("parro_get", {"path": "/systemnews", "limit": 1, "params": {}}),
    ("parro_login_url", {}),
]


@pytest.mark.parametrize(("name", "arguments"), TOOL_CALLS, ids=[c[0] for c in TOOL_CALLS])
def test_every_reading_tool_answers(server, name, arguments):
    mcp, api = server
    result = call(mcp, name, arguments)
    assert result["isError"] is False, result
    (block,) = result["content"]
    json.loads(block["text"])
    assert {r.method for r in api.api_requests()} <= {"GET"}


def test_tool_errors_are_reported_not_raised(server):
    mcp, _ = server
    for name, arguments, expected in [
        ("parro_nope", {}, "unknown tool"),
        ("parro_announcement", {}, "announcement id"),
        ("parro_chat_messages", {"chatroom_id": "x"}, "chatroom id"),
        ("parro_children", {"limit": "many"}, "whole number"),
        ("parro_get", {"path": "https://evil.example/"}, "not a full URL"),
        ("parro_get", {"path": "/event/1"}, "EVENT_BAD_TYPE"),
        ("parro_login", {"method": "magic"}, "Unknown login method"),
        ("parro_login_finish", {}, "redirect URL"),
    ]:
        result = call(mcp, name, arguments)
        assert result["isError"] is True
        assert result["content"][0]["text"].startswith("ERROR: ")
        assert expected in result["content"][0]["text"], name


def test_unexpected_exceptions_do_not_end_the_session(server, monkeypatch):
    mcp, _ = server

    def broken(client, arguments):
        raise RuntimeError("boom")

    monkeypatch.setitem(parro_mcp.TOOL_FUNCTIONS, "parro_unread", broken)
    result = call(mcp, "parro_unread")
    assert result["isError"] is True and "RuntimeError" in result["content"][0]["text"]


def test_attachment_photo_is_returned_as_an_image_block(server):
    mcp, api = server
    event = load_sample("getEvent_calendar-7000000301.200.json")
    api.attachment_bodies[event["calendarItem"]["attachments"][0]["entries"][0]["url"]] = (
        "image/jpeg",
        b"\xff\xd8 jpeg",
    )
    result = call(mcp, "parro_attachment", {"announcement_id": fakes.MUSEUM_TRIP_ID})
    text_block, image_block = result["content"]
    assert json.loads(text_block["text"])["returned_as"] == "image"
    assert image_block["type"] == "image" and image_block["mimeType"] == "image/jpeg"
    without_images = call(
        mcp, "parro_attachment", {"announcement_id": fakes.MUSEUM_TRIP_ID, "no_images": True}
    )
    assert len(without_images["content"]) == 1


def test_logins_by_the_cli_are_picked_up(server, tmp_path):
    mcp, _ = server
    assert call(mcp, "parro_me")["isError"] is False
    (tmp_path / "tokens.json").unlink()  # e.g. `parro_cli.py logout` in another terminal
    result = call(mcp, "parro_me")
    assert result["isError"] is False, "the account is cached; no token needed"
    status = json.loads(call(mcp, "parro_auth_status")["content"][0]["text"])
    assert status["has_access_token"] is False


# --------------------------------------------------------------------------------- stdio


def run_server(tmp_path, stdin_text: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = {k: v for k, v in os.environ.items() if not k.startswith("PARRO_")}
    environment["PARRO_TOKEN_FILE"] = str(tmp_path / "no-tokens.json")
    environment["PARRO_DATA_DIR"] = str(tmp_path / "data")
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "parro_mcp.py"), *arguments],
        input=stdin_text,
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
        check=False,
    )


def test_stdio_session_without_network(tmp_path):
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "parro_auth_status"},
        },
    ]
    stdin_text = "\n".join(json.dumps(line) for line in lines) + "\nnot json\n"
    finished = run_server(tmp_path, stdin_text)
    answers = [json.loads(line) for line in finished.stdout.splitlines()]
    assert [a.get("id") for a in answers] == [1, 2, 3, None]
    assert answers[0]["result"]["protocolVersion"] == "2025-06-18"
    assert len(answers[1]["result"]["tools"]) == 20
    status = json.loads(answers[2]["result"]["content"][0]["text"])
    assert status["has_access_token"] is False and "Not logged in" in status["error"]
    assert answers[3]["error"]["code"] == -32700
    assert "[parro-mcp]" in finished.stderr, "logs go to stderr, never stdout"


def test_manual_tools_and_call_commands(tmp_path):
    listed = run_server(tmp_path, "", "tools")
    assert listed.returncode == 0 and len(listed.stdout.splitlines()) == 20
    called = run_server(tmp_path, "", "call", "parro_auth_status")
    assert called.returncode == 0
    assert json.loads(called.stdout)["has_access_token"] is False
