"""The account, the children, their groups and the state of the privacy choices."""

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QCheckBox, QWidget

from parro import operations
from parro.api_client import ParroClient
from parro.rendering import format_date, join_parts

from ..text import bullets, document, heading, meta, subheading
from ..widgets import SafeTextBrowser
from ..worker import Worker
from .base import Section


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
        self.page = SafeTextBrowser()
        self.main.addWidget(self.page, 1)

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

    def clear(self) -> None:
        self.page.clear()
