"""The local archive written by `parro_cli.py sync` (PLAN-readable-output §3b, release 0.3.0).

    <archive>/
      announcements/2026-10-22-nieuwsbrief-nr-3-5000000101.md   (+ .json)
      announcements/attachments/5000000101-6000000101-Nieuwsbrief-3.pdf
      calendar/2026-11-11-sint-maartenviering-7000000101.md     (+ .json, + attachments/)
      chats/rijden-naar-het-natuurmuseum-8000000001.md          (+ .json)
      index.md                                                  (everything, newest first)
      .sync-state.json                                          (what is archived, for the next run)

This module only writes files; operations.sync_archive() decides what to fetch.

Rules:
  * Incremental: an item whose version (its `lastModifiedAt`) is unchanged is not rewritten, and
    a saved attachment is never downloaded again.
  * File names: date + slug of the title + id. When a title changes, the files are renamed, so
    there is never a stale copy next to the new one.
  * Nothing is ever deleted. An item that is no longer in Parro stays, and index.md marks it.
  * Folders 0700, files 0600 (children's names, photos and school mail); no download links in
    any file.
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .cache import remove_urls, write_private_file

STATE_FILE = ".sync-state.json"
INDEX_FILE = "index.md"
SECTIONS = {"announcement": "announcements", "calendar": "calendar", "chat": "chats"}
SECTION_TITLES = {"announcement": "Announcements", "calendar": "Calendar", "chat": "Chats"}
MAX_SLUG_LENGTH = 50


@dataclass
class SyncCounts:
    """What one run did, per kind of item."""

    written: int = 0
    unchanged: int = 0
    renamed: int = 0
    no_longer_in_parro: int = 0


@dataclass
class ArchiveEntry:
    """One archived item, as remembered in the state file."""

    kind: str
    item_id: int
    version: str
    title: str
    date: str
    path: str  # relative to the archive root, e.g. "announcements/2026-...-5000000101.md"
    scope: str  # "current", "previous" or "chats": which run is responsible for it
    present: bool = True
    groups: list[str] = field(default_factory=list)


class Archive:
    """The archive folder: its files and its memory of what was written before."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.entries: dict[str, ArchiveEntry] = load_state(root / STATE_FILE)
        self.counts: dict[str, SyncCounts] = {kind: SyncCounts() for kind in SECTIONS}
        self._seen: set[str] = set()

    # ------------------------------------------------------------------------ items

    def is_current(self, kind: str, item_id: int, version: str) -> bool:
        """True when this version is already archived (and its file still exists)."""
        entry = self.entries.get(entry_key(kind, item_id))
        return entry is not None and entry.version == version and (self.root / entry.path).exists()

    def keep(self, kind: str, item_id: int) -> None:
        """Note an unchanged item as still present in Parro."""
        key = entry_key(kind, item_id)
        self._seen.add(key)
        self.entries[key].present = True
        self.counts[kind].unchanged += 1

    def save(self, entry: ArchiveEntry, markdown: str, summary: Any) -> None:
        """Write (or rewrite) one item: its .md with a header, and its .json without links."""
        key = entry_key(entry.kind, entry.item_id)
        self._seen.add(key)
        previous = self.entries.get(key)
        name_date = "" if entry.kind == "chat" else entry.date  # chats: no date in the name
        stem = file_stem(name_date, entry.title, entry.item_id)
        entry.path = f"{SECTIONS[entry.kind]}/{stem}.md"
        if previous is not None and previous.path != entry.path:
            self._rename(previous.path, entry.path)
            self.counts[entry.kind].renamed += 1
        header = front_matter(entry)
        self._write(entry.path, (header + markdown).encode("utf-8"))
        self._write(json_path(entry.path), json_text(remove_urls(summary)).encode("utf-8"))
        self.entries[key] = entry
        self.counts[entry.kind].written += 1

    # ------------------------------------------------------------------ attachments

    def has_file(self, relative_path: str) -> bool:
        """True when the file is saved. Files are written in one step, so it is complete."""
        return (self.root / relative_path).exists()

    def save_file(self, relative_path: str, data: bytes) -> None:
        self._write(relative_path, data)

    # ----------------------------------------------------------------------- finish

    def finish(self, scopes: set[str], synced_at: datetime) -> None:
        """Mark what the synced scopes no longer contain, then write index.md and the state."""
        for key, entry in self.entries.items():
            if entry.scope in scopes and key not in self._seen and entry.present:
                entry.present = False
                self.counts[entry.kind].no_longer_in_parro += 1
        self._write(INDEX_FILE, build_index(list(self.entries.values()), synced_at).encode("utf-8"))
        self._write(STATE_FILE, json_text(save_state(self.entries)).encode("utf-8"))

    # ---------------------------------------------------------------------- helpers

    def _write(self, relative_path: str, data: bytes) -> None:
        write_private_file(self.root / relative_path, data)

    def _rename(self, old: str, new: str) -> None:
        for source, target in ((old, new), (json_path(old), json_path(new))):
            old_file, new_file = self.root / source, self.root / target
            if old_file.exists():
                new_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                old_file.replace(new_file)


