"""Telling you about a new version (docs/PLAN-desktop-0.12.md §1.7).

Only after you agreed: the first start asks once, and the answer is kept in desktop-app.json. Then
at most once a day, at start, the app asks GitHub for the newest release (parro.release_check) on a
thread of its own, so a slow answer never holds up Parro. A newer version shows a button that
opens the release page; the app itself downloads and installs nothing. Failures at start say
nothing; *Check for updates now* says what happened.
"""

import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QMessageBox, QPushButton

from parro import __version__
from parro.errors import ParroError
from parro.release_check import LatestRelease, is_newer, latest_release

from . import app_file
from .widgets import APP_NAME, ask, open_url

PART = "update_check"
DAY_SECONDS = 24 * 60 * 60
QUESTION = (
    "Check for new versions when the app starts?\n\n"
    "The app then asks GitHub, where it is published, for the newest version, at most once a day. "
    "Nothing about you or your school goes with it. You can change this in the Help menu."
)
UP_TO_DATE = "You have the newest version, {version}."
COULD_NOT_CHECK = "Could not check for a new version: {reason}"
AVAILABLE = "Version {version} is available"
PIPX_UPDATE = "pipx upgrade parro-api-client"


@dataclass(frozen=True)
class Preference:
    enabled: bool | None  # None: not asked yet
    last_checked: float | None = None


def load_preference(data_dir: Path) -> Preference:
    saved = app_file.read_part(data_dir, PART)
    if not isinstance(saved, dict) or not isinstance(saved.get("enabled"), bool):
        return Preference(None)
    last = saved.get("last_checked")
    return Preference(saved["enabled"], float(last) if isinstance(last, int | float) else None)


def save_preference(data_dir: Path, preference: Preference) -> None:
    part = {"enabled": preference.enabled, "last_checked": preference.last_checked}
    app_file.write_part(data_dir, PART, part)


def due(preference: Preference, now: float) -> bool:
    if not preference.enabled:
        return False
    return preference.last_checked is None or now - preference.last_checked >= DAY_SECONDS


def installed_with_an_installer() -> bool:
    """The MSI, the DMG or the Flatpak, as opposed to pipx or pip: Briefcase's own folder."""
    return bool(os.environ.get("FLATPAK_ID")) or any(
        Path(entry).name == "app_packages" for entry in sys.path
    )


def how_to_update(release: LatestRelease, installer: bool) -> str:
    if installer:
        return (
            f"Download version {release.version} from its release page and install it over this "
            "one. Your login and settings are kept."
        )
    return f"Update it with:\n    {PIPX_UPDATE}"


class UpdateCheck(QObject):
    """Runs parro.release_check on a thread of its own; the answer arrives as a signal."""

    finished = Signal(object)  # LatestRelease | None
    failed = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        fetch: Callable[[], LatestRelease | None] = latest_release,
    ) -> None:
        super().__init__(parent)
        self.fetch = fetch

    def start(self) -> None:
        threading.Thread(target=self._run, name="update-check", daemon=True).start()

    def _run(self) -> None:
        try:
            release = self.fetch()
        except (ParroError, OSError, ValueError) as problem:
            self.failed.emit(str(problem))
            return
        self.finished.emit(release)


class Updates(QObject):
    """The Help menu, the question at the first start, and the button for a new version."""

    def __init__(
        self,
        window: QMainWindow,
        data_dir: Path | None,
        clock: Callable[[], float] = time.time,
        fetch: Callable[[], LatestRelease | None] = latest_release,
    ) -> None:
        super().__init__(window)
        self.window, self.data_dir, self.clock, self.fetch = window, data_dir, clock, fetch
        self.installer = installed_with_an_installer()
        self.release: LatestRelease | None = None
        self.notice = QPushButton()
        self.notice.setVisible(False)
        self.notice.clicked.connect(self.show_release)
        window.statusBar().addPermanentWidget(self.notice)
        menu = window.menuBar().addMenu("&Help")
        self.check_now_action = QAction("Check for updates now", window)
        self.check_now_action.triggered.connect(self.check_now)
        self.at_start_action = QAction("Check for new versions at start", window)
        self.at_start_action.setCheckable(True)
        self.at_start_action.setChecked(bool(self.preference().enabled))
        self.at_start_action.toggled.connect(self._set_enabled)
        self.about_action = QAction(f"About {APP_NAME}", window)
        self.about_action.setMenuRole(QAction.MenuRole.AboutRole)
        self.about_action.triggered.connect(self.show_about)
        for action in (self.check_now_action, self.at_start_action, self.about_action):
            menu.addAction(action)
        self._check: UpdateCheck | None = None
        self._quietly = True
        self.answers = 0  # answers handled, from GitHub or a failure

    def preference(self) -> Preference:
        return load_preference(self.data_dir) if self.data_dir else Preference(False)

    def _store(self, preference: Preference) -> None:
        if self.data_dir:
            save_preference(self.data_dir, preference)

    def _set_enabled(self, enabled: bool) -> None:
        self._store(Preference(enabled, self.preference().last_checked))

    def at_start(self) -> None:
        """From main(): ask once, then check when a day has passed."""
        preference = self.preference()
        if preference.enabled is None and self.data_dir:
            enabled = ask(self.window, QUESTION)
            preference = Preference(enabled)
            self._store(preference)
            self.at_start_action.setChecked(enabled)
        if due(preference, self.clock()):
            self._store(Preference(True, self.clock()))
            self._run(quietly=True)

    def check_now(self) -> None:
        self.check_now_action.setEnabled(False)
        self._run(quietly=False)

    def _run(self, quietly: bool) -> None:
        # Methods of this object, not lambdas: Qt then delivers the answer on the window's thread.
        self._quietly = quietly
        check = UpdateCheck(self, self.fetch)
        check.finished.connect(self._found)
        check.failed.connect(self._failed)
        self._check = check
        check.start()

    def _found(self, release: LatestRelease | None) -> None:
        quietly = self._quietly
        self.answers += 1
        self.check_now_action.setEnabled(True)
        if release is not None and is_newer(release.version):
            self.release = release
            self.notice.setText(AVAILABLE.format(version=release.version))
            self.notice.setVisible(True)
            if not quietly:
                self.show_release()
        elif not quietly:
            self._tell(UP_TO_DATE.format(version=__version__))

    def _failed(self, reason: str) -> None:
        self.answers += 1
        self.check_now_action.setEnabled(True)
        if not self._quietly:
            self._tell(COULD_NOT_CHECK.format(reason=reason))

    def show_release(self) -> None:
        if self.release is None:
            return
        text = f"{AVAILABLE.format(version=self.release.version)}.\n\n"
        text += how_to_update(self.release, self.installer)
        if ask(self.window, f"{text}\n\nOpen the release page in your browser?"):
            open_url(self.release.page)

    def show_about(self) -> None:
        QMessageBox.about(
            self.window,
            f"About {APP_NAME}",
            f"{APP_NAME} {__version__}\n\nAn unofficial desktop app for Parro. Not affiliated with "
            "or endorsed by Topicus, ParnasSys or Parro.\n\n"
            "https://github.com/chris-swift-dev/parro-api-client",
        )

    def _tell(self, text: str) -> None:
        QMessageBox.information(self.window, APP_NAME, text)


def data_dir_of(settings: Any) -> Path | None:
    try:
        return Path(settings().data_dir)
    except ParroError:
        return None
