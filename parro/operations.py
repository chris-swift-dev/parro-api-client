"""One function per user-facing command, shared by the CLI (parro/cli.py) and the MCP server.

Each function fetches with ParroClient, shapes the result with summaries, and returns plain
JSON-ready data. Because both entry points call these same functions, a CLI command and the matching
MCP tool always give identical output.

`raw=True` skips the summary and returns the API's untouched payload.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

from . import archive, attachments, rendering, summaries
from .api_client import (
    ANNOUNCEMENT_LIST_DTYPE,
    CALENDAR_LIST_DTYPE,
    RSVP_ANSWERS,
    ApiResponse,
    FeedEvent,
    ParroClient,
    ReadStateKind,
)
from .errors import AttachmentError, ConfigurationError, ParroError
from .geon import get_object_id, strip_geon_metadata
from .naming import cli_command
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
        summary["error"] = f"Not logged in. Run `{cli_command('login')}` (MCP: parro_login)."
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


def show_announcement(
    client: ParroClient, announcement_id: int | None, raw: bool = False, mark_read: bool = False
) -> Any:
    """One announcement; with `mark_read`, marked as read once it has been fetched to show."""
    event_id = require_id(announcement_id, "announcement id")
    event = client.get_announcement(event_id)
    marked = (
        mark_if_unread(client, "announcement", event_id, event.get("read")) if mark_read else None
    )
    if raw:
        return event
    result = summaries.summarize_announcement_detail(event)
    if marked is not None:
        result["marked_read"] = marked
    return result


CALENDAR_PAGE_SIZE = 50
# A school year has a few hundred items at most; this many pages per group is a safe ceiling.
CALENDAR_MAX_PAGES = 20


def current_time() -> datetime:
    """Now, as an aware datetime. One place, so tests can fix the date."""
    return datetime.now(timezone.utc)


def list_calendar(
    client: ParroClient,
    group_id: int | None = None,
    limit: int = 20,
    event_dtype: str | None = None,
    raw: bool = False,
    details: bool = False,
    past: bool = False,
) -> Any:
    """Calendar items from today on, soonest first; with `past`, earlier items, latest first.

    `details` adds location, description and attachments per shown item: one extra request each
    (cached), because the list does not include them (spec).
    """
    now = current_time()
    groups = None if group_id is not None else client.list_current_group_names()
    feed = collect_calendar(client, event_dtype, group_id, groups, now, past, limit)
    if raw:
        return [item.event for item in feed]
    agenda = choose_period(summaries.summarize_calendar_feed(feed, len(feed)), now, past, limit)
    if details:
        for item in agenda["items"]:
            item["details"] = calendar_details(client, item)
    return agenda


def collect_calendar(
    client: ParroClient,
    event_dtype: str | None,
    group_id: int | None,
    groups: dict[int, str | None] | None,
    now: datetime,
    past: bool,
    wanted: int,
) -> list[FeedEvent]:
    """Calendar items of one group or of every current group, read far enough to reach today.

    The API lists calendar items furthest future first (seen live: the whole-school group's first
    50 of 100 items were 6-9 months ahead). So pages are read until an item lies before today;
    for past items, until `wanted` of them are in.
    """
    chosen = {int(group_id): None} if group_id is not None else dict(groups or {})
    collected: list[FeedEvent] = []
    for one_group_id, group_name in chosen.items():
        offset, past_items = 0, 0
        for _page_number in range(CALENDAR_MAX_PAGES):
            page = client.list_events(
                one_group_id,
                event_dtype or CALENDAR_LIST_DTYPE,
                limit=CALENDAR_PAGE_SIZE,
                offset=offset,
                count_total=True,
            )
            collected.extend(FeedEvent(event, group_name) for event in page.items)
            offset += len(page.items)
            past_items += sum(summaries.is_over(event, now) for event in page.items)
            reached = past_items >= wanted if past else past_items > 0
            if reached or not page.items or (page.total is not None and offset >= page.total):
                break
    return collected


def choose_period(agenda: dict[str, Any], now: datetime, past: bool, limit: int) -> dict[str, Any]:
    """Upcoming items soonest first, or past items latest first; `period` says which."""
    if past:
        items = [item for item in agenda["items"] if summaries.is_over(item, now)][::-1]
    else:
        items = [item for item in agenda["items"] if not summaries.is_over(item, now)]
    shown = items[:limit]
    return {"count": len(shown), "period": "past" if past else "upcoming", "items": shown}


def calendar_details(client: ParroClient, item: dict[str, Any]) -> dict[str, Any]:
    """Details of one calendar item: from the cache while the list shows the same version.

    Items that ask for helpers are always fetched: the number of parents who signed up changes,
    and it is not known whether that changes the item's version.
    """
    event_id = require_id(item.get("id"), "calendar item id")
    calendar_item = item.get("calendarItem") or {}
    if summaries.wants_helpers(calendar_item):
        return summaries.summarize_calendar_details(client.get_calendar_item(event_id))
    version = f"{item.get('lastModifiedAt')}|{calendar_item.get('lastModifiedAt')}"
    cached = client.cache.get_json("events", f"{event_id}.json")
    if isinstance(cached, dict) and cached.get("version") == version:
        return dict(cached.get("details") or {})
    details = summaries.summarize_calendar_details(client.get_calendar_item(event_id))
    client.cache.put_json("events", f"{event_id}.json", {"version": version, "details": details})
    return details


# ------------------------------------------------------------------------------ privacy

PRIVACY_LINK_WARNING = (
    "This link is signed and opens the page without logging in: anyone who has it can see and "
    "change your child's privacy choices. Open it yourself; do not share or publish it."
)


def privacy(client: ParroClient, raw: bool = False) -> Any:
    """Per child: can parents change the privacy choices now, and when were they last changed."""
    response = client.list_children_privacy()
    return response.payload if raw else summaries.summarize_privacy(response)


def privacy_link(client: ParroClient, child_id: Any) -> dict[str, Any]:
    """The signed link to the page where one child's privacy choices are set (a secret)."""
    child = require_id(child_id, "child id")
    link = client.get_privacy_link(child)
    if link is None:
        raise ParroError(
            f"Parro returned no privacy page for child {child}. `privacy` lists the children "
            "and their ids."
        )
    return {"child_id": child, "privacy_link": link, "warning": PRIVACY_LINK_WARNING}


