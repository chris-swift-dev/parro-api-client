"""Phase 5: every parro_cli.py command against the fake transport; exit codes; --help."""

import getpass
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from parro import authenticator, naming, rendering
from parro import cli as parro_cli
from parro.api_client import ParroClient
from parro.settings import Settings
from tests import fakes
from tests.conftest import load_sample


@pytest.fixture
def environment(tmp_path, monkeypatch):
    """A clean PARRO_* environment with a token file holding valid tokens."""
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
    return token_file


@pytest.fixture
def api() -> fakes.FakeParroApi:
    return fakes.FakeParroApi(load_sample)


def run(api: fakes.FakeParroApi, capsys, *argv: str) -> tuple[int, str, str]:
    def make_client(settings: Settings) -> ParroClient:
        return ParroClient(settings, transport=api)

    exit_code = parro_cli.main(list(argv), make_client=make_client)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


COMMANDS_WITH_JSON_OUTPUT = [
    ["status"],
    ["me"],
    ["me", "--raw"],
    ["children", "--limit", "1"],
    ["groups"],
    ["groups", "--previous"],
    ["unread"],
    ["system-news", "--limit", "2"],
    ["announcements", "--limit", "2"],
    ["announcements", "--group", "1", "--unread-only"],
    ["announcement", "5000000101"],
    ["calendar", "--limit", "1"],
    ["chatrooms"],
    ["chat-messages", "8000000001", "--limit", "1"],
    ["get", "/accountsettings"],
    ["get", "/event", "--param", "dtype=event.RAnnouncementEventPrimer", "--param", "group=1"],
    ["login-url"],
    ["--compact", "children"],
    ["children", "--compact"],
]


@pytest.mark.parametrize("argv", COMMANDS_WITH_JSON_OUTPUT, ids=" ".join)
def test_every_reading_command_prints_json(environment, api, capsys, argv):
    exit_code, out, err = run(api, capsys, *argv)
    assert exit_code == 0, err
    json.loads(out)
    assert {r.method for r in api.api_requests()} <= {"GET"}


def test_compact_prints_one_line(environment, api, capsys):
    _, out, _ = run(api, capsys, "--compact", "groups")
    assert out.count("\n") == 1


def test_announcements_output_matches_the_operation(environment, api, capsys):
    _, out, _ = run(api, capsys, "announcements", "--limit", "3")
    data = json.loads(out)
    assert data["count"] == 3
    assert data["announcements"][0]["from"] == "Basisschool De Linde"


def test_token_prints_only_the_token(environment, api, capsys):
    exit_code, out, _ = run(api, capsys, "token")
    assert (exit_code, out) == (0, fakes.ACCESS_TOKEN + "\n")


def test_status_does_not_log_in_without_tokens(environment, api, capsys, monkeypatch):
    environment.unlink()
    monkeypatch.setenv("PARRO_USERNAME", fakes.USERNAME)
    monkeypatch.setenv("PARRO_PASSWORD", fakes.CORRECT_PASSWORD)
    exit_code, out, _ = run(api, capsys, "status")
    assert exit_code == 0
    assert "Not logged in" in json.loads(out)["error"]
    assert api.requests == []


def test_login_with_the_form_and_logout(environment, api, capsys, monkeypatch):
    environment.unlink()
    monkeypatch.setenv("PARRO_USERNAME", fakes.USERNAME)
    monkeypatch.setenv("PARRO_PASSWORD", fakes.CORRECT_PASSWORD)
    exit_code, out, _ = run(api, capsys, "login")
    assert exit_code == 0
    assert json.loads(out)["logged_in_as"]["role_header"] == "GUARDIAN:2000000001"
    assert len(api.idp.credential_posts()) == 1
    exit_code, out, _ = run(api, capsys, "logout")
    assert exit_code == 0 and json.loads(out)["logged_out"] is True
    assert not environment.exists()


def test_login_prompt_reads_the_password_hidden(environment, api, capsys, monkeypatch):
    environment.unlink()
    monkeypatch.setattr(getpass, "getpass", lambda prompt: fakes.CORRECT_PASSWORD)
    monkeypatch.setattr(sys, "stdin", io.StringIO(fakes.USERNAME + "\n"))
    exit_code, _, err = run(api, capsys, "login", "--prompt", "--login-method", "password-grant")
    assert exit_code == 0, err
    (post,) = api.idp.credential_posts()
    assert fakes.form_of(post)["username"] == fakes.USERNAME


