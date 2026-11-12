"""The account, the children, their groups and the state of the privacy choices."""

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QCheckBox, QComboBox, QPushButton, QWidget

from parro import operations
from parro.api_client import ParroClient
from parro.rendering import format_date, join_parts

from .. import widgets
from ..text import bullets, document, heading, meta, subheading
from ..widgets import SafeTextBrowser
from ..worker import Worker
from .base import Section
from .secrets import show_secret

LINK_QUESTION = (
    "Show the link to this child's privacy page? It opens that page without logging in, so keep it "
    "to yourself."
)


def family_html(found: dict[str, Any]) -> str:
    account, school = found["account"], found["account"].get("organisation") or {}
    children = [
        join_parts([child.get("name"), f"since {format_date(child.get('enrolledSince'))}"])
        for child in found["children"].get("children", [])
    ]
    groups = [
        join_parts([group.get("name"), group.get("type"), f"{group.get('unread') or 0} unread"])
        for group in found["groups"].get("groups", [])
    ]
    privacy = [
        join_parts(
            [
                child.get("name"),
                "can be changed now"
                if child.get("parents_can_change")
                else "cannot be changed now",
                f"last changed {format_date(child.get('last_changed'))}"
                if child.get("last_changed")
                else "",
            ]
        )
        for child in found["privacy"].get("children", [])
    ]
    return document(
        heading(account.get("name") or "Account"),
        meta(account.get("email"), school.get("name"), school.get("city")),
        subheading("Children"),
        bullets(children) if children else "",
        subheading("Groups"),
        bullets(groups) if groups else "",
        subheading("Privacy choices"),
        bullets(privacy) if privacy else "",
    )


class FamilySection(Section):
    def __init__(self, worker: Worker, parent: QWidget | None = None) -> None:
        super().__init__(worker, parent)
        self.previous = QCheckBox("Last year's groups")
        self.add_filter(self.previous)
        self.previous.toggled.connect(self.load)
        self.child = QComboBox()
        self.link_button = QPushButton("Privacy page link…")
        self.link_button.setEnabled(False)
        self.link_button.clicked.connect(self.show_privacy_link)
        self.add_filter(self.child)
        self.add_filter(self.link_button)
        self.page = SafeTextBrowser()
        self.main.addWidget(self.page, 1)

    def memory_key(self) -> tuple[Any, ...]:
        return (self.previous.isChecked(),)

    def make_task(self) -> Callable[[ParroClient], Any]:
        scope = "previous" if self.previous.isChecked() else "current"

        def task(client: ParroClient) -> dict[str, Any]:
            return {
                "account": operations.show_account(client),
                "children": operations.list_children(client, 20),
                "groups": operations.list_groups(client, scope, 50),
                "privacy": operations.privacy(client),
            }

        return task

    def show_result(self, result: dict[str, Any]) -> None:
        self.page.setHtml(family_html(result))
        self.child.clear()
        for child in result["privacy"].get("children", []):
            self.child.addItem(str(child.get("name")), child.get("id"))
        self.link_button.setEnabled(self.child.count() > 0)

    def clear(self) -> None:
        self.page.clear()
        self.child.clear()
        self.link_button.setEnabled(False)

    def show_privacy_link(self) -> None:
        """A secret: only on request, and never kept or written anywhere."""
        child_id = self.child.currentData()
        if child_id is None or not widgets.ask(self, LINK_QUESTION):
            return
        self.worker.submit(
            lambda client: operations.privacy_link(client, child_id),
            lambda result: show_secret(
                self, "Privacy page link", result["warning"], result["privacy_link"]
            ),
            self.notice.setText,
        )