# ------------------------------------------------------------------------ calendar link

CALENDAR_LINK_WARNING = (
    "This link is personal and works without logging in: anyone who has it can read your Parro "
    "calendar. Paste it only into your own calendar app; do not share or publish it."
)


def calendar_link(client: ParroClient) -> dict[str, Any]:
    """Parro's own agenda subscription link (GET /calendar/sync), with how to use it."""
    link = client.get_calendar_link()
    if link is None:
        raise ParroError(
            "Parro returned no calendar link. Agenda sync may not be part of your school's Parro "
            "plan (ParnasSys lists it for the paid Parro Ouderapp). `calendar --ics FILE` exports "
            "the agenda to a file instead."
        )
    return {
        "calendar_link": link,
        "warning": CALENDAR_LINK_WARNING,
        "how_to_use": [
            "Google Calendar: Other calendars → + → From URL, paste the link (updates daily).",
            "Apple Calendar: File → New Calendar Subscription, paste the link.",
            "Outlook: Add calendar → Subscribe from web, paste the link.",
        ],
    }


# ---------------------------------------------------------------------------- overview

OVERVIEW_ITEMS = 5


def show_overview(
    client: ParroClient,
    now: datetime | None = None,
    limit: int = OVERVIEW_ITEMS,
    unread_only: bool = True,
) -> dict[str, Any]:
    """The app's home screen: unread counts, announcements, what is coming up, and chats with unread
    messages. `now` decides what "coming up" means (tests pass a fixed time).

    By default only what you have not read yet: unread announcements and unread calendar items
    (the API has no read filter, so this filters itself, before the limit). `unread_only=False`
    shows the latest announcements and everything coming up instead.
    """
    moment = now or current_time()
    groups = client.list_current_group_names()
    per_group = max(limit, UNREAD_SCAN_PAGE_SIZE) if unread_only else limit
    feed = client.collect_feed(ANNOUNCEMENT_LIST_DTYPE, limit_per_group=per_group, groups=groups)
    calendar = collect_calendar(client, None, None, groups, moment, False, limit)
    agenda = summaries.summarize_calendar_feed(calendar, limit=len(calendar))
    if unread_only:
        agenda["items"] = [item for item in agenda["items"] if item.get("read") is False]
    upcoming = choose_period(agenda, moment, past=False, limit=limit)["items"]
    rooms = summaries.summarize_chatrooms(client.list_chatrooms())
    unread_rooms = [room for room in rooms["chatrooms"] if room.get("unreadCount")]
    return {
        "unread_only": unread_only,
        "unread": summaries.summarize_unread_counts(client.get_unread_counts()),
        "announcements": summaries.summarize_announcement_feed(feed, limit, unread_only),
        "calendar": {"count": len(upcoming), "items": upcoming},
        "chats": {"total": len(unread_rooms), "chatrooms": unread_rooms},
    }


# ------------------------------------------------------------------------------ chats


CHAT_TYPES = ("single", "bot", "calendar", "group", "family")
# How archived chats are treated → the API's `archived` value (spec: an uppercase enum).
ARCHIVED_CHOICES = {"exclude": None, "only": "TRUE", "include": "BOTH"}