# ----------------------------------------------------------------------- names and text


def entry_key(kind: str, item_id: int) -> str:
    return f"{kind}:{item_id}"


def slugify(title: str) -> str:
    """'Foto's herfstwandeling!' → 'fotos-herfstwandeling' (ASCII, lowercase, at most 50)."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    words = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower().replace("'", "")).strip("-")
    return words[:MAX_SLUG_LENGTH].rstrip("-") or "untitled"


def file_stem(date: str, title: str, item_id: int) -> str:
    """'2026-10-22-nieuwsbrief-nr-3-5000000101'; chats have no date prefix."""
    prefix = f"{date[:10]}-" if re.match(r"^\d{4}-\d{2}-\d{2}", date or "") else ""
    return f"{prefix}{slugify(title)}-{item_id}"


def attachment_path(kind: str, item_id: int, attachment_id: Any, filename: str | None) -> str:
    """'announcements/attachments/5000000101-6000000101-Nieuwsbrief-3.pdf' (a safe file name).

    Attachments live next to their item's section, so the link from the item's .md file is
    simply 'attachments/<name>'.
    """
    name = Path(filename or "attachment").name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "attachment"
    return f"{SECTIONS[kind]}/attachments/{item_id}-{attachment_id}-{safe}"


def json_path(markdown_path: str) -> str:
    return markdown_path[: -len(".md")] + ".json"


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n"


def front_matter(entry: ArchiveEntry) -> str:
    """A YAML header (strings written as JSON strings, which YAML reads as they are)."""
    lines = [
        "---",
        f"id: {entry.item_id}",
        f"type: {entry.kind}",
        f"title: {json.dumps(entry.title, ensure_ascii=False)}",
        f"date: {json.dumps(entry.date)}",
        f"groups: {json.dumps(entry.groups, ensure_ascii=False)}",
        f"version: {json.dumps(entry.version)}",
        "source: Parro, archived with parro_cli.py sync",
        "---",
        "",
    ]
    return "\n".join(lines) + "\n"


def build_index(entries: list[ArchiveEntry], synced_at: datetime) -> str:
    """index.md: every archived item per kind, newest first, with a mark for removed ones."""
    blocks = [
        "# Parro archive",
        f"Last sync: {synced_at.strftime('%Y-%m-%d %H:%M %Z').strip()}. Items no longer in Parro "
        "stay here and are marked *(no longer in Parro)*.",
    ]
    for kind, title in SECTION_TITLES.items():
        items = sorted((e for e in entries if e.kind == kind), key=lambda e: e.date, reverse=True)
        lines = [index_line(entry) for entry in items]
        blocks.append(f"## {title} ({len(items)})\n" + ("\n".join(lines) if lines else "None yet."))
    return "\n\n".join(blocks) + "\n"


def index_line(entry: ArchiveEntry) -> str:
    when = f"{entry.date[:10]} " if entry.date[:4].isdigit() else ""
    groups = f" · {', '.join(entry.groups)}" if entry.groups else ""
    gone = " *(no longer in Parro)*" if not entry.present else ""
    link_text = entry.title.replace("[", "(").replace("]", ")") or "(no title)"
    return f"- {when}[{link_text}]({entry.path}){groups}{gone}"


# ------------------------------------------------------------------------- state file


def load_state(path: Path) -> dict[str, ArchiveEntry]:
    """The entries of the previous run; an unreadable state file starts a fresh archive."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = {}
    for key, value in (raw.get("entries") or {}).items():
        try:
            entries[key] = ArchiveEntry(**value)
        except TypeError:
            continue
    return entries


def save_state(entries: dict[str, ArchiveEntry]) -> dict[str, Any]:
    return {"format": 1, "entries": {key: vars(entry) for key, entry in sorted(entries.items())}}
