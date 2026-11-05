"""Turn command results into light markdown that people can read (PLAN-readable-output §2).

The input is what parro.operations returns (the same data the JSON output shows). The output is
"light" markdown: `#` headings, `-` lists, `>` quotes, no tables and no bold, so it reads well as
plain text in a terminal, in a file, and for an LLM.

Rules for this module:
  * Pure functions: no requests, no files, no clock. The same input always gives the same text.
  * Every id the JSON shows stays visible (`#5000000101`), so the follow-up commands and MCP tools
    can still be used. A test checks this.
  * Dates are shown in the offset the API sent them in (school time), never converted to the
    machine's timezone: a container running in UTC would otherwise show the wrong times.
  * Labels are English; content (titles, messages) is shown as written.

render(view, data, options) is the entry point; VIEW_RENDERERS lists the views.
"""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from .attachments import extract_html_text, tidy_whitespace
from .errors import ConfigurationError
from .geon import parse_timestamp
from .settings import OutputFormat

Audience = Literal["cli", "mcp"]

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# Markers (decision 4: emoji).
UNREAD_MARK = "●"
ATTACHMENT_MARK = "📎"
PHOTO_MARK = "🖼"
PINNED_MARK = "📌"
WARNING_MARK = "⚠"
PREVIEW_LINES = 3
# Real descriptions often put a whole paragraph on one line (live look), so cap characters too.
PREVIEW_CHARACTERS = 300
GROUPS_SHOWN = 3


@dataclass(frozen=True)
class RenderOptions:
    """How much to show, and for whom the follow-up hints are written."""

    audience: Audience = "cli"
    full_text: bool = False  # list views: whole texts instead of a short preview


def choose_format(requested: OutputFormat, raw: bool, stdout_is_terminal: bool) -> str:
    """'json' or 'markdown' for this run.

    auto means markdown for a person at a terminal and JSON for scripts. --raw is the API's own
    JSON, so it can only be printed as JSON.
    """
    if raw and requested == "markdown":
        raise ConfigurationError("--raw prints the API's own JSON; it cannot be shown as markdown.")
    if requested == "auto":
        return "markdown" if stdout_is_terminal and not raw else "json"
    return requested


# --------------------------------------------------------------------------------- helpers


def format_day(moment: datetime) -> str:
    """'Tue 3 Nov 2026'."""
    return f"{WEEKDAYS[moment.weekday()]} {moment.day} {MONTHS[moment.month - 1]} {moment.year}"


def format_time(moment: datetime) -> str:
    return f"{moment.hour:02d}:{moment.minute:02d}"


def format_timestamp(text: Any) -> str:
    """'Tue 3 Nov 2026 18:39', or the text as is when it is not a timestamp."""
    moment = parse_timestamp(text)
    if moment is None:
        return str(text or "")
    return f"{format_day(moment)} {format_time(moment)}"


def format_date(text: Any) -> str:
    """'Tue 3 Nov 2026' for a timestamp or a plain date such as '2024-08-26'."""
    moment = parse_timestamp(text if "T" in str(text) else f"{text}T00:00")
    return format_day(moment) if moment else str(text or "")


def format_size(byte_count: Any) -> str:
    """'1.5 MB', '24 KB', '512 bytes'."""
    if not isinstance(byte_count, int):
        return ""
    if byte_count >= 1_000_000:
        return f"{byte_count / 1_000_000:.1f}".removesuffix(".0") + " MB"
    if byte_count >= 1_000:
        return f"{round(byte_count / 1_000)} KB"
    return f"{byte_count} bytes"


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    """'1 photo', '3 photos'."""
    return f"{count} {singular if count == 1 else (plural_form or singular + 's')}"


def preview(
    text: Any, line_count: int = PREVIEW_LINES, max_characters: int = PREVIEW_CHARACTERS
) -> str:
    """The first `line_count` non-empty lines, at most `max_characters`, with '…' when cut."""
    lines = [line for line in tidy_whitespace(str(text or "")).split("\n") if line]
    shown = "\n".join(lines[:line_count])
    cut = len(lines) > line_count
    if len(shown) > max_characters:
        shown = shown[:max_characters].rsplit(" ", 1)[0].rstrip(" ,.;:")
        cut = True
    return f"{shown} …" if cut else shown


