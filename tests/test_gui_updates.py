"""The update check in the app: asked once, at most once a day, quiet at start, never automatic."""

import os
import threading
from pathlib import Path
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QMainWindow  # noqa: E402

from parro.errors import NetworkError  # noqa: E402
from parro.release_check import LatestRelease, release_page  # noqa: E402
from parro_gui import app_file, auto_login, updates  # noqa: E402
from parro_gui.updates import DAY_SECONDS, Preference, Updates  # noqa: E402
from tests.gui_helpers import dispose, wait_until  # noqa: E402

NEWER = LatestRelease("99.0.0", release_page("99.0.0"))
SAME = LatestRelease("0.0.1", release_page("0.0.1"))


class GitHub:
    """Counts the checks, notes the thread they run on, and answers as told."""

    def __init__(self, answer: LatestRelease | None = NEWER, fails: bool = False) -> None:
        self.answer, self.fails = answer, fails
        self.threads: list[threading.Thread] = []

    def __call__(self) -> LatestRelease | None:
        self.threads.append(threading.current_thread())
        if self.fails:
            raise NetworkError("No answer for GET api.github.com: timed out")
        return self.answer


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def said(monkeypatch) -> dict[str, list[Any]]:
    """What the app asked, told and opened; every question is answered from `answers`."""
    record: dict[str, list[Any]] = {"asked": [], "told": [], "opened": [], "answers": []}

    def ask(_parent: Any, question: str) -> bool:
        record["asked"].append(question)
        return record["answers"].pop(0) if record["answers"] else False

    monkeypatch.setattr(updates, "ask", ask)

    def open_url(url: str) -> bool:
        record["opened"].append(url)
        return True

    monkeypatch.setattr(updates, "open_url", open_url)
    monkeypatch.setattr(Updates, "_tell", lambda _self, text: record["told"].append(text))
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    return record


@pytest.fixture
def make(application, tmp_path):
    windows: list[QMainWindow] = []

    def build(github: GitHub, clock: Clock | None = None) -> Updates:
        window = QMainWindow()
        windows.append(window)
        return Updates(window, tmp_path, clock or Clock(), github)

    yield build
    for window in windows:
        dispose(window)


def settled(found: Updates, github: GitHub, count: int) -> None:
    """Until GitHub was asked `count` times in all and this window has handled its answer."""
    wait_until(lambda: len(github.threads) >= count and found.answers >= 1)


# ----------------------------------------------------------------------------- the answer


def test_the_answer_is_kept_next_to_the_remembered_login(tmp_path):
    auto_login.save_remembered(tmp_path, auto_login.Remembered("a@example.org", Path("/x")))
    updates.save_preference(tmp_path, Preference(True, 5.0))
    assert auto_login.load_remembered(tmp_path) is not None
    auto_login.save_remembered(tmp_path, None)
    assert updates.load_preference(tmp_path) == Preference(True, 5.0)
    assert set(app_file.read_all(tmp_path)) == {"update_check"}


def test_an_unreadable_answer_counts_as_not_asked(tmp_path):
    app_file.write_part(tmp_path, "update_check", {"enabled": "yes"})
    assert updates.load_preference(tmp_path) == Preference(None)


@pytest.mark.parametrize(
    ("preference", "is_due"),
    [
        (Preference(None), False),
        (Preference(False), False),
        (Preference(True), True),
        (Preference(True, 1000.0 - DAY_SECONDS + 1), False),
        (Preference(True, 1000.0 - DAY_SECONDS), True),
    ],
)
def test_at_most_once_a_day(preference, is_due):
    assert updates.due(preference, 1000.0) is is_due


# ----------------------------------------------------------------------------- at start


def test_nothing_is_checked_before_you_agree(make, said):
    github = GitHub()
    found = make(github)
    found.at_start()
    assert len(said["asked"]) == 1 and github.threads == []
    assert updates.load_preference(found.data_dir) == Preference(False)
    found.at_start()
    assert len(said["asked"]) == 1, "asked once"


def test_after_yes_it_checks_in_the_background_and_shows_a_button(make, said):
    github = GitHub()
    said["answers"].append(True)
    found = make(github)
    found.at_start()
    settled(found, github, 1)
    assert github.threads[0] is not threading.main_thread()
    assert found.notice.text() == "Version 99.0.0 is available" and not found.notice.isHidden()
    assert said["told"] == [] and said["opened"] == [], "quiet at start, nothing opened"
    assert found.at_start_action.isChecked()


def test_the_same_day_it_does_not_check_again(make, said):
    github, clock = GitHub(), Clock()
    first = make(github, clock)
    updates.save_preference(first.data_dir, Preference(True))
    first.at_start()
    settled(first, github, 1)
    clock.now += DAY_SECONDS - 1
    make(github, clock).at_start()
    assert len(github.threads) == 1
    clock.now += 1
    later = make(github, clock)
    later.at_start()
    settled(later, github, 2)


