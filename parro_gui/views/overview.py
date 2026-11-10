"""What is new, like the app's home screen."""

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QCheckBox, QLabel, QWidget

from parro import operations
from parro.api_client import ParroClient
from parro.rendering import join_parts

from ..text import document, heading, meta, paragraph
from ..worker import Worker
from .agenda import agenda_html, agenda_row
from .base import EMPTY, ListDetailSection
from .chats import chat_row
from .news import announcement_html, announcement_row


def unread_line(counts: list[dict[str, Any]]) -> str:
    """'2 announcements · 1 calendar item · 1 chat', added up over everyone on the account."""
    totals = {
        key: sum(c.get(key) or 0 for c in counts) for key in ("announcements", "calendar", "chats")
    }
    parts = [
        f"{totals['announcements']} unread announcements" if totals["announcements"] else "",
        f"{totals['calendar']} new calendar items" if totals["calendar"] else "",
        f"{totals['chats']} unread chats" if totals["chats"] else "",
    ]
    return join_parts(parts) or "Nothing unread"


class OverviewSection(ListDetailSection):
    def __init__(self, worker: Worker, parent: QWidget | None = None) -> None:
        super().__init__(worker, parent)
        self.empty_text = "Nothing new. You are up to date."
        self.everything = QCheckBox("Everything, read or not")
        self.add_filter(self.everything)
        self.everything.toggled.connect(self.load)
        self.counts = QLabel()
        self.main.insertWidget(2, self.counts)

    def make_task(self) -> Callable[[ParroClient], Any]:
        unread_only = not self.everything.isChecked()
        return lambda client: operations.show_overview(client, unread_only=unread_only)

    def show_result(self, result: dict[str, Any]) -> None:
        self.counts.setText(unread_line(result.get("unread") or []))
        super().show_result(result)
        if not self.items:
            self.notice.setText(EMPTY)

    def rows(self, result: dict[str, Any]) -> list[tuple[str, Any]]:
        announcements = (result.get("announcements") or {}).get("announcements", [])
        calendar = (result.get("calendar") or {}).get("items", [])
        chats = (result.get("chats") or {}).get("chatrooms", [])
        return [
            *[(announcement_row(a), ("announcement", a)) for a in announcements],
            *[(agenda_row(c), ("calendar", c)) for c in calendar],
            *[(chat_row(r), ("chat", r)) for r in chats],
        ]

    def show_item(self, item: tuple[str, dict[str, Any]]) -> None:
        kind, data = item
        if kind == "announcement":
            self.detail.setHtml(announcement_html(data))
        elif kind == "calendar":
            self.detail.setHtml(agenda_html(data))
        else:
            last = data.get("lastMessage") or {}
            self.detail.setHtml(
                document(
                    heading(data.get("title") or "Chat"),
                    meta(f"{data.get('unreadCount') or 0} unread"),
                    paragraph(last.get("text")),
                )
            )
