"""Telling you about a new version (docs/PLAN-desktop-0.12.md §1.7).

Only after you agreed: the first start asks once, and the answer is kept in desktop-app.json. Then
at every start, and once a day while the app stays open, the app asks GitHub for the newest release
(parro.release_check) on a thread of its own, so a slow answer never holds up Parro.

A newer version shows a button that opens the release page, and the first time the app finds that
version it also says so in a dialog: a button alone was easy to miss. The app itself downloads and
installs nothing. Failures at start say nothing; *Check for updates now* says what happened.

Until 0.13.0 the check at start ran at most once a day, counted from the last start. A release
published later that day was then found a day later, and nothing showed when the app had last
looked: the owner took that for a check that did not work. So the Help menu and About now say when
the app last checked and what it found, and one small request per start is all the limit saved.
"""

import dataclasses
import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QPushButton

from parro import __version__
from parro.errors import ParroError
from parro.release_check import LatestRelease, is_newer, latest_release
from parro.rendering import format_day

from . import app_file
from .widgets import APP_NAME, ask, open_url

PART = "update_check"
DAY_SECONDS = 24 * 60 * 60
QUESTION = (
    "Check for new versions when the app starts?\n\n"
    "The app then asks GitHub, where it is published, for the newest version each time it starts. "
    "Nothing about you or your school goes with it. You can change this in the Help menu."
)
UP_TO_DATE = "You have the newest version, {version}."
COULD_NOT_CHECK = "Could not check for a new version: {reason}"
AVAILABLE = "Version {version} is available"
PIPX_UPDATE = "pipx upgrade parro-api-client"
WAIT_MS = 500  # how often a question at start looks for a quiet moment


def no_dialog_open() -> bool:
    return QApplication.activeModalWidget() is None


FAILED = "failed"  # `last_found` after a check that got no answer


@dataclass(frozen=True)
class Preference:
    enabled: bool | None  # None: not asked yet
    told_version: str | None = None  # the newest version a dialog at start already announced
    last_checked: float | None = None  # when the last check ended, as time.time()
    last_found: str | None = None  # the newest release it named, "" for none, FAILED


def load_preference(data_dir: Path) -> Preference:
    """What was saved. A file from before 0.14 holds `last_checked` only: when, not what."""
    saved = app_file.read_part(data_dir, PART)
    if not isinstance(saved, dict) or not isinstance(saved.get("enabled"), bool):
        return Preference(None)
    told, last, found = (saved.get(key) for key in ("told_version", "last_checked", "last_found"))
    return Preference(
        saved["enabled"],
        told if isinstance(told, str) else None,
        float(last) if isinstance(last, int | float) and not isinstance(last, bool) else None,
        found if isinstance(found, str) else None,
    )


def save_preference(data_dir: Path, preference: Preference) -> None:
    part = {
        "enabled": preference.enabled,
        "told_version": preference.told_version,
        "last_checked": preference.last_checked,
        "last_found": preference.last_found,
    }
    app_file.write_part(data_dir, PART, part)


def describe_moment(moment: float, now: float) -> str:
    """'today 14:05', 'yesterday 09:30' or 'Sat 14 Nov 2026 14:05', in this computer's time."""
    then, today = datetime.fromtimestamp(moment), datetime.fromtimestamp(now)
    days = (today.date() - then.date()).days
    if days in (0, 1):
        return f"{'today' if days == 0 else 'yesterday'} {then:%H:%M}"
    return f"{format_day(then)} {then:%H:%M}"