def test_at_start_an_up_to_date_app_or_a_failure_says_nothing(make, said):
    for github in (GitHub(SAME), GitHub(None), GitHub(fails=True)):
        found = make(github)
        updates.save_preference(found.data_dir, Preference(True))
        found.at_start()
        settled(found, github, 1)
        assert found.notice.isHidden() and said["told"] == []


# ----------------------------------------------------------------------------- by hand


def test_check_now_says_what_happened(make, said):
    up_to_date = make(GitHub(SAME))
    up_to_date.check_now()
    wait_until(lambda: said["told"] != [])
    assert said["told"][-1].startswith("You have the newest version")
    failing = make(GitHub(fails=True))
    failing.check_now()
    wait_until(lambda: len(said["told"]) == 2)
    assert said["told"][-1].startswith("Could not check for a new version: No answer")


def test_check_now_works_also_when_checks_at_start_are_off(make, said):
    github = GitHub()
    found = make(github)
    updates.save_preference(found.data_dir, Preference(False))
    found.check_now()
    settled(found, github, 1)
    assert said["asked"] and "Version 99.0.0 is available" in said["asked"][-1]


def test_the_release_page_opens_only_on_yes(make, said):
    github = GitHub()
    found = make(github)
    found.check_now()
    settled(found, github, 1)
    assert said["opened"] == []
    said["answers"].append(True)
    found.notice.click()
    assert said["opened"] == [NEWER.page]


def test_the_menu_switch_is_kept(make, said):
    found = make(GitHub())
    found.at_start_action.setChecked(True)
    assert updates.load_preference(found.data_dir).enabled is True
    found.at_start_action.setChecked(False)
    assert updates.load_preference(found.data_dir).enabled is False


# ----------------------------------------------------------------------------- how to update


def test_how_to_update_depends_on_how_it_was_installed(monkeypatch):
    assert "pipx upgrade parro-api-client" in updates.how_to_update(NEWER, installer=False)
    assert "install it over this one" in updates.how_to_update(NEWER, installer=True)
    monkeypatch.setenv("FLATPAK_ID", "io.github.chrisswiftdev.parro-gui")
    assert updates.installed_with_an_installer()
    monkeypatch.delenv("FLATPAK_ID")
    monkeypatch.setattr("sys.path", ["/x/app", "/x/app_packages"])
    assert updates.installed_with_an_installer()
    monkeypatch.setattr("sys.path", ["/usr/lib/python3.14"])
    assert not updates.installed_with_an_installer()


def test_the_answer_is_handled_on_the_windows_thread(make, said, monkeypatch):
    seen: list[threading.Thread] = []
    original = Updates._found

    def found_on(self: Updates, release: LatestRelease | None) -> None:
        seen.append(threading.current_thread())
        original(self, release)

    monkeypatch.setattr(Updates, "_found", found_on)
    github = GitHub()
    found = make(github)
    found.check_now()
    wait_until(lambda: seen != [])
    assert seen == [threading.main_thread()] and github.threads[0] is not threading.main_thread()


def test_a_window_has_the_help_menu_and_checks_nothing_by_itself(
    application, tmp_path, monkeypatch
):
    from parro_gui.window import MainWindow

    for name in list(os.environ):
        if name.startswith("PARRO_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("PARRO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PARRO_TOKEN_FILE", str(tmp_path / "tokens.json"))
    monkeypatch.setattr(updates, "latest_release", lambda: pytest.fail("checked by itself"))
    window = MainWindow(lambda _settings: pytest.fail("no client needed"))
    try:
        titles = [action.text() for action in window.menuBar().actions()]
        assert titles == ["&Help"]
        assert window.updates._check is None and window.updates.data_dir == tmp_path / "data"
    finally:
        dispose(window)


def test_the_question_waits_for_a_quiet_moment(application, tmp_path, said):
    """Asked while another dialog is open, it would be blocked by it, and neither could be used."""
    quiet = {"now": False}
    window = QMainWindow()
    found = Updates(window, tmp_path, Clock(), GitHub(), ready=lambda: quiet["now"])
    try:
        found.at_start()
        QtWidgets.QApplication.processEvents()
        assert said["asked"] == []
        quiet["now"] = True
        wait_until(lambda: len(said["asked"]) == 1)
    finally:
        dispose(window)


def test_the_window_asks_only_after_the_login_dialog_closed(
    application, tmp_path, said, monkeypatch
):
    """The real case: not logged in, so the login dialog opens at start and is modal."""
    from parro_gui.window import MainWindow

    for name in list(os.environ):
        if name.startswith("PARRO_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("PARRO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PARRO_TOKEN_FILE", str(tmp_path / "tokens.json"))
    window = MainWindow()
    try:
        window.show()
        window.updates.at_start()
        wait_until(lambda: window.login_dialog is not None and window.login_dialog.isVisible())
        assert QtWidgets.QApplication.activeModalWidget() is window.login_dialog
        for _ in range(3):
            QtWidgets.QApplication.processEvents()
        assert said["asked"] == [], "not while the login dialog is open"
        window.login_dialog.reject()
        wait_until(lambda: len(said["asked"]) == 1)
    finally:
        dispose(window)