@dataclass(frozen=True)
class ChatFilter:
    """Which chats to list. The default is the API's own: every chat that is not archived."""

    unread: bool = False
    archived: str = "exclude"
    chat_type: str | None = None
    schoolyear: int | None = None

    def as_params(self) -> dict[str, str]:
        if self.archived not in ARCHIVED_CHOICES:
            raise ConfigurationError("`archived` must be 'exclude', 'only' or 'include'.")
        params: dict[str, str] = {}
        if self.unread:
            params["read"] = "false"
        if ARCHIVED_CHOICES[self.archived]:
            params["archived"] = str(ARCHIVED_CHOICES[self.archived])
        if self.chat_type:
            if self.chat_type.lower() not in CHAT_TYPES:
                raise ConfigurationError(f"The chat type must be one of: {', '.join(CHAT_TYPES)}.")
            params["chatRoom.type"] = self.chat_type.upper()
        if self.schoolyear is not None:
            params["chatRoom.createdInSchoolyear"] = str(int(self.schoolyear))
        return params


def list_chatrooms(
    client: ParroClient, limit: int = 25, raw: bool = False, chats: ChatFilter | None = None
) -> Any:
    """Chats, filtered by the API. `unread` is also checked here: the live check could not see
    the API's `read` filter at work (there were no unread chats)."""
    chosen = chats or ChatFilter()
    response = client.list_chatrooms(limit=limit, filters=chosen.as_params())
    if raw:
        return response.payload
    result = summaries.summarize_chatrooms(response)
    if chosen.unread:
        result["chatrooms"] = [room for room in result["chatrooms"] if room.get("unreadCount")]
        result["total"] = len(result["chatrooms"])
    return result


def list_chat_messages(
    client: ParroClient,
    chatroom_id: int | None,
    limit: int = 30,
    raw: bool = False,
    since: str | None = None,
    mark_read: bool = False,
) -> Any:
    """Messages of one chat; with `since` (a date or an ISO time) only those written since then.
    With `mark_read` the chat is marked as read once the messages have been fetched to show."""
    room_id = require_id(chatroom_id, "chatroom id")
    created_since = api_time(since) if since else None
    response = client.list_chat_messages(room_id, limit=limit, created_since=created_since)
    marked = None
    if mark_read:
        unread = client.get_chatroom(room_id).get("unreadCount")
        marked = mark_if_unread(client, "chat", room_id, not unread)
    if raw:
        return response.payload
    result = {"chatroom_id": room_id, **summaries.summarize_chat_messages(response)}
    if created_since:
        result["since"] = created_since
    if marked is not None:
        result["marked_read"] = marked
    return result


def api_time(text: str) -> str:
    """A date (local midnight) or an ISO time, in the API's UTC form: '2026-09-30T22:00:00.000Z'."""
    try:
        moment = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ConfigurationError(
            f"Not a date or time: {text!r}. Use e.g. 2026-10-01 or 2026-10-01T08:00."
        ) from None
    if moment.tzinfo is None:
        moment = moment.astimezone()  # a date or time without offset: the local time zone
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def list_chat_members(
    client: ParroClient, chatroom_id: int | None, include_former: bool = False, raw: bool = False
) -> Any:
    """Who is in a chat: name, parent or teacher, children, admin (spec: chatroommember)."""
    room_id = require_id(chatroom_id, "chatroom id")
    response = client.list_chatroom_members(room_id, active_only=not include_former)
    if raw:
        return response.payload
    return {"chatroom_id": room_id, **summaries.summarize_chat_members(response)}


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
            cache_key=described.cache_key(),
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


# ------------------------------------------------------------------------------- cache


def cache_info(client: ParroClient) -> dict[str, Any]:
    """Where the cache is, whether it is on, and how full it is."""
    info = client.cache.info()
    return {
        "directory": info.directory,
        "enabled": info.enabled,
        "files": info.files,
        "bytes": info.bytes,
        "max_bytes": info.max_bytes,
        "holds": "attachment files and their text; calendar-item details. Never lists.",
    }


def cache_clear(client: ParroClient) -> dict[str, Any]:
    return {"directory": str(client.cache.directory), "removed_files": client.cache.clear()}


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


# ----------------------------------------------------------------------- marking as read
# The only writes (PLAN-read-state-and-filters §2): never automatic, always on request.

MARK_READ_KINDS = ("announcement", "calendar", "chat")
READ_STATE_NOTE = (
    "The school sees this: teachers see who read an announcement, and chats show read receipts. "
    "The Parro app shows it as read too."
)


def mark_if_unread(client: ParroClient, kind: ReadStateKind, item_id: int, is_read: Any) -> bool:
    """Mark as read unless it already is. True when this call marked it."""
    if is_read is True:
        return False
    client.mark_read(kind, item_id)
    return True