def test_browser_login_finish(environment, api, capsys):
    _, out, _ = run(api, capsys, "login-url")
    state = fakes.query_of(json.loads(out)["login_url"])["state"]
    redirect = f"https://talk.parro.com/oauth2?code={fakes.AUTHORIZATION_CODE}&state={state}"
    exit_code, out, _ = run(api, capsys, "login-finish", redirect)
    assert exit_code == 0 and json.loads(out)["has_refresh_token"] is True


def test_exit_code_3_when_not_logged_in(environment, api, capsys):
    environment.unlink()
    exit_code, out, err = run(api, capsys, "me")
    assert exit_code == 3 and out == ""
    assert "login" in err


def test_exit_code_4_when_logins_are_halted(environment, api, capsys, monkeypatch):
    environment.write_text(json.dumps({"login_failed": "wrong password"}))
    monkeypatch.setenv("PARRO_USERNAME", fakes.USERNAME)
    monkeypatch.setenv("PARRO_PASSWORD", fakes.CORRECT_PASSWORD)
    exit_code, _, err = run(api, capsys, "announcements")
    assert exit_code == 4 and "halted" in err
    assert api.requests == []


def test_exit_code_4_when_the_password_is_rejected(environment, api, capsys, monkeypatch):
    environment.unlink()
    monkeypatch.setenv("PARRO_USERNAME", fakes.USERNAME)
    monkeypatch.setenv("PARRO_PASSWORD", "wrong-password-SECRET")
    exit_code, _, err = run(api, capsys, "login")
    assert exit_code == 4
    assert "wrong-password-SECRET" not in err


def test_exit_code_1_for_api_errors(environment, api, capsys):
    exit_code, _, err = run(api, capsys, "get", "/event/1")
    assert exit_code == 1 and "EVENT_BAD_TYPE" in err


@pytest.mark.parametrize(
    "argv",
    [
        ["no-such-command"],
        ["announcement"],
        ["announcement", "not-a-number"],
        ["attachment", "1", "--all", "--attachment-id", "2"],
        ["get", "/x", "--param", "missing-equals"],
        ["get", "https://evil.example/"],
        ["children", "--limit", "0"],
        ["--login-method", "magic", "me"],
    ],
    ids=" ".join,
)
def test_exit_code_2_for_usage_errors(environment, api, capsys, argv):
    try:
        exit_code, _, _ = run(api, capsys, *argv)
    except SystemExit as stop:  # argparse exits by itself
        exit_code = int(stop.code or 0)
    assert exit_code == 2
    assert api.api_requests() == [] or argv[0] in ("children",)


def test_attachment_text_and_save(environment, api, capsys, tmp_path):
    api.calendar_event_ids.add(fakes.MUSEUM_TRIP_ID)
    event = load_sample("getEvent_calendar-7000000301.200.json")
    image_url = event["calendarItem"]["attachments"][0]["entries"][0]["url"]
    api.attachment_bodies[image_url] = ("image/jpeg", b"\xff\xd8 jpeg")
    exit_code, out, _ = run(
        api, capsys, "attachment", str(fakes.MUSEUM_TRIP_ID), "--save-to", str(tmp_path / "out")
    )
    assert exit_code == 0
    summary = json.loads(out)
    assert summary["saved_to"].endswith("Route.jpg")
    assert "base64" not in out, "the CLI never prints image data"
    exit_code, out, _ = run(api, capsys, "attachment", str(fakes.MUSEUM_TRIP_ID), "--text")
    assert exit_code == 0 and out.startswith("[nothing (an image")


def test_verbose_logs_to_stderr_without_secrets(environment, api, capsys):
    exit_code, out, err = run(api, capsys, "-vv", "children")
    assert exit_code == 0
    json.loads(out)
    for secret in (fakes.ACCESS_TOKEN, fakes.REFRESH_TOKEN):
        assert secret not in err


