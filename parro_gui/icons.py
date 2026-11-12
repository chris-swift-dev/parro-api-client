"""The sidebar's icons, coloured for the current theme, and the app's own icon.

The files in icon_files/ come from Lucide (ISC licence, see icon_files/LICENSE) and are drawn with
`currentColor`, which is replaced here because Qt's SVG renderer does not know it.
"""

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
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


# The app's own icon: the chat bubble in white on a rounded square in the light theme's accent
# colour. The window uses it, and tools/make_app_icon.py draws the installers' files from it.
APP_ICON_BACKGROUND = "#2f6feb"
APP_ICON_SIZES = (16, 32, 48, 64, 128, 256, 512, 1024)


def app_icon_image(pixels: int) -> QImage:
    image = QImage(pixels, pixels, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(APP_ICON_BACKGROUND))
    margin = pixels * 0.06  # the platforms' icon grids leave a little room around the square
    side = pixels - 2 * margin
    painter.drawRoundedRect(QRectF(margin, margin, side, side), side * 0.22, side * 0.22)
    drawing = (FOLDER / "message-circle.svg").read_text(encoding="utf-8")
    renderer = QSvgRenderer(QByteArray(drawing.replace("currentColor", "#ffffff").encode("utf-8")))
    bubble = side * 0.58
    offset = (pixels - bubble) / 2
    renderer.render(painter, QRectF(offset, offset, bubble, bubble))
    painter.end()
    return image


def app_icon() -> QIcon:
    icon = QIcon()
    for pixels in APP_ICON_SIZES:
        icon.addPixmap(QPixmap.fromImage(app_icon_image(pixels)))
    return icon
