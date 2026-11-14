"""Small building blocks shared by the windows."""

from typing import Any

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QResizeEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QTextBrowser,
    QWidget,
)

from .theme import document_css

APP_NAME = "Parro"
OPENABLE_SCHEMES = ("http", "https")
CARD_MARGINS = (10, 8, 10, 8)


def open_url(address: str) -> bool:
    return QDesktopServices.openUrl(QUrl(address))


def ask(parent: QWidget | None, question: str) -> bool:
    """A yes/no question. No is the default."""
    no = QMessageBox.StandardButton.No
    answer = QMessageBox.question(
        parent, APP_NAME, question, QMessageBox.StandardButton.Yes | no, no
    )
    return answer == QMessageBox.StandardButton.Yes


def open_folder(path: str) -> bool:
    return QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def open_file(path: str) -> bool:
    """Open a file on this computer in the program the system uses for it."""
    return QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def choose(parent: QWidget | None, question: str, options: list[str]) -> str | None:
    """A question with a button per option; None when the user cancelled."""
    box = QMessageBox(QMessageBox.Icon.Question, APP_NAME, question, parent=parent)
    buttons = [box.addButton(option, QMessageBox.ButtonRole.ActionRole) for option in options]
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    clicked = box.clickedButton()
    return next((o for o, button in zip(options, buttons, strict=True) if button is clicked), None)


def choose_save_file(parent: QWidget | None, suggested: str, kinds: str) -> str:
    """A file name picked by the user, or '' if they cancelled."""
    return QFileDialog.getSaveFileName(parent, "Save as", suggested, kinds)[0]


def choose_file(parent: QWidget | None, title: str) -> str:
    """An existing file picked by the user, or '' if they cancelled."""
    return QFileDialog.getOpenFileName(parent, title)[0]


def choose_folder(parent: QWidget | None) -> str:
    """A folder picked by the user, or '' if they cancelled."""
    return QFileDialog.getExistingDirectory(parent, "Save in which folder?")


def right_aligned(*items: QWidget) -> QHBoxLayout:
    """A row with its widgets at the right-hand side."""
    row = QHBoxLayout()
    row.addStretch(1)
    for item in items:
        row.addWidget(item)
    return row


def make_card(widget: QWidget) -> None:
    """Give a widget the panel look of the theme (`#card`)."""
    widget.setObjectName("card")
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)


class ElidedLabel(QLabel):
    """One line of plain text that shortens itself with "…" to the room it has.

    A plain label asks for the width of its whole text, so a long file name could push the buttons
    next to it out of the window. The full text is in the tooltip.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(60)
        self.full_text = ""
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self.full_text = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt's name)
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        metrics = self.fontMetrics()
        width = max(self.width(), self.minimumWidth())
        self.setText(metrics.elidedText(self.full_text, Qt.TextElideMode.ElideMiddle, width))


class SafeTextBrowser(QTextBrowser):
    """Shows text from others: loads nothing by itself, and links go to the browser after asking.

    The only pictures it shows are those the app handed it with `allow_image`. A link with a
    scheme named in `internal_schemes` is not opened: it is passed on through `internal_link`,
    for the view to act on (a chat uses it to open a message's file).
    """

    internal_link = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.internal_schemes: tuple[str, ...] = ()
        self._images: dict[str, QImage] = {}
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self._follow)
        self._html = ""
        self._follow_end = False  # show_at_end(): keep the end in view while the size changes
        self._at_end = True  # where the reader is; scrolling up leaves the end
        self.document().setDefaultStyleSheet(document_css())
        bar = self.verticalScrollBar()
        bar.rangeChanged.connect(self._range_changed)
        bar.valueChanged.connect(self._value_changed)

    def setHtml(self, text: str) -> None:  # noqa: N802 (Qt's name)
        self._show(text, follow_end=False)

    def show_at_end(self, text: str) -> None:
        """Show the text scrolled to its end, as a chat shows its newest message.

        The text is laid out later, and its height can change with the width, so the end is kept in
        view whenever the height changes, until the reader scrolls up. Back at the end, it is kept
        again.
        """
        self._show(text, follow_end=True)

    def allow_image(self, name: str, image: QImage) -> None:
        """Let the text show this picture, under this name (`<img src="name">`)."""
        self._images[name] = image

    def forget_images(self) -> None:
        self._images = {}

    def replace_keeping_place(self, text: str) -> None:
        """The same text with something added (pictures arrived): the reader stays where they
        were, and a chat that showed its end still does."""
        bar = self.verticalScrollBar()
        follow, at_end, place = self._follow_end, self._at_end, bar.value()
        if follow and at_end:
            self._show(text, follow_end=True)
            return
        self._show(text, follow_end=follow)
        bar.setValue(min(place, bar.maximum()))
        self._at_end = bar.value() >= bar.maximum()

    def _show(self, text: str, follow_end: bool) -> None:
        self._html = text
        self._follow_end = follow_end
        super().setHtml(text)
        self._at_end = True  # setting the text moves the scroll bar too; that is not the reader
        if follow_end:
            self._to_end()

    def _to_end(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _range_changed(self, _minimum: int, _maximum: int) -> None:
        if self._follow_end and self._at_end:
            self._to_end()

    def _value_changed(self, value: int) -> None:
        self._at_end = value >= self.verticalScrollBar().maximum()

    def clear(self) -> None:
        self._images = {}
        self._html = ""  # or a later theme change would bring it back, also after logging out
        self._follow_end = False
        super().clear()

    def restyle(self) -> None:
        """The theme changed: show the same text in the new colours."""
        self.document().setDefaultStyleSheet(document_css())
        at_end = self._at_end
        super().setHtml(self._html)
        if self._follow_end and at_end:
            self._at_end = True
            self._to_end()

    def loadResource(self, _type: int, name: QUrl | str) -> Any:  # noqa: N802 (Qt's name)
        # No remote images, no local files: only the pictures the app itself handed over.
        wanted = name.toString() if isinstance(name, QUrl) else str(name)
        return self._images.get(wanted)

    def _follow(self, url: QUrl) -> None:
        if url.scheme().lower() in self.internal_schemes:
            self.internal_link.emit(url.toString())
            return
        if url.scheme().lower() not in OPENABLE_SCHEMES:
            return
        address = url.toString()
        if ask(self, f"Open this address in your browser?\n\n{address}"):
            open_url(address)
