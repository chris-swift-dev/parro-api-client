"""The formatted text of an announcement (`richTextContents`), read into lines.

Some announcements carry, next to their plain `contents`, a JSON string in the "delta" form of the
Quill editor: a list of pieces `{"insert": "text", "attributes": {...}}` (live look 2026-11-14).
`bold`, `italic`, `underline`, `strike` and `link` belong to a piece of text; `blockquote`, `list`
and `header` belong to a line and sit on the line break that ends it.

The text comes from other people. Nothing here produces markup: it only says which pieces are
bold, which lines are a quote, and where a link goes. Unknown attributes are ignored, the text is
always kept, and embedded things that are not text (a picture) are left out. A link is kept only
when it is a web address.

`formatted()` is the one to call: it gives the lines only when they can be read, hold some
formatting, and say the same as the plain text. In every other case the caller shows the plain
text, as before, so this can cost the formatting but never words.

Standard library only.
"""

import json
from dataclasses import dataclass
from typing import Any

# A value that is longer or has more pieces than any announcement is not read at all.
MAX_CHARS = 500_000
MAX_PIECES = 10_000
LIST_KINDS = ("bullet", "ordered")


@dataclass(frozen=True)
class Run:
    """A piece of text with one look."""

    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    link: str | None = None  # an http(s) address

    def is_plain(self) -> bool:
        return not (self.bold or self.italic or self.underline or self.strike or self.link)


@dataclass(frozen=True)
class Line:
    runs: tuple[Run, ...] = ()
    quote: bool = False
    list: str | None = None  # "bullet" or "ordered"
    header: int | None = None  # 1-6

    def text(self) -> str:
        return "".join(run.text for run in self.runs)

    def is_plain(self) -> bool:
        plain_line = not (self.quote or self.list or self.header)
        return plain_line and all(run.is_plain() for run in self.runs)


def web_address(value: Any) -> str | None:
    """`value` when it is an http(s) address without white space, else None."""
    if not isinstance(value, str):
        return None
    address = value.strip()
    if not address.lower().startswith(("https://", "http://")) or any(c.isspace() for c in address):
        return None
    return address


def _run(text: str, attributes: dict[str, Any]) -> Run:
    return Run(
        text,
        bold=attributes.get("bold") is True,
        italic=attributes.get("italic") is True,
        underline=attributes.get("underline") is True,
        strike=attributes.get("strike") is True,
        link=web_address(attributes.get("link")),
    )


def _line(runs: list[Run], attributes: dict[str, Any]) -> Line:
    kind = attributes.get("list")
    header = attributes.get("header")
    return Line(
        tuple(runs),
        quote=attributes.get("blockquote") is True,
        list=kind if kind in LIST_KINDS else None,
        header=header if isinstance(header, int) and 1 <= header <= 6 else None,
    )


def parse(rich_text: Any) -> list[Line] | None:
    """The lines of a delta, or None when it is not one."""
    if not isinstance(rich_text, str) or not rich_text.strip() or len(rich_text) > MAX_CHARS:
        return None
    try:
        pieces = json.loads(rich_text)
    except ValueError:
        return None
    if isinstance(pieces, dict):  # Quill's own wrapper: {"ops": [...]}
        pieces = pieces.get("ops")
    if not isinstance(pieces, list) or len(pieces) > MAX_PIECES:
        return None
    lines: list[Line] = []
    runs: list[Run] = []
    for piece in pieces:
        if not isinstance(piece, dict):
            return None
        insert = piece.get("insert")
        attributes = piece.get("attributes")
        attributes = attributes if isinstance(attributes, dict) else {}
        if not isinstance(insert, str):
            continue  # a picture or another embedded thing: not text
        parts = insert.replace("\r\n", "\n").split("\n")
        for number, part in enumerate(parts):
            if part:
                runs.append(_run(part, attributes))
            if number < len(parts) - 1:  # a line break: it carries the line's own look
                lines.append(_line(runs, attributes))
                runs = []
    if runs:
        lines.append(_line(runs, {}))
    return lines


def plain_text(lines: list[Line]) -> str:
    return "\n".join(line.text() for line in lines)


def _without_space(text: str) -> str:
    return "".join(text.split())


def same_words(lines: list[Line], contents: Any) -> bool:
    """True when the lines say what the plain text says, white space aside."""
    return _without_space(plain_text(lines)) == _without_space(str(contents or ""))


def formatted(rich_text: Any, contents: Any) -> list[Line] | None:
    """The lines to show in place of `contents`, or None: show `contents`."""
    lines = parse(rich_text)
    if not lines or all(line.is_plain() for line in lines):
        return None
    return lines if same_words(lines, contents) else None


# ------------------------------------------------------------------------------ markdown


def _link_text(run: Run) -> str:
    """'klik hier (https://…)': the address is always shown; once when it is the text itself."""
    text, address = run.text.strip(), str(run.link)
    bare = address.split("://", 1)[1].rstrip("/")
    if text.rstrip("/") in (address.rstrip("/"), bare):
        return address
    return f"{text} ({address})"


def _run_markdown(run: Run) -> str:
    text = _link_text(run) if run.link else run.text
    core = text.strip()
    if not core:
        return text
    marks = ("**" if run.bold else "") + ("*" if run.italic else "") + ("~~" if run.strike else "")
    if not marks:
        return text
    # The marks hug the words: '**word** ', not '**word **', which is not bold in markdown.
    lead = text[: len(text) - len(text.lstrip())]
    tail = text[len(text.rstrip()) :]
    return f"{lead}{marks}{core}{marks[::-1]}{tail}"


def to_markdown(lines: list[Line]) -> str:
    """The lines as markdown: **bold**, *italic*, > quotes, lists, 'text (address)'.

    Underline has no markdown form and stays plain. Ordered lists are numbered again after any
    line that is not part of the list.
    """
    out: list[str] = []
    number = 0
    for line in lines:
        text = "".join(_run_markdown(run) for run in line.runs)
        number = number + 1 if line.list == "ordered" else 0
        if line.header:
            text = f"{'#' * min(6, line.header + 2)} {text}"
        elif line.list == "ordered":
            text = f"{number}. {text}"
        elif line.list == "bullet":
            text = f"- {text}"
        out.append(f"> {text}".rstrip() if line.quote else text)
    return "\n".join(out)
