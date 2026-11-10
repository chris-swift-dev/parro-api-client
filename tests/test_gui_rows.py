"""The drawn list rows and the sidebar icons of the desktop app."""

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QListWidget, QStyleOptionViewItem  # noqa: E402

from parro import operations  # noqa: E402
from parro.api_client import ParroClient  # noqa: E402
from parro_gui import icons, theme  # noqa: E402
from parro_gui.views.rows import RowDelegate, split_row  # noqa: E402
from parro_gui.window import SECTIONS, MainWindow  # noqa: E402
from tests import fakes  # noqa: E402
from tests.conftest import load_sample  # noqa: E402
from tests.gui_helpers import dispose, wait_until  # noqa: E402

ICONS = icons.FOLDER


def test_a_row_is_split_into_its_parts():
    row = split_row("● Excursie\nThu 12 Nov 2026 · all day · RSVP needed · helpers wanted")
    assert row.title == "Excursie" and row.unread
    assert row.detail == "Thu 12 Nov 2026 · all day"
    assert row.labels == ["RSVP needed", "helpers wanted"]


@pytest.mark.parametrize("label", ["RSVP: accepted", "RSVP: declined", "helpers: full"])
def test_every_kind_of_label_is_recognised(label):
    assert split_row(f"T\nMon · {label}").labels == [label]


def test_a_title_with_a_separator_stays_whole():
    row = split_row("Groep 6 · uitje\nMon 2 Nov")
    assert row.title == "Groep 6 · uitje" and row.detail == "Mon 2 Nov" and not row.unread


def test_a_row_without_a_second_line():
    row = split_row("Alleen titel")
    assert row.title == "Alleen titel" and row.detail == "" and row.labels == []


def test_a_row_with_labels_is_taller(application):
    view = QListWidget()
    view.addItems(["T\nMon", "T\nMon · RSVP needed"])
    delegate = RowDelegate(view)
    option = QStyleOptionViewItem()
    option.font = view.font()
    plain = delegate.sizeHint(option, view.model().index(0, 0))
    labelled = delegate.sizeHint(option, view.model().index(1, 0))
    assert labelled.height() > plain.height()
    dispose(view)


@pytest.mark.parametrize("text", ["● Heel lange titel " * 20 + "\nMon · RSVP needed", "T", ""])
def test_drawing_never_fails(application, text):
    view = QListWidget()
    view.addItem(text)
    delegate = RowDelegate(view)
    image = QImage(320, 90, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    option = QStyleOptionViewItem()
    option.font = view.font()
    option.rect = image.rect()
    delegate.paint(painter, option, view.model().index(0, 0))
    painter.end()
    dispose(view)


# ------------------------------------------------------------------------------- the icons


@pytest.mark.parametrize("name", sorted(icons.SECTION_ICONS.values()))
def test_the_icon_files_are_plain_drawings(name):
    text = (ICONS / f"{name}.svg").read_text(encoding="utf-8")
    assert not re.search(r"script|href|url\(|onload|foreignObject|<!ENTITY|<image", text, re.I)
    assert "currentColor" in text


def test_every_section_has_an_icon():
    assert set(icons.SECTION_ICONS) == set(SECTIONS)


def test_the_licence_ships_with_the_icons():
    assert "ISC License" in (ICONS / "LICENSE").read_text(encoding="utf-8")


@pytest.mark.parametrize("colours", [theme.LIGHT, theme.DARK], ids=["light", "dark"])
@pytest.mark.parametrize("section", SECTIONS)
def test_an_icon_really_draws_something(application, colours, section):
    image = icons.section_icon(section, colours).pixmap(icons.ICON_SIZE).toImage()
    pixels = {
        image.pixelColor(x, y).alpha() for x in range(image.width()) for y in range(image.height())
    }
    assert pixels != {0}


# ---------------------------------------------------------------------------- in the window


@pytest.fixture(autouse=True)
def environment(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("PARRO_"):
            monkeypatch.delenv(name)
    path = tmp_path / "tokens.json"
    path.write_text(
        json.dumps(
            {
                "access_token": fakes.ACCESS_TOKEN,
                "refresh_token": fakes.REFRESH_TOKEN,
                "expires_at": time.time() + 3000,
            }
        )
    )
    monkeypatch.setenv("PARRO_TOKEN_FILE", str(path))
    monkeypatch.setenv("PARRO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        operations, "current_time", lambda: datetime(2026, 11, 3, 9, tzinfo=timezone.utc)
    )


@pytest.fixture
def window(application):
    api = fakes.FakeParroApi(load_sample)
    created = MainWindow(lambda settings: ParroClient(settings, transport=api))
    wait_until(lambda: created.logged_in)
    yield created
    dispose(created)


def agenda(window: MainWindow) -> Any:
    view: Any = window.views["Calendar"]
    window.sections.setCurrentRow(SECTIONS.index("Calendar"))
    wait_until(lambda: view.list.count() > 0)
    return view


def test_the_sidebar_has_icons(window):
    assert all(not window.sections.item(i).icon().isNull() for i in range(len(SECTIONS)))


def test_the_row_text_is_unchanged(window):
    text = next(
        t for t in (agenda(window).list.item(i).text() for i in range(7)) if "Natuurmuseum" in t
    )
    assert "RSVP needed" in text and "helpers wanted" in text


def test_a_tooltip_shows_the_whole_row(window):
    view = agenda(window)
    plain = view.list.item(0).text().split("\n")[0]
    assert plain in view.list.item(0).toolTip()


def test_a_tooltip_cannot_carry_markup(window):
    view = agenda(window)
    hostile = '<img src="https://evil.example/a">\nMon'
    view.show_result({"calendar": {"items": []}, "groups": None})
    view.rows = lambda _result: [(hostile, {"calendarItem": {}, "details": {}})]
    view.show_result({"calendar": {"items": []}, "groups": None})
    tip = view.list.item(0).toolTip()
    assert "<img" not in tip and "&lt;img" in tip


def test_a_message_from_parro_is_shown_as_plain_text(window):
    from PySide6.QtCore import Qt

    assert window.views["Calendar"].notice.textFormat() == Qt.TextFormat.PlainText
