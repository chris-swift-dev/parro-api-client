#!/usr/bin/env python3
"""Put the landing page at the root of the GitHub Pages site, next to Swagger UI in api/.

    python3 tools/build_landing.py _site               # asks GitHub for the latest release
    python3 tools/build_landing.py _site --no-release  # buttons to the releases page (offline)

tools/build_site.sh runs this after it has put Swagger UI in _site/api/. The download buttons carry
the latest release's version and file names, so the Pages workflow builds the site again when a
release is published (Plan 16 §5.3). Only the version number is taken from GitHub's answer, and
the file sizes of the installers it names: every link is built here, from that number and
tools/build_release.installer_names. Without a release with all four installers, each button
goes to the releases page. Standard library only.
"""

import argparse
import html
import importlib.util
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "site" / "landing"
REPOSITORY = "chris-swift-dev/parro-api-client"
RELEASES = f"https://github.com/{REPOSITORY}/releases"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
_VERSION = re.compile(r"^v(\d{1,4}\.\d{1,4}\.\d{1,4})$")

# Copied next to index.html, under the same name: the page loads nothing from another site.
PAGE_FILES = ("style.css", "landing.js")
IMAGES = {
    ROOT / "docs" / "images" / name: f"images/{name}"
    for name in (
        "desktop-app-light.png",
        "desktop-app-dark.png",
        "terminal-overview-light.svg",
        "terminal-overview-dark.svg",
        "swagger-operations.png",
    )
}
IMAGES[ROOT / "packaging" / "icon-32.png"] = "images/icon-32.png"
IMAGES[ROOT / "packaging" / "icon-128.png"] = "images/icon-128.png"

# The buttons, in the order of installer_names: system, what it needs, the data-system name.
SYSTEMS = (
    ("Windows", "Windows 10 or 11", "windows"),
    ("macOS", "macOS 14 or newer", "macos"),
    ("Linux", "Flatpak, for a usual PC", "linux-x86_64"),
    ("Linux on ARM", "Flatpak, for a Raspberry Pi 5 or Asahi Linux", "linux-aarch64"),
)


def build_release() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_release", ROOT / "tools" / "build_release.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class Download:
    system: str
    needs: str
    key: str
    url: str
    size: int | None  # bytes; None when the button goes to the releases page


def fetch_latest() -> dict[str, Any] | None:
    """GitHub's answer for the latest release, or None (no release, or no answer)."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "parro-api-client-site"}
    token = os.environ.get("GITHUB_TOKEN")  # in Actions only: more requests allowed. Never printed.
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(LATEST_RELEASE_API, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            answer = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as problem:
        print(
            f"::warning::No latest release from GitHub ({type(problem).__name__}): "
            "the buttons go to the releases page."
        )
        return None
    return answer if isinstance(answer, dict) else None


def downloads(answer: dict[str, Any] | None) -> tuple[str | None, list[Download]]:
    """The version and a button per installer; (None, buttons to the releases page) otherwise."""
    tag = answer.get("tag_name") if answer else None
    found = _VERSION.match(tag) if isinstance(tag, str) else None
    fallback = [Download(s, n, k, RELEASES, None) for s, n, k in SYSTEMS]
    if answer is None or found is None or answer.get("draft") or answer.get("prerelease"):
        return None, fallback
    version = found.group(1)
    sizes: dict[str, int] = {}
    for asset in answer.get("assets") or []:
        if isinstance(asset, dict) and isinstance(asset.get("size"), int):
            sizes[str(asset.get("name"))] = asset["size"]
    names = build_release().installer_names(version)
    if not all(name in sizes for name in names):
        return None, fallback  # a release from before the installers (0.11.0 and older)
    return version, [
        Download(s, n, k, f"{RELEASES}/download/v{version}/{name}", sizes[name])
        for (s, n, k), name in zip(SYSTEMS, names, strict=True)
    ]


def megabytes(size: int) -> str:
    return f"{round(size / (1024 * 1024))} MB"


def buttons(version: str | None, items: list[Download]) -> str:
    rows = []
    for item in items:
        if item.size is None:
            small = "on the releases page"
        else:
            small = f"{html.escape(item.url.rsplit('.', 1)[-1])} · {megabytes(item.size)}"
        rows.append(
            f'<a class="download" data-system="{item.key}" href="{html.escape(item.url)}">'
            f'<span class="download-system">{html.escape(item.system)}</span>'
            f'<span class="download-needs">{html.escape(item.needs)}</span>'
            f'<span class="download-file">{small}</span></a>'
        )
    return "\n          ".join(rows)


def render(version: str | None, items: list[Download]) -> str:
    page = (TEMPLATE / "index.html").read_text(encoding="utf-8")
    if version:
        line = (
            f'Version {html.escape(version)}. <a href="{RELEASES}/tag/v{version}">What is new</a>'
        )
    else:
        line = f'Each release has the installers: <a href="{RELEASES}/latest">latest release</a>'
    page = page.replace("{{version_line}}", line).replace("{{downloads}}", buttons(version, items))
    if "{{" in page:
        raise SystemExit("site/landing/index.html has a placeholder this script does not fill")
    return page


def build(out: Path, answer: dict[str, Any] | None) -> str | None:
    if not (out / "api" / "index.html").exists():
        raise SystemExit(f"{out}/api/ has no Swagger UI: run tools/build_site.sh")
    version, items = downloads(answer)
    (out / "index.html").write_text(render(version, items), encoding="utf-8")
    for name in PAGE_FILES:
        shutil.copyfile(TEMPLATE / name, out / name)
    for source, target in IMAGES.items():
        (out / target).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, out / target)
    return version


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path, help="the site folder, with Swagger UI in api/")
    parser.add_argument("--no-release", action="store_true", help="do not ask GitHub")
    options = parser.parse_args(argv)
    version = build(options.out, None if options.no_release else fetch_latest())
    print(f"landing page in {options.out}/ (downloads: {version or 'the releases page'})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
