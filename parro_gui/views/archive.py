"""The local archive (`sync`) and the cache."""

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QWidget

from parro import operations
from parro.api_client import ParroClient
from parro.operations import SyncOptions
from parro.rendering import format_size, join_parts, plural

from .. import widgets
from ..text import bullets, document, heading, meta, subheading
from ..widgets import SafeTextBrowser
from ..worker import Worker
from .base import Section

STOPPED = "Stopped. What was saved stays, and nothing was marked as gone. Run it again to finish."
KINDS = {"announcement": "Announcements", "calendar": "Calendar items", "chat": "Chats"}
CLEAR_QUESTION = "Empty the cache? Attachments are downloaded again when you next read them."


class SyncStopped(Exception):
    """Raised through the sync to end it. Not a ParroError: nothing went wrong."""


def sync_html(result: dict[str, Any]) -> str:
    lines = []
    for kind, label in KINDS.items():
        counts = result.get(kind)
        if isinstance(counts, dict):
            parts = [
                f"{counts.get('written', 0)} written",
                f"{counts.get('unchanged', 0)} unchanged",
                f"{counts['no_longer_in_parro']} no longer in Parro"
                if counts.get("no_longer_in_parro")
                else "",
            ]
            lines.append(f"{label}: {join_parts(parts)}")
    files = result.get("files_saved", 0)
    size = format_size(result.get("bytes_saved")) or "0 bytes"
    problems = result.get("problems") or []
    return document(
        heading("Archive up to date"),
        meta(result.get("archive")),
        bullets(lines),
        meta(f"{plural(files, 'file')} saved ({size})"),
        subheading(plural(len(problems), "problem")) if problems else "",
        bullets([str(problem) for problem in problems]) if problems else "",
    )


class ArchiveSection(Section):
    progress = Signal(str)

    def __init__(self, worker: Worker, parent: QWidget | None = None) -> None:
        super().__init__(worker, parent)
        self.folder = ""
        self._chosen_folder = False
        self._stop = threading.Event()
        self.folder_label = QLabel()
        self.choose_button = QPushButton("Choose folder…")
        self.open_button = QPushButton("Open folder")
        self.previous = QCheckBox("Last school year")
        self.photos = QCheckBox("Also photos (can be several GB)")
        self.sync_button = QPushButton("Sync now")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.cache_label = QLabel()
        self.clear_button = QPushButton("Empty the cache…")
        self.report = SafeTextBrowser()
        self.add_filter(self.choose_button)
        self.add_filter(self.open_button)
        self.main.addWidget(self.folder_label)
        controls = QHBoxLayout()
        for widget in (self.previous, self.photos, self.sync_button, self.stop_button):
            controls.addWidget(widget)
        controls.addStretch(1)
        self.main.addLayout(controls)
        self.main.addWidget(self.status)
        self.main.addWidget(self.report, 1)
        cache_row = QHBoxLayout()
        cache_row.addWidget(self.cache_label, 1)
        cache_row.addWidget(self.clear_button)
        self.main.addLayout(cache_row)
        self.choose_button.clicked.connect(self.choose_folder)
        self.open_button.clicked.connect(lambda: widgets.open_folder(self.folder))
        self.sync_button.clicked.connect(self.sync)
        self.stop_button.clicked.connect(self._stop.set)
        self.clear_button.clicked.connect(self.clear_cache)
        self.progress.connect(self.status.setText)

    def make_task(self) -> Callable[[ParroClient], Any]:
        def task(client: ParroClient) -> dict[str, Any]:
            return {
                "cache": operations.cache_info(client),
                "folder": str(client.settings.data_dir / "archive"),
            }

        return task

    def show_result(self, result: dict[str, Any]) -> None:
        if not self._chosen_folder:
            self.folder = result["folder"]
            self.folder_label.setText(f"Archive folder: {self.folder}")
        cache = result["cache"]
        files = plural(cache.get("files", 0), "file")
        size = format_size(cache.get("bytes")) or "0 bytes"
        self.cache_label.setText(f"Cache: {files}, {size}")

    def choose_folder(self) -> None:
        folder = widgets.choose_folder(self)
        if folder:
            self.folder, self._chosen_folder = folder, True
            self.folder_label.setText(f"Archive folder: {self.folder}")

    def sync(self) -> None:
        """Reads from Parro only. One at a time, like every request."""
        if not self.folder:
            return
        options = SyncOptions(
            target=Path(self.folder).expanduser(),
            previous_year=self.previous.isChecked(),
            photos=self.photos.isChecked(),
        )
        self._stop.clear()
        self._set_running(True)
        self.status.setText("Starting…")

        def report(what: str) -> None:
            if self._stop.is_set():
                raise SyncStopped
            self.progress.emit(what)

        def task(client: ParroClient) -> dict[str, Any] | None:
            try:
                return operations.sync_archive(client, options, report)
            except SyncStopped:
                return None

        self.worker.submit(task, self._synced, self._sync_failed)

    def _set_running(self, running: bool) -> None:
        self.sync_button.setEnabled(not running)
        self.stop_button.setEnabled(running)

    def _synced(self, result: dict[str, Any] | None) -> None:
        self._set_running(False)
        if result is None:
            self.status.setText(STOPPED)
            return
        self.status.clear()
        self.report.setHtml(sync_html(result))
        self.load()

    def _sync_failed(self, text: str) -> None:
        self._set_running(False)
        self.status.setText(text)

    def clear_cache(self) -> None:
        if widgets.ask(self, CLEAR_QUESTION):
            self.worker.submit(
                operations.cache_clear, lambda _result: self.load(), self.notice.setText
            )

    def stop(self) -> None:
        self._stop.set()

    def clear(self) -> None:
        self.report.clear()
        self.status.clear()
        self.cache_label.clear()
