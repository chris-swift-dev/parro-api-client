"""Shared by the desktop app's tests. Import this only after Qt is known to be there."""

import time
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget


def wait_until(condition: Callable[[], bool], seconds: float = 5.0) -> None:
    """Let the window's thread run until `condition` holds."""
    deadline = time.monotonic() + seconds
    while not condition():
        QApplication.processEvents()
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.002)


def dispose(widget: QWidget) -> None:
    """Close a window and destroy it now, with its children, so finished windows do not pile up."""
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