def quote(text: Any) -> str:
    """Text as a markdown quote ('> ' before every line), e.g. for chat messages."""
    return "\n".join(f"> {line}" if line else ">" for line in str(text or "").split("\n"))


def join_parts(parts: Iterable[Any]) -> str:
    """'a · b · c', skipping empty parts."""
    return " · ".join(str(part) for part in parts if part not in (None, "", []))


def object_id(value: Any) -> str:
    """'#5000000101', or '' when there is no id."""
    return f"#{value}" if value not in (None, "") else ""


def document(*blocks: str | None) -> str:
    """Blocks separated by one empty line; empty blocks are left out. Ends with a newline."""
    return "\n\n".join(block.strip("\n") for block in blocks if block) + "\n"


def hint(options: RenderOptions, cli_command: str, mcp_call: str) -> str:
    """A follow-up hint written for the reader: a CLI command or an MCP tool call."""
    text = f"parro_cli.py {cli_command}" if options.audience == "cli" else mcp_call
    return f"→ {text}"


# ---------------------------------------------------------------------------- simple views


def render_status(status: dict[str, Any], options: RenderOptions) -> str:
    who = status.get("logged_in_as") or {}
    lines = []
    if who:
        account = f"{who.get('accountType')} at {who.get('organisation')}"
        lines.append(f"- Logged in as: {who.get('name')} ({who.get('email')}), {account}")
        lines.append(f"- Role header: {who.get('role_header')}")
    lines.append(f"- Access token: {describe_access_token(status)}")
    credentials = "yes" if status.get("credentials_in_env") else "no"
    lines.append(f"- Login method: {status.get('login_method')} · password set: {credentials}")
    lines.append(f"- Token file: {status.get('token_file')}")
    warnings = []
    if status.get("automatic_login_halted"):
        halted = f"{WARNING_MARK} Automatic login is halted: {status['automatic_login_halted']}"
        warnings.append(f"{halted}\n{status.get('how_to_resume', '')}")
    if status.get("error"):
        warnings.append(f"{WARNING_MARK} {status['error']}")
    return document("# Parro login", "\n".join(lines), *warnings)


def describe_access_token(status: dict[str, Any]) -> str:
    """'valid for 58 min · refresh token: yes'."""
    state = "none"
    if status.get("has_access_token"):
        state = "valid" if status.get("access_token_valid", True) else "expired"
        expires = status.get("access_token_expires_in_seconds")
        if isinstance(expires, int) and expires > 0:
            state += f" for {expires // 60} min"
    refresh = "yes" if status.get("has_refresh_token") else "no"
    return f"{state} · refresh token: {refresh}"


def render_login_url(result: dict[str, Any], options: RenderOptions) -> str:
    steps = "\n".join(f"{n}. {step}" for n, step in enumerate(result.get("instructions", []), 1))
    return document("# Browser login", result.get("login_url", ""), steps)


def render_logout(result: dict[str, Any], options: RenderOptions) -> str:
    revoked = ", ".join(
        f"{kind.replace('_', ' ')}: HTTP {status}"
        for response in result.get("revocation_responses", [])
        for kind, status in response.items()
    )
    lines = [
        f"- Revoked at the IdP: {revoked or 'nothing to revoke'}",
        f"- Token file: {result.get('token_file')}",
    ]
    halted = result.get("automatic_login_halted")
    warning = f"{WARNING_MARK} Automatic login stays halted: {halted}" if halted else None
    return document("# Logged out", "\n".join(lines), warning)


def render_account(account: dict[str, Any], options: RenderOptions) -> str:
    school = account.get("organisation") or {}
    school_line = join_parts([school.get("name"), school.get("city"), object_id(school.get("id"))])
    username = account.get("username")
    kind = join_parts([account.get("accountType"), f"username {username}" if username else ""])
    lines = [
        f"- E-mail: {account.get('email')}",
        f"- Account: {kind}",
        f"- School: {school_line}",
        f"- Role header: {account.get('role_header')}",
    ]
    if account.get("children"):
        lines.append(f"- Children: {', '.join(account['children'])}")
    return document(f"# {account.get('name') or 'Account'}", "\n".join(lines))


