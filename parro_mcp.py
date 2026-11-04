#!/usr/bin/env python3
"""parro_mcp.py: read-only MCP server for Parro (talk.parro.com), speaking JSON-RPC over stdio.

A drop-in replacement for the original server: the same 16 tool names, argument schemas and PARRO_*
environment variables (parro_login gained an optional `method`). All work is done by the shared
core in parro/ (via parro.operations), so tool output equals the matching parro_cli.py command's.

The protocol layer is hand-written with the standard library: handle_request() routes one JSON-RPC
message, list_tools() describes the tools, call_tool() runs one. stdout carries only protocol
messages; logs go to stderr.

Manual use without an MCP client:
    python parro_mcp.py tools
    python parro_mcp.py call parro_auth_status
    python parro_mcp.py call parro_attachment '{"announcement_id": 123, "max_chars": 2000}'

Inspired by fobatai/parro-mcp; independent implementation.
"""

import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from parro import __version__, operations
from parro.api_client import ParroClient
from parro.attachments import ReadOptions
from parro.errors import ConfigurationError, ParroError
from parro.settings import LOGIN_METHODS, Settings, parse_login_method

log = logging.getLogger("parro_mcp")

SERVER_NAME = "parro"
SERVER_VERSION = __version__
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INTERNAL_ERROR = -32603
# Tool errors start with this, as they always have, so existing clients can recognise them.
ERROR_PREFIX = "ERROR: "

LOCKOUT_WARNING = (
    "The ParnasSys IdP locks the account after a few failed logins: after one rejected password "
    "this server stops logging in on its own until parro_login is called explicitly."
)


# ---------------------------------------------------------------------------- tool schemas


def schema(properties: dict[str, Any] | None = None, required: list[str] | None = None,
           raw: bool = True) -> dict[str, Any]:  # fmt: skip
    """An inputSchema object; `raw` adds the common `raw` flag."""
    all_properties = dict(properties or {})
    if raw:
        all_properties["raw"] = {
            "type": "boolean",
            "description": "Give the API's untouched JSON instead of the compact summary.",
        }
    result: dict[str, Any] = {"type": "object", "properties": all_properties}
    if required:
        result["required"] = required
    return result


def integer(description: str | None = None, default: int | None = None) -> dict[str, Any]:
    field: dict[str, Any] = {"type": "integer"}
    if default is not None:
        field["default"] = default
    if description:
        field["description"] = description
    return field


