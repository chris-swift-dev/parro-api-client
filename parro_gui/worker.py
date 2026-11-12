"""Runs calls to Parro in the background, one at a time, and hands the results to the window.

One at a time on purpose. ParroClient has no locks, and two token refreshes at once could use up the
refresh token, so nothing here may run in parallel (PLAN-desktop-app §4).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from parro.api_client import ParroClient
from parro.errors import CredentialsRejected, LoginHalted, NotLoggedIn, ParroError
from parro.settings import Settings

log = logging.getLogger("parro_gui")
# The core's own messages name CLI commands, which mean nothing in a window.
LOG_IN_AGAIN = "You are not logged in. Use the Log in button at the bottom right."

Task = Callable[[ParroClient], Any]
Done = Callable[[Any], None]
Failed = Callable[[str], None]


@dataclass(frozen=True)
class Outcome:
    """What a task produced, on its way back to the window's thread."""

    value: Any
    error: str | None
    done: Done
    failed: Failed


class _Job(QRunnable):
    def __init__(self, worker: "Worker", task: Task, done: Done, failed: Failed) -> None:
        super().__init__()
        self.worker, self.task, self.done, self.failed = worker, task, done, failed

    def run(self) -> None:
        value, error = None, None
        try:
            value = self.task(self.worker.client())
        except CredentialsRejected as problem:
            error = str(problem)
        except (NotLoggedIn, LoginHalted):
            error = LOG_IN_AGAIN
        except ParroError as problem:
            error = str(problem)
        except Exception as unexpected:  # keep running: one broken call must not end the app
            # Only the type: the text of an unexpected error could hold anything.
            log.error("a background task failed: %s", type(unexpected).__name__)
            error = f"Something went wrong ({type(unexpected).__name__})."
        self.worker.finished.emit(Outcome(value, error, self.done, self.failed))


class Worker(QObject):
    """Create and use this on the window's thread. Results arrive there too."""

    finished = Signal(object)

    def __init__(
        self,
        make_client: Callable[[Settings], ParroClient] = ParroClient,
        parent: QObject | None = None,
        settings: Callable[[], Settings] = Settings.from_environment,
    ) -> None:
        super().__init__(parent)
        self.make_client = make_client
        self.settings = settings
        self._client: ParroClient | None = None
        self._closed = False
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self.finished.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    def client(self) -> ParroClient:
        """The shared client, created on first use. Runs on the background thread.

        Made again when the settings change, for example after the login dialog remembered a
        password file.
        """
        settings = self.settings()
        if self._client is None or self._client.settings != settings:
            self._client = self.make_client(settings)
        # Pick up logins done meanwhile by the CLI or the MCP server.
        self._client.token_store.reload()
        return self._client

    def submit(self, task: Task, done: Done, failed: Failed) -> None:
        if not self._closed:
            self._pool.start(_Job(self, task, done, failed))

    def close(self) -> None:
        """Drop what has not started, wait for what has, and deliver nothing more."""
        self._closed = True
        self._pool.clear()
        self._pool.waitForDone()

    @Slot(object)
    def _deliver(self, outcome: Outcome) -> None:
        if self._closed:
            return
        if outcome.error is not None:
            outcome.failed(outcome.error)
        else:
            outcome.done(outcome.value)
