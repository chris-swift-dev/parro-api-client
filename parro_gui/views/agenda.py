"""The calendar: what is coming up, or what has been."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from parro import icalendar, operations
from parro.api_client import ParroClient
from parro.cache import write_private_file
from parro.rendering import (
    format_date,
    group_names,
    helper_slot_text,
    helper_status,
    join_parts,
    rsvp_marker,
    time_span,
)

from .. import widgets
from ..text import bullets, document, heading, meta, paragraph, subheading
from ..worker import Worker
from .attachments import AttachmentBar
from .base import ListDetailSection
from .previews import ANSWER_WORDS, helper_preview, rsvp_preview
from .secrets import show_secret

MAX_ITEMS = 30  # each item costs one more request for its details
MAX_EXPORTED_ITEMS = 500
LINK_QUESTION = (
    "Show your calendar subscription link? Anyone who has it can read your Parro calendar without "
    "logging in."
)


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
        paragraph(f"Link: {details['link']}") if details.get("link") else "",
        subheading("Helpers") if slots else "",
        bullets(slots) if slots else "",
    )


class ActionBar(QWidget):
    """What can be done with the chosen item: answer it, and sign up or withdraw per slot."""

    def __init__(self, section: "AgendaSection") -> None:
        super().__init__(section)
        self.section = section
        widgets.make_card(self)
        self.setVisible(False)
        self.rows = QVBoxLayout(self)
        self.rows.setContentsMargins(*widgets.CARD_MARGINS)
        self.rsvp_buttons: dict[str, QPushButton] = {}
        self.slot_rows: list[tuple[QSpinBox, QPushButton, QPushButton]] = []

    def clear(self) -> None:
        while self.rows.count():
            row = self.rows.takeAt(0)
            widget = row.widget() if row is not None else None
            if widget is not None:
                widget.hide()  # gone now, not only once the event loop deletes it
                widget.deleteLater()
        self.rsvp_buttons, self.slot_rows = {}, []
        self.setVisible(False)

    def show_actions(self, item: dict[str, Any]) -> None:
        self.clear()
        event_id = item.get("id")
        if (item.get("calendarItem") or {}).get("rsvpRequired"):
            self._add_rsvp_row(event_id)
        for slot in (item.get("details") or {}).get("helpers") or []:
            self._add_slot_row(event_id, slot)
        self.setVisible(bool(self.rsvp_buttons or self.slot_rows))

    def _add_rsvp_row(self, event_id: Any) -> None:
        row, layout = self._row()
        layout.addWidget(QLabel("Your answer:"))
        for answer, word in ANSWER_WORDS.items():
            button = QPushButton(f"{word}…")
            button.clicked.connect(
                lambda _checked=False, chosen=answer, clicked=button: self.section.answer(
                    event_id, chosen, clicked
                )
            )
            layout.addWidget(button)
            self.rsvp_buttons[answer] = button
        layout.addStretch(1)
        self.rows.addWidget(row)

    def _add_slot_row(self, event_id: Any, slot: dict[str, Any]) -> None:
        row, layout = self._row()
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setText(helper_slot_text(slot))
        count = QSpinBox()
        count.setRange(1, 99)
        count.setToolTip("How many places you take")
        signup, withdraw = QPushButton("Sign up…"), QPushButton("Withdraw…")
        mine = bool(slot.get("you_signed_up"))
        count.setEnabled(not mine)
        signup.setEnabled(not mine)
        withdraw.setEnabled(mine)
        slot_id = slot.get("id")
        signup.clicked.connect(
            lambda: self.section.change_slot("signup", event_id, slot_id, count.value(), signup)
        )
        withdraw.clicked.connect(
            lambda: self.section.change_slot("withdraw", event_id, slot_id, 1, withdraw)
        )
        layout.addWidget(label, 1)
        for widget in (count, signup, withdraw):
            layout.addWidget(widget)
        self.rows.addWidget(row)
        self.slot_rows.append((count, signup, withdraw))

    @staticmethod
    def _row() -> tuple[QWidget, QHBoxLayout]:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        return row, layout


class AgendaSection(ListDetailSection):
    def __init__(self, worker: Worker, parent: QWidget | None = None) -> None:
        super().__init__(worker, parent)
        self.empty_text = "Nothing in the calendar for this choice."
        self.group = QComboBox()
        self.group.addItem("All groups", None)
        self.past = QCheckBox("Earlier items")
        self.add_filter(self.group)
        self.add_filter(self.past)
        self.group.activated.connect(self.load)
        self.past.toggled.connect(self.load)
        self.export_button = QPushButton("Export .ics…")
        self.link_button = QPushButton("Subscription link…")
        self.add_filter(self.export_button)
        self.add_filter(self.link_button)
        self.export_button.clicked.connect(self.export)
        self.link_button.clicked.connect(self.show_link)
        self._groups_added = False
        self.action_bar = ActionBar(self)
        self.add_to_panel(self.action_bar)
        self.attachments = AttachmentBar(worker, self.notice.setText)
        self.add_to_panel(self.attachments)
        self.add_action(self.attachments.save_all_button)
        self.mark_button = self.add_mark_button()
        self.mark_button.clicked.connect(self._mark_current)

    def memory_key(self) -> tuple[Any, ...]:
        return (self.group.currentData(), self.past.isChecked())

    def make_task(self) -> Callable[[ParroClient], Any]:
        past, group = self.past.isChecked(), self.group.currentData()
        with_groups = not self._groups_added

        def task(client: ParroClient) -> dict[str, Any]:
            found = operations.list_calendar(
                client, group, MAX_ITEMS, None, details=True, past=past
            )
            groups = operations.list_groups(client, "current", 50) if with_groups else None
            return {"calendar": found, "groups": groups}

        return task

    def show_result(self, result: dict[str, Any]) -> None:
        if result.get("groups") and not self._groups_added:
            self._groups_added = True
            for group in result["groups"].get("groups", []):
                self.group.addItem(str(group.get("name")), group.get("id"))
        super().show_result(result)

    def rows(self, result: dict[str, Any]) -> list[tuple[str, Any]]:
        return [(agenda_row(item), item) for item in result["calendar"].get("items", [])]

    def _mark_current(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.items):
            self.mark_read("calendar", self.items[row].get("id"))

    def export(self) -> None:
        """What the list shows, as an iCalendar file: dates only, like `calendar --ics`."""
        name = widgets.choose_save_file(self, "parro.ics", "iCalendar (*.ics)")
        if not name:
            return
        past, group = self.past.isChecked(), self.group.currentData()

        def task(client: ParroClient) -> int:
            agenda = operations.list_calendar(client, group, MAX_EXPORTED_ITEMS, None, past=past)
            text = icalendar.build_icalendar(agenda, operations.current_time())
            write_private_file(Path(name), text.encode("utf-8"))
            return int(agenda["count"])

        self.run_action(
            self.export_button,
            task,
            lambda count: self.notice.setText(f"Exported {count} calendar items."),
        )

    def show_link(self) -> None:
        """A secret: only on request, and never kept or written anywhere."""
        if not widgets.ask(self, LINK_QUESTION):
            return
        self.run_action(self.link_button, operations.calendar_link, self._link_arrived)

    def _link_arrived(self, result: dict[str, Any]) -> None:
        show_secret(self, "Calendar subscription link", result["warning"], result["calendar_link"])

    def answer(self, event_id: Any, answer: str, button: QPushButton) -> None:
        """Reads first: the preview, or nothing at all if this is already your answer."""
        self.run_action(
            button,
            lambda client: operations.prepare_rsvp(client, event_id, answer),
            self._confirm_answer,
        )

    def _confirm_answer(self, prepared: dict[str, Any]) -> None:
        word = ANSWER_WORDS[prepared["answer"]]
        if prepared["unchanged"]:
            self.notice.setText(f"Already answered: {word}.")
            return
        self.ask_to_confirm(
            "Answer an invitation",
            rsvp_preview(prepared),
            word,
            lambda client: operations.apply_rsvp(client, prepared),
            lambda _result: self.reload_here(f"Answered: {word}."),
        )

    def change_slot(
        self, action: str, event_id: Any, slot_id: Any, count: int, button: QPushButton
    ) -> None:
        self.run_action(
            button,
            lambda client: operations.prepare_helper_change(
                client, action, event_id, slot_id, count
            ),
            self._confirm_slot,
        )

    def _confirm_slot(self, prepared: dict[str, Any]) -> None:
        signing_up = prepared["action"] == "signup"
        self.ask_to_confirm(
            "Sign up" if signing_up else "Withdraw",
            helper_preview(prepared),
            "Sign up" if signing_up else "Withdraw",
            lambda client: operations.apply_helper_change(client, prepared),
            lambda _result: self.reload_here("Signed up." if signing_up else "Withdrawn."),
        )

    def show_item(self, item: dict[str, Any]) -> None:
        self.detail.setHtml(agenda_html(item))
        self.action_bar.show_actions(item)
        self.mark_button.setEnabled(item.get("read") is False)
        attachments = (item.get("details") or {}).get("attachments") or []
        self.attachments.show_attachments(item.get("id"), attachments)

    def clear(self) -> None:
        super().clear()
        if hasattr(self, "action_bar"):
            self.attachments.clear()
            self.action_bar.clear()