def text(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def flag(description: str) -> dict[str, Any]:
    return {"type": "boolean", "description": description}


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "parro_auth_status",
        "description": "Login state: account, role header, token expiry, and whether automatic "
        "login is halted. Never spends a password check. Use this first when something fails.",
        "inputSchema": schema(raw=False),
    },
    {
        "name": "parro_login",
        "description": "Log in now with PARRO_USERNAME and the password from PARRO_PASSWORD_FILE "
        "or PARRO_PASSWORD. Usually not needed: tools log in and refresh by themselves. "
        f"{LOCKOUT_WARNING} This call clears that halt and spends exactly one attempt "
        "(method 'auto': at most two). Default method: PARRO_LOGIN_METHOD, else 'login-form'.",
        "inputSchema": schema(
            {
                "method": {
                    "type": "string",
                    "enum": list(LOGIN_METHODS),
                    "description": "login-form: like a browser, 1 password check. "
                    "password-grant: OAuth2 password grant, 1 check. "
                    "auto: password grant, then the form once (up to 2 checks).",
                }
            },
            raw=False,
        ),
    },
    {
        "name": "parro_login_url",
        "description": "Start a browser login without storing a password: returns a URL to open. "
        "Afterwards pass the address you land on to parro_login_finish.",
        "inputSchema": schema(raw=False),
    },
    {
        "name": "parro_login_finish",
        "description": "Finish the browser login with the https://talk.parro.com/oauth2?code=... "
        "address from the address bar. Copy it quickly: a code works only once.",
        "inputSchema": schema(
            {"url": text("The full redirect address, or only the code.")}, raw=False
        ),
    },
    {
        "name": "parro_logout",
        "description": "Revoke the tokens at the IdP and forget them locally.",
        "inputSchema": schema(raw=False),
    },
    {
        "name": "parro_me",
        "description": "The logged-in account: name, e-mail, account type and school.",
        "inputSchema": schema(),
    },
    {
        "name": "parro_children",
        "description": "Children linked to the account, with enrolment details.",
        "inputSchema": schema({"limit": integer(default=20)}),
    },
    {
        "name": "parro_groups",
        "description": "Groups (classes, school-wide) of the account, with unread counts and the "
        "ids that parro_announcements and parro_calendar accept.",
        "inputSchema": schema(
            {
                "scope": {
                    "type": "string",
                    "enum": ["current", "previous"],
                    "default": "current",
                    "description": "'current': this school year; 'previous': last year.",
                },
                "limit": integer(default=50),
            }
        ),
    },
    {
        "name": "parro_announcements",
        "description": "Announcements ('mededelingen') from teachers and school, the main feed. "
        "Without group_id all groups are merged, newest first. Includes the full text and the "
        "attachment list.",
        "inputSchema": schema(
            {
                "group_id": integer("Only this group (ids from parro_groups)."),
                "limit": integer(default=20),
                "unread_only": flag("Only announcements that are not read yet."),
            }
        ),
    },
    {
        "name": "parro_announcement",
        "description": "One announcement in full, with author and attachment details.",
        "inputSchema": schema({"id": integer()}, required=["id"]),
    },
    {
        "name": "parro_attachment",
        "description": "Read what is INSIDE an attachment, e.g. the newsletter ('nieuwsbrief') "
        "PDF: downloads it and returns the text, ready to summarise or search. Also reads .docx, "
        "text/csv and HTML; photos come back as (downscaled) images. Works for announcements and "
        "calendar items: pass announcement_id with that id, or a direct url.",
        "inputSchema": schema(
            {
                "announcement_id": integer("Announcement or calendar item with the attachment."),
                "attachment_id": integer("Which attachment, when there are several."),
                "all": flag("Read all attachments of the event."),
                "url": text("A direct attachment url instead of an event id."),
                "filename": text("With url: the file name, to choose the reader."),
                "content_type": text("With url: the content type, e.g. application/pdf."),
                "max_chars": integer("Cut the returned text off at this length.", default=40000),
                "no_images": flag("Do not return photos as image data."),
            },
            raw=False,
        ),
    },
    {
        "name": "parro_calendar",
        "description": "Calendar items (activities, parent evenings, trips), soonest first.",
        "inputSchema": schema(
            {
                "group_id": integer(),
                "limit": integer(default=20),
                "dtype": text("Event type to list; default event.RCalendarItemEventPrimer."),
            }
        ),
    },
    {
        "name": "parro_chatrooms",
        "description": "Chat conversations with teachers and other parents.",
        "inputSchema": schema({"limit": integer(default=25)}),
    },
    {
        "name": "parro_chat_messages",
        "description": "Messages of one chat conversation (ids from parro_chatrooms).",
        "inputSchema": schema(
            {"chatroom_id": integer(), "limit": integer(default=30)}, required=["chatroom_id"]
        ),
    },
    {
        "name": "parro_unread",
        "description": "Unread counts: announcements, calendar, chats, system news.",
        "inputSchema": schema(),
    },
    {
        "name": "parro_get",
        "description": "For endpoints without their own tool: GET any path below /rest/v2 "
        "(read-only) and return the compact JSON. Examples: /accountsettings, /absence/setting, "
        "/systemnews, /organisation/{id} (the school id is in parro_me).",
        "inputSchema": schema(
            {
                "path": text("e.g. /accountsettings"),
                "params": {
                    "type": "object",
                    "description": 'Query parameters, e.g. {"dtype": "..."}.',
                },
                "limit": integer("Page size (sends a Range header)."),
                "offset": integer(default=0),
            },
            required=["path"],
        ),
    },
]


# --------------------------------------------------------------------------- tool calling

