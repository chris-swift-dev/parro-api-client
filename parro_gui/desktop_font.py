"""In a Flatpak, the desktop's own font, so the text is as large as in the other apps.

Outside a sandbox Qt finds the font itself. Inside one it often cannot: Fedora's KDE, for example,
sets Noto Sans 10 in a system folder the sandbox does not see, and Qt falls back to "Sans Serif 9",
which looks smaller. The desktop's settings portal, which sandboxed apps may ask, knows the font.
This is a local D-Bus call to the desktop: no network, and nothing is written.
"""

import logging
import os
from typing import Any

from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage, QDBusVariant
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

LOG = logging.getLogger(__name__)
KDE = ("org.kde.kdeglobals.General", "font")  # "Noto Sans,10,-1,5,50,0,0,0,0,0"
GNOME = ("org.gnome.desktop.interface", "font-name")  # "Cantarell 11", "Noto Sans  10"
TIMEOUT_MS = 1000  # the window waits for this at start


def kde_font(value: str) -> QFont | None:
    font = QFont()
    return font if font.fromString(value) and font.family() else None


def gnome_font(value: str) -> QFont | None:
    """The last word is the size in points: "Cantarell 11", "Noto Sans  10"."""
    family, _, size = value.strip().rpartition(" ")
    try:
        points = float(size)
    except ValueError:
        return None
    family = family.strip()
    if not family or not 4 <= points <= 72:
        return None
    font = QFont(family)
    font.setPointSizeF(points)
    return font


def unwrap(value: Any) -> Any:
    """The portal's Read wraps the value in one or two variants."""
    while isinstance(value, QDBusVariant):
        value = value.variant()
    return value


def portal_font(portal: Any) -> QFont | None:
    """The desktop's font: KDE's setting first, then GNOME's. None when neither answers."""
    for (namespace, key), parse in ((KDE, kde_font), (GNOME, gnome_font)):
        reply = portal.call("ReadOne", namespace, key)
        if reply.type() != QDBusMessage.MessageType.ReplyMessage:
            reply = portal.call("Read", namespace, key)  # portals older than version 2
        if reply.type() != QDBusMessage.MessageType.ReplyMessage or not reply.arguments():
            continue
        value = unwrap(reply.arguments()[0])
        if isinstance(value, str) and (font := parse(value)) is not None:
            return font
    return None


def use_desktop_font(application: QApplication) -> None:
    """Only in a Flatpak; anywhere else Qt's own choice is right."""
    if not os.environ.get("FLATPAK_ID"):
        return
    portal = QDBusInterface(
        "org.freedesktop.portal.Desktop",
        "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.Settings",
        QDBusConnection.sessionBus(),
    )
    portal.setTimeout(TIMEOUT_MS)
    font = portal_font(portal) if portal.isValid() else None
    if font is None:
        LOG.info("The desktop's font is not known; Qt's own is used.")
        return
    application.setFont(font)
