"""The attachments of the chosen item: read them here, open them, or save the file.

A document is read here as text, a photo is shown here, and a video or a sound recording opens
in the program the system uses for it. The same goes for the file of a chat message.
"""

import atexit
import base64
import os
import shutil
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
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
OPEN_IN_PLAYER, SAVE_FILE = "Open", "Save…"
ACTUAL_SIZE, FIT_TO_WINDOW = "Actual size", "Fit to window"
# A photo in the strip is shown at most this large.
STRIP_SIZE = 96
PLAYED = ("video", "audio")

_media_folder: Path | None = None


def flatpak_media_folder(environment: Mapping[str, str]) -> Path | None:
    """In a Flatpak, a folder the desktop can reach too; None elsewhere.

    A Flatpak's /tmp exists only inside the sandbox. The desktop's portal, which opens a file in
    another program for the app, cannot find a file there, and then nothing happens at all (live
    check of 0.13.0). The app's cache folder is the same folder inside and outside the sandbox.
    """
    if not environment.get("FLATPAK_ID"):
        return None
    cache = environment.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / "parro-media"


def media_folder() -> Path:
    """Where a video or recording is kept while its player shows it: a private folder that is
    removed when the app closes."""
    global _media_folder
    if _media_folder is None or not _media_folder.is_dir():
        shared = flatpak_media_folder(os.environ)
        if shared is None:
            _media_folder = Path(tempfile.mkdtemp(prefix="parro-media-"))
        else:
            # Left behind if the app was killed: a film of a child should not stay around.
            shutil.rmtree(shared, ignore_errors=True)
            shared.mkdir(parents=True, exist_ok=True, mode=0o700)
            _media_folder = shared
        atexit.register(shutil.rmtree, _media_folder, ignore_errors=True)
    return _media_folder


def is_picture(attachment: dict[str, Any]) -> bool:
    """A photo. Details kept from before 0.13 have no `media`, so the content type decides too."""
    content_type = str(attachment.get("contentType") or "")
    return attachment.get("media") == "image" or content_type.startswith("image/")


def is_played(attachment: dict[str, Any]) -> bool:
    return attachment.get("media") in PLAYED


def file_label(attachment: dict[str, Any]) -> str:
    size = format_size(attachment.get("size"))
    return f"{attachment.get('filename') or 'attachment'}" + (f" ({size})" if size else "")


def files(count: int) -> str:
    return f"{count} {'file' if count == 1 else 'files'}"


def reason(file: dict[str, Any]) -> str:
    """Why a file was not saved: it could not be fetched, or not be written."""
    return str(file.get("error") or file.get("save_error") or "not saved")


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
    reasons = Counter(str(reason(f)) for f in failed)
    counted = "; ".join(f"{reason} ({count})" for reason, count in reasons.most_common())
    text = f"Saved {len(saved)} of {files(len(found))} in {folder}."
    text += f" {len(failed)} not saved: {counted}."
    details = "Not saved:\n" + "\n".join(
        f"- {f.get('filename') or 'attachment'}: {reason(f)}" for f in failed
    )
    return text, details