def mark_read(client: ParroClient, kind: str, item_id: int | None) -> dict[str, Any]:
    """Mark one announcement, calendar item or chat as read.

    The item is fetched first, so a wrong id or the wrong kind is an error and not a write, and
    an item that is already read is left alone.
    """
    if kind not in MARK_READ_KINDS:
        raise ConfigurationError(f"Mark what as read? One of: {', '.join(MARK_READ_KINDS)}.")
    identifier = require_id(item_id, f"{kind} id")
    if kind == "announcement":
        event = client.get_announcement(identifier)
        title, is_read = event.get("title"), event.get("read")
        marked = mark_if_unread(client, "announcement", identifier, is_read)
    elif kind == "calendar":
        event = client.get_calendar_item(identifier)
        title, is_read = (event.get("calendarItem") or {}).get("title"), event.get("read")
        marked = mark_if_unread(client, "calendar", identifier, is_read)
    else:
        room = client.get_chatroom(identifier)
        title, is_read = room.get("title"), not room.get("unreadCount")
        marked = mark_if_unread(client, "chat", identifier, is_read)
    return {
        "kind": kind,
        "id": identifier,
        "title": title,
        "marked_read": marked,
        "already_read": not marked,
        "note": READ_STATE_NOTE,
    }


def mark_group_announcements_read(
    client: ParroClient, group_id: int | None, confirmed: bool = False
) -> dict[str, Any]:
    """All unread announcements of one group: counted first, marked only when `confirmed`."""
    identifier = require_id(group_id, "group id")
    groups = client.list_current_group_names()
    if identifier not in groups:
        raise ConfigurationError(f"Group #{identifier} is not one of your current groups.")
    feed = client.collect_feed(
        ANNOUNCEMENT_LIST_DTYPE, identifier, limit_per_group=UNREAD_SCAN_PAGE_SIZE
    )
    unread = [item.event for item in feed if item.event.get("read") is False]
    result: dict[str, Any] = {
        "group_id": identifier,
        "group": groups[identifier],
        "unread": len(unread),
        "titles": [str(event.get("title") or "") for event in unread],
        "marked_read": False,
        "note": READ_STATE_NOTE,
    }
    if confirmed and unread:
        client.mark_read("group-announcements", identifier)
        result["marked_read"] = True
    return result


# --------------------------------------------------------------------- sending a chat message
# Real people receive it, under the user's name, and it cannot be taken back (PLAN-send-chat-message
# §2): prepare_chat_message() shows what would happen; only send_prepared_message() sends.


def clean_message_text(text: Any) -> str:
    """The text to send: line breaks as \\n (a Windows file has \\r\\n), without a final one."""
    raw = str(text if text is not None else "")
    cleaned = raw.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    if not cleaned.strip():
        raise ConfigurationError("Not sent: the message is empty.")
    try:
        cleaned.encode("utf-8")
    except UnicodeEncodeError:
        raise ConfigurationError("Not sent: the text is not valid UTF-8.") from None
    return cleaned


def why_chat_is_closed(room: dict[str, Any]) -> str | None:
    """Why no message should go to this chat, or None when it can be written to."""
    if room.get("archived") is True:
        return "this chat is archived."
    if room.get("active") is False:
        return "you are no longer active in this chat."
    if room.get("repliesEnabled") is False:
        return "replies are switched off in this chat."
    if str(room.get("type") or "").upper() == "BOT":
        return "this chat is with a bot, not with people."
    return None


def prepare_chat_message(client: ParroClient, chatroom_id: int | None, text: Any) -> dict[str, Any]:
    """What would be sent to whom. Reads only; raises when the message should not be sent."""
    room_id = require_id(chatroom_id, "chatroom id")
    cleaned = clean_message_text(text)
    room = client.get_chatroom(room_id)
    closed = why_chat_is_closed(room)
    if closed:
        raise ConfigurationError(f"Not sent: {closed}")
    members = summaries.summarize_chat_members(client.list_chatroom_members(room_id))["members"]
    own_id = str(client.get_role_header() or "").rpartition(":")[2]
    return {
        "chatroom_id": room_id,
        "title": room.get("title"),
        "type": str(room.get("type") or "").lower() or None,
        "recipients": [member for member in members if str(member.get("id")) != own_id],
        "text": cleaned,
    }


def send_prepared_message(client: ParroClient, prepared: dict[str, Any]) -> dict[str, Any]:
    """Send what prepare_chat_message() returned, once."""
    response = client.send_chat_message(prepared["chatroom_id"], prepared["text"])
    message = response.items[0] if response.items else {}
    return {
        "sent": True,
        "chatroom_id": prepared["chatroom_id"],
        "title": prepared.get("title"),
        "message_id": get_object_id(message),
        "created_at": message.get("createdAt"),
    }


