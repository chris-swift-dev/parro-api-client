"""What every section has in common: loading in the background, and showing what went wrong."""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from parro import operations
from parro.api_client import ParroClient

from .. import widgets
from ..text import placeholder, safe_html
from ..widgets import SafeTextBrowser
from ..worker import Worker
from .confirm import ConfirmDialog
from .rows import RowDelegate

LOADING = "Loading…"
EMPTY = "Nothing to show."
LOG_IN_FIRST = "Log in to see this."
NOTHING_CHOSEN = "Nothing to show here."
SECTION_MARGINS = (20, 14, 20, 12)
LIST_WIDTH = 330
DETAIL_MIN_HEIGHT = 90  # the text keeps a few lines, however much is below it
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
    """A list on the left and the chosen item on the right.

    The right-hand side is the text, and below it a row of actions that stays visible and a panel
    that scrolls (attachments, answers, helper slots). A splitter shares the height between the
    text and that lower part: the lower part gets what it needs, up to half, until you drag it.
    """

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
        self.detail.setMinimumHeight(DETAIL_MIN_HEIGHT)
        self.action_row = QHBoxLayout()
        self.action_row.setContentsMargins(0, 0, 0, 0)
        self.action_row.addStretch(1)
        self.panel_content = QWidget()
        self.panel_content.setObjectName("detailPanel")
        self.panel_layout = QVBoxLayout(self.panel_content)
        self.panel_layout.setContentsMargins(0, 0, 0, 0)
        self.panel_layout.setSpacing(8)
        self.panel_layout.addStretch(1)
        self.panel = QScrollArea()
        self.panel.setObjectName("detailPanel")
        self.panel.setWidget(self.panel_content)
        self.panel.setWidgetResizable(True)
        self.panel.setFrameShape(QScrollArea.Shape.NoFrame)
        self.panel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.panel.setVisible(False)
        self.lower_part = QWidget()
        self.lower_layout = QVBoxLayout(self.lower_part)
        self.lower_layout.setContentsMargins(0, 0, 0, 0)
        self.lower_layout.setSpacing(8)
        self.lower_layout.addLayout(self.action_row)
        self.lower_layout.addWidget(self.panel, 1)
        self.lower_part.setVisible(False)
        self.detail_splitter = QSplitter(Qt.Orientation.Vertical)
        self.detail_splitter.setHandleWidth(12)
        self.detail_splitter.setChildrenCollapsible(False)
        self.detail_splitter.addWidget(self.detail)
        self.detail_splitter.addWidget(self.lower_part)
        self.detail_splitter.setStretchFactor(0, 1)
        self.detail_splitter.splitterMoved.connect(self._dragged)
        self._user_dragged = False
        self._fit_pending = False
        self.panel_content.installEventFilter(self)
        self.detail_splitter.installEventFilter(self)
        self.side = QWidget()
        self.side_layout = QVBoxLayout(self.side)
        self.side_layout.setContentsMargins(0, 0, 0, 0)
        self.side_layout.setSpacing(8)
        self.side_layout.addWidget(self.detail_splitter, 1)
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
        self.add_action(button)
        return button

    def add_action(self, button: QPushButton) -> None:
        """A button in the row under the text, which never scrolls away."""
        self.action_row.addWidget(button)
        self.fit_lower()

    def add_to_panel(self, widget: QWidget) -> None:
        """A part of the lower panel, which scrolls when it holds more than fits."""
        self.panel_layout.insertWidget(self.panel_layout.count() - 1, widget)
        widget.installEventFilter(self)  # a hidden panel hears of a part shown or hidden
        self.fit_lower()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt's name)
        shown_or_hidden = (QEvent.Type.ShowToParent, QEvent.Type.HideToParent)
        content_changed = (
            watched is self.panel_content and event.type() == QEvent.Type.LayoutRequest
        ) or (event.type() in shown_or_hidden and watched in self._panel_parts())
        if content_changed:
            self._user_dragged = False  # other content: it gets the height it needs again
            self._fit_soon()
        elif watched is self.detail_splitter and event.type() == QEvent.Type.Resize:
            if not self._user_dragged:
                self._fit_soon()
        return super().eventFilter(watched, event)

    def _dragged(self, _position: int, _index: int) -> None:
        self._user_dragged = True

    def _fit_soon(self) -> None:
        if not self._fit_pending:
            self._fit_pending = True
            QTimer.singleShot(0, self.fit_lower)

    def lower_height_needed(self) -> int:
        """The action row plus everything in the panel, at the panel's width."""
        needed = 0
        if self._has_actions():
            needed += self.action_row.sizeHint().height()
        if not self.panel.isHidden():
            width = max(self.panel.viewport().width(), self.lower_part.width(), 1)
            layout = self.panel_layout
            content = (
                layout.totalHeightForWidth(width)
                if layout.hasHeightForWidth()
                else layout.totalSizeHint().height()
            )
            needed += content + (self.lower_layout.spacing() if needed else 0)
        return needed

    def fit_lower(self) -> None:
        """Give the lower part what it needs, but never more than half the height."""
        self._fit_pending = False
        self.panel.setVisible(self._panel_shows_something())
        self.lower_part.setVisible(not self.panel.isHidden() or self._has_actions())
        available = self.detail_splitter.height() - self.detail_splitter.handleWidth()
        if self.lower_part.isHidden() or available <= 0:
            return
        floor = self.action_row.sizeHint().height() if self._has_actions() else 0
        lower = max(min(self.lower_height_needed(), available // 2), floor)
        self.detail_splitter.setSizes([available - lower, lower])

    def _panel_parts(self) -> list[QWidget]:
        items = (self.panel_layout.itemAt(i) for i in range(self.panel_layout.count()))
        return [widget for item in items if item is not None and (widget := item.widget())]

    def _panel_shows_something(self) -> bool:
        return any(not part.isHidden() for part in self._panel_parts())

    def _has_actions(self) -> bool:
        return any(
            item is not None and item.widget() is not None
            for item in (self.action_row.itemAt(i) for i in range(self.action_row.count()))
        )

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
