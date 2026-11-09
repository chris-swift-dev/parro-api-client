#!/usr/bin/env python3
"""Build the files of a GitHub release: source archives, checksums and release notes.

    python3 tools/build_release.py                 # version from parro/__init__.py
    python3 tools/build_release.py --tag v0.1.0    # also check that the tag matches that version
    python3 tools/build_release.py --packages      # also list the wheel and sdist in SHA256SUMS

Writes to dist/:
    parro-api-client-<version>.zip and .tar.gz   what a user needs to run the CLI or the MCP server
    SHA256SUMS                                     checksums of both archives (and, with
                                                   --packages, of the wheel and sdist that
                                                   `python -m build --outdir dist` wrote there)
    release-notes.md                               the CHANGELOG.md section of this version

Archive *contents* are reproducible: with SOURCE_DATE_EPOCH set (the release workflow uses the commit
time), the same sources give the same files, dates and modes, and the same uncompressed tar. The
compressed bytes, and so SHA256SUMS, repeat only with the same zlib build: GitHub's runner and a
local Python can compress differently. To check a release, compare unpacked contents, not
checksums. Standard library only.
"""

import argparse
import gzip
import hashlib
import io
import os
import re
import sys
import tarfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

# What goes into the archives: the runnable client plus what a user should read. No tests, no
# tooling, nothing git-ignored.
INCLUDED_FILES = [
    "parro_cli.py",
    "parro_mcp.py",
    "README.md",
    "CHANGELOG.md",
    "DEPLOY.md",
    "LICENSE",
    "LICENSE-CODE",
    "requirements.txt",
    "docs/CALENDAR-AND-ARCHIVE.md",
    "docs/CHANGING-THINGS.md",
    "docs/CODE-TOUR.md",
    "docs/LOGIN.md",
    "docs/MCP.md",
    "docs/CONFIGURATION.md",
    "docs/API-NOTES.md",
    "openapi/parro.public.openapi.json",
]
INCLUDED_PACKAGE = "parro"


def read_version() -> str:
    text = (ROOT / "parro" / "__init__.py").read_text(encoding="utf-8")
    found = re.search(r'^__version__ = "([^"]+)"$', text, re.MULTILINE)
    if not found:
        sys.exit("error: no __version__ in parro/__init__.py")
    return found.group(1)


def check_pyproject_version(version: str) -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    found = re.search(r'^version = "([^"]+)"$', text, re.MULTILINE)
    if not found or found.group(1) != version:
        sys.exit(f"error: pyproject.toml version differs from parro.__version__ {version}")


def release_notes(version: str) -> str:
    """The body of the `## [<version>]` section of CHANGELOG.md."""
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)",
        changelog,
        re.MULTILINE | re.DOTALL,
    )
    if not section or not section.group(1).strip():
        sys.exit(f"error: CHANGELOG.md has no section for {version}")
    return section.group(1).strip() + "\n"


def collect_files() -> list[Path]:
    package = sorted(
        path
        for path in (ROOT / INCLUDED_PACKAGE).rglob("*.py")
        if "__pycache__" not in path.parts
    )
    listed = [ROOT / name for name in INCLUDED_FILES]
    missing = [str(path.relative_to(ROOT)) for path in listed if not path.is_file()]
    if missing:
        sys.exit(f"error: missing release files: {', '.join(missing)}")
    return sorted(listed + package, key=lambda path: str(path.relative_to(ROOT)))


def build_zip(target: Path, prefix: str, files: list[Path], timestamp: int) -> None:
    date_time = time.gmtime(max(timestamp, 315532800))[:6]  # zip cannot store dates before 1980
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            entry = zipfile.ZipInfo(f"{prefix}/{path.relative_to(ROOT).as_posix()}", date_time)
            entry.external_attr = (0o755 if os.access(path, os.X_OK) else 0o644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, path.read_bytes())


def build_tar_gz(target: Path, prefix: str, files: list[Path], timestamp: int) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path in files:
            data = path.read_bytes()
            entry = tarfile.TarInfo(f"{prefix}/{path.relative_to(ROOT).as_posix()}")
            entry.size, entry.mtime = len(data), timestamp
            entry.mode = 0o755 if os.access(path, os.X_OK) else 0o644
            entry.uname = entry.gname = ""
            archive.addfile(entry, io.BytesIO(data))
    with open(target, "wb") as raw_file:
        with gzip.GzipFile(fileobj=raw_file, mode="wb", mtime=timestamp, filename="") as packed:
            packed.write(buffer.getvalue())


def python_packages(version: str) -> list[Path]:
    """The wheel and sdist of this version in dist/, for pipx / uv / pip and PyPI."""
    packages = [
        DIST / f"parro_api_client-{version}-py3-none-any.whl",
        DIST / f"parro_api_client-{version}.tar.gz",
    ]
    missing = [path.name for path in packages if not path.exists()]
    if missing:
        sys.exit(f"error: {', '.join(missing)} not in dist/: run `python -m build --outdir dist`")
    return packages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tag", help="the git tag being released, e.g. v0.1.0")
    parser.add_argument(
        "--packages",
        action="store_true",
        help="include the wheel and sdist already in dist/ (built by `python -m build`)",
    )
    args = parser.parse_args()

    version = read_version()
    check_pyproject_version(version)
    if args.tag is not None and args.tag != f"v{version}":
        sys.exit(f"error: tag {args.tag} does not match the code's version v{version}")

    timestamp = int(os.environ.get("SOURCE_DATE_EPOCH", time.time()))
    prefix = f"parro-api-client-{version}"
    files = collect_files()
    DIST.mkdir(exist_ok=True)
    archives = [DIST / f"{prefix}.zip", DIST / f"{prefix}.tar.gz"]
    build_zip(archives[0], prefix, files, timestamp)
    build_tar_gz(archives[1], prefix, files, timestamp)

    if args.packages:
        archives += python_packages(version)
    checksums = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in archives
    )
    (DIST / "SHA256SUMS").write_text(checksums, encoding="utf-8")
    (DIST / "release-notes.md").write_text(release_notes(version), encoding="utf-8")
    print(f"built {prefix}: {len(files)} files")
    print(checksums, end="")


if __name__ == "__main__":
    main()
