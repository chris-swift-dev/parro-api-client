"""How a row in a list is drawn: a bold title, a quieter line below it, a dot for unread, labels.

The row's text stays the same plain two lines; this only decides how they look.
"""

from dataclasses import dataclass, field

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ..theme import current_colours

UNREAD_MARK = "● "
SEPARATOR = " · "
LABELS = ("RSVP needed", "helpers wanted", "helpers: full", "you signed up to help")
PADDING = 8
LINE_GAP = 2
LABEL_HEIGHT_EXTRA = 6
LABEL_GAP = 6


@dataclass(frozen=True)
class Row:
    title: str
    unread: bool = False
    detail: str = ""
    labels: list[str] = field(default_factory=list)


def is_label(part: str) -> bool:
    return part in LABELS or part.startswith("RSVP: ")


def split_row(text: str) -> Row:
    """'● Title\\nThu 12 Nov · RSVP needed' into its parts."""
    title, _, second = text.partition("\n")
    unread = title.startswith(UNREAD_MARK)
    parts = second.split(SEPARATOR) if second else []
    return Row(
        title.removeprefix(UNREAD_MARK),
        unread,
        SEPARATOR.join(part for part in parts if not is_label(part)),
        [part for part in parts if is_label(part)],
    )


class RowDelegate(QStyledItemDelegate):
    def _fonts(self, option: QStyleOptionViewItem) -> tuple[QFont, QFont]:
        title = QFont(option.font)
        title.setWeight(QFont.Weight.DemiBold)
        small = QFont(option.font)
        small.setPointSizeF(max(option.font.pointSizeF() - 1, 7.0))
        return title, small

    def sizeHint(  # noqa: N802 (Qt's name)
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        title, small = self._fonts(option)
        height = PADDING * 2 + QFontMetrics(title).height() + LINE_GAP
        height += QFontMetrics(small).height()
        if split_row(str(index.data())).labels:
            height += LINE_GAP * 2 + QFontMetrics(small).height() + LABEL_HEIGHT_EXTRA
        return QSize(200, height + 2)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        colours = current_colours()
        row = split_row(str(index.data()))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = option.rect.adjusted(1, 1, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        if selected or option.state & QStyle.StateFlag.State_MouseOver:
            painter.setBrush(QColor(colours.selected if selected else colours.hover))
            painter.drawRoundedRect(area, 8, 8)
        if option.state & QStyle.StateFlag.State_HasFocus:  # for people using the keyboard
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor(colours.accent))
            painter.drawRoundedRect(area, 8, 8)
        title_font, small_font = self._fonts(option)
        left = area.left() + PADDING + 6
        width = area.width() - PADDING * 2 - 6
        top = area.top() + PADDING - 1
        height = QFontMetrics(title_font).height()
        if row.unread:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colours.accent))
            painter.drawEllipse(area.left() + 5, top + height // 2 - 3, 6, 6)
        painter.setFont(title_font)
        painter.setPen(QColor(colours.selected_text if selected else colours.text))
        shown = QFontMetrics(title_font).elidedText(row.title, Qt.TextElideMode.ElideRight, width)
        painter.drawText(QRect(left, top, width, height), Qt.TextFlag.TextSingleLine, shown)
        top += height + LINE_GAP
        painter.setFont(small_font)
        metrics = QFontMetrics(small_font)
        painter.setPen(QColor(colours.selected_text if selected else colours.muted))
        shown = metrics.elidedText(row.detail, Qt.TextElideMode.ElideRight, width)
        painter.drawText(
            QRect(left, top, width, metrics.height()), Qt.TextFlag.TextSingleLine, shown
        )
        top += metrics.height() + LINE_GAP * 2
        x = left
        for label in row.labels:
            text_width = metrics.horizontalAdvance(label)
            pill = QRect(x, top, text_width + 12, metrics.height() + LABEL_HEIGHT_EXTRA - 2)
            if pill.right() > left + width:
                break
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colours.surface if selected else colours.selected))
            painter.drawRoundedRect(pill, 6, 6)
            painter.setPen(QColor(colours.selected_text))
            painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, label)
            x = pill.right() + LABEL_GAP
        painter.restore()
