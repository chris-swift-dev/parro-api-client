"""The calendar: what is coming up, or what has been."""

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QCheckBox, QWidget

from parro import operations
from parro.api_client import ParroClient
from parro.rendering import (
    format_date,
    group_names,
    helper_slot_text,
    helper_status,
    join_parts,
    rsvp_marker,
    time_span,
)

from ..text import bullets, document, heading, meta, paragraph, subheading
from ..worker import Worker
from .attachments import AttachmentBar
from .base import ListDetailSection

MAX_ITEMS = 30  # each item costs one more request for its details


def agenda_row(item: dict[str, Any]) -> str:
    calendar_item = item.get("calendarItem") or {}
    title = str(calendar_item.get("title") or "(no title)")
    if item.get("cancelled"):
        title = f"{title} (cancelled)"
    if item.get("read") is False:
        title = f"● {title}"
    when = join_parts([format_date(calendar_item.get("startDate")), time_span(item)])
    return f"{title}\n{join_parts([when, rsvp_marker(item), helper_status(item)])}"


def agenda_html(item: dict[str, Any]) -> str:
    calendar_item = item.get("calendarItem") or {}
    details = item.get("details") or {}
    title = calendar_item.get("title") or "(no title)"
    slots = [helper_slot_text(slot) for slot in details.get("helpers") or []]
    return document(
        heading(f"{title} (cancelled)" if item.get("cancelled") else title),
        meta(format_date(calendar_item.get("startDate")), time_span(item)),
        meta(", ".join(group_names(item)), details.get("location"), rsvp_marker(item)),
        paragraph(details.get("description")),
        subheading("Helpers") if slots else "",
        bullets(slots) if slots else "",
    )


class AgendaSection(ListDetailSection):
    def __init__(self, worker: Worker, parent: QWidget | None = None) -> None:
        super().__init__(worker, parent)
        self.past = QCheckBox("Earlier items")
        self.add_filter(self.past)
        self.past.toggled.connect(self.load)
        self.attachments = AttachmentBar(worker, self.notice.setText)
        self.side_layout.addWidget(self.attachments)

    def make_task(self) -> Callable[[ParroClient], Any]:
        past = self.past.isChecked()
        return lambda client: operations.list_calendar(
            client, None, MAX_ITEMS, None, details=True, past=past
        )

    def rows(self, result: dict[str, Any]) -> list[tuple[str, Any]]:
        return [(agenda_row(item), item) for item in result.get("items", [])]

    def show_item(self, item: dict[str, Any]) -> None:
        self.detail.setHtml(agenda_html(item))
        attachments = (item.get("details") or {}).get("attachments") or []
        self.attachments.show_attachments(item.get("id"), attachments)

    def clear(self) -> None:
        super().clear()
        if hasattr(self, "attachments"):
            self.attachments.clear()
