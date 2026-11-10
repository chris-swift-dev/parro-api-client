"""The attachments of the chosen item: read them here, or save the file."""

import base64
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
from ..worker import Worker

# A newsletter is long, but a window should not try to show a whole book.
MAX_CHARS = 300_000


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

    def show_attachments(self, event_id: Any, attachments: list[dict[str, Any]]) -> None:
        self.clear()
        for attachment in attachments:
            self._add_row(event_id, attachment)
        self.setVisible(bool(attachments))

    def clear(self) -> None:
        while self.rows.count():
            row = self.rows.takeAt(0)
            widget = row.widget() if row is not None else None
            if widget is not None:
                widget.deleteLater()
        self.read_buttons, self.save_buttons = [], []
        self.setVisible(False)

    def _add_row(self, event_id: Any, attachment: dict[str, Any]) -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        name = f"{attachment.get('filename')} ({format_size(attachment.get('size'))})"
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setText(name)
        read, save = QPushButton("Read"), QPushButton("Save…")
        attachment_id = attachment.get("attachment_id")
        read.clicked.connect(lambda: self.read(event_id, attachment_id))
        save.clicked.connect(lambda: self.save(event_id, attachment_id))
        layout.addWidget(label, 1)
        layout.addWidget(read)
        layout.addWidget(save)
        self.rows.addWidget(row)
        self.read_buttons.append(read)
        self.save_buttons.append(save)

    def read(self, event_id: Any, attachment_id: Any) -> None:
        options = ReadOptions(max_chars=MAX_CHARS, include_images=True)
        self.worker.submit(
            lambda client: operations.read_attachments(
                client, event_id=event_id, attachment_id=attachment_id, options=options
            ),
            self._show_reading,
            self.report_problem,
        )

    def _show_reading(self, report: Any) -> None:
        self.dialog = ReadingDialog(report, self)
        self.dialog.open()

    def save(self, event_id: Any, attachment_id: Any) -> None:
        folder = widgets.choose_folder(self)
        if not folder:
            return
        options = ReadOptions(max_chars=1, include_images=False, save_directory=Path(folder))
        self.worker.submit(
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