def send_or_preview_chat_message(
    client: ParroClient, chatroom_id: int | None, text: Any, confirm: bool
) -> dict[str, Any]:
    """For an assistant, which has no terminal to ask at: the preview, or the send if `confirm`."""
    prepared = prepare_chat_message(client, chatroom_id, text)
    if confirm:
        return send_prepared_message(client, prepared)
    return {**prepared, "sent": False, "preview": True}


# ------------------------------------------------------------------------- helper slots
# A sign-up is a promise in the user's name (PLAN-helper-signup §2). prepare_helper_change() reads
# and shows what would happen; only apply_helper_change() writes.


def find_helper_slot(calendar_item: dict[str, Any], slot_id: int | None) -> dict[str, Any]:
    """The slot asked for; `slot_id` may be left out when there is only one."""
    slots = [slot for slot in calendar_item.get("resources") or [] if isinstance(slot, dict)]
    if not slots:
        raise ConfigurationError("Nothing changed: this calendar item asks for no helpers.")
    if slot_id is None and len(slots) == 1:
        return slots[0]
    for slot in slots:
        if slot_id is not None and get_object_id(slot) == slot_id:
            return slot
    choices = ", ".join(
        f"{slot.get('title') or 'Helpers'} (#{get_object_id(slot)})" for slot in slots
    )
    raise ConfigurationError(
        f"Nothing changed: choose a slot (--slot, or slot_id in MCP): {choices}."
    )


def check_room_for_signup(slot: dict[str, Any], count: Any) -> int:
    """The count to sign up with, or why it cannot be done."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ConfigurationError("Nothing changed: the count must be a whole number from 1 up.")
    if slot.get("commitedByMe"):  # the API's spelling
        raise ConfigurationError(
            "Nothing changed: you are already signed up on this slot. To change your count, "
            "withdraw and sign up again."
        )
    wanted, taken = slot.get("amount"), slot.get("amountCommitted") or 0
    if wanted is not None:
        left = wanted - taken
        if left <= 0:
            raise ConfigurationError("Nothing changed: this slot is full.")
        if count > left:
            raise ConfigurationError(
                f"Nothing changed: only {left} of {wanted} places are left on this slot."
            )
    return count


def own_commitment_id(slot: dict[str, Any]) -> int:
    """Your commitment's id: the API lists only your own (PLAN-helper-signup, probe results)."""
    mine = [c for c in slot.get("commitments") or [] if isinstance(c, dict)]
    if not slot.get("commitedByMe") or not mine:
        raise ConfigurationError("Nothing changed: you are not signed up on this slot.")
    if len(mine) > 1:
        raise ConfigurationError(
            f"Nothing changed: you have {len(mine)} commitments on this slot; use the Parro app."
        )
    return require_id(get_object_id(mine[0]), "commitment id")


def prepare_helper_change(
    client: ParroClient,
    action: str,
    event_id: int | None,
    slot_id: int | None = None,
    count: Any = 1,
) -> dict[str, Any]:
    """What would change, on which slot. Reads only; raises when it should not be done."""
    if action not in ("signup", "withdraw"):
        raise ConfigurationError("Choose signup or withdraw.")
    identifier = require_id(event_id, "calendar item id")
    calendar_item = client.get_calendar_item(identifier).get("calendarItem") or {}
    slot = find_helper_slot(calendar_item, slot_id)
    if summaries.is_over({"calendarItem": calendar_item}, current_time()):
        raise ConfigurationError("Nothing changed: this calendar item is in the past.")
    prepared: dict[str, Any] = {
        "action": action,
        "event_id": identifier,
        # Not the event id: the API answers 404 for that (spec: addCommitment).
        "calendar_item_id": require_id(get_object_id(calendar_item), "calendar item id"),
        "slot_id": require_id(get_object_id(slot), "slot id"),
        "title": calendar_item.get("title"),
        "start": calendar_item.get("startDate"),
        "slot": str(slot.get("title") or "").strip() or None,
        "wanted": slot.get("amount"),
        "signed_up": slot.get("amountCommitted") or 0,
    }
    if action == "signup":
        prepared["count"] = check_room_for_signup(slot, count)
    else:
        prepared["commitment_id"] = own_commitment_id(slot)
    return prepared


def apply_helper_change(client: ParroClient, prepared: dict[str, Any]) -> dict[str, Any]:
    """Do what prepare_helper_change() returned, once."""
    item_id, slot_id = prepared["calendar_item_id"], prepared["slot_id"]
    result = {key: prepared.get(key) for key in ("action", "event_id", "title", "slot", "slot_id")}
    if prepared["action"] == "signup":
        response = client.add_helper_commitment(item_id, slot_id, prepared["count"])
        commitment = response.items[0] if response.items else {}
        result.update(count=prepared["count"], commitment_id=get_object_id(commitment))
    else:
        client.remove_helper_commitment(item_id, slot_id, prepared["commitment_id"])
    return {**result, "done": True}


