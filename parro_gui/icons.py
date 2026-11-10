"""The sidebar's icons, coloured for the current theme.

The files in icon_files/ come from Lucide (ISC licence, see icon_files/LICENSE) and are drawn with
`currentColor`, which is replaced here because Qt's SVG renderer does not know it.
"""

from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .theme import Colours

FOLDER = Path(__file__).parent / "icon_files"
SECTION_ICONS = {
    "Overview": "house",
    "Announcements": "megaphone",
    "Calendar": "calendar-days",
    "Chats": "message-circle",
    "Family": "users",
    "Archive": "archive",
}
# Drawn large and scaled down, so they stay sharp on high-resolution screens.
_PIXELS = 72
ICON_SIZE = QSize(18, 18)


def _pixmap(name: str, colour: str) -> QPixmap:
    drawing = (FOLDER / f"{name}.svg").read_text(encoding="utf-8").replace("currentColor", colour)
    renderer = QSvgRenderer(QByteArray(drawing.encode("utf-8")))
    pixmap = QPixmap(_PIXELS, _PIXELS)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def section_icon(section: str, colours: Colours) -> QIcon:
    """The icon of a section, in the text colour, and in the accent colour when selected."""
    name = SECTION_ICONS[section]
    icon = QIcon(_pixmap(name, colours.muted))
    icon.addPixmap(_pixmap(name, colours.selected_text), QIcon.Mode.Selected)
    return icon
