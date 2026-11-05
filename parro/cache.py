"""A small file cache for data that is expensive to fetch and can be checked for staleness exactly.

Only two things are cached (PLAN-readable-output §3b):
  * attachment files and their extracted text, keyed by attachment id + upload id + size. An upload
    never changes (a new upload has a new id), so these entries never go stale;
  * calendar-item details, stored with the item's `lastModifiedAt` from the list, and used only
    while the list still shows that same value.
Lists are never cached: they are cheap, and they are how we learn what is new or read.

Rules for this module:
  * Folders are created with mode 0700, files with 0600: the cache holds children's photos and
    school letters.
  * Nothing stored here contains a download URL (the CDN links are unsigned, see the spec).
  * A broken or unreadable entry counts as "not cached"; the caller fetches again.
  * The total size stays under the configured limit: the oldest entries go first.
"""

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Entry names are built from ids; anything else is refused rather than used as a path.
SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,150}$")


@dataclass(frozen=True)
class CacheInfo:
    directory: str
    enabled: bool
    files: int
    bytes: int
    max_bytes: int


class Cache:
    """Files under one folder, in sections such as 'attachments' and 'events'."""

    def __init__(self, directory: Path, max_bytes: int, enabled: bool = True) -> None:
        self.directory = directory
        self.max_bytes = max_bytes
        self.enabled = enabled

    # ------------------------------------------------------------------------------- read

    def get_bytes(self, section: str, key: str) -> bytes | None:
        path = self._path(section, key)
        if path is None:
            return None
        try:
            return path.read_bytes()
        except OSError:
            return None

    def get_json(self, section: str, key: str) -> Any:
        data = self.get_bytes(section, key)
        if data is None:
            return None
        try:
            return json.loads(data)
        except ValueError:
            log.warning("ignoring a damaged cache entry %s/%s", section, key)
            return None

    # ------------------------------------------------------------------------------ write

    def put_bytes(self, section: str, key: str, data: bytes) -> None:
        path = self._path(section, key)
        if path is None:
            return
        try:
            write_private_file(path, data)
        except OSError as error:
            log.warning("could not write the cache entry %s/%s: %s", section, key, error.strerror)
            return
        self._keep_under_limit()

    def put_json(self, section: str, key: str, value: Any) -> None:
        self.put_bytes(section, key, json.dumps(value, ensure_ascii=False).encode("utf-8"))

    # ----------------------------------------------------------------------- maintenance

    def clear(self) -> int:
        """Delete every cached file. Returns how many were deleted."""
        removed = 0
        for path in self._files():
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def info(self) -> CacheInfo:
        files = self._files()
        return CacheInfo(
            directory=str(self.directory),
            enabled=self.enabled,
            files=len(files),
            bytes=sum(_size(path) for path in files),
            max_bytes=self.max_bytes,
        )

    def _keep_under_limit(self) -> None:
        """Delete the oldest files until the total is under max_bytes."""
        files = sorted(self._files(), key=_modified_time)
        total = sum(_size(path) for path in files)
        for path in files:
            if total <= self.max_bytes:
                break
            total -= _size(path)
            path.unlink(missing_ok=True)

    def _files(self) -> list[Path]:
        if not self.directory.is_dir():
            return []
        return [path for path in self.directory.rglob("*") if path.is_file()]

    def _path(self, section: str, key: str) -> Path | None:
        if not self.enabled:
            return None
        if not (SAFE_KEY.match(section) and SAFE_KEY.match(key)):
            log.warning("refusing an unsafe cache key")
            return None
        return self.directory / section / key


def write_private_file(path: Path, data: bytes) -> None:
    """Write a file only the owner can read (0600, folders 0700), replacing it in one step."""
    for folder in reversed([path.parent, *path.parent.parents]):
        if not folder.exists():
            folder.mkdir(mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".cache-")
    try:
        os.chmod(temporary_name, 0o600)
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(data)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def remove_urls(value: Any) -> Any:
    """A copy without any `url` field, at any depth: download links are never cached."""
    if isinstance(value, dict):
        return {key: remove_urls(item) for key, item in value.items() if key != "url"}
    if isinstance(value, list):
        return [remove_urls(item) for item in value]
    return value


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _modified_time(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
