"""Calendar items as an iCalendar (.ics) file (RFC 5545), for importing into another calendar app.

Input: the agenda that operations.list_calendar() returns (with `--details`, location and
description are included). Output: one VCALENDAR text with one VEVENT per item.

Choices, and why:
  * Each event's UID is built from its Parro id, so importing a newer export updates events
    instead of adding duplicates.
  * Timed events are written in UTC ("…Z"): unambiguous without VTIMEZONE blocks.
  * All-day events use dates; DTEND is the day *after* the last day (RFC 5545 §3.6.1).
  * Text is escaped and long lines are folded at 75 octets, never inside a UTF-8 character.
  * Lines end in CRLF, as the standard requires.

This is a snapshot: run the export again to update it. Parro's own subscription link
(`calendar-link`) updates by itself.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any

from .geon import parse_timestamp

PRODUCT_ID = "-//parro-api-client//Parro agenda export//EN"
UID_DOMAIN = "parro-api-client"
MAX_LINE_OCTETS = 75


def build_icalendar(agenda: dict[str, Any], generated_at: datetime) -> str:
    """The whole .ics text for the items of an agenda."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODUCT_ID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Parro",
    ]
    stamp = utc_stamp(generated_at)
    for item in agenda.get("items", []):
        lines += event_lines(item, stamp)
    lines.append("END:VCALENDAR")
    return "".join(fold(line) + "\r\n" for line in lines)


def event_lines(item: dict[str, Any], stamp: str) -> list[str]:
    """One VEVENT. Items without a start date are skipped (empty list)."""
    calendar_item = item.get("calendarItem") or {}
    start = parse_timestamp(calendar_item.get("startDate"))
    if start is None:
        return []
    lines = [
        "BEGIN:VEVENT",
        f"UID:parro-event-{item.get('id')}@{UID_DOMAIN}",
        f"DTSTAMP:{stamp}",
        *time_lines(item, start),
        f"SUMMARY:{escape(str(calendar_item.get('title') or 'Parro').strip())}",
    ]
    details = item.get("details") or {}
    if details.get("location"):
        lines.append(f"LOCATION:{escape(str(details['location']))}")
    lines.append(f"DESCRIPTION:{escape(description(item))}")
    groups = [g.get("name") for g in item.get("groups") or [] if isinstance(g, dict)]
    if any(groups):
        lines.append("CATEGORIES:" + ",".join(escape(str(name)) for name in groups if name))
    if item.get("cancelled"):
        lines.append("STATUS:CANCELLED")
    lines.append("END:VEVENT")
    return lines


def time_lines(item: dict[str, Any], start: datetime) -> list[str]:
    """DTSTART/DTEND: dates for all-day and multi-day items, UTC times otherwise."""
    calendar_item = item.get("calendarItem") or {}
    end = parse_timestamp(calendar_item.get("endDate"))
    day_dates = [parse_timestamp(d) for d in calendar_item.get("dayDates") or []]
    days = [d for d in day_dates if d is not None]
    all_day = (start.hour, start.minute) == (0, 0) and (
        end is None or (end.hour, end.minute) == (0, 0)
    )
    if all_day or (item.get("numberOfDays") or 1) > 1:
        last_day = days[-1].date() if days else (end or start).date()
        last_day = max(last_day, start.date())
        return [
            f"DTSTART;VALUE=DATE:{ical_date(start.date())}",
            f"DTEND;VALUE=DATE:{ical_date(last_day + timedelta(days=1))}",
        ]
    finish = end if end is not None and end > start else start + timedelta(hours=1)
    return [f"DTSTART:{utc_stamp(start)}", f"DTEND:{utc_stamp(finish)}"]


def description(item: dict[str, Any]) -> str:
    """The item's description, plus what the app shows next to it (groups, RSVP, id)."""
    details = item.get("details") or {}
    calendar_item = item.get("calendarItem") or {}
    parts = [str(details.get("description") or "").strip()]
    if calendar_item.get("rsvpRequired"):
        parts.append("Reply needed in Parro.")
    parts.append(f"Parro calendar item #{item.get('id')}")
    return "\n\n".join(part for part in parts if part)


def escape(text: str) -> str:
    """RFC 5545 §3.3.11 TEXT: escape backslash, semicolon, comma and line breaks."""
    text = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def fold(line: str) -> str:
    """Split a content line into pieces of at most 75 octets, continued with CRLF + space."""
    pieces: list[str] = []
    current, size = "", 0
    for character in line:
        width = len(character.encode("utf-8"))
        limit = MAX_LINE_OCTETS if not pieces else MAX_LINE_OCTETS - 1  # the space counts
        if size + width > limit:
            pieces.append(current)
            current, size = "", 0
        current += character
        size += width
    pieces.append(current)
    return "\r\n ".join(pieces)


def utc_stamp(moment: datetime) -> str:
    """'20261111T163000Z'."""
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ical_date(day: date) -> str:
    return day.strftime("%Y%m%d")
