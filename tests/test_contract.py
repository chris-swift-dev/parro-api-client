"""Every API response the tests use is valid according to the spec.

* The invented fixtures in tests/fixtures/api/ are checked against the committed public spec, so
  this part runs everywhere, CI included.
* The real samples in samples/ are checked against the full spec. Both are git-ignored, so that
  part skips when they are absent.

File names say which response they are: <operationId>[_<variant>].<status>.json
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import (
    FIXTURES_DIR,
    FULL_SPEC_PATH,
    PUBLIC_SPEC_PATH,
    SAMPLES_DIR,
    load_real_sample,
    load_sample,
)

openapi_schema_validator = pytest.importorskip("openapi_schema_validator")


def response_schema(spec: dict[str, Any], file_name: str) -> dict[str, Any]:
    """The schema of the response a file is an example of, with the spec's components attached."""
    operation_id = file_name.split(".")[0].split("_")[0]
    status = file_name.split(".")[1]
    operation = next(
        operation
        for path_item in spec["paths"].values()
        for operation in path_item.values()
        if isinstance(operation, dict) and operation.get("operationId") == operation_id
    )
    responses = operation["responses"]
    # Collections are documented as 206; their samples are named .200.
    response = responses.get(status) or responses["206"]
    if "$ref" in response:
        response = spec["components"]["responses"][response["$ref"].rsplit("/", 1)[-1]]
    (media_type,) = response["content"].values()
    return dict(media_type["schema"], components=spec["components"])


def problems(spec: dict[str, Any], file_name: str, payload: Any) -> list[str]:
    validator = openapi_schema_validator.OAS30Validator(
        response_schema(spec, file_name),
        format_checker=openapi_schema_validator.oas30_format_checker,
    )
    return [
        f"/{'/'.join(map(str, error.absolute_path))}: {error.message[:120]}"
        for error in validator.iter_errors(payload)
    ]


def json_files(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.glob("*.json") if path.stat().st_size)


@pytest.mark.parametrize("file_name", json_files(FIXTURES_DIR))
def test_fixture_matches_the_public_spec(file_name):
    spec = json.loads(PUBLIC_SPEC_PATH.read_text(encoding="utf-8"))
    assert problems(spec, file_name, load_sample(file_name)) == []


@pytest.mark.parametrize("file_name", json_files(SAMPLES_DIR) if SAMPLES_DIR.exists() else ["-"])
def test_real_sample_matches_the_full_spec(file_name):
    if not FULL_SPEC_PATH.exists() or file_name == "-":
        pytest.skip("samples/ or openapi/parro.openapi.json not present (git-ignored)")
    spec = json.loads(FULL_SPEC_PATH.read_text(encoding="utf-8"))
    assert problems(spec, file_name, load_real_sample(file_name)) == []
