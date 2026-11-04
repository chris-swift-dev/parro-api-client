"""Shared pytest setup.

samples/ and openapi/parro.openapi.json hold redacted real-world data and are git-ignored, so they
are missing in CI. Tests that need them use the fixtures below, which skip instead of failing.
"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = PROJECT_ROOT / "samples"
FULL_SPEC_PATH = PROJECT_ROOT / "openapi" / "parro.openapi.json"

# Make `import parro`, `import parro_cli` and `import parro_mcp` work without installing anything.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_sample(file_name: str) -> Any:
    """Parse one samples/*.json file, or skip the calling test when samples/ is absent."""
    path = SAMPLES_DIR / file_name
    if not path.exists():
        pytest.skip(f"samples/{file_name} not present (git-ignored)")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def sample() -> Any:
    """Fixture form of load_sample(), for tests that prefer injection."""
    return load_sample
