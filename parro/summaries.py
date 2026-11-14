"""Turn raw API payloads into the compact dicts that both the CLI and the MCP server print.

Pure functions: they take what ParroClient returned and never send requests. Field names in the
output are kept stable (they match the original MCP server's output), because scripts and MCP
clients may depend on them.
"""

from datetime import datetime
from typing import Any

from .api_client import ApiResponse, FeedEvent
from .attachments import (
    AttachmentFile,
    can_extract_text,
    describe_attachment,
    detect_format,
    find_attachments,
)
from .authenticator import LoginStatus
from .geon import full_name, get_object_id, parse_timestamp, strip_geon_metadata
from .naming import cli_command

READ_ATTACHMENT_HINT = "Use parro_attachment with this announcement id to read the attachment text."


def drop_missing(fields: dict[str, Any]) -> dict[str, Any]:
    """The same dict without the keys whose value is None."""
    return {key: value for key, value in fields.items() if value is not None}


def total_or_count(response: ApiResponse) -> int:
    """The total from Content-Range, or the number of items when the header has none."""
    total = response.total
    return total if total is not None else len(response.items)


# ------------------------------------------------------------------------------- account


def summarize_account(account: dict[str, Any], role_header: str | None) -> dict[str, Any]:
    identity = account.get("identity") or {}
    child_names = [child.get("firstname") for child in identity.get("children") or []]
    return {
        "name": full_name(identity),
        "email": account.get("email"),
        "username": account.get("username"),
        "accountType": account.get("accountType"),
        "role_header": role_header,
        "organisation": strip_geon_metadata(account.get("organisation") or {}),
        "children": child_names or None,
    }


def summarize_logged_in_account(account: dict[str, Any], role_header: str | None) -> dict[str, Any]:
    """The short account block of the status output."""
    return {
        "name": full_name(account.get("identity")),
        "email": account.get("email"),
        "accountType": account.get("accountType"),
        "organisation": (account.get("organisation") or {}).get("name"),
        "role_header": role_header,
    }


def summarize_login_status(status: LoginStatus, scope: str, base_uri: str) -> dict[str, Any]:
    """Login state without secrets. The caller adds `logged_in_as` or `error`."""
    summary: dict[str, Any] = {
        "token_file": status.token_file,
        "has_access_token": status.has_access_token,
        "has_refresh_token": status.has_refresh_token,
        "credentials_in_env": status.credentials_configured,
        "login_method": status.login_method,
        "scope": scope,
        "base_uri": base_uri,
    }
    if status.login_halted_reason:
        summary["automatic_login_halted"] = status.login_halted_reason
        summary["how_to_resume"] = (
            f"Fix the password first. Then log in explicitly (CLI: `{cli_command('login')}`, MCP: "
            "parro_login), which spends exactly one attempt. Nothing retries on its own, so the "
            "account cannot get locked."
        )
    if status.access_token_expires_in_seconds is not None:
        summary["access_token_expires_in_seconds"] = status.access_token_expires_in_seconds
        summary["access_token_valid"] = status.access_token_expires_in_seconds > 0
    if status.login_expires_at is not None and status.login_expires_in_seconds is not None:
        # The login ends when the refresh token expires: then a new password check is needed.
        valid_until = datetime.fromtimestamp(status.login_expires_at).astimezone()
        summary["login_valid_until"] = valid_until.isoformat(timespec="seconds")
        summary["login_expires_in_seconds"] = status.login_expires_in_seconds
    return summary


# ------------------------------------------------------------------------ people, groups


def summarize_children(response: ApiResponse) -> dict[str, Any]:
    return {
        "total": total_or_count(response),
        "children": [
            {
                "id": get_object_id(child),
                "name": full_name(child),
                "archived": child.get("archived"),
                "enrolledSince": child.get("enrolledSince"),
                "numberOfGuardians": child.get("numberOfGuardians"),
            }
            for child in response.items
        ],
    }


def summarize_group(group: dict[str, Any]) -> dict[str, Any]:
    child_names = [avatar.get("firstname") for avatar in group.get("childAvatars") or []]
    return {
        "id": get_object_id(group),
        "name": group.get("name"),
        "schoolyear": group.get("schooljaar"),
        "type": group.get("type"),
        "isHomeGroup": group.get("stamgroep"),
        "unread": group.get("unreadCount"),
        "muted": group.get("memberMuted"),
        "children": child_names or None,
        "counts": {
            "children": group.get("numberOfChildren"),
            "guardians": group.get("numberOfGuardians"),
            "teachers": group.get("numberOfTeachers"),
        },
    }