ToolResult = Any  # JSON-ready data, or an operations.AttachmentReport
ToolFunction = Callable[[ParroClient, dict[str, Any]], ToolResult]


def integer_argument(arguments: dict[str, Any], name: str, default: int | None = None) -> Any:
    """An integer argument; MCP clients sometimes send numbers as strings."""
    value = arguments.get(name, default)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigurationError(f"`{name}` must be a whole number.") from None


def run_login(client: ParroClient, arguments: dict[str, Any]) -> ToolResult:
    method = arguments.get("method")
    return operations.login(client, method=parse_login_method(method) if method else None)


def run_attachment(client: ParroClient, arguments: dict[str, Any]) -> ToolResult:
    options = ReadOptions(
        max_chars=integer_argument(arguments, "max_chars", 40000),
        include_images=not arguments.get("no_images"),
    )
    return operations.read_attachments(
        client,
        event_id=integer_argument(arguments, "announcement_id"),
        attachment_id=integer_argument(arguments, "attachment_id"),
        read_all=bool(arguments.get("all")),
        url=arguments.get("url"),
        filename=arguments.get("filename"),
        content_type=arguments.get("content_type"),
        options=options,
    )


def raw(arguments: dict[str, Any]) -> bool:
    return bool(arguments.get("raw"))


TOOL_FUNCTIONS: dict[str, ToolFunction] = {
    "parro_auth_status": lambda c, a: operations.auth_status(c),
    "parro_login": run_login,
    "parro_login_url": lambda c, a: operations.login_url(c),
    "parro_login_finish": lambda c, a: operations.login_finish(c, str(a.get("url") or "")),
    "parro_logout": lambda c, a: operations.logout(c),
    "parro_me": lambda c, a: operations.show_account(c, raw=raw(a)),
    "parro_children": lambda c, a: operations.list_children(
        c, integer_argument(a, "limit", 20), raw=raw(a)
    ),
    "parro_groups": lambda c, a: operations.list_groups(
        c, str(a.get("scope") or "current"), integer_argument(a, "limit", 50), raw=raw(a)
    ),
    "parro_announcements": lambda c, a: operations.list_announcements(
        c,
        integer_argument(a, "group_id"),
        integer_argument(a, "limit", 20),
        bool(a.get("unread_only")),
        raw=raw(a),
    ),
    "parro_announcement": lambda c, a: operations.show_announcement(c, a.get("id"), raw=raw(a)),
    "parro_attachment": run_attachment,
    "parro_calendar": lambda c, a: operations.list_calendar(
        c,
        integer_argument(a, "group_id"),
        integer_argument(a, "limit", 20),
        a.get("dtype"),
        raw=raw(a),
    ),
    "parro_chatrooms": lambda c, a: operations.list_chatrooms(
        c, integer_argument(a, "limit", 25), raw=raw(a)
    ),
    "parro_chat_messages": lambda c, a: operations.list_chat_messages(
        c, a.get("chatroom_id"), integer_argument(a, "limit", 30), raw=raw(a)
    ),
    "parro_unread": lambda c, a: operations.show_unread_counts(c, raw=raw(a)),
    "parro_get": lambda c, a: operations.get_any(
        c,
        str(a.get("path") or ""),
        a.get("params") or None,
        integer_argument(a, "limit"),
        integer_argument(a, "offset", 0),
        raw=raw(a),
    ),
}


@dataclass(frozen=True)
class ToolCallResult:
    content: list[dict[str, Any]]
    is_error: bool


def to_content_blocks(result: ToolResult) -> list[dict[str, Any]]:
    """MCP content: one JSON text block, plus an image block per photo of an attachment."""
    if isinstance(result, operations.AttachmentReport):
        blocks = [{"type": "text", "text": operations.to_json_text(result.summary)}]
        for image in result.images:
            blocks.append({"type": "image", "data": image.base64_data, "mimeType": image.mime_type})
        return blocks
    return [{"type": "text", "text": operations.to_json_text(result)}]