def render_children(result: dict[str, Any], options: RenderOptions) -> str:
    lines = []
    for child in result.get("children", []):
        since = (
            f"at school since {format_date(child['enrolledSince'])}"
            if child.get("enrolledSince")
            else ""
        )
        archived = "archived" if child.get("archived") else ""
        lines.append(
            f"- {join_parts([child.get('name'), since, archived, object_id(child.get('id'))])}"
        )
    heading = f"# Children ({result.get('total', len(lines))})"
    return document(heading, "\n".join(lines) or "No children linked to this account.")


GROUP_KINDS = {"SCHOOLWIDE": "whole school", "NORMAL": "class", "COLLEAGUES": "colleagues"}


def render_groups(result: dict[str, Any], options: RenderOptions) -> str:
    lines = [f"- {describe_group(group)}" for group in result.get("groups", [])]
    year = "last school year" if result.get("scope") == "previous" else "this school year"
    heading = f"# Groups, {year} ({result.get('total', len(lines))})"
    return document(heading, "\n".join(lines) or "No groups.")


def describe_group(group: dict[str, Any]) -> str:
    """One line per group: name, kind, unread, your child, member counts, id."""
    counts = group.get("counts") or {}
    member_counts = [
        plural(counts["children"], "child", "children") if counts.get("children") else "",
        plural(counts["guardians"], "guardian") if counts.get("guardians") else "",
        plural(counts["teachers"], "teacher") if counts.get("teachers") else "",
    ]
    members = ", ".join(part for part in member_counts if part)
    unread = f"{UNREAD_MARK} {group['unread']} unread" if group.get("unread") else ""
    yours = f"your child: {', '.join(group['children'])}" if group.get("children") else ""
    kind = GROUP_KINDS.get(str(group.get("type")), str(group.get("type") or "").lower())
    return join_parts([group.get("name"), kind, unread, yours, members, object_id(group.get("id"))])


UNREAD_LABELS = (
    ("announcements", "announcement"),
    ("calendar", "calendar item"),
    ("chats", "chat"),
    ("systemNews", "system news item"),
    ("portal", "portal notification"),
)


def render_unread(result: list[dict[str, Any]], options: RenderOptions) -> str:
    blocks = []
    for counts in result:
        unread = [plural(counts[key], label) for key, label in UNREAD_LABELS if counts.get(key)]
        children = f" ({', '.join(counts['children'])})" if counts.get("children") else ""
        body = "\n".join(f"- {item}" for item in unread) or "Nothing unread."
        blocks.append(f"{counts.get('for')}{children}\n{body}")
    return document("# Unread", *blocks)


def render_system_news(result: dict[str, Any], options: RenderOptions) -> str:
    blocks = []
    for news in result.get("items", []):
        text = tidy_whitespace(extract_html_text(str(news.get("contents") or "")))
        body = text if options.full_text else preview(text)
        meta = join_parts([format_date(news.get("scheduleDate")), object_id(news.get("id"))])
        blocks.append(f"## {news.get('title')}\n{meta}\n\n{body}")
    return document("# News from Parro", *blocks)