def summarize_groups(response: ApiResponse, scope_name: str) -> dict[str, Any]:
    return {
        "scope": scope_name,
        "total": total_or_count(response),
        "groups": [summarize_group(group) for group in response.items],
    }


def summarize_unread_counts(response: ApiResponse) -> list[dict[str, Any]]:
    summaries = []
    for counts in response.items:
        person = counts.get("guardian") or counts.get("identity") or {}
        summaries.append(
            {
                "for": full_name(person),
                "children": person.get("childNames"),
                "announcements": counts.get("numberOfUnreadAnnouncements"),
                "calendar": counts.get("numberOfUnreadCalendarItems"),
                "systemNews": counts.get("numberOfUnreadSystemNewsItems"),
                "chats": counts.get("numberOfUnreadChatRooms"),
                "portal": counts.get("numberOfUnreadPortalNotifications"),
            }
        )
    return summaries


# ------------------------------------------------------------------------- announcements


def summarize_attachment_list(event: dict[str, Any]) -> list[dict[str, Any]]:
    """The attachments of an event or a chat message, compact. A photo has no file name in the
    API, so it gets one here: 'photo-<attachment id>.jpg'."""
    summaries = []
    for attachment in find_attachments(event):
        described = describe_attachment(attachment)
        file_format = detect_format(described.content_type, described.filename)
        summaries.append(
            drop_missing(
                {
                    "attachment_id": described.attachment_id,
                    "kind": described.kind,
                    "filename": described.filename or made_up_filename(described, file_format),
                    "contentType": described.content_type,
                    "size": described.size,
                    "url": described.url,
                    "readable": can_extract_text(described.content_type, described.filename),
                    "media": file_format if file_format in MEDIA_FORMATS else None,
                    "has_thumbnail": True if described.thumbnail_url else None,
                }
            )
        )
    return summaries


# What `media` can be: shown or played, not read as text.
MEDIA_FORMATS = ("image", "video", "audio")
MEDIA_NAMES = {"image": "photo", "video": "video", "audio": "audio"}


def made_up_filename(described: AttachmentFile, file_format: str | None) -> str | None:
    """'photo-6000000201.jpg' for a file the API gives no name."""
    if described.attachment_id is None:
        return None
    subtype = str(described.content_type or "").split(";", 1)[0].rpartition("/")[2].lower()
    extension = {"jpeg": "jpg", "quicktime": "mov", "mpeg": "mp3"}.get(subtype, subtype)
    name = MEDIA_NAMES.get(str(file_format), "attachment")
    return f"{name}-{described.attachment_id}" + (f".{extension}" if extension.isalnum() else "")


def summarize_announcement(
    event: dict[str, Any], group_name: str | None = None, group_names: list[str] | None = None
) -> dict[str, Any]:
    """One announcement. `group_names` is set when it came in through several groups."""
    summary = {
        "id": get_object_id(event),
        "date": event.get("sortDate") or event.get("createdAt"),
        "title": event.get("title"),
        "from": group_name,
        "groups": group_names if group_names and len(group_names) > 1 else None,
        "author": full_name(event.get("owner")) or None,
        "pinned": True if event.get("pinned") else None,
        "read": event.get("read"),
        "liked": event.get("liked"),
        "contents": event.get("contents"),
    }
    attachments = summarize_attachment_list(event)
    if attachments:
        summary["attachments"] = attachments
        summary["hint"] = READ_ATTACHMENT_HINT
    return drop_missing(summary)


def summarize_announcement_detail(event: dict[str, Any]) -> dict[str, Any]:
    """One announcement in full: also who read and liked it (counts only)."""
    summary = summarize_announcement(event)
    counts = event.get("readCount")
    if isinstance(counts, dict):
        summary["readCount"] = drop_missing(
            {key: counts.get(key) for key in ("read", "total", "liked")}
        )
    return summary


def newest_first(feed: list[FeedEvent]) -> list[FeedEvent]:
    return sorted(feed, key=lambda item: item.event.get("sortDate") or "", reverse=True)