class McpServer:
    """The tools and the JSON-RPC routing. One ParroClient is kept for the server's lifetime."""

    def __init__(self, make_client: Callable[[Settings], ParroClient] = ParroClient) -> None:
        self.make_client = make_client
        self._client: ParroClient | None = None

    def get_client(self) -> ParroClient:
        """The shared client, created on first use (so a settings error is a tool error)."""
        if self._client is None:
            self._client = self.make_client(Settings.from_environment())
        # Pick up logins done meanwhile by parro_cli.py or another server process.
        self._client.token_store.reload()
        return self._client

    def list_tools(self) -> list[dict[str, Any]]:
        return TOOL_DEFINITIONS

    def call_tool(self, name: str, arguments: dict[str, Any] | None) -> ToolCallResult:
        tool = TOOL_FUNCTIONS.get(name)
        if tool is None:
            return error_result(f"unknown tool: {name}")
        try:
            result = tool(self.get_client(), dict(arguments or {}))
        except ParroError as problem:
            return error_result(str(problem))
        except Exception as unexpected:  # keep serving: one broken call must not end the session
            log.exception("tool %s failed unexpectedly", name)
            return error_result(f"internal error in {name}: {type(unexpected).__name__}")
        return ToolCallResult(to_content_blocks(result), is_error=False)

    def handle_request(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Answer one JSON-RPC message. Notifications (no id) get no answer."""
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        if method == "initialize":
            return reply(request_id, self.describe_server(params))
        if method == "ping":
            return reply(request_id, {})
        if method == "tools/list":
            return reply(request_id, {"tools": self.list_tools()})
        if method == "tools/call":
            outcome = self.call_tool(str(params.get("name", "")), params.get("arguments"))
            return reply(request_id, {"content": outcome.content, "isError": outcome.is_error})
        if method in ("resources/list", "prompts/list"):
            return reply(request_id, {method.split("/")[0]: []})
        if request_id is None:  # a notification, e.g. notifications/initialized
            return None
        return error_reply(request_id, JSONRPC_METHOD_NOT_FOUND, f"Method not found: {method}")

    @staticmethod
    def describe_server(params: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocolVersion": params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }


def error_result(message: str) -> ToolCallResult:
    return ToolCallResult([{"type": "text", "text": ERROR_PREFIX + message}], is_error=True)


def reply(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_reply(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


# ------------------------------------------------------------------------------------ main


def serve_stdio(server: McpServer) -> None:
    """Read one JSON-RPC message per line from stdin, write answers to stdout."""
    log.info("started; API at %s", Settings.from_environment().api_base_uri)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as problem:
            log.warning("ignoring a line that is not JSON: %s", problem.msg)
            write_message(error_reply(None, JSONRPC_PARSE_ERROR, "Parse error"))
            continue
        try:
            answer = server.handle_request(message) if isinstance(message, dict) else None
        except Exception:
            log.exception("could not handle a request")
            answer = error_reply(message.get("id"), JSONRPC_INTERNAL_ERROR, "Internal error")
        if answer is not None:
            write_message(answer)
    log.info("stdin closed; stopping")


def write_message(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def run_manual_command(server: McpServer, argv: list[str]) -> int:
    """`tools` lists the tools; `call <name> [json-arguments]` runs one and prints the result."""
    if argv[0] == "tools":
        for tool in server.list_tools():
            print(f"{tool['name']:22s} {tool['description'].split('. ')[0]}")
        return 0
    name = argv[1] if len(argv) > 1 else "parro_auth_status"
    arguments = json.loads(argv[2]) if len(argv) > 2 else {}
    outcome = server.call_tool(name, arguments)
    for block in outcome.content:
        if block["type"] == "image":
            print(f"<image {block['mimeType']}, {len(block['data'])} base64 characters>")
        else:
            print(block["text"])
    return 1 if outcome.is_error else 0


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    logging.basicConfig(level=logging.INFO, format="[parro-mcp] %(message)s", stream=sys.stderr)
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    server = McpServer()
    if arguments and arguments[0] in ("tools", "call"):
        return run_manual_command(server, arguments)
    serve_stdio(server)
    return 0


if __name__ == "__main__":
    sys.exit(main())