def change_or_preview_helper_slot(
    client: ParroClient,
    action: str,
    event_id: int | None,
    slot_id: int | None,
    count: Any = 1,
    confirm: bool = False,
) -> dict[str, Any]:
    """For an assistant, which has no terminal to ask at: the preview, or `confirm` to change."""
    prepared = prepare_helper_change(client, action, event_id, slot_id, count)
    if confirm:
        return apply_helper_change(client, prepared)
    return {**prepared, "done": False, "preview": True}


# ------------------------------------------------------------------------------- invitations
# An answer is a statement in the user's name, and it can be changed but not removed
# (PLAN-rsvp §2). prepare_rsvp() reads and shows what would happen; only apply_rsvp() writes.


def prepare_rsvp(client: ParroClient, event_id: int | None, answer: Any) -> dict[str, Any]:
    """What would change on which item. Reads only; raises when it should not be done."""
    wanted = answer.strip().upper() if isinstance(answer, str) else None
    if wanted not in RSVP_ANSWERS:
        raise ConfigurationError("Nothing changed: answer with accept, decline or tentative.")
    identifier = require_id(event_id, "calendar item id")
    event = client.get_calendar_item(identifier)
    calendar_item = event.get("calendarItem") or {}
    if not calendar_item.get("rsvpRequired"):
        raise ConfigurationError("Nothing changed: this calendar item does not ask for an answer.")
    if event.get("cancelled"):
        raise ConfigurationError("Nothing changed: this calendar item is cancelled.")
    if summaries.is_over({"calendarItem": calendar_item}, current_time()):
        raise ConfigurationError("Nothing changed: this calendar item is in the past.")
    groups = [g.get("name") for g in event.get("groups") or [] if isinstance(g, dict)]
    previous = event.get("rsvp") if event.get("rsvp") in RSVP_ANSWERS else None
    return {
        "event_id": identifier,
        # Not the event id: the API answers 404 for that (spec: answerRsvp).
        "calendar_item_id": require_id(get_object_id(calendar_item), "calendar item id"),
        "title": calendar_item.get("title"),
        "start": calendar_item.get("startDate"),
        "groups": [name for name in groups if name],
        "answer": wanted,
        "previous": previous,
        "unchanged": previous == wanted,
    }


def answer_or_preview_rsvp(
    client: ParroClient, event_id: int | None, answer: Any, confirm: bool = False
) -> dict[str, Any]:
    """For an assistant, which has no terminal to ask at: the preview, or `confirm` to answer."""
    prepared = prepare_rsvp(client, event_id, answer)
    if confirm or prepared["unchanged"]:
        return apply_rsvp(client, prepared)
    return {**prepared, "done": False, "preview": True}


def apply_rsvp(client: ParroClient, prepared: dict[str, Any]) -> dict[str, Any]:
    """Do what prepare_rsvp() returned, once. The answer you already gave is not sent again."""
    if not prepared["unchanged"]:
        client.answer_rsvp(prepared["calendar_item_id"], prepared["answer"])
    keys = ("event_id", "title", "start", "answer", "previous")
    return {
        **{key: prepared.get(key) for key in keys},
        "changed": not prepared["unchanged"],
        "done": True,
    }


def require_id(value: Any, what: str) -> int:
    """An id argument as int, with a usage error instead of a traceback when it is missing."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ConfigurationError(f"A numeric {what} is required.") from None
    if number <= 0:
        raise ConfigurationError(f"A numeric {what} is required.")
    return number


# ------------------------------------------------------------------------------ archive

SYNC_PAGE_SIZE = 50
# A safety ceiling per list: 200 pages of 50 is far more than a school year holds.
SYNC_MAX_PAGES = 200


@dataclass(frozen=True)
class SyncOptions:
    target: Path
    previous_year: bool = False  # last school year's groups instead of this year's
    photos: bool = False  # also save photos (documents are always saved)


@dataclass
class SyncProgress:
    """Files saved and problems met during one sync; a problem never stops the run."""

    files_saved: int = 0
    bytes_saved: int = 0
    photos_not_saved: int = 0
    problems: list[str] = field(default_factory=list)
    report: Callable[[str], None] | None = None  # told what is being done, item by item

    def note(self, what: str) -> None:
        if self.report is not None:
            self.report(what)


def sync_archive(
    client: ParroClient,
    options: SyncOptions,
    report: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Write or update the local archive (PLAN-readable-output §3b). Read-only towards Parro.

    `report` hears what is being done. If it raises, the run stops there, and the archive keeps
    what it had: only a run that reaches the end marks items as gone.
    """
    target = archive.Archive(options.target)
    progress = SyncProgress(report=report)
    scope = "previous" if options.previous_year else "current"
    groups = (
        previous_group_names(client) if options.previous_year else client.list_current_group_names()
    )
    sync_announcements(client, target, groups, scope, options, progress)
    sync_calendar_items(client, target, groups, scope, options, progress)
    scopes = {scope}
    if not options.previous_year:  # chats do not belong to a school year
        sync_chats(client, target, progress)
        scopes.add("chats")
    target.finish(scopes, current_time())
    return {
        "archive": str(options.target),
        "school_year": "previous" if options.previous_year else "current",
        **{kind: vars(counts) for kind, counts in target.counts.items() if kind != "chat"},
        **({"chat": vars(target.counts["chat"])} if not options.previous_year else {}),
        "files_saved": progress.files_saved,
        "bytes_saved": progress.bytes_saved,
        "photos_not_saved": progress.photos_not_saved,
        "problems": progress.problems,
    }


