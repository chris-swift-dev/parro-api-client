"""The message line above each section: at most two lines, the rest behind *Details…*.

Found on the live check of 0.12.0: saving 20 attachments that all failed wrote every file and its
error into a label that grew to fit, squeezed the list and the details, and still cut text off
because it could not scroll. Now the line never takes more than two lines; *Details…* shows the
whole text, scrolling, to read and copy; and a close button removes the message.

It keeps QLabel's `setText()` and `text()`, so every section and test uses it as before.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics, QResizeEvent, QTextLayout
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

MAX_LINES = 2
DETAILS = "Details…"


def first_lines(text: str, font: QFont, width: int, count: int) -> tuple[str, bool]:
    """The text as it fits in `count` lines of `width` pixels, and whether some was left out.

    Lines wrap at word boundaries, as the label would wrap them; the last line that fits ends in
    "…" when more follows.
    """
    width = max(width, 40)
    metrics = QFontMetrics(font)
    lines: list[str] = []
    paragraphs = text.split("\n")
    for number, paragraph in enumerate(paragraphs):
        layout = QTextLayout(paragraph, font)
        layout.beginLayout()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            start, length = line.textStart(), line.textLength()
            if len(lines) == count - 1:
                layout.endLayout()
                rest = " ".join([paragraph[start:], *paragraphs[number + 1 :]]).strip()
                elided = metrics.elidedText(rest, Qt.TextElideMode.ElideRight, width)
                lines.append(elided)
                return "\n".join(lines), elided != rest
            lines.append(paragraph[start : start + length].rstrip())
        layout.endLayout()
    return "\n".join(lines), False


class DetailsDialog(QDialog):
    """The whole message: scrolls, and can be selected and copied."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Details")
        self.setMinimumSize(420, 240)
        self.resize(640, 400)
        self.text = QPlainTextEdit(text)
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text)
        layout.addWidget(buttons)


class Notice(QWidget):
    """Loading, done, or what went wrong: one or two lines, Details…, and a close button."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = ""
        self._details = ""
        self.truncated = False
        self.label = QLabel()
        self.label.setObjectName("notice")
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # Ignored: the label never asks for the width of its longest line, so a long message cannot
        # make the window wider or stop it from becoming narrower.
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.details_button = QPushButton(DETAILS)
        self.details_button.clicked.connect(self.show_details)
        self.close_button = QToolButton()
        self.close_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton)
        )
        self.close_button.setAccessibleName("Close this message")
        self.close_button.setToolTip("Close this message")
        self.close_button.setAutoRaise(True)
        self.close_button.clicked.connect(self.clear)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.details_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        self.dialog: DetailsDialog | None = None
        self.setVisible(False)

    def setText(self, text: str, details: str | None = None) -> None:  # noqa: N802 (QLabel's name)
        """`details`: more than the text, such as every file that was not saved."""
        self._text = str(text or "")
        self._details = str(details or "")
        self.setVisible(bool(self._text))
        self._fit()

    def text(self) -> str:
        return self._text

    def details(self) -> str:
        """What Details… shows: the details if there are any, else the whole text."""
        if self._details:
            return f"{self._text}\n\n{self._details}"
        return self._text

    def clear(self) -> None:
        self.setText("")

    def show_details(self) -> None:
        self.dialog = DetailsDialog(self.details(), self)
        self.dialog.open()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt's name)
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        metrics = self.label.fontMetrics()
        width = self.label.width() if self.label.width() > 40 else 600
        shown, self.truncated = first_lines(self._text, self.label.font(), width, MAX_LINES)
        self.label.setText(shown)
        lines = max(1, shown.count("\n") + 1) if shown else 1
        self.label.setFixedHeight(metrics.lineSpacing() * lines + 2)
        self.details_button.setVisible(bool(self._text) and (self.truncated or bool(self._details)))
        self.close_button.setVisible(bool(self._text))
