"""Small building blocks shared by the windows."""

from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QMessageBox, QTextBrowser, QWidget

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


class SafeTextBrowser(QTextBrowser):
    """Shows text from others: loads nothing by itself, and links go to the browser after asking."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self._follow)
        self._html = ""
        self.document().setDefaultStyleSheet(document_css())

    def setHtml(self, text: str) -> None:  # noqa: N802 (Qt's name)
        self._html = text
        super().setHtml(text)

    def clear(self) -> None:
        self._html = ""  # or a later theme change would bring it back, also after logging out
        super().clear()

    def restyle(self) -> None:
        """The theme changed: show the same text in the new colours."""
        self.document().setDefaultStyleSheet(document_css())
        super().setHtml(self._html)

    def loadResource(self, _type: int, _name: QUrl | str) -> Any:  # noqa: N802 (Qt's name)
        return None  # no remote images, no local files

    def _follow(self, url: QUrl) -> None:
        if url.scheme().lower() not in OPENABLE_SCHEMES:
            return
        address = url.toString()
        if ask(self, f"Open this address in your browser?\n\n{address}"):
            open_url(address)
