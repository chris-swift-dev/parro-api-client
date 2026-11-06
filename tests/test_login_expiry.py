"""`status` / parro_auth_status say until when the login lasts (docs/LOGIN.md: at most 8 hours).

The end of a login is the refresh token's `exp` claim. It is read for display only; the token is
never printed, logged or verified.
"""

import base64
import json
import os
import time
from datetime import datetime, timezone

import pytest

from parro import cli as parro_cli
from parro import mcp_server as parro_mcp
from parro import rendering
from parro.api_client import ParroClient
from parro.token_store import token_expiry
from tests import fakes
from tests.conftest import load_sample

NOW = 1_800_000_000.0  # a fixed "now" for the status computation


def jwt(**claims: object) -> str:
    """An unsigned JWT with these claims (the client never verifies it, it only reads `exp`)."""

    def part(value: object) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'RS256'})}.{part(claims)}.c2lnbmF0dXJl"


def test_token_expiry_reads_only_a_jwts_exp():
    assert token_expiry(jwt(iat=NOW, exp=NOW + 8 * 3600, scope="openid")) == NOW + 8 * 3600
    for unreadable in (
        None,
        "",
        fakes.REFRESH_TOKEN,  # opaque
        "a.b",
        "a.%%%.c",  # not base64
        jwt(iat=NOW),  # no exp
        jwt(exp="tomorrow"),
        jwt(exp=True),
        "a." + base64.urlsafe_b64encode(b"[1, 2]").decode() + ".c",  # not an object
    ):
        assert token_expiry(unreadable) is None, unreadable


@pytest.fixture
def token_file(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("PARRO_"):
            monkeypatch.delenv(name)
    path = tmp_path / "tokens.json"
    monkeypatch.setenv("PARRO_TOKEN_FILE", str(path))
    return path


def write_tokens(path, refresh_token: str) -> None:
    path.write_text(
        json.dumps(
            {
                "access_token": fakes.ACCESS_TOKEN,
                "refresh_token": refresh_token,
                "expires_at": time.time() + 3000,
            }
        )
    )


def test_status_says_until_when_the_login_lasts(token_file, capsys):
    ends = time.time() + 7 * 3600 + 40 * 60 + 30
    refresh_token = jwt(iat=ends - 8 * 3600, exp=ends, refresh_count=1)
    write_tokens(token_file, refresh_token)
    api = fakes.FakeParroApi(load_sample)
    make_client = lambda s: ParroClient(s, transport=api)  # noqa: E731

    assert parro_cli.main(["status", "--format", "json"], make_client=make_client) == 0
    result = json.loads(capsys.readouterr().out)
    assert 7 * 3600 + 39 * 60 < result["login_expires_in_seconds"] <= 7 * 3600 + 40 * 60 + 30
    valid_until = datetime.fromisoformat(result["login_valid_until"])
    assert abs(valid_until.timestamp() - ends) < 1 and valid_until.tzinfo is not None

    assert parro_cli.main(["status", "--format", "markdown"], make_client=make_client) == 0
    text = capsys.readouterr().out
    assert "- Login: valid until " in text and "(7 h 40 min left); then log in again" in text
    assert refresh_token not in text and refresh_token.split(".")[1] not in text


def test_mcp_auth_status_has_the_same_fields(token_file):
    write_tokens(token_file, jwt(exp=time.time() + 3600))
    api = fakes.FakeParroApi(load_sample)
    server = parro_mcp.McpServer(make_client=lambda s: ParroClient(s, transport=api))
    result = json.loads(server.call_tool("parro_auth_status", {}).content[0]["text"])
    assert 3500 < result["login_expires_in_seconds"] <= 3600 and "login_valid_until" in result


def test_an_opaque_refresh_token_shows_no_login_line(token_file, capsys):
    write_tokens(token_file, fakes.REFRESH_TOKEN)
    api = fakes.FakeParroApi(load_sample)
    parro_cli.main(["status"], make_client=lambda s: ParroClient(s, transport=api))
    result = json.loads(capsys.readouterr().out)
    assert "login_expires_in_seconds" not in result and "login_valid_until" not in result


VALID_UNTIL = datetime(2026, 11, 6, 19, 37, tzinfo=timezone.utc).isoformat()


@pytest.mark.parametrize(
    ("status", "line"),
    [
        (
            {"login_valid_until": VALID_UNTIL, "login_expires_in_seconds": 7 * 3600 + 40 * 60},
            "valid until Fri 6 Nov 2026 19:37 (7 h 40 min left); then log in again",
        ),
        (
            {
                "login_valid_until": VALID_UNTIL,
                "login_expires_in_seconds": 25 * 60,
                "credentials_in_env": True,
            },
            "valid until Fri 6 Nov 2026 19:37 (25 min left); "
            "then the client logs in again on its own (one password check)",
        ),
        (
            {"login_valid_until": VALID_UNTIL, "login_expires_in_seconds": -60},
            "expired at Fri 6 Nov 2026 19:37; log in again: parro-client login --prompt",
        ),
        ({}, ""),
        ({"login_valid_until": "not a time", "login_expires_in_seconds": 5}, ""),
    ],
)
def test_login_line_wording(status, line):
    assert rendering.describe_login_expiry(status) == line