def previous_group_names(client: ParroClient) -> dict[int, str | None]:
    """{group id: name} for last school year's groups."""
    names: dict[int, str | None] = {}
    for group in client.list_groups(previous_year=True, limit=50).items:
        group_id = get_object_id(group)
        if group_id is not None:
            names[group_id] = group.get("name")
    return names


def read_all_pages(fetch_page: Callable[[int], ApiResponse]) -> list[Any]:
    """Every item of a paged list: fetch_page(offset) until the Content-Range total is reached."""
    items: list[Any] = []
    for _page_number in range(SYNC_MAX_PAGES):
        page = fetch_page(len(items))
        items.extend(page.items)
        if not page.items or page.total is None or len(items) >= page.total:
            break
    return items


def collect_all_events(
    client: ParroClient, groups: dict[int, str | None], event_dtype: str
) -> list[FeedEvent]:
    """Every event of every group (all pages), each with the group it was found through."""
    feed: list[FeedEvent] = []
    for group_id, group_name in groups.items():

        def fetch_page(offset: int, group: int = group_id) -> ApiResponse:
            return client.list_events(group, event_dtype, SYNC_PAGE_SIZE, offset, count_total=True)

        feed.extend(FeedEvent(event, group_name) for event in read_all_pages(fetch_page))
    return feed


def sync_announcements(
    client: ParroClient,
    target: archive.Archive,
    groups: dict[int, str | None],
    scope: str,
    options: SyncOptions,
    progress: SyncProgress,
) -> None:
    progress.note("Reading the announcements")
    feed = collect_all_events(client, groups, ANNOUNCEMENT_LIST_DTYPE)
    merged = summaries.merge_duplicates(feed)
    for number, (item, names) in enumerate(merged, 1):
        progress.note(f"Announcement {number} of {len(merged)}")
        event_id = get_object_id(item.event)
        if event_id is None:
            continue
        version = f"{item.event.get('lastModifiedAt')}|photos={options.photos}"
        if target.is_current("announcement", event_id, version):
            target.keep("announcement", event_id)
            continue
        summary = summaries.summarize_announcement(item.event, item.group_name, names)
        files = save_attachments(
            client, target, "announcement", event_id, item.event, options, progress
        )
        version = mark_if_incomplete(version, files, options)
        markdown = rendering.render_archived_announcement(summary, files)
        entry = archive.ArchiveEntry(
            "announcement", event_id, version, str(summary.get("title") or ""),
            str(summary.get("date") or ""), "", scope, groups=names,
        )  # fmt: skip
        target.save(entry, markdown, summary)


def sync_calendar_items(
    client: ParroClient,
    target: archive.Archive,
    groups: dict[int, str | None],
    scope: str,
    options: SyncOptions,
    progress: SyncProgress,
) -> None:
    progress.note("Reading the calendar")
    feed = collect_all_events(client, groups, CALENDAR_LIST_DTYPE)
    ordered = sorted(feed, key=lambda entry: entry.event.get("sortDate") or "")
    entries = summaries.one_per_calendar_item([e for e, _ in summaries.merge_duplicates(ordered)])
    for number, entry in enumerate(entries, 1):
        progress.note(f"Calendar item {number} of {len(entries)}")
        sync_calendar_item(client, target, entry, scope, options, progress)


