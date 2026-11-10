"""What every section has in common: loading in the background, and showing what went wrong."""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from parro import operations
from parro.api_client import ParroClient

from .. import widgets
from ..text import placeholder, safe_html
from ..widgets import SafeTextBrowser, right_aligned
from ..worker import Worker
from .confirm import ConfirmDialog
from .rows import RowDelegate

LOADING = "Loading…"
EMPTY = "Nothing to show."
LOG_IN_FIRST = "Log in to see this."
NOTHING_CHOSEN = "Nothing to show here."
SECTION_MARGINS = (20, 14, 20, 12)
LIST_WIDTH = 330
MARK_READ_QUESTION = "Mark this as read? The school can see that you did."


class Section(QWidget):
    """Subclasses say what to fetch (`make_task`) and how to show it (`show_result`)."""

    def __init__(self, worker: Worker, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.worker = worker
        self.loaded = False
        self._generation = 0
        self.next_notice = ""  # shown when the next load has finished
        self.confirmation: ConfirmDialog | None = None
        self.notice = QLabel()
        self.notice.setTextFormat(Qt.TextFormat.PlainText)
        self.notice.setWordWrap(True)
        self.title = QLabel()
        self.title.setObjectName("sectionTitle")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.load)
        header = QHBoxLayout()
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.refresh_button)
        self.filters = QHBoxLayout()
        self.filters.addStretch(1)
        self.main = QVBoxLayout(self)
        self.main.setContentsMargins(*SECTION_MARGINS)
        self.main.setSpacing(8)
        self.main.addLayout(header)
        self.main.addLayout(self.filters)
        self.main.addWidget(self.notice)

    def add_filter(self, widget: QWidget) -> None:
        self.filters.insertWidget(self.filters.count() - 1, widget)

    def set_title(self, title: str) -> None:
        self.title.setText(title)

    def make_task(self) -> Callable[[ParroClient], Any]:
        """Read the filters here, on the window's thread; the task itself must not touch widgets."""
        raise NotImplementedError

    def show_result(self, result: Any) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        """Forget what is shown."""

    def stop(self) -> None:
        """The window is closing: end long-running work."""

    def load(self) -> None:
        self.loaded = True
        self._generation += 1
        generation = self._generation
        self.notice.setText(LOADING)
        self.worker.submit(
            self.make_task(),
            lambda result: self._arrived(generation, result),
            lambda text: self._failed(generation, text),
        )

    def ensure_loaded(self) -> None:
        if not self.loaded:
            self.load()

    def reset(self, message: str = "") -> None:
        """After logging in or out: what is shown belongs to the previous state."""
        self.loaded = False
        self._generation += 1  # an answer still on its way is out of date
        self.clear()
        self.notice.setText(message)

    def _arrived(self, generation: int, result: Any) -> None:
        if generation == self._generation:
            self.notice.setText(self.next_notice)
            self.next_notice = ""
            self.show_result(result)

    def _failed(self, generation: int, text: str) -> None:
        if generation == self._generation:
            self.notice.setText(text)

    def ask_to_confirm(
        self,
        title: str,
        preview_html: str,
        confirm_label: str,
        task: Callable[[ParroClient], Any],
        on_done: Callable[[Any], None],
    ) -> None:
        self.confirmation = ConfirmDialog(
            self.worker, title, preview_html, confirm_label, task, on_done, self
        )
        self.confirmation.open()


class ListDetailSection(Section):
    """A list on the left and the chosen item on the right."""

    def __init__(self, worker: Worker, parent: QWidget | None = None) -> None:
        super().__init__(worker, parent)
        self.items: list[Any] = []
        self.empty_text = NOTHING_CHOSEN
        self._detail_generation = 0
        self._wanted_row = 0
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setItemDelegate(RowDelegate(self.list))
        self.list.setMouseTracking(True)  # for the hover colour
        self.list.currentRowChanged.connect(self._row_chosen)
        self.detail = SafeTextBrowser()
        self.side = QWidget()
        self.side_layout = QVBoxLayout(self.side)
        self.side_layout.setContentsMargins(0, 0, 0, 0)
        self.side_layout.setSpacing(8)
        self.side_layout.addWidget(self.detail, 1)
        splitter = QSplitter()
        splitter.setHandleWidth(12)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.list)
        splitter.addWidget(self.side)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([LIST_WIDTH, 700])
        self.main.addWidget(splitter, 1)

    def rows(self, result: Any) -> list[tuple[str, Any]]:
        """(the text of the row, the item it stands for)."""
        raise NotImplementedError

    def show_item(self, item: Any) -> None:
        raise NotImplementedError

    def show_result(self, result: Any) -> None:
        rows = self.rows(result)
        self.clear()
        self.items = [item for _text, item in rows]
        self.list.addItems([text for text, _item in rows])
        for row, (text, _item) in enumerate(rows):
            # Rows cut long text short. Escaped, because a tooltip would read HTML in a title.
            self.list.item(row).setToolTip(f"<p>{safe_html(text)}</p>")
        if rows:
            self.list.setCurrentRow(min(self._wanted_row, len(rows) - 1))
        else:
            self.detail.setHtml(placeholder(self.empty_text))
            if not self.notice.text():
                self.notice.setText(EMPTY)
        self._wanted_row = 0

    def clear(self) -> None:
        self._detail_generation += 1
        self.items = []
        self.list.clear()
        self.detail.clear()

    def _row_chosen(self, row: int) -> None:
        self._detail_generation += 1
        if 0 <= row < len(self.items):
            self.show_item(self.items[row])

    def reload_here(self, message: str) -> None:
        """Load again after a change, staying on the same row, and say what happened."""
        self._wanted_row = max(self.list.currentRow(), 0)
        self.next_notice = message
        self.load()

    def add_mark_button(self) -> QPushButton:
        button = QPushButton("Mark as read")
        button.setEnabled(False)
        self.side_layout.addLayout(right_aligned(button))
        return button

    def mark_read(self, kind: str, item_id: Any) -> None:
        """Only ever from a button, and it asks first: the school sees it."""
        if not widgets.ask(self, MARK_READ_QUESTION):
            return
        self.worker.submit(
            lambda client: operations.mark_read(client, kind, item_id),
            lambda result: self.reload_here(
                "Marked as read." if result.get("marked_read") else "It was already read."
            ),
            self.notice.setText,
        )

    def fetch_detail(self, task: Callable[[ParroClient], Any], done: Callable[[Any], None]) -> None:
        """Fetch more about the chosen item. An answer for an item left behind is dropped."""
        generation = self._detail_generation

        def arrived(result: Any) -> None:
            if generation == self._detail_generation:
                done(result)

        def failed(text: str) -> None:
            if generation == self._detail_generation:
                self.notice.setText(text)

        self.worker.submit(task, arrived, failed)
