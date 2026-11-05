"""Shared pytest setup.

The tests run on invented API responses in tests/fixtures/api/ (written by
tests/fixtures/make_api_fixtures.py, committed), so they behave the same locally and in CI.

samples/ and openapi/parro.openapi.json hold redacted real-world data and are git-ignored. Only the
contract test reads them (load_real_sample), and it skips when they are absent.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "api"
SAMPLES_DIR = PROJECT_ROOT / "samples"
FULL_SPEC_PATH = PROJECT_ROOT / "openapi" / "parro.openapi.json"
PUBLIC_SPEC_PATH = PROJECT_ROOT / "openapi" / "parro.public.openapi.json"

# Make `import parro`, `import parro_cli` and `import parro_mcp` work without installing anything.
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
    """Every test gets its own empty HOME, so nothing is ever written to the real one.

    The defaults ~/.parro-mcp/tokens.json and ~/.parro/data (cache) resolve inside it.
    """
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    return home


# "Today" for every test: the invented fixtures are dated around it.
FIXED_NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone(timedelta(hours=1)))


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Freeze parro.operations.current_time(), so calendar results do not change as time passes."""
    from parro import operations

    monkeypatch.setattr(operations, "current_time", lambda: FIXED_NOW)
    return FIXED_NOW
