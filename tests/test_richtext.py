"""Formatted announcements (docs/PLAN-0.14.md §3): `richTextContents`, Quill's "delta" form.

The text is other people's. The reader only says what is bold and where a link goes; it never
passes markup on, and it can cost the formatting but never words.
"""

import json
from typing import Any

import pytest

from parro import rendering, richtext, summaries
from parro.richtext import Line, Run
from tests.conftest import load_sample

WORDS = "Beste ouders,\nKom allemaal naar de kijkavond.\nNeem mee:\nEen stoel\nMeer op de site.\n"
DELTA = [
    {"insert": "Beste ouders,\n"},
    {"insert": "Kom "},
    {"insert": "allemaal ", "attributes": {"bold": True}},
    {"insert": "naar de "},
    {"insert": "kijkavond", "attributes": {"underline": True, "italic": True}},
    {"insert": "."},
    {"insert": "\n", "attributes": {"blockquote": True}},
    {"insert": "Neem mee:\nEen stoel"},
    {"insert": "\n", "attributes": {"list": "bullet"}},
    {"insert": "Meer op "},
    {"insert": "de site", "attributes": {"link": "https://www.example.com/kijkavond"}},
    {"insert": ".\n"},
]


def delta(pieces: Any = None) -> str:
    return json.dumps(DELTA if pieces is None else pieces, ensure_ascii=False)


# ------------------------------------------------------------------------------ reading


def test_pieces_become_lines_and_a_line_s_look_sits_on_its_line_break():
    lines = richtext.parse(delta())

    assert lines is not None and [line.text() for line in lines] == WORDS.splitlines()
    greeting, quote, plain, item, last = lines
    assert greeting.is_plain() and plain.is_plain()
    assert quote.quote and not quote.list
    assert quote.runs[1] == Run("allemaal ", bold=True)
    assert quote.runs[3] == Run("kijkavond", italic=True, underline=True)
    assert item.list == "bullet" and item.text() == "Een stoel"
    assert last.runs[1].link == "https://www.example.com/kijkavond"


def test_the_wrapper_with_ops_and_a_last_line_without_a_break_are_read_too():
    lines = richtext.parse(json.dumps({"ops": [{"insert": "een\ntwee"}]}))

    assert lines == [Line((Run("een"),)), Line((Run("twee"),))]


@pytest.mark.parametrize(
    "value",
    [None, "", "   ", 7, "geen json", "{}", '"tekst"', "[1, 2]", '[{"insert": "x"}, "y"]'],
)
def test_what_is_not_a_delta_is_not_read(value):
    assert richtext.parse(value) is None


def test_a_value_that_is_too_large_is_not_read():
    huge = delta([{"insert": "x" * richtext.MAX_CHARS}])
    many = delta([{"insert": "x"}] * (richtext.MAX_PIECES + 1))

    assert richtext.parse(huge) is None and richtext.parse(many) is None


def test_unknown_looks_and_embedded_things_cost_nothing_but_themselves():
    pieces = [
        {"insert": "tekst", "attributes": {"color": "red", "bold": "yes", "font": "x"}},
        {"insert": {"image": "https://evil.example/a.png"}},
        {"insert": " verder\n", "attributes": {"header": 9, "list": "checked", "align": "right"}},
    ]

    assert richtext.parse(delta(pieces)) == [Line((Run("tekst"), Run(" verder")))]


@pytest.mark.parametrize(
    "address",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "mailto:x@example.com",
        "",
        5,
        None,
        "https://a b",
    ],
)
def test_only_a_web_address_is_kept_as_a_link(address):
    lines = richtext.parse(delta([{"insert": "klik", "attributes": {"link": address}}]))

    assert lines == [Line((Run("klik"),))]


# --------------------------------------------------------------------- never worse


def test_formatting_is_used_only_when_it_says_the_same_as_the_plain_text():
    assert richtext.formatted(delta(), WORDS) is not None
    assert richtext.formatted(delta(), WORDS.replace("\n", " \n\n ")) is not None, "white space"
    assert richtext.formatted(delta(), WORDS + "PS: tot dan!") is None, "words would be lost"
    assert richtext.formatted(delta(), "iets heel anders") is None
    assert richtext.formatted("kapot", WORDS) is None
    assert richtext.formatted(None, WORDS) is None


def test_a_delta_without_any_formatting_is_left_to_the_plain_text():
    assert richtext.formatted(delta([{"insert": "gewoon\ntekst\n"}]), "gewoon\ntekst\n") is None


# ----------------------------------------------------------------------------- markdown


def test_markdown_shows_bold_italic_quotes_lists_and_the_address_of_a_link():
    lines = richtext.parse(delta())
    assert lines is not None

    assert richtext.to_markdown(lines) == (
        "Beste ouders,\n"
        "> Kom **allemaal** naar de *kijkavond*.\n"
        "Neem mee:\n"
        "- Een stoel\n"
        "Meer op de site (https://www.example.com/kijkavond)."
    )


def test_a_link_that_is_its_own_text_is_shown_once_and_numbers_restart():
    pieces = [
        {"insert": "www.example.com/a", "attributes": {"link": "https://www.example.com/a"}},
        {"insert": "\neen"},
        {"insert": "\n", "attributes": {"list": "ordered"}},
        {"insert": "twee"},
        {"insert": "\n", "attributes": {"list": "ordered"}},
        {"insert": "tussendoor\nopnieuw"},
        {"insert": "\n", "attributes": {"list": "ordered"}},
        {"insert": "Kop"},
        {"insert": "\n", "attributes": {"header": 1}},
        {"insert": "weg", "attributes": {"strike": True, "bold": True}},
    ]
    lines = richtext.parse(delta(pieces))
    assert lines is not None

    assert richtext.to_markdown(lines).splitlines() == [
        "https://www.example.com/a",
        "1. een",
        "2. twee",
        "tussendoor",
        "1. opnieuw",
        "### Kop",
        "**~~weg~~**",
    ]


# -------------------------------------------------------------------- in the client


def test_an_announcement_carries_its_formatted_text_and_the_views_use_it():
    event = load_sample("getEvent_announcement.200.json")

    summary = summaries.summarize_announcement_detail(event)
    text = rendering.render_announcement(summary, rendering.RenderOptions())

    assert json.loads(summary["rich_text"])[1]["attributes"] == {"bold": True}
    assert "nieuwsbrief nr. 3 met" in summary["contents"], "the plain text stays as it was"
    assert "vindt u **nieuwsbrief nr. 3** met de agenda tot de kerstvakantie." in text


def test_an_announcement_without_formatting_has_no_rich_text_key():
    plain = {**load_sample("getEvent_announcement.200.json")}
    del plain["richTextContents"]

    summary = summaries.summarize_announcement_detail(plain)

    assert "rich_text" not in summary
    assert rendering.announcement_text(summary) == summary["contents"].strip()


def test_when_the_two_texts_differ_the_plain_one_is_shown():
    item = {"contents": "De echte tekst.", "rich_text": delta([{"insert": "Iets anders."}])}

    assert rendering.announcement_text(item) == "De echte tekst."
