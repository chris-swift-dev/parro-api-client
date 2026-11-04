"""Turn raw API payloads into the compact dicts that both the CLI and the MCP server print.

Pure functions: they take what ParroClient returned and never send requests. Field names in the
output are kept stable (they match the original MCP server's output), because scripts and MCP
clients may depend on them.
"""

from typing import Any

from .api_client import ApiResponse, FeedEvent
from .attachments import can_extract_text, describe_attachment, find_attachments
from .authenticator import LoginStatus
from .geon import full_name, get_object_id, strip_geon_metadata

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
            "Fix the password first. Then log in explicitly (CLI: `parro_cli.py login`, MCP: "
            "parro_login), which spends exactly one attempt. Nothing retries on its own, so the "
            "account cannot get locked."
        )
    if status.access_token_expires_in_seconds is not None:
        summary["access_token_expires_in_seconds"] = status.access_token_expires_in_seconds
        summary["access_token_valid"] = status.access_token_expires_in_seconds > 0
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
    summaries = []
    for attachment in find_attachments(event):
        described = describe_attachment(attachment)
        summaries.append(
            drop_missing(
                {
                    "attachment_id": described.attachment_id,
                    "kind": described.kind,
                    "filename": described.filename,
                    "contentType": described.content_type,
                    "size": described.size,
                    "url": described.url,
                    "readable": can_extract_text(described.content_type, described.filename),
                }
            )
        )
    return summaries


def summarize_announcement(event: dict[str, Any], group_name: str | None = None) -> dict[str, Any]:
    summary = {
        "id": get_object_id(event),
        "date": event.get("sortDate") or event.get("createdAt"),
        "title": event.get("title"),
        "from": group_name,
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
    summary = summarize_announcement(event)
    author = full_name(event.get("owner"))
    if author:
        summary["author"] = author
    return summary


def newest_first(feed: list[FeedEvent]) -> list[FeedEvent]:
    return sorted(feed, key=lambda item: item.event.get("sortDate") or "", reverse=True)


def summarize_announcement_feed(
    feed: list[FeedEvent], limit: int, unread_only: bool = False
) -> dict[str, Any]:
    """Merged feed, newest first. With unread_only the filter runs *before* the limit (fix 5)."""
    ordered = newest_first(feed)
    if unread_only:
        ordered = [item for item in ordered if not item.event.get("read")]
    shown = [summarize_announcement(item.event, item.group_name) for item in ordered[:limit]]
    return {"count": len(shown), "announcements": shown}


# ------------------------------------------------------------------------------ calendar


def summarize_calendar_feed(feed: list[FeedEvent], limit: int) -> dict[str, Any]:
    """Calendar items, soonest first. `count` is the number of items shown."""
    ordered = sorted(feed, key=lambda item: item.event.get("sortDate") or "")
    shown = [
        {**strip_geon_metadata(item.event), "group": item.group_name} for item in ordered[:limit]
    ]
    return {"count": len(shown), "items": shown}


# ---------------------------------------------------------------------------------- chats


def summarize_chatrooms(response: ApiResponse) -> dict[str, Any]:
    return {
        "total": total_or_count(response),
        "chatrooms": [strip_geon_metadata(room) for room in response.items],
    }


def summarize_chat_messages(response: ApiResponse) -> dict[str, Any]:
    return {
        "total": total_or_count(response),
        "messages": [strip_geon_metadata(message) for message in response.items],
    }


# ------------------------------------------------------------------------------ anything


def summarize_any_response(response: ApiResponse, raw: bool = False) -> dict[str, Any]:
    """Output of the generic `get` command: the Content-Range plus the (stripped) body."""
    body = response.payload if raw else strip_geon_metadata(response.payload)
    return {"content_range": response.content_range, "body": body}