class ReadingDialog(QDialog):
    """One attachment: its text, or the picture. With `save`, a button that saves the file."""

    def __init__(
        self,
        report: Any,
        parent: QWidget | None = None,
        save: Callable[[QAbstractButton], None] | None = None,
    ) -> None:
        super().__init__(parent)
        summary = report.summary
        self.setWindowTitle(str(summary.get("filename") or "Attachment"))
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        self.text = widgets.SafeTextBrowser()
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # The photo as fetched; what the label shows is scaled from it, never the other way round.
        self.original = QPixmap()
        self.fitted = True
        self.picture_area = QScrollArea()
        self.size_button = QPushButton(ACTUAL_SIZE)
        self.size_button.setVisible(False)
        self.size_button.clicked.connect(self.toggle_size)
        if report.images:
            self.original.loadFromData(base64.b64decode(report.images[0].base64_data))
            self.picture_area.setWidget(self.picture)
            self.picture_area.setWidgetResizable(True)
            self.picture_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.picture_area, 1)
            self.size_button.setVisible(True)
            self._show_picture()
        else:
            notes = (summary.get("error"), summary.get("warning"))
            self.text.setHtml(
                document(
                    *(meta(note) for note in notes if note),
                    paragraph(summary.get("text")),
                )
            )
            layout.addWidget(self.text)
        self.save_button = QPushButton(SAVE_FILE)
        self.save_button.setVisible(save is not None)
        if save is not None:
            self.save_button.clicked.connect(lambda: save(self.save_button))
        layout.addLayout(widgets.right_aligned(self.size_button, self.save_button))

    def toggle_size(self) -> None:
        """Between the whole photo in the window, and the photo at its own size with scroll bars."""
        self.fitted = not self.fitted
        self.size_button.setText(ACTUAL_SIZE if self.fitted else FIT_TO_WINDOW)
        self._show_picture()

    def _show_picture(self) -> None:
        if self.original.isNull():
            return
        if not self.fitted:
            self.picture_area.setWidgetResizable(False)
            self.picture.setPixmap(self.original)
            self.picture.resize(self.original.size())
            return
        self.picture_area.setWidgetResizable(True)
        room = self.picture_area.viewport().size()
        size = self.original.size()
        if size.width() > room.width() or size.height() > room.height():  # never enlarged
            size = size.scaled(room, Qt.AspectRatioMode.KeepAspectRatio)
        self.picture.setPixmap(
            self.original.scaled(
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt's name)
        super().resizeEvent(event)
        if self.fitted:
            self._show_picture()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt's name)
        super().showEvent(event)
        if self.fitted:  # only now does the window know how much room the photo has
            self._show_picture()


class FileOpener:
    """Reads, opens or saves one file: of an event (`event_id`, `attachment_id`) or of a chat
    message (`chatroom_id`, `message_id`). `where` holds those, as `read_attachments` takes them.
    """

    def __init__(self, worker: Worker, report_problem: Any, parent: QWidget) -> None:
        self.worker = worker
        self.report_problem = report_problem
        self.parent = parent
        self.dialog: ReadingDialog | None = None
        self._opened: dict[Any, str] = {}  # files already fetched for a player, by attachment id

    def activate(
        self, where: dict[str, Any], attachment: dict[str, Any], button: QAbstractButton
    ) -> None:
        """What a click on a file does: a video or recording asks 'open or save', the rest is
        shown here."""
        if not is_played(attachment):
            self.read(where, button)
            return
        kind = str(attachment.get("media"))
        question = f"{file_label(attachment)}\n\nOpen this {kind} in your player, or save it?"
        answer = widgets.choose(self.parent, question, [OPEN_IN_PLAYER, SAVE_FILE])
        if answer == OPEN_IN_PLAYER:
            self.open_in_player(where, attachment, button)
        elif answer == SAVE_FILE:
            self.save(where, button)

    def read(self, where: dict[str, Any], button: QAbstractButton) -> None:
        options = ReadOptions(max_chars=MAX_CHARS, include_images=True)
        submit_from(
            self.worker,
            button,
            lambda client: operations.read_attachments(client, options=options, **where),
            lambda report: self._show_reading(report, where),
            self.report_problem,
        )

    def _show_reading(self, report: Any, where: dict[str, Any]) -> None:
        self.dialog = ReadingDialog(report, self.parent, save=lambda b: self.save(where, b))
        self.dialog.open()

    def open_in_player(
        self, where: dict[str, Any], attachment: dict[str, Any], button: QAbstractButton
    ) -> None:
        """Fetch the file once, into a folder that goes when the app closes, and hand it to the
        system. Nothing from the message decides which program opens: only the file itself."""
        key = attachment.get("attachment_id")
        known = self._opened.get(key)
        if known and Path(known).is_file():
            self._play(known)
            return
        folder = Path(tempfile.mkdtemp(dir=media_folder()))
        options = ReadOptions(max_chars=1, include_images=False, save_directory=folder)
        self.report_problem(f"Fetching {file_label(attachment)}…")

        def fetched(report: Any) -> None:
            summary = report.summary
            path = summary.get("saved_to")
            if not path:
                problem = summary.get("error") or summary.get("save_error") or "not fetched"
                self.report_problem(f"{file_label(attachment)}: {problem}")
                return
            self._opened[key] = str(path)
            self._play(str(path))

        submit_from(
            self.worker,
            button,
            lambda client: operations.read_attachments(client, options=options, **where),
            fetched,
            self.report_problem,
        )

    def _play(self, path: str) -> None:
        # The system opens it, and does not always say whether it could: in a Flatpak the app
        # never hears back. So the message says what was done, and what to do if nothing opens.
        opened = widgets.open_file(path)
        name = Path(path).name
        self.report_problem(
            f"Handed {name} to your computer to open. If nothing opens, use Save… instead."
            if opened
            else f"No program on this computer opens {name}. Save the file instead."
        )

    def save(self, where: dict[str, Any], button: QAbstractButton) -> None:
        folder = widgets.choose_folder(self.parent)
        if not folder:
            return
        options = ReadOptions(max_chars=1, include_images=False, save_directory=Path(folder))
        submit_from(
            self.worker,
            button,
            lambda client: operations.read_attachments(client, options=options, **where),
            self._saved,
            self.report_problem,
        )

    def _saved(self, report: Any) -> None:
        summary = report.summary
        problem = summary.get("error") or summary.get("save_error")
        self.report_problem(str(problem) if problem else f"Saved in {summary.get('saved_to')}.")


def image_from(data: bytes) -> QImage | None:
    image = QImage.fromData(data)
    return None if image.isNull() else image


class AttachmentBar(QWidget):
    """The attachments of the chosen item: the photos as a strip of small pictures, and a row per
    other file. A click on a photo shows it; a document has Read, a video or recording Open."""

    def __init__(self, worker: Worker, report_problem: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.worker = worker
        self.report_problem = report_problem
        self.opener = FileOpener(worker, report_problem, self)
        widgets.make_card(self)
        self.setVisible(False)
        self.rows = QVBoxLayout(self)
        self.rows.setContentsMargins(*widgets.CARD_MARGINS)
        # Every file's first button (a photo's picture, Read or Open), and the Save… buttons.
        self.read_buttons: list[QAbstractButton] = []
        self.save_buttons: list[QPushButton] = []
        self.photo_buttons: dict[Any, QToolButton] = {}
        self.event_id: Any = None
        # The section puts this button in its action row, next to Mark as read.
        self.save_all_button = QPushButton(SAVE_ALL)
        self.save_all_button.setEnabled(False)
        self.save_all_button.clicked.connect(self.save_all)
        self._saving_all = False

    @property
    def dialog(self) -> ReadingDialog | None:
        """The window that shows the file that was read last."""
        return self.opener.dialog

    def show_attachments(self, event_id: Any, attachments: list[dict[str, Any]]) -> None:
        self.clear()
        self.event_id = event_id
        photos = [a for a in attachments if is_picture(a)]
        if photos:
            self._add_strip(event_id, photos)
        for attachment in attachments:
            if attachment not in photos:
                self._add_row(event_id, attachment)
        self.setVisible(bool(attachments))
        self._enable_save_all()
        if any(a.get("has_thumbnail") for a in attachments):
            self._fetch_pictures(event_id)

    def _add_strip(self, event_id: Any, photos: list[dict[str, Any]]) -> None:
        """The photos side by side; the strip scrolls sideways when there are many."""
        strip = QWidget()
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for number, photo in enumerate(photos, start=1):
            button = QToolButton()
            button.setText(f"Photo {number}")
            button.setToolTip(file_label(photo))
            button.setAccessibleName(f"Photo {number} of {len(photos)}")
            button.setIconSize(QSize(STRIP_SIZE, STRIP_SIZE))
            button.setFixedSize(STRIP_SIZE + 10, STRIP_SIZE + 10)
            where = {"event_id": event_id, "attachment_id": photo.get("attachment_id")}
            button.clicked.connect(lambda _checked=False, w=where, b=button: self.opener.read(w, b))
            layout.addWidget(button)
            self.read_buttons.append(button)
            self.photo_buttons[photo.get("attachment_id")] = button
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(strip)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(STRIP_SIZE + 30)
        # The card's own colour shows through: a scroll area would paint the window's.
        scroll.viewport().setAutoFillBackground(False)
        strip.setAutoFillBackground(False)
        self.rows.addWidget(scroll)

    def _fetch_pictures(self, event_id: Any) -> None:
        """The small pictures arrive after the item is shown; for another item they are dropped."""

        def arrived(pictures: dict[Any, bytes]) -> None:
            if event_id != self.event_id:
                return
            for attachment_id, data in pictures.items():
                button, image = self.photo_buttons.get(attachment_id), image_from(data)
                if button is not None and image is not None:
                    button.setIcon(QIcon(QPixmap.fromImage(image)))

        self.worker.submit(
            lambda client: operations.load_thumbnails(client, event_id=event_id),
            arrived,
            lambda _text: None,  # the photos still open without their small pictures
        )

    def clear(self) -> None:
        while self.rows.count():
            row = self.rows.takeAt(0)
            widget = row.widget() if row is not None else None
            if widget is not None:
                widget.hide()  # gone now, not only once the event loop deletes it
                widget.deleteLater()
        self.read_buttons, self.save_buttons, self.photo_buttons = [], [], {}
        self.event_id = None
        self.setVisible(False)
        self._enable_save_all()

    def _enable_save_all(self) -> None:
        self.save_all_button.setEnabled(bool(self.read_buttons) and not self._saving_all)

    def _add_row(self, event_id: Any, attachment: dict[str, Any]) -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        label = widgets.ElidedLabel(file_label(attachment))  # never pushes the buttons away
        played = is_played(attachment)
        read, save = QPushButton(OPEN_IN_PLAYER if played else "Read"), QPushButton(SAVE_FILE)
        where = {"event_id": event_id, "attachment_id": attachment.get("attachment_id")}
        if played:
            read.clicked.connect(lambda: self.opener.open_in_player(where, attachment, read))
        else:
            read.clicked.connect(lambda: self.opener.read(where, read))
        save.clicked.connect(lambda: self.opener.save(where, save))
        layout.addWidget(label, 1)
        layout.addWidget(read)
        layout.addWidget(save)
        self.rows.addWidget(row)
        self.read_buttons.append(read)
        self.save_buttons.append(save)

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
