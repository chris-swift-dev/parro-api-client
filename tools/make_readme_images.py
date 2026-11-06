#!/usr/bin/env python3
"""Draw the README's terminal pictures from the snapshot files (docs/PLAN-readme-visuals.md).

Each picture is an SVG of a terminal window: a prompt line with the command, then the command's
output exactly as tests/snapshots/<name>.md holds it. The snapshots are rendered from the invented
fixtures by tests/test_rendering.py, so no picture can show real data, and
tests/test_readme_images.py fails when a picture no longer matches its snapshot.

Every picture comes in a light and a dark variant; the README picks one with <picture>.

--swagger also takes the two Swagger UI screenshots (docs/images/swagger-*.png), see
swagger_screenshots.py. That needs Firefox and the network, so it is not part of --check or the
tests: run it by hand after a change to the spec, and look at the result.

Standard library only.  Usage:
    python3 tools/make_readme_images.py           # (re)write docs/images/terminal-*.svg
    python3 tools/make_readme_images.py --check   # exit 1 when a picture is out of date
    python3 tools/make_readme_images.py --swagger # also the Swagger UI screenshots
"""

import argparse
import html
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = ROOT / "tests" / "snapshots"
IMAGES = ROOT / "docs" / "images"


@dataclass(frozen=True)
class Picture:
    snapshot: str  # tests/snapshots/<snapshot>.md
    command: str  # shown after the prompt
    description: str  # the SVG's title, for screen readers


PICTURES = [
    Picture(
        "overview",
        "parro-client overview",
        "Terminal output of parro-client overview: unread counts, the latest announcements, "
        "the coming calendar items and chats with unread messages (invented example data).",
    ),
    Picture(
        "calendar-details",
        "parro-client calendar --details",
        "Terminal output of parro-client calendar --details: the agenda per day, with locations, "
        "descriptions and attachments (invented example data).",
    ),
    Picture(
        "announcements",
        "parro-client announcements",
        "Terminal output of parro-client announcements: each announcement with its author, groups, "
        "date, a preview and its attachments (invented example data).",
    ),
]


@dataclass(frozen=True)
class Theme:
    name: str
    background: str
    frame: str
    border: str
    text: str
    dim: str
    heading: str
    subheading: str
    hint: str
    marker: str
    prompt: str


THEMES = [
    Theme(
        name="light",
        background="#ffffff",
        frame="#f6f8fa",
        border="#d1d9e0",
        text="#1f2328",
        dim="#6e7781",
        heading="#0550ae",
        subheading="#8250df",
        hint="#116329",
        marker="#bc4c00",
        prompt="#116329",
    ),
    Theme(
        name="dark",
        background="#0d1117",
        frame="#161b22",
        border="#30363d",
        text="#e6edf3",
        dim="#8b949e",
        heading="#79c0ff",
        subheading="#d2a8ff",
        hint="#7ee787",
        marker="#ffa657",
        prompt="#7ee787",
    ),
]

FONT_SIZE = 13
CHAR_WIDTH = 7.8  # 0.6 em: the advance of a typical monospace font
LINE_HEIGHT = 19
PADDING = 18
TITLE_BAR = 32
FONT = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"

# The parts of a line that get their own colour: ids, the unread marker, separators, RSVP.
TOKENS = re.compile(r"(#\d{6,}|● ?(?:new|\d+ unread|\d+ \w+)?|\s·\s|RSVP needed)")


def cell_width(text: str) -> int:
    """Terminal cells: emoji and wide characters take two."""
    cells = 0
    for char in text:
        if unicodedata.combining(char) or char == "️":
            continue
        wide = unicodedata.east_asian_width(char) in "WF" or ord(char) >= 0x1F000
        cells += 2 if wide else 1
    return cells


def style_line(line: str, theme: Theme) -> str:
    """One output line as SVG <tspan>s."""
    stripped = line.lstrip()
    if line.startswith("# "):
        return span(line, theme.heading, bold=True)
    if line.startswith("## "):
        return span(line, theme.subheading, bold=True)
    if stripped.startswith("→ "):
        return span(line, theme.hint)
    parts = []
    for piece in TOKENS.split(line):
        if not piece:
            continue
        if piece.startswith("#") or piece.strip() == "·":
            parts.append(span(piece, theme.dim))
        elif piece.startswith("●") or piece == "RSVP needed":
            parts.append(span(piece, theme.marker))
        else:
            parts.append(html.escape(piece, quote=False))
    return "".join(parts)


