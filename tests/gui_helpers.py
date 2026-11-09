"""Shared by the desktop app's tests. Import this only after Qt is known to be there."""

import time
from collections.abc import Callable

from PySide6.QtWidgets import QApplication


def wait_until(condition: Callable[[], bool], seconds: float = 5.0) -> None:
    """Let the window's thread run until `condition` holds."""
    deadline = time.monotonic() + seconds
    while not condition():
        QApplication.processEvents()
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.002)
