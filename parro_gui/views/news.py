"""Announcements, and the news from Parro itself."""

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QCheckBox, QComboBox, QWidget

from parro import operations
from parro.api_client import ParroClient
from parro.attachments import extract_html_text, tidy_whitespace
from parro.rendering import format_date, format_timestamp, join_parts

from ..text import document, heading, meta, paragraph
from ..worker import Worker
from .attachments import AttachmentBar
from .base import ListDetailSection

MAX_ITEMS = 50
PARRO_NEWS = -1


def announcement_row(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "(no title)")
    if item.get("read") is False:
        title = f"● {title}"
    return f"{title}\n{join_parts([format_date(item.get('date')), item.get('author')])}"


def announcement_html(item: dict[str, Any]) -> str:
    counts = item.get("readCount") or {}
    read = f"read by {counts['read']} of {counts['total']}" if counts.get("total") else ""
    return document(
        heading(item.get("title") or "(no title)"),
        meta(format_timestamp(item.get("date")), item.get("author"), read),
        paragraph(item.get("contents")),
    )


class NewsSection(ListDetailSection):
    def __init__(self, worker: Worker, parent: QWidget | None = None) -> None:
        super().__init__(worker, parent)
        self.source = QComboBox()
        self.source.addItem("All groups", None)
        self.source.addItem("News from Parro", PARRO_NEWS)
        self.unread_only = QCheckBox("Unread only")
        self.add_filter(self.source)
        self.add_filter(self.unread_only)
        self.source.activated.connect(self.load)
        self.unread_only.toggled.connect(self.load)
        self.attachments = AttachmentBar(worker, self.notice.setText)
        self.side_layout.addWidget(self.attachments)
        self._groups_added = False

    def make_task(self) -> Callable[[ParroClient], Any]:
        source, unread = self.source.currentData(), self.unread_only.isChecked()
        with_groups = not self._groups_added

        def task(client: ParroClient) -> dict[str, Any]:
            groups = operations.list_groups(client, "current", 50) if with_groups else None
            if source == PARRO_NEWS:
                return {"news": operations.list_system_news(client, MAX_ITEMS), "groups": groups}
            found = operations.list_announcements(client, source, MAX_ITEMS, unread)
            return {"announcements": found, "groups": groups}

        return task

    def show_result(self, result: dict[str, Any]) -> None:
        if result.get("groups") and not self._groups_added:
            self._groups_added = True
            for offset, group in enumerate(result["groups"].get("groups", [])):
                self.source.insertItem(1 + offset, str(group.get("name")), group.get("id"))
        super().show_result(result)

    def rows(self, result: dict[str, Any]) -> list[tuple[str, Any]]:
        if "news" in result:
            return [
                (f"{n.get('title')}\n{format_date(n.get('scheduleDate'))}", {"news": n})
                for n in result["news"].get("items", [])
            ]
        return [
            (announcement_row(item), {"announcement": item})
            for item in result["announcements"].get("announcements", [])
        ]

    def show_item(self, item: dict[str, Any]) -> None:
        self.attachments.clear()
        if "news" in item:
            news = item["news"]
            body = tidy_whitespace(extract_html_text(str(news.get("contents") or "")))
            self.detail.setHtml(
                document(
                    heading(news.get("title")),
                    meta(format_date(news.get("scheduleDate"))),
                    paragraph(body),
                )
            )
            return
        listed = item["announcement"]
        self.detail.setHtml(announcement_html(listed))
        self.fetch_detail(
            lambda client: operations.show_announcement(client, listed.get("id")),
            self._show_full,
        )

    def _show_full(self, full: dict[str, Any]) -> None:
        self.detail.setHtml(announcement_html(full))
        self.attachments.show_attachments(full.get("id"), full.get("attachments") or [])

    def clear(self) -> None:
        super().clear()
        if hasattr(self, "attachments"):
            self.attachments.clear()
