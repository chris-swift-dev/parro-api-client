"""A formatted announcement in the desktop app: the app's own marks around escaped text."""

import os
import re
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtGui import QTextDocument

from parro import richtext
from parro_gui import text as gui_text
from parro_gui.views.news import announcement_html
from tests.test_richtext import DELTA, WORDS, delta


def lines_of(pieces: Any) -> list[richtext.Line]:
    lines = richtext.parse(delta(pieces))
    assert lines is not None
    return lines


def plain(html: str) -> str:
    document = QTextDocument()
    document.setHtml(html)
    return document.toPlainText()


def test_bold_underline_quote_list_and_link_are_shown():
    html = gui_text.rich_html(lines_of(DELTA))

    assert "<b>allemaal </b>" in html and "<u><i>kijkavond</i></u>" in html
    assert '<td class="quote">Kom <b>allemaal </b>naar de' in html
    assert "<ul><li>Een stoel</li></ul>" in html
    link = '<a href="https://www.example.com/kijkavond">de site</a>'
    assert f"{link} (https://www.example.com/kijkavond)" in html, "the address is in sight"
    shown = plain(html)
    assert [w for w in WORDS.split() if w.strip(".,:") not in shown] == [], "no word is lost"


def test_a_link_that_is_its_own_text_shows_the_address_once():
    address = "https://www.example.com/a"
    html = gui_text.rich_html(lines_of([{"insert": address, "attributes": {"link": address}}]))

    assert html == f'<p><a href="{address}">{address}</a></p>'


def test_text_from_others_stays_text_inside_the_marks():
    evil = '<img src=https://evil.example/a> <a href="https://evil.example">klik</a>'
    pieces = [
        {"insert": evil, "attributes": {"bold": True}},
        {"insert": "\n", "attributes": {"blockquote": True}},
        {"insert": '"><script>x</script>', "attributes": {"link": 'https://a.example/"><b>'}},
    ]

    html = gui_text.rich_html(lines_of(pieces))

    assert set(re.findall(r"<(\w+)", html)) <= {"table", "tr", "td", "b", "p", "a"}, "no img"
    assert "&lt;script&gt;" in html and "&lt;img src=" in html, "shown as the text it is"
    # Every link shows where it goes: its own address as its text, or the address after it.
    for target, shown, after in re.findall(r'<a href="([^"]*)">(.*?)</a>( \([^)]*\))?', html):
        assert shown == target or after == f" ({target})", target


def test_the_announcement_view_uses_the_formatting_or_falls_back():
    item = {"title": "Kijkavond", "contents": WORDS, "rich_text": delta()}

    assert "<b>allemaal </b>" in announcement_html(item)
    different = {**item, "contents": WORDS + "PS: neem een jas mee."}
    html = announcement_html(different)
    assert "<b>" not in html and "neem een jas mee" in plain(html), "the plain text wins"
    assert "<b>" not in announcement_html({"title": "x", "contents": WORDS})


def test_both_themes_colour_a_quote():
    from parro_gui import theme

    assert "td.quote" in theme.document_css()