def merge_duplicates(feed: list[FeedEvent]) -> list[tuple[FeedEvent, list[str]]]:
    """One entry per event id, with the names of every group it came in through.

    The feed is fetched per group, so an announcement sent to two groups arrives twice. The first
    occurrence is kept (the order stays as given).
    """
    merged: dict[Any, tuple[FeedEvent, list[str]]] = {}
    for item in feed:
        key = get_object_id(item.event) or id(item)
        _first, names = merged.setdefault(key, (item, []))
        if item.group_name and item.group_name not in names:
            names.append(item.group_name)
    return list(merged.values())


def summarize_announcement_feed(
    feed: list[FeedEvent], limit: int, unread_only: bool = False
) -> dict[str, Any]:
    """Merged feed, newest first, each announcement once.

    With unread_only the filter runs *before* the limit (fix 5).
    """
    entries = merge_duplicates(newest_first(feed))
    if unread_only:
        entries = [(item, names) for item, names in entries if not item.event.get("read")]
    shown = [
        summarize_announcement(item.event, item.group_name, names)
        for item, names in entries[:limit]
    ]
    return {"count": len(shown), "announcements": shown}


# ------------------------------------------------------------------------------ calendar


def summarize_calendar_feed(feed: list[FeedEvent], limit: int) -> dict[str, Any]:
    """Calendar items, soonest first, each item once. `count` is the number of items shown.

    An item for several groups already lists them all in its own `groups` field; `group` is the
    group it was found through first.
    """
    ordered = sorted(feed, key=lambda item: item.event.get("sortDate") or "")
    entries = one_per_calendar_item([item for item, _names in merge_duplicates(ordered)])
    shown = [
        {**strip_geon_metadata(item.event), "group": item.group_name} for item in entries[:limit]
    ]
    return {"count": len(shown), "items": shown}


def one_per_calendar_item(entries: list[FeedEvent]) -> list[FeedEvent]:
    """Keep one entry per calendar item: the API lists a multi-day item once per day.

    Each day has its own event id and `dayNumber`, but all share the `calendarItem` (seen live
    2026-11-05: one 40-day item gave 40 entries). The first entry (the earliest day, as the
    list is sorted) is kept; its calendarItem's start, end and dayDates describe the whole span.
    """
    kept: list[FeedEvent] = []
    seen: set[Any] = set()
    for entry in entries:
        key = get_object_id(entry.event.get("calendarItem")) or get_object_id(entry.event)
        if key is None or key not in seen:
            kept.append(entry)
            seen.add(key)
    return kept


def is_over(item: dict[str, Any], now: datetime) -> bool:
    """True when a calendar item's last day lies before today (in the item's own time zone)."""
    calendar_item = item.get("calendarItem") or {}
    days = calendar_item.get("dayDates") or [
        calendar_item.get("endDate") or calendar_item.get("startDate")
    ]
    last_day = parse_timestamp(days[-1])
    if last_day is None or last_day.tzinfo is None:
        return False
    return last_day.date() < now.astimezone(last_day.tzinfo).date()


def summarize_calendar_details(event: dict[str, Any]) -> dict[str, Any]:
    """What the calendar list leaves out: location, description, helper slots and attachments
    (spec: getEvent).

    Attachments are listed without their download `url`: these details may be cached, and links
    are never cached. `attachment <event id>` fetches a fresh link when one is needed.

    `link` is the web address a teacher added to the item (`calendarItem.url`, only in this detail
    call): part of the item's own text, so it is kept. Anything but http(s) is left out.
    """
    item = event.get("calendarItem") or {}
    attachments = [without_url(a) for a in summarize_attachment_list(event)]
    return drop_missing(
        {
            "location": item.get("location") or None,
            "description": item.get("description") or None,
            "link": web_address(item.get("url")),
            "helpers": summarize_helpers(item) or None,
            "attachments": attachments or None,
        }
    )


# Calendar item types that ask parents to help (seen live: VOLUNTEER and SCHOOLWIDE_VOLUNTEER).
VOLUNTEER_TYPE_SUFFIX = "VOLUNTEER"
RSVP_WORDS = {"ACCEPT": "accepted", "DECLINE": "declined", "TENTATIVE": "tentative"}


def summarize_helpers(calendar_item: dict[str, Any]) -> list[dict[str, Any]]:
    """The helper slots of a calendar item that asks for volunteers (spec: getCalendarItem).

    Each slot: its title, how many helpers are wanted, how many signed up, and whether you did.
    The API spells the last one `commitedByMe`.
    """
    slots = []
    for resource in calendar_item.get("resources") or []:
        if not isinstance(resource, dict):
            continue
        slots.append(
            drop_missing(
                {
                    "id": get_object_id(resource),
                    "title": str(resource.get("title") or "").strip() or None,
                    "wanted": resource.get("amount"),
                    "signed_up": resource.get("amountCommitted"),
                    "you_signed_up": bool(resource.get("commitedByMe")),
                }
            )
        )
    return slots


