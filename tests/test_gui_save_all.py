"""Save all attachments: one question, every file saved, failures named, nothing overwritten."""

import copy
import json
import os
import time
from collections.abc import Callable
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from parro.api_client import ParroClient  # noqa: E402
from parro_gui import widgets as gui_widgets  # noqa: E402
from parro_gui.views.attachments import SAVE_ALL  # noqa: E402
from parro_gui.views.base import LOADING  # noqa: E402
from parro_gui.window import SECTIONS, MainWindow  # noqa: E402
from tests import fakes  # noqa: E402
from tests.conftest import load_sample  # noqa: E402
from tests.gui_helpers import dispose, wait_until  # noqa: E402

SECOND_URL = "https://d111111abcdef8.cloudfront.net/application/x/second.txt"


@pytest.fixture(autouse=True)
def environment(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("PARRO_"):
            monkeypatch.delenv(name)
    path = tmp_path / "tokens.json"
    path.write_text(
        json.dumps(
            {
                "access_token": fakes.ACCESS_TOKEN,
                "refresh_token": fakes.REFRESH_TOKEN,
                "expires_at": time.time() + 3000,
            }
        )
    )
    monkeypatch.setenv("PARRO_TOKEN_FILE", str(path))
    monkeypatch.setenv("PARRO_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def api() -> fakes.FakeParroApi:
    """The newsletter announcement, with a second attachment next to it."""
    created = fakes.FakeParroApi(load_sample)
    sample = copy.deepcopy(load_sample("getEvent_announcement.200.json"))
    first = sample["attachments"][0]
    first["entries"][0]["contentType"] = "text/plain"
    second = copy.deepcopy(first)
    second["links"][0]["id"] = 222
    second["entries"][0]["url"] = SECOND_URL
    sample["attachments"].append(second)
    created.load_sample = lambda name: (
        sample if name == "getEvent_announcement.200.json" else load_sample(name)
    )
    created.attachment_bodies[first["entries"][0]["url"]] = ("text/plain", b"first file")
    created.attachment_bodies[SECOND_URL] = ("text/plain", b"second file")
    return created


@pytest.fixture
def window(application, api) -> Any:
    make_client: Callable[[Any], ParroClient] = lambda s: ParroClient(s, transport=api)  # noqa: E731
    created = MainWindow(make_client)
    wait_until(lambda: created.logged_in)
    yield created
    dispose(created)


@pytest.fixture
def questions(monkeypatch, tmp_path) -> list[str]:
    """Answers every folder question with tmp_path/out, and counts them."""
    asked: list[str] = []
    folder = tmp_path / "out"

    def choose(_parent: Any) -> str:
        asked.append("folder")
        return str(folder)

    monkeypatch.setattr(gui_widgets, "choose_folder", choose)
    return asked


def newsletter(window: MainWindow) -> Any:
    view: Any = window.views["Announcements"]
    window.sections.setCurrentRow(SECTIONS.index("Announcements"))
    wait_until(lambda: view.loaded and view.notice.text() != LOADING)
    row = next(i for i in range(view.list.count()) if "Nieuwsbrief" in view.list.item(i).text())
    view.list.setCurrentRow(row)
    wait_until(lambda: len(view.attachments.read_buttons) == 2)
    return view


def save_all(view: Any) -> str:
    view.attachments.save_all_button.click()
    wait_until(lambda: view.attachments.save_all_button.isEnabled())
    return str(view.notice.text())


def test_the_button_sits_next_to_mark_as_read(window):
    view = newsletter(window)
    button = view.attachments.save_all_button
    assert button.text() == SAVE_ALL and button.isEnabled()
    assert button.parent() is view.mark_button.parent() is view.lower_part


def test_every_file_is_saved_after_one_question(window, api, questions, tmp_path):
    view = newsletter(window)
    reported = save_all(view)
    folder = tmp_path / "out"
    assert questions == ["folder"]
    assert sorted(p.read_bytes() for p in folder.iterdir()) == [b"first file", b"second file"]
    assert reported == f"Saved 2 files in {folder}."
    assert api.writes() == [], "nothing but GET reaches the Parro API"


def test_a_file_with_the_same_name_is_kept(window, questions, tmp_path):
    view = newsletter(window)
    folder = tmp_path / "out"
    save_all(view)
    names = sorted(p.name for p in folder.iterdir())
    for path in folder.iterdir():
        path.write_bytes(b"mine")
    save_all(view)
    assert all((folder / name).read_bytes() == b"mine" for name in names), "nothing overwritten"
    assert len(list(folder.iterdir())) == 4


def test_a_failed_file_is_named(window, api, questions, tmp_path):
    del api.attachment_bodies[SECOND_URL]  # the CDN fails for this one
    view = newsletter(window)
    reported = save_all(view)
    assert reported.startswith(f"Saved 1 file in {tmp_path / 'out'}. Not saved: ")
    assert len(list((tmp_path / "out").iterdir())) == 1


def test_no_folder_chosen_saves_nothing(window, api, monkeypatch, tmp_path):
    monkeypatch.setattr(gui_widgets, "choose_folder", lambda _parent: "")
    view = newsletter(window)
    count = len(api.requests)
    view.attachments.save_all_button.click()
    assert len(api.requests) == count
    assert view.attachments.save_all_button.isEnabled()


def test_without_attachments_the_button_is_off(window):
    view = newsletter(window)
    view._show_full({"id": 1, "title": "No files", "contents": "Text", "attachments": []})
    assert not view.attachments.save_all_button.isEnabled()


def test_one_click_saves_once(window, questions, tmp_path):
    view = newsletter(window)
    button = view.attachments.save_all_button
    button.click()
    assert not button.isEnabled(), "off while saving"
    button.click()
    wait_until(button.isEnabled)
    assert questions == ["folder"] and len(list((tmp_path / "out").iterdir())) == 2
