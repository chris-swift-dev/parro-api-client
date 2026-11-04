"""One function per user-facing command, shared by parro_cli.py and parro_mcp.py.

Each function fetches with ParroClient, shapes the result with summaries, and returns plain
JSON-ready data. Because both entry points call these same functions, a CLI command and the matching
MCP tool always give identical output.

`raw=True` skips the summary and returns the API's untouched payload.
"""

import json
from dataclasses import dataclass
from typing import Any

from . import attachments, summaries
from .api_client import ANNOUNCEMENT_LIST_DTYPE, CALENDAR_LIST_DTYPE, ParroClient
from .errors import AttachmentError, ConfigurationError, ParroError
from .settings import LoginMethod

# With unread_only, look further back per group than `limit`, so older unread items are not missed.
UNREAD_SCAN_PAGE_SIZE = 50


def to_json_text(data: Any, compact: bool = False) -> str:
    """The one JSON formatting used for output: UTF-8 text, indented unless `compact`."""
    if compact:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    return json.dumps(data, ensure_ascii=False, indent=1, default=str)


# ------------------------------------------------------------------------------- login


def auth_status(client: ParroClient) -> dict[str, Any]:
    """Login state, plus who is logged in. Never spends a password check (refresh is fine)."""
    status = client.authenticator.get_login_status()
    summary = summaries.summarize_login_status(
        status, client.settings.scope, client.settings.api_base_uri
    )
    if not (status.has_access_token or status.has_refresh_token):
        summary["error"] = "Not logged in. Run `parro_cli.py login` (MCP: parro_login)."
        return summary
    try:
        account = client.get_account(allow_password_login=False)
        role = client.get_role_header(allow_password_login=False)
        summary["logged_in_as"] = summaries.summarize_logged_in_account(account, role)
    except ParroError as problem:
        summary["error"] = str(problem)
    return summary


