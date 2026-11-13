"""The attachments of the chosen item: read them here, or save the file."""

import base64
from collections import Counter
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from parro import operations
from parro.attachments import ReadOptions
from parro.rendering import format_size

from .. import widgets
from ..text import document, meta, paragraph
from ..worker import Worker, submit_from

# A newsletter is long, but a window should not try to show a whole book.
MAX_CHARS = 300_000
SAVE_ALL = "Save all attachments…"


def files(count: int) -> str:
    return f"{count} {'file' if count == 1 else 'files'}"


def describe_saved(report: Any, folder: str) -> tuple[str, str]:
    """What Save all did, short, and the files that were not saved, one per line.

    The short text counts the reasons instead of naming every file: twenty files that failed for
    one reason are one line, not twenty (live check of 0.12.0).
    """
    summary = report.summary
    found = summary.get("attachments") or [summary]
    saved = [f for f in found if f.get("saved_to")]
    failed = [f for f in found if not f.get("saved_to")]
    if not failed:
        return f"Saved {files(len(saved))} in {folder}.", ""
    reasons = Counter(str(f.get("error") or "not saved") for f in failed)
    counted = "; ".join(f"{reason} ({count})" for reason, count in reasons.most_common())
    text = f"Saved {len(saved)} of {files(len(found))} in {folder}."
    text += f" {len(failed)} not saved: {counted}."
    details = "Not saved:\n" + "\n".join(
        f"- {f.get('filename') or 'attachment'}: {f.get('error') or 'not saved'}" for f in failed
    )
    return text, details


class ReadingDialog(QDialog):
    """One attachment: its text, or the picture."""

    def __init__(self, report: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        summary = report.summary
        self.setWindowTitle(str(summary.get("filename") or "Attachment"))
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        self.text = widgets.SafeTextBrowser()
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if report.images:
            pixels = QPixmap()
            pixels.loadFromData(base64.b64decode(report.images[0].base64_data))
            self.picture.setPixmap(pixels)
            scroll = QScrollArea()
            scroll.setWidget(self.picture)
            layout.addWidget(scroll)
        else:
            notes = (summary.get("error"), summary.get("warning"))
            self.text.setHtml(
                document(
                    *(meta(note) for note in notes if note),
                    paragraph(summary.get("text")),
                )
            )
            layout.addWidget(self.text)


class AttachmentBar(QWidget):
    """A row per attachment of the chosen item."""

    def __init__(self, worker: Worker, report_problem: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.worker = worker
        self.report_problem = report_problem
        self.dialog: ReadingDialog | None = None
        widgets.make_card(self)
        self.setVisible(False)
        self.rows = QVBoxLayout(self)
        self.rows.setContentsMargins(*widgets.CARD_MARGINS)
        self.read_buttons: list[QPushButton] = []
        self.save_buttons: list[QPushButton] = []
        self.event_id: Any = None
        # The section puts this button in its action row, next to Mark as read.
        self.save_all_button = QPushButton(SAVE_ALL)
        self.save_all_button.setEnabled(False)
        self.save_all_button.clicked.connect(self.save_all)
        self._saving_all = False

    def show_attachments(self, event_id: Any, attachments: list[dict[str, Any]]) -> None:
        self.clear()
        self.event_id = event_id
        for attachment in attachments:
            self._add_row(event_id, attachment)
        self.setVisible(bool(attachments))
        self._enable_save_all()

    def clear(self) -> None:
        while self.rows.count():
            row = self.rows.takeAt(0)
            widget = row.widget() if row is not None else None
            if widget is not None:
                widget.hide()  # gone now, not only once the event loop deletes it
                widget.deleteLater()
        self.read_buttons, self.save_buttons = [], []
        self.event_id = None
        self.setVisible(False)
        self._enable_save_all()

    def _enable_save_all(self) -> None:
        self.save_all_button.setEnabled(bool(self.read_buttons) and not self._saving_all)

    def _add_row(self, event_id: Any, attachment: dict[str, Any]) -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        name = f"{attachment.get('filename')} ({format_size(attachment.get('size'))})"
        label = widgets.ElidedLabel(name)  # a long name never pushes the buttons away
        read, save = QPushButton("Read"), QPushButton("Save…")
        attachment_id = attachment.get("attachment_id")
        read.clicked.connect(lambda: self.read(event_id, attachment_id, read))
        save.clicked.connect(lambda: self.save(event_id, attachment_id, save))
        layout.addWidget(label, 1)
        layout.addWidget(read)
        layout.addWidget(save)
        self.rows.addWidget(row)
        self.read_buttons.append(read)
        self.save_buttons.append(save)

    def read(self, event_id: Any, attachment_id: Any, button: QPushButton) -> None:
        options = ReadOptions(max_chars=MAX_CHARS, include_images=True)
        submit_from(
            self.worker,
            button,
            lambda client: operations.read_attachments(
                client, event_id=event_id, attachment_id=attachment_id, options=options
            ),
            self._show_reading,
            self.report_problem,
        )

    def _show_reading(self, report: Any) -> None:
        self.dialog = ReadingDialog(report, self)
        self.dialog.open()

    def save(self, event_id: Any, attachment_id: Any, button: QPushButton) -> None:
        folder = widgets.choose_folder(self)
        if not folder:
            return
        options = ReadOptions(max_chars=1, include_images=False, save_directory=Path(folder))
        submit_from(
            self.worker,
            button,
            lambda client: operations.read_attachments(
                client, event_id=event_id, attachment_id=attachment_id, options=options
            ),
            self._saved,
            self.report_problem,
        )

    def _saved(self, report: Any) -> None:
        summary = report.summary
        problem = summary.get("error") or summary.get("save_error")
        self.report_problem(str(problem) if problem else f"Saved in {summary.get('saved_to')}.")

    def save_all(self) -> None:
        """One folder question, then every file, one after another, through the one worker."""
        event_id = self.event_id
        if event_id is None or not self.read_buttons:
            return
        folder = widgets.choose_folder(self)
        if not folder:
            return
        options = ReadOptions(max_chars=1, include_images=False, save_directory=Path(folder))
        self._saving_all = True  # a second click would save every file a second time
        self._enable_save_all()
        self.report_problem(f"Saving {len(self.read_buttons)} attachments…")
        self.worker.submit(
            lambda client: operations.read_attachments(
                client, event_id=event_id, read_all=True, options=options
            ),
            lambda report: self._saved_all(*describe_saved(report, folder)),
            self._saved_all,
        )

    def _saved_all(self, text: str, details: str = "") -> None:
        self._saving_all = False
        self._enable_save_all()
        if details:
            self.report_problem(text, details)
        else:
            self.report_problem(text)
