"""The look of the desktop app: readable in both themes, and following the system."""

import os
from dataclasses import fields

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QtMsgType, qInstallMessageHandler  # noqa: E402
from PySide6.QtGui import QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from parro_gui import text as gui_text  # noqa: E402
from parro_gui import theme  # noqa: E402
from parro_gui import widgets as gui_widgets  # noqa: E402
from parro_gui.views.confirm import ConfirmDialog  # noqa: E402
from parro_gui.worker import Worker  # noqa: E402
from tests.gui_helpers import dispose  # noqa: E402

THEMES = [theme.LIGHT, theme.DARK]
AA_TEXT = 4.5


def luminance(colour: str) -> float:
    def channel(value: int) -> float:
        part = value / 255
        return part / 12.92 if part <= 0.03928 else ((part + 0.055) / 1.055) ** 2.4

    red, green, blue = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def contrast(first: str, second: str) -> float:
    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize("colours", THEMES, ids=["light", "dark"])
@pytest.mark.parametrize(
    ("foreground", "background"),
    [
        ("text", "background"),
        ("text", "surface"),
        ("text", "sidebar"),
        ("text", "control"),
        ("text", "hover"),
        ("muted", "background"),
        ("muted", "surface"),
        ("accent_text", "accent"),
        ("selected_text", "selected"),
        ("selected_text", "surface"),
    ],
)
def test_text_meets_the_contrast_standard(colours, foreground, background):
    ratio = contrast(getattr(colours, foreground), getattr(colours, background))
    assert ratio >= AA_TEXT, f"{foreground} on {background}: {ratio:.2f}"


def test_both_themes_set_every_colour():
    for colours in THEMES:
        for colour_field in fields(colours):
            value = getattr(colours, colour_field.name)
            values = value if isinstance(value, tuple) else (value,)
            assert values and all(v.startswith("#") for v in values), colour_field.name


@pytest.fixture
def restored(application):
    style, palette = application.style().name(), application.palette()
    yield application
    application.setStyleSheet("")
    application.setPalette(palette)
    application.setStyle(style)


@pytest.mark.parametrize("colours", THEMES, ids=["light", "dark"])
def test_qt_accepts_the_stylesheet(restored, colours):
    complaints: list[str] = []

    def handler(kind: QtMsgType, _context: object, message: str) -> None:
        if "style" in message.lower() or "parse" in message.lower():
            complaints.append(message)

    previous = qInstallMessageHandler(handler)
    try:
        restored.setStyleSheet(theme.stylesheet(colours))
        button = QPushButton("x")
        button.ensurePolished()
    finally:
        qInstallMessageHandler(previous)
    assert complaints == []


def test_the_stylesheet_loads_nothing():
    for colours in THEMES:
        assert "url(" not in theme.stylesheet(colours)
    assert "url(" not in theme.document_css() and "@import" not in theme.document_css()


def test_the_palette_uses_the_colours():
    built = theme.palette(theme.DARK)
    assert built.color(QPalette.ColorRole.Window).name() == theme.DARK.background
    assert built.color(QPalette.ColorRole.Text).name() == theme.DARK.text


@pytest.mark.parametrize(
    ("dark", "expected"), [(False, theme.LIGHT), (True, theme.DARK)], ids=["light", "dark"]
)
def test_it_follows_the_system(restored, monkeypatch, dark, expected):
    monkeypatch.setattr(theme, "is_dark", lambda: dark)
    theme.refresh(restored)
    assert restored.styleSheet() == theme.stylesheet(expected)
    assert restored.palette().color(QPalette.ColorRole.Window).name() == expected.background


def test_apply_uses_the_same_style_everywhere(restored):
    theme.apply_theme(restored)
    restored.setStyleSheet("")  # a stylesheet wraps the style, and hides its name
    assert restored.style().name().lower() == "fusion"


def test_text_on_screen_changes_with_the_theme(restored, monkeypatch):
    browser = gui_widgets.SafeTextBrowser()
    browser.setHtml(gui_text.document(gui_text.meta("Grijs"), gui_text.paragraph("Tekst")))
    monkeypatch.setattr(theme, "is_dark", lambda: True)
    theme.refresh(restored)
    assert theme.DARK.muted in browser.document().defaultStyleSheet()
    assert "Grijs" in browser.toPlainText() and "Tekst" in browser.toPlainText()
    dispose(browser)


def test_restyling_does_not_make_text_from_others_active(application):
    browser = gui_widgets.SafeTextBrowser()
    browser.setHtml(gui_text.paragraph("<img src=https://evil.example/a><b>vet</b>"))
    browser.restyle()
    assert "<img src=https://evil.example/a><b>vet</b>" in browser.toPlainText()
    dispose(browser)


def test_only_confirm_is_the_coloured_button(application):
    worker = Worker()
    dialog = ConfirmDialog(worker, "t", "<p>x</p>", "Confirm", lambda _c: None, lambda _r: None)
    assert dialog.confirm_button.property("confirm") is True
    assert not dialog.cancel_button.property("confirm")
    dispose(dialog)
    worker.close()
    QApplication.processEvents()
