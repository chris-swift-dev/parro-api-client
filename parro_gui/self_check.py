"""`parro-client-gui --self-check`: does this copy of the app start? For the built installers.

A bundled app can miss a Qt plugin or a system library and still build. This starts Qt without a
screen, builds the whole window, draws the icons, and stops. It logs in nowhere and sends nothing:
the settings point to an empty temporary folder, and every request is refused and counted.
"""

import os
import sys
import tempfile
from importlib.util import find_spec
from pathlib import Path

from parro import __version__

# What a login or a request could use, from the environment of whoever runs the check.
_IGNORED = ("PARRO_USERNAME", "PARRO_PASSWORD", "PARRO_PASSWORD_FILE", "PARRO_ACCESS_TOKEN")
OPTIONAL_LIBRARIES = {"pypdf": "pypdf", "PIL": "Pillow", "fitz": "PyMuPDF"}


def run_self_check() -> int:
    """0 when the app can start; prints what it found."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="parro-self-check-") as folder:
        for name in [n for n in os.environ if n.startswith("PARRO_") or n in _IGNORED]:
            del os.environ[name]
        os.environ["PARRO_DATA_DIR"] = str(Path(folder) / "data")
        os.environ["PARRO_TOKEN_FILE"] = str(Path(folder) / "tokens.json")
        problems, requests = _check_the_window()
    if requests:
        problems.append(f"{requests} request(s) were attempted; the self-check sends none")
    libraries = [label for module, label in OPTIONAL_LIBRARIES.items() if find_spec(module)]
    print(f"parro-client-gui {__version__}")
    print(
        f"Python {sys.version.split()[0]}, attachment libraries: {', '.join(libraries) or 'none'}"
    )
    for problem in problems:
        print(f"problem: {problem}", file=sys.stderr)
    print("self-check: " + ("failed" if problems else "ok"))
    return 1 if problems else 0


def _check_the_window() -> tuple[list[str], int]:
    from PySide6 import __version__ as qt_version
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from PySide6.QtWidgets import QApplication

    from parro.api_client import ParroClient
    from parro.errors import NetworkError
    from parro.http import HttpRequest, HttpResponse
    from parro.settings import Settings

    from .icons import SECTION_ICONS, app_icon
    from .theme import apply_theme
    from .window import SECTIONS, MainWindow

    attempts: list[str] = []

    class NoNetwork:
        def send(self, request: HttpRequest) -> HttpResponse:
            attempts.append(request.method)
            raise NetworkError("The self-check sends no requests.")

    def make_client(settings: Settings) -> ParroClient:
        return ParroClient(settings, transport=NoNetwork())

    problems: list[str] = []
    application = QApplication.instance() or QApplication([sys.argv[0]])
    print(f"Qt for Python {qt_version}, platform {QApplication.platformName()}")
    apply_theme(application)  # type: ignore[arg-type]
    if app_icon().isNull():
        problems.append("the app icon could not be drawn")
    window = MainWindow(make_client)
    window.show()
    for row, name in enumerate(SECTIONS):
        if window.sections.item(row).icon().isNull():
            problems.append(f"the icon {SECTION_ICONS[name]!r} could not be drawn")
        window.sections.setCurrentRow(row)
    QTimer.singleShot(300, application.quit)
    application.exec()
    if window.login_dialog is not None:
        window.login_dialog.close()
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return problems, len(attempts)
