"""One conversation as HTML: your own messages on the right, the others on the left.

Qt's rich text has no rounded corners and no maximum width, so each message is a small table:
an outer row with an empty cell that keeps the message off the other side, and an inner table
that is only as wide as its text. Alignment and a tint together tell your messages from the
others, so it never depends on colour alone.

Everything from other people is escaped (`parro_gui.text`). The only pictures are the thumbnails
the app fetched itself, and a file opens through an internal `parro-attachment:` link that names
the message, never through an address from the text.
"""

import html
from dataclasses import dataclass, field
from typing import Any

from parro.geon import parse_timestamp
from parro.rendering import (
    attachment_kind,
    format_day,
    format_size,
    format_time,
    full_name_of,
    is_status_message,
    join_parts,
    member_role,
    status_text,
)

from ..text import document, heading, meta, safe_html
from ..theme import NAME_COLOUR_COUNT

ATTACHMENT_SCHEME = "parro-attachment"
THUMBNAIL_SCHEME = "parro-thumbnail"
# A thumbnail is shown at most this wide and high.
THUMBNAIL_BOX = 240
# The empty cell beside a message: a message is at most 100 - this wide.
SPACE_PERCENT = 22
KIND_MARKS = {"photo": "▣", "video": "▶", "audio": "♪", "file": "▤"}


@dataclass(frozen=True)
class Conversation:
    """What the view needs besides the messages."""

    my_ids: frozenset[Any] = frozenset()
    # attachment id → (width, height) of the thumbnails the pane may show
    pictures: dict[Any, tuple[int, int]] = field(default_factory=dict)
    show_names: bool = True  # False in a chat with one other person


def thumbnail_name(attachment_id: Any) -> str:
    return f"{THUMBNAIL_SCHEME}:{attachment_id}"


def attachment_link(message_id: Any) -> str:
    return f"{ATTACHMENT_SCHEME}:{message_id}"


def fitted(width: int, height: int, box: int = THUMBNAIL_BOX) -> tuple[int, int]:
    """The size to show a picture at: inside the box, never enlarged."""
    if width <= 0 or height <= 0:
        return box, box
    scale = min(1.0, box / width, box / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def name_class(identity: Any) -> str:
    """A colour of their own for each person: the same person always gets the same one."""
    key = identity.get("id") if isinstance(identity, dict) else None
    number = key if isinstance(key, int) else sum(str(full_name_of(identity)).encode())
    return f"name{number % NAME_COLOUR_COUNT}"


def attachment_html(message: dict[str, Any], view: Conversation) -> str:
    """The thumbnail (when there is one) and a line naming the file; both open it."""
    attachment = message.get("attachment")
    if not isinstance(attachment, dict):
        return ""
    link = html.escape(attachment_link(message.get("id")), quote=True)
    kind = attachment_kind(attachment)
    parts = [kind.capitalize(), attachment.get("filename"), format_size(attachment.get("size"))]
    line = f"{KIND_MARKS.get(kind, KIND_MARKS['file'])} {join_parts(parts)}"
    blocks = []
    size = view.pictures.get(attachment.get("attachment_id"))
    if size:
        width, height = fitted(*size)
        source = html.escape(thumbnail_name(attachment.get("attachment_id")), quote=True)
        picture = f'<img src="{source}" width="{width}" height="{height}">'
        blocks.append(f'<a href="{link}">{picture}</a>')
    blocks.append(f'<a href="{link}">{html.escape(line)}</a>')
    return "<br>".join(blocks)


def bubble(message: dict[str, Any], mine: bool, with_name: bool, view: Conversation) -> str:
    when = parse_timestamp(message.get("createdAt"))
    parts = []
    if with_name:
        name = html.escape(full_name_of(message.get("identity")))
        parts.append(f'<span class="{name_class(message.get("identity"))}"><b>{name}</b></span>')
    if message.get("deleted"):
        parts.append('<span class="meta">(message deleted)</span>')
    else:
        text = str(message.get("text") or "").strip("\n")
        parts += [part for part in (safe_html(text), attachment_html(message, view)) if part]
    body = "<br>".join(parts)
    time = f'&nbsp;&nbsp;<span class="time">{format_time(when)}</span>' if when else ""
    side, cell = ("right", "mine") if mine else ("left", "other")
    inner = (
        f'<table align="{side}" cellspacing="0" cellpadding="8">'
        f'<tr><td class="{cell}">{body}{time}</td></tr></table>'
    )
    space = f'<td width="{SPACE_PERCENT}%"></td>'
    cells = f"{space}<td>{inner}</td>" if mine else f"<td>{inner}</td>{space}"
    return (
        '<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:6px">'
        f"<tr>{cells}</tr></table>"
    )


def centred(text: str, css_class: str) -> str:
    return f'<p class="{css_class}" align="center">{html.escape(text)}</p>'


def messages_html(messages: list[dict[str, Any]], view: Conversation) -> str:
    """The messages in reading order: a line per day, a small line for 'joined' and 'left', and
    a person's name once per run of their messages."""
    ordered = sorted(messages, key=lambda m: str(m.get("createdAt") or ""))
    blocks: list[str] = []
    last_day, last_author = None, None
    for message in ordered:
        when = parse_timestamp(message.get("createdAt"))
        day = format_day(when) if when else ""
        if day != last_day:
            blocks.append(centred(day or "Date unknown", "day"))
            last_day, last_author = day, None
        identity = message.get("identity")
        author = identity.get("id") if isinstance(identity, dict) else None
        if is_status_message(message):
            blocks.append(centred(f"{full_name_of(identity)} {status_text(message)}", "meta"))
            last_author = None
            continue
        mine = author is not None and author in view.my_ids
        with_name = view.show_names and not mine and author != last_author
        blocks.append(bubble(message, mine, with_name, view))
        last_author = author
    return "".join(blocks)


def conversation_html(
    room: dict[str, Any], messages: Any, members: Any, view: Conversation | None = None
) -> str:
    names = [
        join_parts([person.get("name"), member_role(person)])
        for person in members.get("members", [])
    ]
    if view is None:
        view = Conversation()
    return document(
        heading(room.get("title") or "Chat"),
        meta(", ".join(names)),
        messages_html(messages.get("messages", []), view),
    )
