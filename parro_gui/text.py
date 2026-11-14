"""Turns text written by other people into HTML that can do nothing but be read.

Announcements and chats are untrusted. Everything is escaped, and the only links are addresses
that are written out in the text, so a link cannot pretend to go somewhere else. An address
written without its scheme ('www.school.nl') is a link too, and opens as https://.
"""

import html
import re

# An address with its scheme, or one that starts with 'www.' at the start of a word.
_ADDRESS = re.compile(r"https?://[^\s<>\"']+|(?<![\w@./-])www\.[\w-]+\.[^\s<>\"']+", re.IGNORECASE)
_TRAILING = ".,;:!?)]}"


def safe_html(text: object) -> str:
    """`text` as escaped HTML, with line breaks and its own http(s) addresses as links."""
    source = str(text if text is not None else "")
    parts, position = [], 0
    for match in _ADDRESS.finditer(source):
        address = match.group().rstrip(_TRAILING)
        if not address:
            continue
        parts.append(html.escape(source[position : match.start()]))
        shown = html.escape(address)
        target = address if "://" in address else f"https://{address}"
        parts.append(f'<a href="{html.escape(target, quote=True)}">{shown}</a>')
        position = match.start() + len(address)
    parts.append(html.escape(source[position:]))
    return "".join(parts).replace("\r\n", "\n").replace("\n", "<br>")


def heading(text: object) -> str:
    return f"<h2>{html.escape(str(text))}</h2>"


def subheading(text: object) -> str:
    return f"<h3>{html.escape(str(text))}</h3>"


def meta(*parts: object) -> str:
    """A small grey line: 'Tue 3 Nov 2026 · Groep 6'. Empty parts are left out."""
    shown = " · ".join(html.escape(str(part)) for part in parts if part not in (None, ""))
    return f'<p class="meta">{shown}</p>' if shown else ""


def paragraph(text: object) -> str:
    return f"<p>{safe_html(text)}</p>" if str(text or "").strip() else ""


def bullets(lines: list[str]) -> str:
    """A list; each line is escaped."""
    return "<ul>" + "".join(f"<li>{safe_html(line)}</li>" for line in lines) + "</ul>"


def placeholder(text: object) -> str:
    """A quiet line in the middle of an empty pane."""
    return f'<p class="meta" align="center"><br><br>{html.escape(str(text))}</p>'


def document(*blocks: str) -> str:
    return "".join(block for block in blocks if block)
