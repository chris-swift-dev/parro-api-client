"""The message line above each section, and the window's minimum size (live check of 0.12.0).

Saving 20 attachments that all failed wrote every file into a label that grew without end and
could not scroll. Now: at most two lines, the rest behind Details…, a close button, and a window
that cannot be made so small that buttons fall off.
"""

import json
import os
import time
from collections.abc import Callable
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QWidget,
)

from parro.api_client import ParroClient  # noqa: E402
from parro_gui.notice import MAX_LINES, Notice, first_lines  # noqa: E402
from parro_gui.views.base import DETAIL_MIN_HEIGHT, LOADING  # noqa: E402
from parro_gui.widgets import ElidedLabel  # noqa: E402
from parro_gui.window import MINIMUM_SIZE, SECTIONS, MainWindow  # noqa: E402
from tests import fakes  # noqa: E402
from tests.conftest import load_sample  # noqa: E402
from tests.gui_helpers import dispose, wait_until  # noqa: E402

THIRTY_FAILED = "\n".join(
    f"- worksheet-{n}.pdf: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"
    for n in range(30)
)
LONG = (
    "Saved 0 of 30 files in /home/someone/Downloads. 30 not saved: "
    + "certificate verify failed; " * 12
)


def settle() -> None:
    for _ in range(20):
        QApplication.processEvents()
        time.sleep(0.002)


# ----------------------------------------------------------------------------- the line itself


def test_a_short_message_is_shown_whole(application):
    notice = Notice()
    shown, cut = first_lines("Marked as read.", notice.label.font(), 400, MAX_LINES)
    assert (shown, cut) == ("Marked as read.", False)


def test_a_long_message_takes_two_lines_and_ends_in_dots(application):
    notice = Notice()
    shown, cut = first_lines(LONG, notice.label.font(), 300, MAX_LINES)
    assert cut and shown.endswith("…") and shown.count("\n") == MAX_LINES - 1


def test_the_label_never_grows_past_two_lines(application):
    notice = Notice()
    notice.resize(400, 200)
    notice.setText(LONG, "Not saved:\n" + THIRTY_FAILED)
    line = notice.label.fontMetrics().lineSpacing()
    assert notice.label.height() <= line * MAX_LINES + 2
    assert notice.truncated and not notice.details_button.isHidden()
    assert notice.details().count("worksheet-") == 30, "Details… has every file"
    dispose(notice)


def test_details_scroll_and_close_removes_the_message(application):
    notice = Notice()
    notice.setText(LONG, THIRTY_FAILED)
    notice.show_details()
    assert notice.dialog is not None and notice.dialog.text.isReadOnly()
    assert notice.dialog.text.toPlainText().count("worksheet-") == 30
    notice.dialog.reject()
    notice.close_button.click()
    assert notice.text() == "" and notice.isHidden()
    dispose(notice)


def test_a_short_message_without_details_has_no_button(application):
    notice = Notice()
    notice.resize(500, 100)
    notice.setText("Marked as read.")
    assert notice.details_button.isHidden() and not notice.truncated
    notice.setText("")
    assert notice.isHidden()
    dispose(notice)


def test_a_long_file_name_does_not_push_its_buttons_away(application):
    row = QWidget()
    layout = QHBoxLayout(row)
    label = ElidedLabel("a-very-long-name-for-a-worksheet-about-the-autumn-trip-" * 4 + ".pdf")
    buttons = [QPushButton("Read"), QPushButton("Save…")]
    layout.addWidget(label, 1)
    for button in buttons:
        layout.addWidget(button)
    row.resize(320, 40)
    row.show()
    settle()
    assert all(row.rect().contains(b.geometry()) for b in buttons)
    assert "…" in label.text() and label.toolTip() == label.full_text
    dispose(row)


# ----------------------------------------------------------------------------- in the window


@pytest.fixture
def window(application, tmp_path, monkeypatch) -> Any:
    for name in list(os.environ):
        if name.startswith("PARRO_"):
            monkeypatch.delenv(name)
    tokens = tmp_path / "tokens.json"
    tokens.write_text(
        json.dumps(
            {
                "access_token": fakes.ACCESS_TOKEN,
                "refresh_token": fakes.REFRESH_TOKEN,
                "expires_at": time.time() + 3000,
            }
        )
    )
    monkeypatch.setenv("PARRO_TOKEN_FILE", str(tokens))
    monkeypatch.setenv("PARRO_DATA_DIR", str(tmp_path / "data"))
    api = fakes.FakeParroApi(load_sample)
    make_client: Callable[[Any], ParroClient] = lambda s: ParroClient(s, transport=api)  # noqa: E731
    created = MainWindow(make_client)
    created.resize(1000, 680)
    created.show()
    wait_until(lambda: created.logged_in)
    yield created
    dispose(created)


def show(window: MainWindow, name: str) -> Any:
    view: Any = window.views[name]
    window.sections.setCurrentRow(SECTIONS.index(name))
    wait_until(lambda: view.loaded and view.notice.text() != LOADING)
    if getattr(view, "list", None) is not None and view.list.count():
        view.list.setCurrentRow(0)
    settle()
    return view


def test_thirty_failed_files_leave_the_details_their_room(window):
    view = show(window, "Announcements")
    view.notice.setText(LONG, "Not saved:\n" + THIRTY_FAILED)
    settle()
    line = view.notice.label.fontMetrics().lineSpacing()
    tallest = max(line * MAX_LINES + 2, view.notice.details_button.sizeHint().height())
    assert view.notice.height() <= tallest
    assert view.detail.height() >= DETAIL_MIN_HEIGHT


def test_the_window_does_not_get_smaller_than_its_minimum(window):
    window.resize(300, 200)
    settle()
    assert (window.width(), window.height()) == MINIMUM_SIZE


CONTROLS = (QAbstractButton, QComboBox, QSpinBox)


def cut_off(window: MainWindow, view: Any) -> list[str]:
    found = []
    for kind in CONTROLS:
        for control in view.findChildren(kind):
            if not control.isVisible() or control.width() == 0:
                continue
            corner = control.mapTo(window, QPoint(0, 0))
            if not window.rect().contains(QRect(corner, control.size())):
                found.append(f"{type(control).__name__} outside the window")
            elif (
                isinstance(control, QPushButton)
                and control.width() < control.sizeHint().width() - 1
            ):
                found.append(f"{control.text()!r} squeezed")
    return found


@pytest.mark.parametrize("name", SECTIONS)
def test_at_the_minimum_size_every_control_fits(window, name):
    view = show(window, name)
    window.resize(*MINIMUM_SIZE)
    settle()
    assert cut_off(window, view) == []