def render_json_block(data: Any, options: RenderOptions) -> str:
    """Fallback for data without a dedicated view (e.g. `get`): fenced JSON."""
    return "```json\n" + json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n```\n"


def render_any_response(result: dict[str, Any], options: RenderOptions) -> str:
    content_range = result.get("content_range")
    header = f"Content-Range: {content_range}" if content_range else None
    return document(header, render_json_block(result.get("body"), options))


# --------------------------------------------------------------------------- announcements


def render_announcement_feed(result: dict[str, Any], options: RenderOptions) -> str:
    announcements = result.get("announcements", [])
    # Like the app: pinned announcements on top, the rest newest first (the order given).
    ordered = [a for a in announcements if a.get("pinned")]
    ordered += [a for a in announcements if not a.get("pinned")]
    blocks = [render_feed_item(item, options) for item in ordered]
    heading = f"# Announcements ({result.get('count', len(blocks))})"
    return document(heading, *blocks) if blocks else document(heading, "No announcements.")


def render_feed_item(item: dict[str, Any], options: RenderOptions) -> str:
    body = (
        str(item.get("contents") or "").strip()
        if options.full_text
        else preview(item.get("contents"))
    )
    return "\n\n".join(
        part
        for part in (
            f"## {announcement_title(item)}\n{announcement_byline(item)}",
            body,
            attachment_lines(item, options),
        )
        if part
    )


def announcement_title(item: dict[str, Any]) -> str:
    """'📌 Title ● new'."""
    pinned = f"{PINNED_MARK} " if item.get("pinned") else ""
    new = f" {UNREAD_MARK} new" if item.get("read") is False else ""
    return f"{pinned}{item.get('title') or '(no title)'}{new}"


def announcement_byline(item: dict[str, Any], extra: Iterable[str] = ()) -> str:
    """'Lotte Bakker → Groep 3, Groep 6 · Mon 2 Nov 2026 12:28 · #5000000102'."""
    groups = item.get("groups") or ([item["from"]] if item.get("from") else [])
    who = item.get("author") or ""
    if groups:
        who = f"{who} → {', '.join(groups)}" if who else ", ".join(groups)
    return join_parts([who, format_timestamp(item.get("date")), *extra, object_id(item.get("id"))])


def attachment_lines(item: dict[str, Any], options: RenderOptions) -> str:
    """Documents by name and size, photos as a count, then the command that reads them."""
    attachments = item.get("attachments") or []
    if not attachments:
        return ""
    photos = [a for a in attachments if is_photo(a)]
    documents = [a for a in attachments if a not in photos]
    shown = [
        f"{ATTACHMENT_MARK} {join_parts([a.get('filename'), format_size(a.get('size'))])}"
        for a in documents
    ]
    if photos:
        shown.append(f"{PHOTO_MARK} {plural(len(photos), 'photo')}")
    return "\n".join([" · ".join(shown), read_attachments_hint(item, len(attachments), options)])


def read_attachments_hint(item: dict[str, Any], count: int, options: RenderOptions) -> str:
    event_id = item.get("id")
    if count == 1:
        return hint(
            options, f"attachment {event_id}", f"parro_attachment(announcement_id={event_id})"
        )
    return hint(
        options,
        f"attachment {event_id} --all  (or --attachment-id ID, --save-to DIR)",
        f"parro_attachment(announcement_id={event_id}, all=true)",
    )


def render_announcement(item: dict[str, Any], options: RenderOptions) -> str:
    counts = item.get("readCount") or {}
    read_by = f"read by {counts['read']} of {counts['total']}" if counts.get("total") else ""
    likes = plural(counts["liked"], "like") if counts.get("liked") else ""
    return document(
        f"# {announcement_title(item)}\n{announcement_byline(item, [read_by, likes])}",
        str(item.get("contents") or "").strip(),
        attachment_list(item, options),
    )


def attachment_list(item: dict[str, Any], options: RenderOptions) -> str | None:
    """'## Attachments' with one line per file (name, size, id) and the command to read them."""
    attachments = item.get("attachments") or []
    if not attachments:
        return None
    lines = [f"- {attachment_line(a)}" for a in attachments]
    lines.append(read_attachments_hint(item, len(attachments), options))
    return "## Attachments\n" + "\n".join(lines)


def attachment_line(attachment: dict[str, Any]) -> str:
    """'📎 Nieuwsbrief-3.pdf · 1.5 MB · #6000000101'."""
    mark = PHOTO_MARK if is_photo(attachment) else ATTACHMENT_MARK
    parts = [attachment.get("filename"), format_size(attachment.get("size"))]
    return f"{mark} {join_parts([*parts, object_id(attachment.get('attachment_id'))])}"


def is_photo(attachment: dict[str, Any]) -> bool:
    return str(attachment.get("contentType") or "").startswith("image/")


# -------------------------------------------------------------------------------- calendar

LOCATION_MARK = "📍"


def render_agenda(result: dict[str, Any], options: RenderOptions) -> str:
    """Calendar items grouped by day, like the app's agenda (items arrive soonest first)."""
    days: dict[str, list[str]] = {}
    for item in result.get("items", []):
        start = parse_timestamp((item.get("calendarItem") or {}).get("startDate"))
        day = format_day(start) if start else "Date unknown"
        days.setdefault(day, []).append(agenda_entry(item, options))
    blocks = [f"## {day}\n" + "\n".join(entries) for day, entries in days.items()]
    title = "Agenda, earlier items" if result.get("period") == "past" else "Agenda"
    heading = f"# {title} ({result.get('count', len(result.get('items', [])))})"
    return document(heading, *blocks) if blocks else document(heading, "Nothing planned.")


def agenda_entry(item: dict[str, Any], options: RenderOptions) -> str:
    """'- 17:30-19:00  Title · group(s) · RSVP needed · ● new · #id', plus details lines."""
    calendar_item = item.get("calendarItem") or {}
    title = str(calendar_item.get("title") or "(no title)")
    if item.get("cancelled"):
        title = f"{title} (cancelled)"
    markers = [
        short_list(group_names(item)),
        "RSVP needed" if calendar_item.get("rsvpRequired") else "",
        f"{UNREAD_MARK} new" if item.get("read") is False else "",
        object_id(item.get("id")),
    ]
    lines = [f"- {time_span(item)}  {join_parts([title, *markers])}"]
    lines += [f"  {line}" for line in detail_lines(item, options)]
    return "\n".join(lines)


def short_list(names: list[str], shown: int = GROUPS_SHOWN) -> str:
    """'a, b, c +5 more' instead of eight names on one line."""
    if len(names) <= shown + 1:
        return ", ".join(names)
    return f"{', '.join(names[:shown])} +{len(names) - shown} more"


def group_names(item: dict[str, Any]) -> list[str]:
    names = [
        str(g["name"]) for g in item.get("groups") or [] if isinstance(g, dict) and g.get("name")
    ]
    return names or ([str(item["group"])] if item.get("group") else [])


def time_span(item: dict[str, Any]) -> str:
    """'17:30-19:00', 'all day', or 'all day, 5 days until Fri 25 Dec 2026'."""
    calendar_item = item.get("calendarItem") or {}
    start = parse_timestamp(calendar_item.get("startDate"))
    end = parse_timestamp(calendar_item.get("endDate"))
    day_count = item.get("numberOfDays") or len(calendar_item.get("dayDates") or []) or 1
    if start is None:
        return ""
    if day_count > 1:
        last_day = parse_timestamp((calendar_item.get("dayDates") or [None])[-1]) or end
        until = f" until {format_day(last_day)}" if last_day else ""
        return f"all day, {day_count} days{until}"
    if (start.hour, start.minute) == (0, 0) and (end is None or (end.hour, end.minute) == (0, 0)):
        return "all day"
    if end is None or end == start:
        return format_time(start)
    return f"{format_time(start)}-{format_time(end)}"


def detail_lines(item: dict[str, Any], options: RenderOptions) -> list[str]:
    """Location, description and attachments, when `--details` fetched them."""
    details = item.get("details") or {}
    lines = []
    if details.get("location"):
        lines.append(f"{LOCATION_MARK} {details['location']}")
    if details.get("description"):
        text = str(details["description"]).strip()
        lines += (text if options.full_text else preview(text)).split("\n")
    for attachment in details.get("attachments") or []:
        lines.append(attachment_line(attachment))
    if details.get("attachments"):
        event_id = item.get("id")
        lines.append(
            hint(options, f"attachment {event_id}", f"parro_attachment(announcement_id={event_id})")
        )
    return lines


# ----------------------------------------------------------------------------------- chats


def render_chatrooms(result: dict[str, Any], options: RenderOptions) -> str:
    rooms = result.get("chatrooms", [])
    active = [room for room in rooms if not room.get("archived")]
    archived = [room for room in rooms if room.get("archived")]
    blocks = [chatroom_block(room, options) for room in active]
    if archived:
        lines = [f"- {archived_room_line(room)}" for room in archived]
        blocks.append("## Archived\n" + "\n".join(lines))
    heading = f"# Chats ({result.get('total', len(rooms))})"
    return document(heading, *blocks) if blocks else document(heading, "No chats.")


def chatroom_block(room: dict[str, Any], options: RenderOptions) -> str:
    unread = f" {UNREAD_MARK} {room['unreadCount']} unread" if room.get("unreadCount") else ""
    members = ", ".join(room.get("memberNames") or [])
    count = plural(room["numberOfMembers"], "member") if room.get("numberOfMembers") else ""
    lines = [
        f"## {room.get('title') or '(no title)'}{unread}",
        join_parts([members, count, object_id(room.get("id"))]),
    ]
    last = room.get("lastMessage") or {}
    if last:
        lines.append(
            f"{full_name_of(last.get('identity'))}, {format_timestamp(last.get('createdAt'))}:"
        )
        lines.append(
            quote(message_text(last) if options.full_text else preview(message_text(last)))
        )
    room_id = room.get("id")
    lines.append(
        hint(options, f"chat-messages {room_id}", f"parro_chat_messages(chatroom_id={room_id})")
    )
    return "\n".join(lines)


def archived_room_line(room: dict[str, Any]) -> str:
    return join_parts([room.get("title"), last_message_date(room), object_id(room.get("id"))])


def last_message_date(room: dict[str, Any]) -> str:
    last = room.get("lastMessage") or {}
    when = parse_timestamp(last.get("createdAt") or room.get("sortDate"))
    return f"last message {format_day(when)}" if when else ""


def render_conversation(result: dict[str, Any], options: RenderOptions) -> str:
    """Messages in reading order (oldest first), grouped by day, whatever order the API used."""
    messages = sorted(result.get("messages", []), key=lambda m: m.get("createdAt") or "")
    days: dict[str, list[str]] = {}
    for message in messages:
        when = parse_timestamp(message.get("createdAt"))
        day = format_day(when) if when else "Date unknown"
        header = join_parts(
            [full_name_of(message.get("identity")), format_time(when) if when else ""]
        )
        days.setdefault(day, []).append(f"{header}\n{quote(message_text(message))}")
    blocks = [f"## {day}\n\n" + "\n\n".join(entries) for day, entries in days.items()]
    total = result.get("total", len(messages))
    shown = plural(len(messages), "message") + (f" of {total}" if total > len(messages) else "")
    heading = f"# Chat {object_id(result.get('chatroom_id'))} ({shown})".replace(
        "Chat  (", "Chat ("
    )
    return document(heading, *blocks) if blocks else document(heading, "No messages.")


def message_text(message: dict[str, Any]) -> str:
    return "(message deleted)" if message.get("deleted") else str(message.get("text") or "")


def full_name_of(person: Any) -> str:
    if not isinstance(person, dict):
        return "Someone"
    parts = [person.get("firstname"), person.get("surname")]
    return " ".join(str(part) for part in parts if part) or "Someone"


# ----------------------------------------------------------------------------- attachments


def render_attachment(result: dict[str, Any], options: RenderOptions) -> str:
    """One attachment's text (or what happened to it), several, or the list to choose from."""
    title = result.get("announcement")
    if "message" in result:  # several attachments and none chosen
        lines = [f"- {attachment_line(a)}" for a in result.get("attachments", [])]
        return document(f"# {title}", result["message"], "\n".join(lines))
    readings = result.get("attachments", [result])
    blocks = [attachment_reading(reading, options) for reading in readings]
    heading = f"# Attachments of: {title}" if len(readings) > 1 else None
    return document(heading, *blocks) if heading else document(*blocks)


def attachment_reading(reading: dict[str, Any], options: RenderOptions) -> str:
    photo = is_photo(reading)
    kind = "image" if photo else str(reading.get("format") or "").upper()
    pages = plural(reading["pages"], "page") if reading.get("pages") else ""
    meta = join_parts(
        [
            reading.get("announcement"),
            join_parts([kind, pages]).replace(" · ", ", "),
            format_size(reading.get("bytes")),
            object_id(reading.get("attachment_id")),
        ]
    )
    notes = [
        f"{WARNING_MARK} {reading['error']}" if reading.get("error") else "",
        f"{WARNING_MARK} {reading['warning']}\n{reading.get('url', '')}"
        if reading.get("warning")
        else "",
        f"Saved to {reading['saved_to']}" if reading.get("saved_to") else "",
        f"Shown as an image ({reading.get('contentType')})"
        if reading.get("returned_as") == "image"
        else "",
        f"(Cut off after {reading['shown_chars']} characters: {reading.get('hint', '')})"
        if reading.get("truncated")
        else "",
    ]
    return document(
        f"## {PHOTO_MARK if photo else ATTACHMENT_MARK} {reading.get('filename')}\n{meta}",
        "\n".join(note for note in notes if note),
        str(reading.get("text") or "").strip(),
    ).rstrip("\n")


# -------------------------------------------------------------------------------- overview


def render_overview(result: dict[str, Any], options: RenderOptions) -> str:
    """The app's home screen in four short sections, each with the command that shows more."""
    return document(
        "# Overview",
        overview_unread(result.get("unread") or []),
        overview_announcements(result.get("announcements") or {}, options),
        overview_calendar(result.get("calendar") or {}, options),
        overview_chats(result.get("chats") or {}, options),
    )


def overview_unread(counts_per_guardian: list[dict[str, Any]]) -> str:
    lines = []
    for counts in counts_per_guardian:
        unread = [plural(counts[key], label) for key, label in UNREAD_LABELS if counts.get(key)]
        lines.append(f"{UNREAD_MARK} {', '.join(unread)}" if unread else "Nothing unread.")
    return "## Unread\n" + "\n".join(lines or ["Nothing unread."])


def overview_announcements(feed: dict[str, Any], options: RenderOptions) -> str:
    lines = [f"- {overview_announcement_line(item)}" for item in feed.get("announcements", [])]
    more = hint(options, "announcements", "parro_announcements()")
    return "## Latest announcements\n" + "\n".join([*lines, more] if lines else ["None."])


def overview_announcement_line(item: dict[str, Any]) -> str:
    when = format_timestamp(item.get("date"))
    return join_parts(
        [announcement_title(item), item.get("author"), when, object_id(item.get("id"))]
    )


def overview_calendar(agenda: dict[str, Any], options: RenderOptions) -> str:
    lines = []
    for item in agenda.get("items", []):
        start = parse_timestamp((item.get("calendarItem") or {}).get("startDate"))
        day = format_day(start) if start else ""
        entry = agenda_entry(item, RenderOptions(audience=options.audience)).split("\n")[0]
        lines.append(f"- {day}, {entry.removeprefix('- ')}")
    more = hint(options, "calendar --details", "parro_calendar(details=true)")
    return "## Coming up\n" + "\n".join([*lines, more] if lines else ["Nothing planned."])


def overview_chats(chats: dict[str, Any], options: RenderOptions) -> str:
    lines = []
    for room in chats.get("chatrooms", []):
        unread = f"{UNREAD_MARK} {room.get('unreadCount')} unread"
        lines.append(f"- {join_parts([room.get('title'), unread, object_id(room.get('id'))])}")
    more = hint(options, "chatrooms", "parro_chatrooms()")
    return "## Chats with unread messages\n" + "\n".join([*lines, more] if lines else ["None."])


def render_cache(result: dict[str, Any], options: RenderOptions) -> str:
    if "removed_files" in result:
        removed = plural(result["removed_files"], "file")
        return document("# Cache emptied", f"Removed {removed} from {result['directory']}.")
    state = "on" if result.get("enabled") else "off"
    used = format_size(result.get("bytes")) or "0 bytes"
    limit = format_size(result.get("max_bytes"))
    size = f"{plural(result.get('files', 0), 'file')}, {used} of at most {limit}"
    lines = [
        f"- Folder: {result.get('directory')} ({state})",
        f"- Size: {size}",
        f"- Holds: {result.get('holds')}",
    ]
    return document("# Cache", "\n".join(lines))


# ---------------------------------------------------------------------------------- render

Renderer = Callable[[Any, RenderOptions], str]
VIEW_RENDERERS: dict[str, Renderer] = {
    "status": render_status,
    "login_url": render_login_url,
    "logout": render_logout,
    "account": render_account,
    "children": render_children,
    "groups": render_groups,
    "unread": render_unread,
    "system_news": render_system_news,
    "get": render_any_response,
    "announcements": render_announcement_feed,
    "announcement": render_announcement,
    "calendar": render_agenda,
    "chatrooms": render_chatrooms,
    "chat_messages": render_conversation,
    "attachment": render_attachment,
    "cache": render_cache,
    "overview": render_overview,
}


def render(view: str, data: Any, options: RenderOptions | None = None) -> str:
    """Markdown for one command result. Views without a renderer fall back to fenced JSON."""
    renderer = VIEW_RENDERERS.get(view, render_json_block)
    return renderer(data, options or RenderOptions())
