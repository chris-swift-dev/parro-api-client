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
from parro.rendering import format_timestamp, join_parts

from ..text import heading
from ..widgets import right_aligned
from ..worker import Worker
from .attachments import FileOpener, image_from
from .base import ListDetailSection
from .conversation import ATTACHMENT_SCHEME, Conversation, conversation_html, thumbnail_name
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


class ChatsSection(ListDetailSection):
    def __init__(self, worker: Worker, parent: QWidget | None = None) -> None:
        super().__init__(worker, parent)
        self.empty_text = "No chats for this choice."
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
        self.side_layout.addLayout(right_aligned(self.send_button))
        # A click on a file in the conversation: the link names the message, nothing else.
        self.opener = FileOpener(worker, self.notice.setText, self)
        self.detail.internal_schemes = (ATTACHMENT_SCHEME,)
        self.detail.internal_link.connect(self._open_file)
        self._shown: tuple[Any, ...] | None = None  # room, messages, members, view
        # Not shown: it only keeps a second click from fetching the same file twice.
        self.open_button = QPushButton(self)
        self.open_button.setVisible(False)

    def memory_key(self) -> tuple[Any, ...]:
        return (
            self.unread.isChecked(),
            self.archived.currentData(),
            self.kind.currentData(),
            self.year.value(),
        )

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
        self.run_action(
            self.send_button,
            lambda client: operations.prepare_chat_message(client, room_id, text),
            self._confirm_send,
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
        self._shown = None
        self.detail.forget_images()

        def task(client: ParroClient) -> tuple[Any, Any, Any]:
            return (
                operations.list_chat_messages(client, room_id, MAX_MESSAGES),
                operations.list_chat_members(client, room_id),
                operations.own_identity_ids(client),
            )

        def show(found: tuple[Any, Any, Any]) -> None:
            messages, members, my_ids = found
            view = Conversation(my_ids=my_ids, show_names=room.get("type") != "SINGLE")
            self._shown = (room, messages, members, view)
            self.detail.show_at_end(conversation_html(room, messages, members, view))
            if any(with_picture(message) for message in messages.get("messages", [])):
                self._fetch_pictures(room_id)

        self.detail.setHtml(heading(room.get("title") or "Chat"))
        self.fetch_detail(task, show)

    def _fetch_pictures(self, room_id: Any) -> None:
        """The small pictures arrive after the text, and are put in without moving the reader."""

        def arrived(pictures: dict[Any, bytes]) -> None:
            if self._shown is None:
                return
            room, messages, members, view = self._shown
            sizes = dict(view.pictures)
            for attachment_id, data in pictures.items():
                image = image_from(data)
                if image is not None:
                    self.detail.allow_image(thumbnail_name(attachment_id), image)
                    sizes[attachment_id] = (image.width(), image.height())
            view = Conversation(view.my_ids, sizes, view.show_names)
            self._shown = (room, messages, members, view)
            self.detail.replace_keeping_place(conversation_html(room, messages, members, view))

        self.fetch_detail(
            lambda client: operations.load_thumbnails(
                client, chatroom_id=room_id, limit=MAX_MESSAGES
            ),
            arrived,
        )

    def _open_file(self, link: str) -> None:
        """A click on a message's file. The link holds the message's id; the file's details come
        from the messages the app fetched, never from the link."""
        if self._shown is None:
            return
        room, messages, _members, _view = self._shown
        wanted = link.partition(":")[2]
        for message in messages.get("messages", []):
            attachment = message.get("attachment")
            if str(message.get("id")) == wanted and isinstance(attachment, dict):
                where = {"chatroom_id": room.get("id"), "message_id": message.get("id")}
                self.opener.activate(where, attachment, self.open_button)
                return

    def clear(self) -> None:
        super().clear()
        self._shown = None


def with_picture(message: dict[str, Any]) -> bool:
    attachment = message.get("attachment")
    return isinstance(attachment, dict) and bool(attachment.get("has_thumbnail"))