def login(
    client: ParroClient,
    method: LoginMethod | None = None,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    """Explicit login: clears the latch, spends one attempt (auto: at most two)."""
    client.authenticator.login(method=method, username=username, password=password)
    return auth_status(client)


def login_url(client: ParroClient) -> dict[str, Any]:
    url = client.authenticator.start_browser_login()
    return {
        "login_url": url,
        "instructions": [
            "Open login_url in a browser and log in with your ParnasSys account.",
            f"You end up on {client.settings.redirect_uri}?code=...&state=... Copy that full "
            "address right away: the Parro web app also tries to use the code, and a code works "
            "only once.",
            "Hand the copied address to login-finish (MCP: parro_login_finish). If it fails, "
            "start again with login-url.",
        ],
    }


def login_finish(client: ParroClient, redirect_url: str) -> dict[str, Any]:
    if not redirect_url or not redirect_url.strip():
        raise ConfigurationError("Pass the redirect URL (or just the code) from the browser.")
    client.authenticator.finish_browser_login(redirect_url)
    return auth_status(client)


def logout(client: ParroClient) -> dict[str, Any]:
    results = client.authenticator.logout()
    summary: dict[str, Any] = {
        "logged_out": True,
        "revocation_responses": [{result.token_kind: result.status} for result in results],
        "token_file": str(client.token_store.path),
    }
    halted_reason = client.token_store.get_login_halted_reason()
    if halted_reason:
        summary["automatic_login_halted"] = halted_reason
    return summary


def access_token(client: ParroClient) -> str:
    """A valid access token (refreshed if needed), e.g. to paste into Swagger UI."""
    return client.authenticator.get_access_token()


# --------------------------------------------------------------------- account, groups


def show_account(client: ParroClient, raw: bool = False) -> Any:
    account = client.get_account()
    if raw:
        return account
    return summaries.summarize_account(account, client.get_role_header())


def list_children(client: ParroClient, limit: int = 20, raw: bool = False) -> Any:
    response = client.list_children(limit=limit)
    return response.payload if raw else summaries.summarize_children(response)


def list_groups(
    client: ParroClient, scope: str = "current", limit: int = 50, raw: bool = False
) -> Any:
    scope_name = (scope or "current").strip().lower()
    if scope_name not in ("current", "previous"):
        raise ConfigurationError("scope must be 'current' or 'previous'.")
    response = client.list_groups(previous_year=scope_name == "previous", limit=limit)
    return response.payload if raw else summaries.summarize_groups(response, scope_name)


def show_unread_counts(client: ParroClient, raw: bool = False) -> Any:
    response = client.get_unread_counts()
    return response.payload if raw else summaries.summarize_unread_counts(response)


def list_system_news(client: ParroClient, limit: int = 20, raw: bool = False) -> Any:
    response = client.list_system_news(limit=limit)
    if raw:
        return response.payload
    return summaries.summarize_any_response(response)["body"] or {"items": []}


# ----------------------------------------------------------------------------- events


def list_announcements(
    client: ParroClient,
    group_id: int | None = None,
    limit: int = 20,
    unread_only: bool = False,
    raw: bool = False,
) -> Any:
    page_size = max(limit, UNREAD_SCAN_PAGE_SIZE) if unread_only else limit
    feed = client.collect_feed(ANNOUNCEMENT_LIST_DTYPE, group_id, limit_per_group=page_size)
    if raw:
        return [item.event for item in feed]
    return summaries.summarize_announcement_feed(feed, limit, unread_only)


def show_announcement(client: ParroClient, announcement_id: int | None, raw: bool = False) -> Any:
    event = client.get_announcement(require_id(announcement_id, "announcement id"))
    return event if raw else summaries.summarize_announcement_detail(event)


def list_calendar(
    client: ParroClient,
    group_id: int | None = None,
    limit: int = 20,
    event_dtype: str | None = None,
    raw: bool = False,
) -> Any:
    feed = client.collect_feed(event_dtype or CALENDAR_LIST_DTYPE, group_id, limit_per_group=limit)
    if raw:
        return [item.event for item in feed]
    return summaries.summarize_calendar_feed(feed, limit)


# ------------------------------------------------------------------------------ chats


def list_chatrooms(client: ParroClient, limit: int = 25, raw: bool = False) -> Any:
    response = client.list_chatrooms(limit=limit)
    return response.payload if raw else summaries.summarize_chatrooms(response)


def list_chat_messages(
    client: ParroClient, chatroom_id: int | None, limit: int = 30, raw: bool = False
) -> Any:
    response = client.list_chat_messages(require_id(chatroom_id, "chatroom id"), limit=limit)
    return response.payload if raw else summaries.summarize_chat_messages(response)


# ------------------------------------------------------------------------- attachments


@dataclass(frozen=True)
class AttachmentReport:
    """JSON-ready summary plus the photos (MCP shows them as images; the CLI leaves them out)."""

    summary: dict[str, Any]
    images: list[attachments.AttachmentImage]


def read_attachments(
    client: ParroClient,
    event_id: int | None = None,
    attachment_id: int | None = None,
    read_all: bool = False,
    url: str | None = None,
    filename: str | None = None,
    content_type: str | None = None,
    options: attachments.ReadOptions | None = None,
) -> AttachmentReport:
    """Read the attachment(s) of an announcement or calendar item, or of a direct url."""
    options = options or attachments.ReadOptions()
    if url:
        reading = attachments.read_attachment_file(
            client, url, filename, content_type, None, options
        )
        return AttachmentReport(reading.summary, [reading.image] if reading.image else [])
    if event_id is None:
        raise ConfigurationError("Give an announcement (or calendar item) id, or a direct url.")
    event = client.get_announcement_or_calendar_item(require_id(event_id, "event id"))
    title = event.get("title") or (event.get("calendarItem") or {}).get("title")
    files = choose_attachment_files(event, attachment_id, read_all)
    if files is None:
        return AttachmentReport(
            {
                "announcement": title,
                "message": "This event has several attachments. Ask for one with its "
                "attachment id, or read them all (MCP: all=true, CLI: --all).",
                "attachments": summaries.summarize_attachment_list(event),
            },
            [],
        )
    readings = [read_one_attachment(client, described, options) for described in files]
    images = [reading.image for reading in readings if reading.image]
    if len(readings) == 1:
        return AttachmentReport({**readings[0].summary, "announcement": title}, images)
    return AttachmentReport(
        {"announcement": title, "attachments": [r.summary for r in readings]}, images
    )


def choose_attachment_files(
    event: dict[str, Any], attachment_id: int | None, read_all: bool
) -> list[attachments.AttachmentFile] | None:
    """The files to read; None means "several, and the caller did not say which"."""
    files = [attachments.describe_attachment(a) for a in attachments.find_attachments(event)]
    if not files:
        raise AttachmentError("This event has no attachments.")
    if attachment_id is not None:
        files = [f for f in files if f.attachment_id == int(attachment_id)]
        if not files:
            raise AttachmentError(f"Attachment {attachment_id} is not on this event.")
        return files
    if len(files) > 1 and not read_all:
        return None
    return files


def read_one_attachment(
    client: ParroClient, described: attachments.AttachmentFile, options: attachments.ReadOptions
) -> attachments.AttachmentReading:
    """Read one file; a failure becomes an `error` entry, so the other files still get read."""
    try:
        if not described.url:
            raise AttachmentError("This attachment has no download url.")
        reading = attachments.read_attachment_file(
            client,
            described.url,
            described.filename,
            described.content_type,
            described.size,
            options,
        )
    except ParroError as problem:
        failed = {
            "attachment_id": described.attachment_id,
            "filename": described.filename,
            "error": str(problem),
        }
        return attachments.AttachmentReading(failed)
    return attachments.AttachmentReading(
        {**reading.summary, "attachment_id": described.attachment_id}, reading.image
    )


# --------------------------------------------------------------------------- anything


def get_any(
    client: ParroClient,
    path: str,
    params: dict[str, Any] | None = None,
    limit: int | None = None,
    offset: int = 0,
    raw: bool = False,
) -> dict[str, Any]:
    """GET any API path (read-only). Used for endpoints without a dedicated command."""
    if not path or not path.strip():
        raise ConfigurationError("Give a path, e.g. /accountsettings or /absence/setting.")
    response = client.get(path, params, limit=limit, offset=offset, count_total=True)
    return summaries.summarize_any_response(response, raw=raw)


def require_id(value: Any, what: str) -> int:
    """An id argument as int, with a usage error instead of a traceback when it is missing."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ConfigurationError(f"A numeric {what} is required.") from None
    if number <= 0:
        raise ConfigurationError(f"A numeric {what} is required.")
    return number
