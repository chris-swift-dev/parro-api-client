"""A short memory of what the app fetched: kept in this process only, never written to disk.

Going back to a section or a filter choice within a few minutes shows the kept answer at once.
The disk cache in parro/cache.py deliberately holds no lists, because a stale list would hide what
is new or read; this memory is short for the same reason, and the app says how old it is.
"""

import copy
import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

KEEP_SECONDS = 5 * 60


@dataclass(frozen=True)
class Kept:
    result: Any
    fetched_at: datetime  # for people: "Fetched at 14:32"
    stored: float  # for the memory: a monotonic clock, untouched by changes to the system time


class Memory:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.clock = clock
        self.wall_clock = wall_clock
        self._kept: dict[Hashable, Kept] = {}

    def put(self, key: Hashable, result: Any) -> Kept:
        """Keep a copy, so what a view does with the answer it shows cannot change it."""
        kept = Kept(copy.deepcopy(result), self.wall_clock(), self.clock())
        self._kept[key] = kept
        return Kept(result, kept.fetched_at, kept.stored)

    def get(self, key: Hashable) -> Kept | None:
        """The kept answer, if it is younger than KEEP_SECONDS; a copy, for the same reason."""
        kept = self._kept.get(key)
        if kept is None:
            return None
        if self.expired(kept):
            del self._kept[key]
            return None
        return Kept(copy.deepcopy(kept.result), kept.fetched_at, kept.stored)

    def expired(self, kept: Kept) -> bool:
        return self.clock() - kept.stored >= KEEP_SECONDS

    def forget(self) -> None:
        """After a change, and after logging in or out: nothing kept is to be trusted."""
        self._kept.clear()

    def __len__(self) -> int:
        return len(self._kept)