def describe_last_check(preference: Preference, now: float, current: str = __version__) -> str:
    """One line for the Help menu and About: when the app last looked, and what it found."""
    if preference.last_checked is None:
        return "Not checked yet"
    when = describe_moment(preference.last_checked, now)
    found = preference.last_found
    if found == FAILED:
        return f"Last check failed: {when}"
    if found is None:  # a file from before 0.14: when, but not what
        return f"Last checked: {when}"
    if found and is_newer(found, current):
        return f"Last checked: {when} · version {found} is available"
    return f"Last checked: {when} · you have the newest version"


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
        fetch: Callable[[], LatestRelease | None] = latest_release,
        ready: Callable[[], bool] = no_dialog_open,
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(window)
        self.window, self.data_dir, self.fetch = window, data_dir, fetch
        self.ready, self.clock = ready, clock
        # An app that is left open for days still hears about a new version.
        self.daily = QTimer(self)
        self.daily.setInterval(DAY_SECONDS * 1000)
        self.daily.timeout.connect(self._check_again)
        self.installer = installed_with_an_installer()
        self.release: LatestRelease | None = None
        self.notice = QPushButton()
        self.notice.setVisible(False)
        self.notice.clicked.connect(self.show_release)
        window.statusBar().addPermanentWidget(self.notice)
        menu = window.menuBar().addMenu("&Help")
        self.check_now_action = QAction("Check for updates now", window)
        self.check_now_action.triggered.connect(self.check_now)
        # When the app last looked and what it found: shown, not clickable.
        self.last_check_action = QAction(window)
        self.last_check_action.setEnabled(False)
        self.at_start_action = QAction("Check for new versions at start", window)
        self.at_start_action.setCheckable(True)
        self.at_start_action.setChecked(bool(self.preference().enabled))
        self.at_start_action.toggled.connect(self._set_enabled)
        self.about_action = QAction(f"About {APP_NAME}", window)
        self.about_action.setMenuRole(QAction.MenuRole.AboutRole)
        self.about_action.triggered.connect(self.show_about)
        for action in (
            self.check_now_action,
            self.last_check_action,
            self.at_start_action,
            self.about_action,
        ):
            menu.addAction(action)
        menu.aboutToShow.connect(self._show_last_check)  # "today" may have become "yesterday"
        self._show_last_check()
        self._check: UpdateCheck | None = None
        self._quietly = True
        self.answers = 0  # answers handled, from GitHub or a failure

    def preference(self) -> Preference:
        return load_preference(self.data_dir) if self.data_dir else Preference(False)

    def _store(self, preference: Preference) -> None:
        if self.data_dir:
            save_preference(self.data_dir, preference)

    def _set_enabled(self, enabled: bool) -> None:
        self._store(dataclasses.replace(self.preference(), enabled=enabled))

    def last_check_text(self) -> str:
        return describe_last_check(self.preference(), self.clock())

    def _show_last_check(self) -> None:
        self.last_check_action.setText(self.last_check_text())

    def _note_check(self, found: str) -> None:
        """Keep when a check ended and what it found. Only once the answer is in: a check that
        is still running, or was never answered, is not a check."""
        preference = self.preference()
        if preference.enabled is not None:  # nothing is kept before the first question
            changed = dataclasses.replace(preference, last_checked=self.clock(), last_found=found)
            self._store(changed)
        self._show_last_check()

    def at_start(self) -> None:
        """From main(): ask once, then check, at every start.

        The question waits for a quiet moment: asked while the login dialog is open, it would sit
        behind it, blocked by it, and neither could be answered.
        """
        preference = self.preference()
        if preference.enabled is None and self.data_dir:
            if not self.ready():
                QTimer.singleShot(WAIT_MS, self.at_start)
                return
            enabled = ask(self.window, QUESTION)
            preference = Preference(enabled)
            self._store(preference)
            self.at_start_action.setChecked(enabled)
        if preference.enabled:
            self._run(quietly=True)
            self.daily.start()

    def _check_again(self) -> None:
        if self.preference().enabled:
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
        self._note_check(release.version if release is not None else "")
        if release is not None and is_newer(release.version):
            self.release = release
            self.notice.setText(AVAILABLE.format(version=release.version))
            self.notice.setVisible(True)
            if not quietly:
                self.show_release()
            elif self.preference().told_version != release.version:
                self._announce()
        elif not quietly:
            self._tell(UP_TO_DATE.format(version=__version__))

    def _announce(self) -> None:
        """A version the check at start has not told about yet: say it once, in the dialog the
        check by hand shows. It waits for a quiet moment, as the first question does. From then on
        this version is only the button, so the app does not nag at every start."""
        release = self.release
        if release is None:
            return
        if not self.ready():
            QTimer.singleShot(WAIT_MS, self._announce)
            return
        self._store(dataclasses.replace(self.preference(), told_version=release.version))
        self.show_release()

    def _failed(self, reason: str) -> None:
        self.answers += 1
        self.check_now_action.setEnabled(True)
        self._note_check(FAILED)
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
            f"{APP_NAME} {__version__}\n{self.last_check_text()}\n\n"
            "An unofficial desktop app for Parro. Not affiliated with "
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