def span(text: str, colour: str, bold: bool = False) -> str:
    weight = ' font-weight="bold"' if bold else ""
    return f'<tspan fill="{colour}"{weight}>{html.escape(text, quote=False)}</tspan>'


def draw(picture: Picture, output: str, theme: Theme) -> str:
    """The SVG text of one picture in one theme."""
    lines = output.rstrip("\n").split("\n")
    prompt = f"$ {picture.command}"
    cells = max(cell_width(line) for line in [prompt, *lines])
    width = round(2 * PADDING + (cells + 2) * CHAR_WIDTH)  # 2 cells spare: fonts differ
    rows = len(lines) + 2  # the prompt line and an empty line under it
    height = TITLE_BAR + 2 * PADDING + rows * LINE_HEIGHT - (LINE_HEIGHT - FONT_SIZE)
    title = html.escape(picture.description, quote=False)
    first_baseline = TITLE_BAR + PADDING + FONT_SIZE

    text_rows = [
        f'<text x="{PADDING}" y="{first_baseline}">'
        f'<tspan fill="{theme.prompt}" font-weight="bold">$</tspan> '
        f"{html.escape(picture.command, quote=False)}</text>"
    ]
    for number, line in enumerate(lines, start=2):
        if line:
            y = first_baseline + number * LINE_HEIGHT
            text_rows.append(f'<text x="{PADDING}" y="{y}">{style_line(line, theme)}</text>')

    dots = "".join(
        f'<circle cx="{18 + index * 20}" cy="{TITLE_BAR // 2}" r="6" fill="{colour}"/>'
        for index, colour in enumerate(("#ff5f57", "#febc2e", "#28c840"))
    )
    body = "\n  ".join(text_rows)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" \
viewBox="0 0 {width} {height}" role="img" aria-labelledby="title">
  <title id="title">{title}</title>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="8" \
fill="{theme.background}" stroke="{theme.border}"/>
  <path d="M0.5 {TITLE_BAR} V8.5 a8 8 0 0 1 8 -8 H{width - 8.5} a8 8 0 0 1 8 8 V{TITLE_BAR} Z" \
fill="{theme.frame}" stroke="{theme.border}"/>
  {dots}
  <text x="{width / 2:g}" y="{TITLE_BAR // 2 + 4}" text-anchor="middle" fill="{theme.dim}" \
font-family="{FONT}" font-size="12">parro-api-client</text>
  <g font-family="{FONT}" font-size="{FONT_SIZE}" fill="{theme.text}" xml:space="preserve">
  {body}
  </g>
</svg>
"""


def image_path(picture: Picture, theme: Theme) -> Path:
    return IMAGES / f"terminal-{picture.snapshot}-{theme.name}.svg"


def all_images() -> dict[Path, str]:
    """Every picture in every theme: path → SVG text."""
    images = {}
    for picture in PICTURES:
        output = (SNAPSHOTS / f"{picture.snapshot}.md").read_text(encoding="utf-8")
        for theme in THEMES:
            images[image_path(picture, theme)] = draw(picture, output, theme)
    return images


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only report outdated pictures")
    parser.add_argument("--swagger", action="store_true", help="also take the Swagger screenshots")
    args = parser.parse_args(argv)
    if args.swagger and not args.check:
        from swagger_screenshots import take_screenshots  # noqa: PLC0415 (needs Firefox)

        for path in take_screenshots(IMAGES):
            print(f"{path.relative_to(ROOT)}: written ({path.stat().st_size // 1024} KB)")
    outdated = []
    for path, svg in all_images().items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == svg:
            continue
        outdated.append(path)
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(svg, encoding="utf-8")
    for path in outdated:
        verb = "out of date" if args.check else "written"
        print(f"{path.relative_to(ROOT)}: {verb}")
    return 1 if args.check and outdated else 0


if __name__ == "__main__":
    sys.exit(main())
