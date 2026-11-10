"""Showing a link that works without logging in. It stays in this dialog and in nothing else."""

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SecretDialog(QDialog):
    def __init__(self, title: str, warning: str, link: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        note = QLabel()
        note.setWordWrap(True)
        note.setText(warning)
        self.link = QLineEdit(link)
        self.link.setReadOnly(True)
        self.copy_button = QPushButton("Copy")
        self.copy_button.clicked.connect(self.copy)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(note)
        layout.addWidget(self.link)
        layout.addLayout(buttons)

    def copy(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.link.text())


def show_secret(parent: QWidget, title: str, warning: str, link: str) -> None:
    dialog = SecretDialog(title, warning, link, parent)
    parent.secret_dialog = dialog  # type: ignore[attr-defined]  # for as long as it is open
    dialog.open()