def test_help_reads_well(capsys):
    with pytest.raises(SystemExit) as stop:
        parro_cli.main(["--help"])
    assert stop.value.code == 0
    text = capsys.readouterr().out
    for expected in (
        "Client for Parro",
        "the school can see that",
        "mark-read",
        "announcements",
        "attachment",
        "exit codes",
    ):
        assert expected in text
    for command in parro_cli.HANDLERS:
        with pytest.raises(SystemExit):
            parro_cli.main([command, "--help"])
        assert "usage: parro-client " + command in capsys.readouterr().out


# ------------------------------------------------------------------- the program's name


def test_installed_and_launcher_names(monkeypatch, capsys):
    """Installed it is `parro-client`; the launchers (archives, source) say `parro_cli.py`."""
    with pytest.raises(SystemExit):
        parro_cli.main(["--help"])
    assert capsys.readouterr().out.startswith("usage: parro-client ")
    monkeypatch.setattr(naming, "_name", naming.FROM_SOURCE)
    with pytest.raises(SystemExit):
        parro_cli.main(["--help"])
    text = capsys.readouterr().out
    assert text.startswith("usage: parro_cli.py ") and "  parro_cli.py login --prompt" in text
    assert "`parro_cli.py login`" in authenticator.how_to_log_in()
    hint = rendering.hint(rendering.RenderOptions(), "announcements", "parro_announcements()")
    assert hint == "→ parro_cli.py announcements"


@pytest.mark.parametrize(
    ("launcher", "first_line"),
    [("parro_cli.py", "usage: parro_cli.py "), ("parro_mcp.py", None)],
)
def test_the_launchers_name_themselves(launcher, first_line, tmp_path):
    """Started as scripts, in a fresh process, from another folder."""
    project = Path(__file__).resolve().parent.parent
    # The whole environment (Windows needs SYSTEMROOT to start Python), with a private home.
    environment = {k: v for k, v in os.environ.items() if not k.startswith("PARRO_")}
    environment.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    environment["PARRO_TOKEN_FILE"] = str(tmp_path / "t.json")
    arguments = ["--help"] if first_line else ["call", "parro_auth_status"]
    result = subprocess.run(
        [sys.executable, str(project / launcher), *arguments],
        capture_output=True, text=True, cwd=tmp_path, env=environment, timeout=60, check=False,
    )  # fmt: skip
    if first_line:
        assert result.stdout.startswith(first_line)
    else:
        assert "`parro_cli.py login`" in result.stdout, "the MCP launcher's login hint"


# --------------------------------------------------------------- Windows-like consoles


def windows_console() -> io.TextIOWrapper:
    """A text stream like a Windows console: legacy code page, "\\n" written as "\\r\\n"."""
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="\r\n")


def test_ics_keeps_single_crlf_on_a_windows_console(monkeypatch, tmp_path):
    token_file = tmp_path / "tokens.json"
    token_file.write_text(json.dumps({"access_token": fakes.ACCESS_TOKEN, "expires_at": 9e12}))
    monkeypatch.setenv("PARRO_TOKEN_FILE", str(token_file))
    console = windows_console()
    monkeypatch.setattr(sys, "stdout", console)
    api = fakes.FakeParroApi(load_sample)
    exit_code = parro_cli.main(
        ["calendar", "--ics", "-"], make_client=lambda s: ParroClient(s, transport=api)
    )
    console.flush()
    written = console.buffer.getvalue()  # type: ignore[attr-defined]
    assert exit_code == 0 and written.startswith(b"BEGIN:VCALENDAR\r\n")
    assert b"\r\r\n" not in written and written.count(b"\r\n") == written.count(b"\n")


def test_utf8_output_lets_a_windows_console_print_the_markers(monkeypatch):
    console = windows_console()
    monkeypatch.setattr(sys, "stdout", console)
    monkeypatch.setattr(sys, "stderr", windows_console())
    with pytest.raises(UnicodeEncodeError):
        print("● 📌 🙋")  # what an installed command would hit without the switch
    parro_cli.use_utf8_output()
    print("● 📌 🙋")
    console.flush()
    assert "● 📌 🙋".encode() in console.buffer.getvalue()  # type: ignore[attr-defined]