def rsvp_answer(item: dict[str, Any]) -> str | None:
    """'accepted', 'declined' or 'tentative': your answer (the event's `rsvp`), None if none yet."""
    return RSVP_WORDS.get(str(item.get("rsvp")))


def wants_helpers(calendar_item: dict[str, Any]) -> bool:
    """True for a calendar item that asks parents to help (the list shows only its type)."""
    kind = str(calendar_item.get("type") or "")
    return kind.endswith(VOLUNTEER_TYPE_SUFFIX) or bool(calendar_item.get("resources"))


def web_address(value: Any) -> str | None:
    """`value` when it is an http(s) address, else None."""
    address = str(value or "").strip()
    return address if address.lower().startswith(("https://", "http://")) else None


def without_url(attachment: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in attachment.items() if key != "url"}


# -------------------------------------------------------------------------------- privacy


def summarize_privacy(response: ApiResponse) -> dict[str, Any]:
    """Per child, the state of the privacy choices (spec: listChildren, privacy variant).

    The choices themselves are not in the API; `privacy --link` gives the page that has them.
    `lastEditedBy` is a plain name here (a person object elsewhere in the API).
    """
    children = []
    for child in response.items:
        setting = child.get("setting") if isinstance(child.get("setting"), dict) else {}
        changed_by = setting.get("lastEditedBy")
        children.append(
            drop_missing(
                {
                    "id": get_object_id(child),
                    "name": child.get("firstname") or full_name(child) or None,
                    "parents_can_change": setting.get("editableForGuardians"),
                    "editable_in_period": setting.get("editableInPeriod"),
                    "state": setting.get("state"),
                    "last_changed": setting.get("lastModifiedAt"),
                    "last_changed_by": (
                        full_name(changed_by) if isinstance(changed_by, dict) else changed_by
                    )
                    or None,
                }
            )
        )
    return {"total": total_or_count(response), "children": children}


# ---------------------------------------------------------------------------------- chats


def summarize_chatrooms(response: ApiResponse) -> dict[str, Any]:
    return {
        "total": total_or_count(response),
        "chatrooms": [summarize_chatroom(room) for room in response.items],
    }


def summarize_chatroom(room: dict[str, Any]) -> dict[str, Any]:
    """A chat; its last message in the same compact form as in the conversation."""
    summary: dict[str, Any] = strip_geon_metadata(room)
    last = room.get("lastMessage")
    if isinstance(last, dict):
        summary["lastMessage"] = summarize_chat_message(last)
    return summary


def summarize_chat_members(response: ApiResponse) -> dict[str, Any]:
    """Members of a chat: each a guardian (parent) or a teacher (spec: RChatRoomMember)."""
    members = []
    for member in response.items:
        person = member.get("guardian") or member.get("teacher") or member.get("identity") or {}
        role = "teacher" if member.get("teacher") else "parent" if member.get("guardian") else None
        members.append(
            drop_missing(
                {
                    "id": get_object_id(person),
                    "name": full_name(person) or None,
                    "role": role,
                    "children": [str(name) for name in person.get("childNames") or []] or None,
                    "admin": bool(member.get("admin")),
                    "active": member.get("active"),
                }
            )
        )
    return {"total": total_or_count(response), "members": members}


def summarize_chat_messages(response: ApiResponse) -> dict[str, Any]:
    return {
        "total": total_or_count(response),
        "messages": [summarize_chat_message(message) for message in response.items],
    }


def summarize_chat_message(message: dict[str, Any]) -> dict[str, Any]:
    """One message; its attachment (a photo, video, document) in the compact form of an event's."""
    summary: dict[str, Any] = strip_geon_metadata(message)
    found = summarize_attachment_list(message)
    if found:
        summary["attachment"] = found[0]
    return summary


# ------------------------------------------------------------------------------ anything


def summarize_any_response(response: ApiResponse, raw: bool = False) -> dict[str, Any]:
    """Output of the generic `get` command: the Content-Range plus the (stripped) body."""
    body = response.payload if raw else strip_geon_metadata(response.payload)
    return {"content_range": response.content_range, "body": body}
