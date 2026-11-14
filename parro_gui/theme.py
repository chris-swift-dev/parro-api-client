"""How the app looks: one set of colours for light and one for dark, and a stylesheet built on them.

It follows the system's light or dark setting. Spin boxes, combo boxes and check boxes get their
colours from the palette only: styling those directly loses their arrows and tick marks.
"""

from dataclasses import asdict, dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Colours:
    background: str
    surface: str
    sidebar: str
    text: str
    muted: str
    line: str
    accent: str
    accent_text: str  # on `accent`
    selected: str
    selected_text: str  # on `selected`
    control: str
    hover: str
    disabled: str
    own_message: str  # behind your own chat messages
    other_message: str  # behind everyone else's
    names: tuple[str, ...] = ()  # a colour per person in a chat, readable on `other_message`


LIGHT = Colours(
    background="#f6f7f9",
    surface="#ffffff",
    sidebar="#eef1f5",
    text="#1c2330",
    muted="#5d6778",
    line="#dfe3e9",
    accent="#2f6feb",
    accent_text="#ffffff",
    selected="#e3edff",
    selected_text="#1b4fb8",
    control="#ffffff",
    hover="#eff2f7",
    disabled="#a2abb9",
    own_message="#dbe7ff",
    other_message="#eef1f5",
    names=("#b3261e", "#1a7431", "#7a3fd1", "#8a5a00", "#0b6e8e", "#b0277a"),
)
DARK = Colours(
    background="#14171c",
    surface="#1c2027",
    sidebar="#101317",
    text="#e8ebf0",
    muted="#a3adbd",
    line="#2f3641",
    accent="#6d9eff",
    accent_text="#0d1420",
    selected="#21314f",
    selected_text="#9dbdff",
    control="#262c35",
    hover="#2e3540",
    disabled="#667080",
    own_message="#223660",
    other_message="#2a303a",
    names=("#ff9a8f", "#7ee787", "#d2a8ff", "#e3b341", "#76d0ee", "#ff9bd2"),
)

NAME_COLOUR_COUNT = len(LIGHT.names)

_STYLESHEET = """
QStatusBar {{ background: {background}; color: {muted}; border-top: 1px solid {line}; }}
QStatusBar::item {{ border: none; }}
QSplitter::handle {{ background: transparent; }}

QLabel#sectionTitle {{ font-size: 16pt; font-weight: 600; }}
QLabel#fetchedAt {{ color: {muted}; }}
#card {{ background: {surface}; border: 1px solid {line}; border-radius: 10px; }}

QListWidget#sections {{
    background: {sidebar}; border: none; padding: 10px 8px; outline: none;
}}
QListWidget#sections::item {{ padding-left: 12px; border-radius: 8px; }}
QListWidget#sections::item:hover {{ background: {hover}; }}
QListWidget#sections::item:selected {{
    background: {selected}; color: {selected_text}; font-weight: 600;
}}

QListWidget {{
    background: {surface}; border: 1px solid {line}; border-radius: 10px; outline: none;
    padding: 4px;
}}
QListWidget::item {{ padding: 6px 8px; border-radius: 8px; }}
QListWidget::item:hover {{ background: {hover}; }}
QListWidget::item:selected {{ background: {selected}; color: {selected_text}; }}

QTextBrowser, QPlainTextEdit, QLineEdit {{
    background: {surface}; border: 1px solid {line}; border-radius: 8px; padding: 6px;
}}
QTextBrowser {{ border-radius: 10px; padding: 12px; }}
QPlainTextEdit:focus, QLineEdit:focus {{ border-color: {accent}; }}

QPushButton {{
    background: {control}; border: 1px solid {line}; border-radius: 7px; padding: 5px 14px;
}}
QPushButton:hover {{ background: {hover}; }}
QPushButton:focus {{ border-color: {accent}; }}
QPushButton:disabled {{ color: {disabled}; background: transparent; }}
QPushButton[confirm="true"] {{
    background: {accent}; border-color: {accent}; color: {accent_text}; font-weight: 600;
}}
QPushButton[confirm="true"]:disabled {{
    background: transparent; border-color: {line}; color: {disabled};
}}

QTabWidget::pane {{ border: 1px solid {line}; border-radius: 8px; background: {surface}; }}
QTabBar::tab {{ padding: 6px 14px; color: {muted}; background: transparent; border: none; }}
QTabBar::tab:selected {{ color: {selected_text}; font-weight: 600; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {line}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""

# For QTextDocument, which understands only part of CSS. Colours for text come from the palette.
_DOCUMENT_CSS = """
h2 {{ font-size: x-large; font-weight: 600; }}
h3 {{ font-size: large; font-weight: 600; }}
.meta {{ color: {muted}; }}
a {{ color: {accent_link}; }}
.day {{ color: {muted}; font-weight: 600; }}
.time {{ color: {muted}; font-size: small; }}
td.mine {{ background-color: {own_message}; }}
td.other {{ background-color: {other_message}; }}
"""


def stylesheet(colours: Colours) -> str:
    values = {key: value for key, value in asdict(colours).items() if key != "names"}
    return _STYLESHEET.format(**values)


def is_dark() -> bool:
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def current_colours() -> Colours:
    return DARK if is_dark() else LIGHT


def document_css() -> str:
    colours = current_colours()
    css = _DOCUMENT_CSS.format(
        muted=colours.muted,
        accent_link=colours.selected_text,
        own_message=colours.own_message,
        other_message=colours.other_message,
    )
    names = "".join(
        f".name{number} {{ color: {colour}; }}\n" for number, colour in enumerate(colours.names)
    )
    return css + names


def palette(colours: Colours) -> QPalette:
    """Colours for everything the stylesheet leaves to Qt."""
    roles = {
        QPalette.ColorRole.Window: colours.background,
        QPalette.ColorRole.WindowText: colours.text,
        QPalette.ColorRole.Base: colours.control,
        QPalette.ColorRole.AlternateBase: colours.hover,
        QPalette.ColorRole.Text: colours.text,
        QPalette.ColorRole.PlaceholderText: colours.muted,
        QPalette.ColorRole.Button: colours.control,
        QPalette.ColorRole.ButtonText: colours.text,
        QPalette.ColorRole.BrightText: colours.accent_text,
        QPalette.ColorRole.Highlight: colours.accent,
        QPalette.ColorRole.HighlightedText: colours.accent_text,
        QPalette.ColorRole.Link: colours.selected_text,
        QPalette.ColorRole.LinkVisited: colours.selected_text,
        QPalette.ColorRole.ToolTipBase: colours.surface,
        QPalette.ColorRole.ToolTipText: colours.text,
    }
    result = QPalette()
    for role, value in roles.items():
        result.setColor(role, QColor(value))
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
    ):
        result.setColor(QPalette.ColorGroup.Disabled, role, QColor(colours.disabled))
    return result


def refresh(application: QApplication) -> None:
    """Colour the app for the system's current setting, also what is already on the screen."""
    colours = current_colours()
    application.setPalette(palette(colours))
    application.setStyleSheet(stylesheet(colours))
    for widget in application.allWidgets():
        restyle = getattr(widget, "restyle", None)
        if callable(restyle):
            restyle()


def apply_theme(application: QApplication) -> None:
    """The same style on every system, kept in step with the system's light or dark setting."""
    application.setStyle("Fusion")
    refresh(application)
    application.styleHints().colorSchemeChanged.connect(lambda _scheme: refresh(application))
