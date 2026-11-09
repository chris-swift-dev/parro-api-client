"""Links in the Markdown files resolve, and the release archives hold what they point to.

The README is also the PyPI page, so it links to other files with full GitHub addresses. Those are
checked against the files in this repository, as if the branch were already merged. Old plans in
docs/archive and the output snapshots are left out: they record what was true at the time.
"""

import importlib.util
import re
import subprocess
from collections import Counter
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUILD_RELEASE = ROOT / "tools" / "build_release.py"
LEFT_OUT = ("tests/snapshots/", "docs/archive/")
# For people working on this project: the README links to them, but a download does not need them.
NOT_FOR_DOWNLOADS = {"docs/DEVELOPMENT.md", "docs/LIVE-CHECKS.md"}

REPOSITORY = "chris-swift-dev/parro-api-client"
ON_GITHUB = re.compile(rf"^https://github\.com/{REPOSITORY}/(?:blob|tree)/main/([^#?]+)(?:#(.+))?$")
RAW_FILE = re.compile(rf"^https://raw\.githubusercontent\.com/{REPOSITORY}/main/([^#?]+)$")
OTHER_ADDRESS = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)

FENCED_CODE = re.compile(r"^ *(```|~~~).*?^ *\1[^\n]*$", re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")
HEADING = re.compile(r"^#{1,6} +(.+?) *#* *$", re.MULTILINE)
MARKDOWN_LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_LINK = re.compile(r"\b(?:href|src|srcset)=\"([^\"]+)\"")
HTML_ANCHOR = re.compile(r"<a\s+(?:name|id)=\"([^\"]+)\"")


def anchor_of(heading: str) -> str:
    """The anchor GitHub gives a heading."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading.strip())
    text = text.replace("`", "").replace("*", "").lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def anchors_in(text: str) -> set[str]:
    without_code = FENCED_CODE.sub("", text)
    seen: Counter[str] = Counter()
    found = set(HTML_ANCHOR.findall(without_code))
    for heading in HEADING.findall(without_code):
        anchor = anchor_of(heading)
        found.add(f"{anchor}-{seen[anchor]}" if seen[anchor] else anchor)
        seen[anchor] += 1
    return found


def links_in(text: str) -> list[str]:
    without_code = INLINE_CODE.sub("", FENCED_CODE.sub("", text))
    return MARKDOWN_LINK.findall(without_code) + HTML_LINK.findall(without_code)


def target_of(source: str, link: str) -> tuple[str, str | None] | None:
    """(path in the repository, anchor) a link points to; None for another site."""
    on_github = ON_GITHUB.match(link) or RAW_FILE.match(link)
    if on_github:
        groups = on_github.groups()
        return str(PurePosixPath(groups[0])), groups[1] if len(groups) > 1 else None
    if OTHER_ADDRESS.match(link) or link.startswith("//"):
        return None
    path, _, anchor = link.partition("#")
    if not path:
        return source, anchor
    parts: list[str] = []
    for part in (PurePosixPath(source).parent / path.split("?")[0]).parts:
        if part == "..":
            if not parts:
                return f"(outside the repository: {link})", None
            parts.pop()
        elif part != ".":
            parts.append(part)
    return "/".join(parts), anchor or None


def broken_links(source: str, text: str, files: dict[str, str]) -> Iterator[str]:
    """What is wrong with the links in one document, given every tracked file and its text."""
    for link in links_in(text):
        target = target_of(source, link)
        if target is None:
            continue
        path, anchor = target
        is_directory = any(name.startswith(f"{path.rstrip('/')}/") for name in files)
        if path not in files and not is_directory:
            yield f"{source}: {link}: no such file"
        elif anchor and path.endswith(".md") and anchor not in anchors_in(files[path]):
            yield f"{source}: {link}: no such heading"


def tracked_files() -> dict[str, str]:
    """Every tracked Markdown file with its text; other tracked files with an empty text."""
    try:
        listing = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    names = [name for name in listing.split("\0") if name]
    if not names:
        pytest.skip("not a git checkout")
    return {
        name: (ROOT / name).read_text(encoding="utf-8") if name.endswith(".md") else ""
        for name in names
    }


def shipped_files() -> set[str]:
    spec = importlib.util.spec_from_file_location("build_release", BUILD_RELEASE)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return set(module.INCLUDED_FILES)


def checked_documents(files: dict[str, str]) -> list[str]:
    return [n for n in files if n.endswith(".md") and not n.startswith(LEFT_OUT)]


def test_every_link_resolves():
    files = tracked_files()
    problems = [
        p for name in checked_documents(files) for p in broken_links(name, files[name], files)
    ]
    assert problems == []


def test_the_check_covers_the_documents_that_matter():
    assert {"README.md", "SECURITY.md", "docs/CONFIGURATION.md"} <= set(
        checked_documents(tracked_files())
    )
    assert any(ON_GITHUB.match(link) for link in links_in(tracked_files()["README.md"]))


def test_relative_links_in_shipped_documents_stay_in_the_archive():
    files, shipped = tracked_files(), shipped_files()
    outside = []
    for name in sorted(shipped):
        if name.endswith(".md"):
            for link in links_in(files[name]):
                target = None if ON_GITHUB.match(link) else target_of(name, link)
                if target and not RAW_FILE.match(link) and target[0] not in shipped:
                    outside.append(f"{name}: {link}")
    assert outside == []


def test_the_documents_the_readme_links_to_are_shipped():
    """A new guide belongs in a download. If it does not, say so in NOT_FOR_DOWNLOADS."""
    linked = {
        target[0]
        for link in links_in(tracked_files()["README.md"])
        if (target := target_of("README.md", link)) and ON_GITHUB.match(link)
    }
    guides = {path for path in linked if path.startswith("docs/") and path.endswith(".md")}
    assert guides, "the README links to its guides with full addresses"
    assert guides - shipped_files() - NOT_FOR_DOWNLOADS == set()


# ------------------------------------------------------------------------- the check itself


FILES = {
    "README.md": "# Quick start\n\n## Your own archive: `sync`\n\n## FAQ\n\n## FAQ\n",
    "docs/GUIDE.md": "# Guide\n\n```\n# not a heading\n```\n",
    "docs/images/a.svg": "",
}
FULL = f"https://github.com/{REPOSITORY}/blob/main"
RAW = f"https://raw.githubusercontent.com/{REPOSITORY}/main"


@pytest.mark.parametrize(
    ("source", "link"),
    [
        ("README.md", "#quick-start"),
        ("README.md", "#your-own-archive-sync"),
        ("README.md", "#faq-1"),
        ("README.md", "docs/GUIDE.md"),
        ("README.md", "docs/GUIDE.md#guide"),
        ("README.md", "docs"),
        ("docs/GUIDE.md", "../README.md#faq"),
        ("docs/GUIDE.md", "images/a.svg"),
        ("README.md", f"{FULL}/docs/GUIDE.md"),
        ("README.md", f"{FULL}/README.md#faq"),
        ("README.md", f"{RAW}/docs/images/a.svg"),
        ("README.md", "https://example.com/elsewhere"),
        ("README.md", "mailto:someone@example.com"),
    ],
)
def test_good_links_pass(source, link):
    assert list(broken_links(source, f"[x]({link})", FILES)) == []


@pytest.mark.parametrize(
    ("source", "link", "why"),
    [
        ("README.md", "#nope", "no such heading"),
        ("README.md", "#not-a-heading", "no such heading"),
        ("README.md", "docs/MISSING.md", "no such file"),
        ("README.md", "docs/GUIDE.md#nope", "no such heading"),
        ("docs/GUIDE.md", "README.md", "no such file"),
        ("docs/GUIDE.md", "../../README.md", "no such file"),
        ("README.md", f"{FULL}/docs/MISSING.md", "no such file"),
        ("README.md", f"{FULL}/README.md#nope", "no such heading"),
        ("README.md", f"{RAW}/docs/images/missing.svg", "no such file"),
    ],
)
def test_broken_links_are_found(source, link, why):
    (problem,) = list(broken_links(source, f"[x]({link})", FILES))
    assert why in problem


def test_html_links_are_checked_too():
    (problem,) = list(broken_links("README.md", f'<img src="{RAW}/missing.png">', FILES))
    assert "no such file" in problem


def test_links_inside_code_are_ignored():
    text = "`[x](missing.md)`\n\n```\n[x](missing.md)\n```\n"
    assert list(broken_links("README.md", text, FILES)) == []
