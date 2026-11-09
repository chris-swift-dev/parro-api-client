"""Conversations: the list with its filters, and one conversation."""

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from parro import operations
from parro.api_client import ParroClient
from parro.operations import ChatFilter
from parro.rendering import format_timestamp, full_name_of, join_parts, member_role, message_text

from ..text import document, heading, meta, paragraph
from ..worker import Worker
from .base import ListDetailSection
from .previews import chat_preview

MAX_CHATS = 60
MAX_MESSAGES = 100
NO_YEAR = 2000  # the spin box's lowest value stands for "every year"


def chat_row(room: dict[str, Any]) -> str:
    title = str(room.get("title") or "(no title)")
    unread = room.get("unreadCount") or 0
    if unread:
        title = f"● {title} ({unread})"
    kind = str(room.get("type") or "").lower()
    return f"{title}\n{join_parts([kind, format_timestamp(room.get('sortDate'))])}"


def conversation_html(room: dict[str, Any], messages: Any, members: Any) -> str:
    names = [
        join_parts([person.get("name"), member_role(person)])
        for person in members.get("members", [])
    ]
    ordered = sorted(messages.get("messages", []), key=lambda m: str(m.get("createdAt") or ""))
    blocks = [heading(room.get("title") or "Chat"), meta(", ".join(names))]
    for message in ordered:
        blocks.append(
            meta(full_name_of(message.get("identity")), format_timestamp(message.get("createdAt")))
        )
        blocks.append(paragraph(message_text(message)))
    return document(*blocks)


class ChatsSection(ListDetailSection):
    def __init__(self, worker: Worker, parent: QWidget | None = None) -> None:
        super().__init__(worker, parent)
        self.unread = QCheckBox("Unread only")
        self.archived = QComboBox()
        for label, value in (
            ("Not archived", "exclude"),
            ("Archived", "only"),
            ("Archived too", "include"),
        ):
            self.archived.addItem(label, value)
        self.kind = QComboBox()
        self.kind.addItem("Every kind", None)
        for kind in ("single", "group", "calendar", "family", "bot"):
            self.kind.addItem(kind.capitalize(), kind)
        self.year = QSpinBox()
        self.year.setRange(NO_YEAR, 2100)
        self.year.setSpecialValueText("Every school year")
        for widget in (self.unread, self.archived, self.kind, self.year):
            self.add_filter(widget)
        self.unread.toggled.connect(self.load)
        self.archived.activated.connect(self.load)
        self.kind.activated.connect(self.load)
        self.year.editingFinished.connect(self.load)
        self.mark_button = self.add_mark_button()
        self.mark_button.clicked.connect(self._mark_current)
        self.compose = QPlainTextEdit()
        self.compose.setPlaceholderText("Write a message…")
        self.compose.setMaximumHeight(90)
        self.send_button = QPushButton("Send…")
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.send)
        self.side_layout.addWidget(self.compose)
        self.side_layout.addWidget(self.send_button)

    def make_task(self) -> Callable[[ParroClient], Any]:
        year = None if self.year.value() == NO_YEAR else self.year.value()
        chats = ChatFilter(
            self.unread.isChecked(), str(self.archived.currentData()), self.kind.currentData(), year
        )
        return lambda client: operations.list_chatrooms(client, MAX_CHATS, chats=chats)

    def rows(self, result: dict[str, Any]) -> list[tuple[str, Any]]:
        return [(chat_row(room), room) for room in result.get("chatrooms", [])]

    def _current_room(self) -> dict[str, Any] | None:
        row = self.list.currentRow()
        return self.items[row] if 0 <= row < len(self.items) else None

    def _mark_current(self) -> None:
        room = self._current_room()
        if room is not None:
            self.mark_read("chat", room.get("id"))

    def send(self) -> None:
        """Reads first: the chat, who receives it and the exact text. Only Confirm sends."""
        room = self._current_room()
        if room is None:
            return
        room_id, text = room.get("id"), self.compose.toPlainText()
        self.worker.submit(
            lambda client: operations.prepare_chat_message(client, room_id, text),
            self._confirm_send,
            self.notice.setText,
        )

    def _confirm_send(self, prepared: dict[str, Any]) -> None:
        self.ask_to_confirm(
            "Send a message",
            chat_preview(prepared),
            "Send",
            lambda client: operations.send_prepared_message(client, prepared),
            self._sent,
        )

    def _sent(self, _result: dict[str, Any]) -> None:
        self.compose.clear()
        self.reload_here("Sent.")

    def show_item(self, room: dict[str, Any]) -> None:
        self.send_button.setEnabled(True)
        self.mark_button.setEnabled(bool(room.get("unreadCount")))
        room_id = room.get("id")

        def task(client: ParroClient) -> tuple[Any, Any]:
            return (
                operations.list_chat_messages(client, room_id, MAX_MESSAGES),
                operations.list_chat_members(client, room_id),
            )

        def show(found: tuple[Any, Any]) -> None:
            self.detail.setHtml(conversation_html(room, *found))

        self.detail.setHtml(heading(room.get("title") or "Chat"))
        self.fetch_detail(task, show)