def sync_calendar_item(
    client: ParroClient,
    target: archive.Archive,
    entry: FeedEvent,
    scope: str,
    options: SyncOptions,
    progress: SyncProgress,
) -> None:
    """One calendar item: details fetched only when its version changed (one request)."""
    event_id = get_object_id(entry.event)
    if event_id is None:
        return
    calendar_item = entry.event.get("calendarItem") or {}
    version = (
        f"{entry.event.get('lastModifiedAt')}|{calendar_item.get('lastModifiedAt')}"
        f"|photos={options.photos}"
    )
    if summaries.wants_helpers(calendar_item):
        version += "|helpers"  # 0.4.0 added the helper slots: rewrite such items once
    if target.is_current("calendar", event_id, version):
        target.keep("calendar", event_id)
        return
    try:
        detail = client.get_calendar_item(event_id)
    except ParroError as problem:
        progress.problems.append(f"calendar item {event_id}: {problem}")
        detail = entry.event
    item = {**strip_geon_metadata(entry.event), "group": entry.group_name}
    details = summaries.summarize_calendar_details(detail)
    files = save_attachments(client, target, "calendar", event_id, detail, options, progress)
    version = mark_if_incomplete(version, files, options)
    markdown = rendering.render_archived_calendar_item(item, details, files)
    names = rendering.group_names(item)
    record = archive.ArchiveEntry(
        "calendar", event_id, version, str(calendar_item.get("title") or "").strip(),
        str(calendar_item.get("startDate") or ""), "", scope, groups=names,
    )  # fmt: skip
    target.save(record, markdown, {**item, "details": details})


def sync_chats(client: ParroClient, target: archive.Archive, progress: SyncProgress) -> None:
    """Every chat as one file; the messages are fetched only when the chat changed."""
    # The API leaves archived chats out unless asked (spec: `archived`); the archive keeps them all.
    everything = {"archived": "BOTH"}
    progress.note("Reading the chats")
    rooms = read_all_pages(
        lambda offset: client.list_chatrooms(SYNC_PAGE_SIZE, offset, filters=everything)
    )
    for number, room in enumerate(rooms, 1):
        progress.note(f"Chat {number} of {len(rooms)}")
        room_id = get_object_id(room)
        if room_id is None:
            continue
        last_message = get_object_id(room.get("lastMessage"))
        version = f"{room.get('lastModifiedAt')}|{last_message}"
        if target.is_current("chat", room_id, version):
            target.keep("chat", room_id)
            continue
        messages = read_all_pages(partial(client.list_chat_messages, room_id, SYNC_PAGE_SIZE))
        conversation = {
            "chatroom_id": room_id,
            "title": room.get("title"),
            "total": len(messages),
            "messages": [strip_geon_metadata(message) for message in messages],
        }
        markdown = rendering.render(
            "chat_messages", conversation, rendering.RenderOptions(full_text=True)
        )
        record = archive.ArchiveEntry(
            "chat", room_id, version, str(room.get("title") or "").strip(),
            str(room.get("sortDate") or room.get("lastModifiedAt") or ""), "", "chats",
            groups=list(room.get("memberNames") or []),
        )  # fmt: skip
        target.save(record, markdown, conversation)


def save_attachments(
    client: ParroClient,
    target: archive.Archive,
    kind: str,
    item_id: int,
    event: dict[str, Any],
    options: SyncOptions,
    progress: SyncProgress,
) -> list[rendering.SavedFile]:
    """Save an item's attachments (photos only with --photos); never download a file twice."""
    saved = []
    for raw_attachment in attachments.find_attachments(event):
        file = attachments.describe_attachment(raw_attachment)
        path = archive.attachment_path(kind, item_id, file.attachment_id, file.filename)
        photo = attachments.detect_format(file.content_type, file.filename) == "image"
        if not target.has_file(path):
            if photo and not options.photos:
                progress.photos_not_saved += 1
            else:
                store_attachment(client, target, path, file, progress)
        # Link whatever is on disk, also photos saved by an earlier run with --photos.
        link = path.split("/", 1)[1] if target.has_file(path) else None
        saved.append(
            rendering.SavedFile(
                file.attachment_id, file.filename, file.content_type, file.size, link
            )
        )
    return saved


def mark_if_incomplete(version: str, files: list[rendering.SavedFile], options: SyncOptions) -> str:
    """Add '|incomplete' when a file that should be saved is missing (e.g. a failed download).

    The next run computes the version without it, sees a difference, and tries again. Photos
    left out on purpose (no --photos) do not count.
    """
    for file in files:
        photo = attachments.detect_format(file.content_type, file.filename) == "image"
        if file.link is None and (options.photos or not photo):
            return f"{version}|incomplete"
    return version


def store_attachment(
    client: ParroClient,
    target: archive.Archive,
    path: str,
    file: attachments.AttachmentFile,
    progress: SyncProgress,
) -> bool:
    """Write one attachment: from the cache when it is there, else downloaded once."""
    key = file.cache_key()
    data = client.cache.get_bytes("attachments", f"{key}.bin") if key else None
    if data is None:
        if not file.url:
            progress.problems.append(f"{path}: no download link")
            return False
        try:
            data = attachments.download_attachment(
                client, file.url, file.size, file.content_type
            ).data
        except ParroError as problem:
            progress.problems.append(f"{path}: {problem}")
            return False
    target.save_file(path, data)
    progress.files_saved += 1
    progress.bytes_saved += len(data)
    return True
