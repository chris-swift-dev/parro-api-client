"""`privacy` / `parro_privacy` (PLAN-unverified-endpoints §4): the state of each child's privacy
choices, and the signed link to the page where they are set. That link is a secret: never in a
log, the cache or the archive.
"""

import json
import logging
import os
import time
from typing import Any

import pytest

import parro_cli
import parro_mcp
from parro.api_client import ParroClient
from tests import fakes
from tests.conftest import load_sample

MILA, DAAN = 3000000001, 3000000002
SIGNATURE = "signedpermission=EXAMPLE-3000000001"


@pytest.fixture
def environment(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("PARRO_"):
            monkeypatch.delenv(name)
    token_file = tmp_path / "tokens.json"
    token_file.write_text(
        json.dumps(
            {
                "access_token": fakes.ACCESS_TOKEN,
                "refresh_token": fakes.REFRESH_TOKEN,
                "expires_at": time.time() + 3000,
            }
        )
    )
    monkeypatch.setenv("PARRO_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("PARRO_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def run(capsys, *argv: str, api: fakes.FakeParroApi | None = None) -> tuple[int, str, str]:
    api = api or fakes.FakeParroApi(load_sample)
    exit_code = parro_cli.main(list(argv), make_client=lambda s: ParroClient(s, transport=api))
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_privacy_per_child_in_one_request(environment, capsys):
    api = fakes.FakeParroApi(load_sample)
    exit_code, out, _ = run(capsys, "privacy", "--format", "json", api=api)
    result = json.loads(out)
    assert exit_code == 0 and result["total"] == 2
    mila, daan = result["children"]
    assert mila == {
        "id": MILA,
        "name": "Mila",
        "parents_can_change": True,
        "editable_in_period": False,
        "state": "OPEN",
        "last_changed": "2026-09-14T20:12:05.000+02:00",
        "last_changed_by": "Sanne de Vries",
    }
    assert daan["parents_can_change"] is False and daan["last_changed_by"] == "Lotte Bakker"
    child_requests = [r.url for r in api.api_requests() if "/child" in r.url]
    assert len(child_requests) == 1 and "dtype=identity.RPrivacySettingChild" in child_requests[0]


def test_raw_gives_the_api_payload(environment, capsys):
    _, out, _ = run(capsys, "privacy", "--raw")
    assert json.loads(out)["items"][0]["setting"]["dtype"] == "privacy.RPrivacyCentreSetting"


def test_privacy_link_with_its_warning(environment, capsys):
    exit_code, out, _ = run(capsys, "privacy", "--link", str(MILA), "--format", "json")
    result = json.loads(out)
    assert exit_code == 0 and result["child_id"] == MILA
    assert result["privacy_link"].endswith(SIGNATURE)
    assert "without logging in" in result["warning"]
    _, markdown, _ = run(capsys, "privacy", "--link", str(MILA), "--format", "markdown")
    assert markdown.startswith(f"# Privacy page for child #{MILA}") and SIGNATURE in markdown


def test_the_link_is_never_logged_cached_or_written(environment, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    api = fakes.FakeParroApi(load_sample)
    run(capsys, "-vv", "privacy", "--link", str(MILA), api=api)
    request = next(r for r in api.requests if r.url.endswith("/privacy"))
    assert request.log_label == f"GET /rest/v2/child/{MILA}/privacy", "what the transport logs"
    assert "signedpermission" not in caplog.text
    data = environment / "data"
    stored = [p for p in data.rglob("*") if p.is_file()] if data.exists() else []
    assert not any(b"signedpermission" in path.read_bytes() for path in stored)


def test_unknown_child_and_bad_ids(environment, capsys):
    exit_code, out, err = run(capsys, "privacy", "--link", "1")
    assert exit_code == 1 and out == "" and "404" in err  # the API's own answer
    exit_code, _, err = run(capsys, "privacy", "--link", "0")
    assert exit_code == 2 and "child id" in err

    def without_link(name: str) -> Any:
        if name.startswith("getChildPrivacy_"):
            return {"dtype": "identity.RPrivacySettings", "defined": False}
        return load_sample(name)

    exit_code, _, err = run(
        capsys, "privacy", "--link", str(DAAN), api=fakes.FakeParroApi(without_link)
    )
    assert exit_code == 1 and "no privacy page" in err and "`privacy`" in err


def test_mcp_privacy_tool(environment):
    api = fakes.FakeParroApi(load_sample)
    server = parro_mcp.McpServer(make_client=lambda s: ParroClient(s, transport=api))
    listing = server.call_tool("parro_privacy", {"format": "markdown"})
    text = listing.content[0]["text"]
    assert not listing.is_error and text.startswith("# Privacy choices (2)")
    assert "parro_privacy(child_id=ID, link=true)" in text, "hints name the tool, not the CLI"
    link = server.call_tool("parro_privacy", {"child_id": MILA, "link": True})
    assert json.loads(link.content[0]["text"])["privacy_link"].endswith(SIGNATURE)
    missing = server.call_tool("parro_privacy", {"link": True})
    assert missing.is_error and "child id" in missing.content[0]["text"]
    tool = next(t for t in parro_mcp.TOOL_DEFINITIONS if t["name"] == "parro_privacy")
    assert "only to the user" in tool["description"]
