"""In a Flatpak the app asks the desktop's settings portal for its font (desktop_font.py)."""

import os
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtDBus import QDBusMessage, QDBusVariant  # noqa: E402

from parro_gui import desktop_font  # noqa: E402
from parro_gui.desktop_font import gnome_font, kde_font, portal_font, unwrap  # noqa: E402


class Reply:
    def __init__(self, value: Any = None, ok: bool = True) -> None:
        self.value, self.ok = value, ok

    def type(self) -> QDBusMessage.MessageType:
        kind = QDBusMessage.MessageType
        return kind.ReplyMessage if self.ok else kind.ErrorMessage

    def arguments(self) -> list[Any]:
        return [self.value] if self.ok else ["not found"]


class Portal:
    """Answers like the settings portal: a value wrapped in variants, or an error."""

    def __init__(self, answers: dict[tuple[str, str], Any], read_one: bool = True) -> None:
        self.answers, self.read_one = answers, read_one
        self.calls: list[tuple[str, str, str]] = []

    def call(self, method: str, namespace: str, key: str) -> Reply:
        self.calls.append((method, namespace, key))
        if method == "ReadOne" and not self.read_one:
            return Reply(ok=False)
        if (namespace, key) not in self.answers:
            return Reply(ok=False)
        value = QDBusVariant(self.answers[(namespace, key)])
        return Reply(QDBusVariant(value) if method == "Read" else value)


def test_kde_writes_the_font_as_qt_does(application):
    font = kde_font("Noto Sans,10,-1,5,50,0,0,0,0,0")
    assert font is not None and font.family() == "Noto Sans" and font.pointSizeF() == 10


def test_gnome_writes_family_then_size(application):
    font = gnome_font("Noto Sans  10")
    assert font is not None and font.family() == "Noto Sans" and font.pointSizeF() == 10
    cantarell = gnome_font("Cantarell 11")
    assert cantarell is not None and cantarell.pointSizeF() == 11


@pytest.mark.parametrize("value", ["", "Cantarell", "11", "Cantarell big", "Cantarell 900"])
def test_a_strange_gnome_value_is_ignored(application, value):
    assert gnome_font(value) is None


def test_variants_are_unwrapped():
    assert unwrap(QDBusVariant(QDBusVariant("x"))) == "x" and unwrap("y") == "y"


def test_kde_first_then_gnome(application):
    both = Portal(
        {desktop_font.KDE: "Noto Sans,10,-1,5,50,0,0,0,0,0", desktop_font.GNOME: "Cantarell 11"}
    )
    assert portal_font(both).family() == "Noto Sans"  # type: ignore[union-attr]
    gnome = Portal({desktop_font.GNOME: "Cantarell 11"})
    assert portal_font(gnome).pointSizeF() == 11  # type: ignore[union-attr]


def test_an_older_portal_is_asked_with_read(application):
    portal = Portal({desktop_font.KDE: "Noto Sans,10,-1,5,50,0,0,0,0,0"}, read_one=False)
    assert portal_font(portal) is not None
    assert portal.calls[:2] == [("ReadOne", *desktop_font.KDE), ("Read", *desktop_font.KDE)]


def test_no_answer_leaves_qts_font(application):
    assert portal_font(Portal({})) is None


def test_outside_a_flatpak_nothing_is_asked(application, monkeypatch):
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    before = application.font()
    monkeypatch.setattr(desktop_font, "QDBusInterface", lambda *_a: pytest.fail("asked the portal"))
    desktop_font.use_desktop_font(application)
    assert application.font() == before
