#!/usr/bin/env python3
"""Draw docs/images/desktop-app.png: the desktop app with the invented data of the test suite.

Needs Qt (`pip install -r requirements-gui.txt`) and no display, and never contacts Parro.
    python3 tools/make_desktop_picture.py
"""

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from parro import operations
    from parro.api_client import ParroClient
    from parro_gui.window import SECTIONS, MainWindow
    from tests import fakes
    from tests.conftest import load_sample
    from tests.gui_helpers import dispose, wait_until

    folder = Path(tempfile.mkdtemp(prefix="parro-picture-"))
    tokens = folder / "tokens.json"
    tokens.write_text(
        json.dumps(
            {
                "access_token": fakes.ACCESS_TOKEN,
                "refresh_token": fakes.REFRESH_TOKEN,
                "expires_at": time.time() + 3000,
            }
        )
    )
    os.environ.update(PARRO_TOKEN_FILE=str(tokens), PARRO_DATA_DIR=str(folder / "data"))
    operations.current_time = lambda: datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)
    application = QApplication([])
    api = fakes.FakeParroApi(load_sample)
    window = MainWindow(lambda settings: ParroClient(settings, transport=api))
    window.resize(1100, 700)
    window.show()
    wait_until(lambda: window.logged_in)
    window.sections.setCurrentRow(SECTIONS.index("Calendar"))
    view = window.views["Calendar"]
    wait_until(lambda: view.list.count() > 0)
    view.list.setCurrentRow(next(i for i in range(view.list.count()) if "Natuurmuseum" in view.list.item(i).text()))
    for _ in range(40):
        application.processEvents()
        time.sleep(0.005)
    target = ROOT / "docs" / "images" / "desktop-app.png"
    window.grab().save(str(target))
    print(f"wrote {target.relative_to(ROOT)}")
    dispose(window)
    application.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
