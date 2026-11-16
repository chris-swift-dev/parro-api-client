"""Which changes the app makes without asking first (docs/PLAN-0.14-additions.md §3).

At first every change asks: a yes/no question for marking as read, a dialog with a preview for the
others. *Settings → Confirmations…* has a tick per action; unticking one skips its question. The
choice is kept in desktop-app.json, as a list of the actions that are not asked about.

Skipping the question skips nothing else. The app still reads first (the chat, the message, the
slot) and refuses what it refused before; a change is still sent once; and what happened is said
in the message line above the section. Only the desktop app: the command line has `--yes`, and an
assistant's tools keep `confirm: true`.
"""

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from . import app_file

PART = "skip_confirmation"
# (the name in the file, what the tick says). The order is the order in the dialog.
ACTIONS = (
    ("mark_read", "Mark as read"),
    ("mark_group_read", "Mark a whole group's announcements as read"),
    ("send_chat", "Send a chat message"),
    ("delete_chat", "Delete a chat message"),
    ("helper", "Sign up or withdraw as a helper"),
    ("rsvp", "Answer an invitation"),
)
ACTION_NAMES = frozenset(name for name, _label in ACTIONS)
EXPLANATION = (
    "The app asks before it changes something in Parro. Untick an action to skip its question: "
    "one click then does it at once.\n\n"
    "Sending and deleting a message cannot be undone, and the school sees what you mark as read. "
    "The app still checks first whether the change is possible, and still sends it only once."
)


class Confirmations:
    """Which actions are done without asking. Without a data folder: every action asks."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir

    def skipped(self) -> frozenset[str]:
        """The actions that are not asked about. Anything odd in the file counts as 'ask'."""
        if self.data_dir is None:
            return frozenset()
        saved = app_file.read_part(self.data_dir, PART)
        if not isinstance(saved, list):
            return frozenset()
        return frozenset(name for name in saved if isinstance(name, str)) & ACTION_NAMES

    def skips(self, action: str) -> bool:
        return action in self.skipped()

    def set_skipped(self, actions: frozenset[str]) -> None:
        if self.data_dir is None:
            return
        kept = sorted(actions & ACTION_NAMES)
        app_file.write_part(self.data_dir, PART, kept or None)


class ConfirmationsDialog(QDialog):
    """A tick per action: ticked asks first."""

    def __init__(self, confirmations: Confirmations, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.confirmations = confirmations
        self.setWindowTitle("Confirmations")
        layout = QVBoxLayout(self)
        explanation = QLabel(EXPLANATION)
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        layout.addWidget(QLabel("Ask first before I:"))
        skipped = confirmations.skipped()
        self.boxes: dict[str, QCheckBox] = {}
        for name, label in ACTIONS:
            box = QCheckBox(label)
            box.setChecked(name not in skipped)
            self.boxes[name] = box
            layout.addWidget(box)
        buttons = QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        self.buttons = QDialogButtonBox(buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.setMinimumWidth(440)

    def accept(self) -> None:
        unticked = frozenset(name for name, box in self.boxes.items() if not box.isChecked())
        self.confirmations.set_skipped(unticked)
        super().accept()
