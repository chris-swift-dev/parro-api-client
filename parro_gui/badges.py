"""The unread count beside a section in the sidebar (docs/PLAN-0.14-additions.md §4).

A small round badge at the right of Announcements, Calendar and Chats, with the number Parro
itself gives (`GET /identity/unreadcounts`). Nothing is drawn for zero. Reading the counts changes
nothing in Parro.
"""

from typing import Any

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QListWidgetItem, QStyledItemDelegate, QStyleOptionViewItem

from .theme import current_colours

UNREAD_ROLE = Qt.ItemDataRole.UserRole + 1
# The section's name → the count's name in operations.unread_totals().
COUNTED = {"Announcements": "announcements", "Calendar": "calendar", "Chats": "chats"}
MOST_SHOWN = 99
BADGE_HEIGHT = 18
BADGE_MARGIN = 10


def badge_text(count: int) -> str:
    """'3', '99+'; '' for nothing to show."""
    if count <= 0:
        return ""
    return str(count) if count <= MOST_SHOWN else f"{MOST_SHOWN}+"


def set_unread(item: QListWidgetItem, name: str, count: int | None) -> None:
    """Give a sidebar row its count; None or 0 takes the badge away."""
    shown = count if isinstance(count, int) and not isinstance(count, bool) and count > 0 else 0
    item.setData(UNREAD_ROLE, shown)
    # What a screen reader says, and what a mouse sees: the number is not only a picture.
    said = f"{name}, {shown} unread" if shown else name
    item.setData(Qt.ItemDataRole.AccessibleTextRole, said)
    item.setToolTip(f"{shown} unread" if shown else "")


def unread_of(item: QListWidgetItem) -> int:
    value: Any = item.data(UNREAD_ROLE)
    return value if isinstance(value, int) else 0


class SectionDelegate(QStyledItemDelegate):
    """Draws the row as Qt does, and the count on top of it, at the right."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        value = index.data(UNREAD_ROLE)
        text = badge_text(value if isinstance(value, int) else 0)
        if not text:
            return
        colours = current_colours()
        font = QFont(option.font)
        font.setPointSizeF(max(option.font.pointSizeF() - 1.5, 7.0))
        font.setWeight(QFont.Weight.DemiBold)
        width = max(BADGE_HEIGHT, QFontMetrics(font).horizontalAdvance(text) + 10)
        area = option.rect
        badge = QRect(
            area.right() - BADGE_MARGIN - width,
            area.center().y() - BADGE_HEIGHT // 2,
            width,
            BADGE_HEIGHT,
        )
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colours.accent))
        painter.drawRoundedRect(badge, BADGE_HEIGHT / 2, BADGE_HEIGHT / 2)
        painter.setPen(QColor(colours.accent_text))
        painter.setFont(font)
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()
