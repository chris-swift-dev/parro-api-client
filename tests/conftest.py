"""Shared pytest setup.

The tests run on invented API responses in tests/fixtures/api/ (written by
tests/fixtures/make_api_fixtures.py, committed), so they behave the same locally and in CI.

samples/ and openapi/parro.openapi.json hold redacted real-world data and are git-ignored. Only the
contract test reads them (load_real_sample), and it skips when they are absent.
"""

import gc
import json
import sys
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

# PySide6 crashes the interpreter before Python 3.12 (see parro_gui/app.py), and the app refuses to
# start there, so its window tests do not run there either.
collect_ignore = (
    [f"test_gui_{name}.py" for name in ("app", "local", "login", "views", "writes")]
    if sys.version_info < (3, 12)
    else []
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "api"
SAMPLES_DIR = PROJECT_ROOT / "samples"
FULL_SPEC_PATH = PROJECT_ROOT / "openapi" / "parro.openapi.json"
PUBLIC_SPEC_PATH = PROJECT_ROOT / "openapi" / "parro.public.openapi.json"

# Make `import parro` work without installing anything.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_sample(file_name: str) -> Any:
    """Parse one invented API response from tests/fixtures/api/. Missing → FileNotFoundError."""
    return json.loads((FIXTURES_DIR / file_name).read_text(encoding="utf-8"))


def load_real_sample(file_name: str) -> Any:
    """Parse one samples/*.json file, or skip the calling test when samples/ is absent."""
    path = SAMPLES_DIR / file_name
    if not path.exists():
        pytest.skip(f"samples/{file_name} not present (git-ignored)")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def private_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test gets its own empty home folder, so nothing is ever written to the real one.

    The defaults ~/.parro-mcp/tokens.json and ~/.parro/data (cache) resolve inside it. Windows
    finds the home folder through USERPROFILE, the other systems through HOME: both are set.
    """
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


# "Today" for every test: the invented fixtures are dated around it.
FIXED_NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone(timedelta(hours=1)))


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Freeze parro.operations.current_time(), so calendar results do not change as time passes."""
    from parro import operations

    monkeypatch.setattr(operations, "current_time", lambda: FIXED_NOW)
    return FIXED_NOW


@pytest.fixture(scope="session")
def application() -> Iterator[Any]:
    """The one QApplication of the test run, shut down properly so Qt cannot crash at exit."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication([])
    yield app
    for widget in app.topLevelWidgets():
        widget.close()
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    app.shutdown()
