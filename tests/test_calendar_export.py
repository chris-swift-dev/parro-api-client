"""Calendar export: Parro's own subscription link (calendar-link) and our .ics file."""

import json
import logging
import os
import stat
import time
from typing import Any

import pytest

from parro import cli as parro_cli
from parro import icalendar
from parro import mcp_server as parro_mcp
from parro.api_client import ParroClient
from tests import fakes
from tests.conftest import load_sample

LINK_TOKEN = "00000000-0000-4000-8000-0000000000aa"


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
    return tmp_path


def run(capsys, *argv: str, api: fakes.FakeParroApi | None = None) -> tuple[int, str, str]:
    api = api or fakes.FakeParroApi(load_sample)
    exit_code = parro_cli.main(list(argv), make_client=lambda s: ParroClient(s, transport=api))
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


# -------------------------------------------------------------------------- calendar-link


def test_calendar_link_from_the_sync_endpoint(environment, capsys):
    exit_code, out, _ = run(capsys, "calendar-link", "--format", "json")
    result = json.loads(out)
    assert exit_code == 0
    assert result["calendar_link"].startswith("https://calendar.parro.com/ical/2000000001/")
    assert "anyone who has it" in result["warning"]
    _, markdown, _ = run(capsys, "calendar-link", "--format", "markdown")
    assert markdown.startswith("# Your Parro calendar link") and LINK_TOKEN in markdown


def test_calendar_link_is_never_logged(environment, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    api = fakes.FakeParroApi(load_sample)
    run(capsys, "-vv", "calendar-link", "--format", "json", api=api)
    sync_request = next(r for r in api.requests if r.url.endswith("/calendar/sync"))
    assert sync_request.log_label == "GET /rest/v2/calendar/sync", "what the transport logs"
    assert LINK_TOKEN not in caplog.text


def test_no_link_gives_a_clear_error(environment, capsys):
    def without_link(name: str) -> Any:
        if name == "getCalendarSync.200.json":
            return {"dtype": "Strings", "strings": []}
        return load_sample(name)

    exit_code, out, err = run(capsys, "calendar-link", api=fakes.FakeParroApi(without_link))
    assert exit_code == 1 and out == ""
    assert "no calendar link" in err and "--ics" in err


def test_mcp_calendar_link_tool(environment):
    api = fakes.FakeParroApi(load_sample)
    server = parro_mcp.McpServer(make_client=lambda s: ParroClient(s, transport=api))
    result = server.call_tool("parro_calendar_link", {})
    assert not result.is_error
    assert json.loads(result.content[0]["text"])["calendar_link"].endswith(
        LINK_TOKEN[-2:] + "?noCache=00000000-0000-4000-8000-0000000000bb"
    )
    tool = next(t for t in parro_mcp.TOOL_DEFINITIONS if t["name"] == "parro_calendar_link")
    assert "secret" in tool["description"]


# ---------------------------------------------------------------------------- .ics export


def unfold(text: str) -> list[str]:
    """RFC 5545 §3.1: join continuation lines (CRLF + space) back into content lines."""
    return text.replace("\r\n ", "").split("\r\n")[:-1]


def events(text: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT" and current is not None:
            found.append(current)
            current = None
        elif current is not None:
            name, _, value = line.partition(":")
            current[name] = value
    return found


def test_ics_to_standard_output_follows_the_standard(environment, capsys):
    exit_code, out, _ = run(capsys, "calendar", "--ics", "-", "--details")
    assert exit_code == 0
    assert out.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n") and out.endswith(
        "END:VCALENDAR\r\n"
    )
    raw_lines = out.split("\r\n")[:-1]
    assert all(len(line.encode("utf-8")) <= 75 for line in raw_lines), "folded at 75 octets"
    assert "\n" not in out.replace("\r\n", ""), "only CRLF line endings"
    by_title = {e["SUMMARY"]: e for e in events(out)}
    assert len(events(out)) == len(by_title) == 7, "the seven upcoming items, each once"

    st_martin = by_title["Sint-Maartenviering"]
    assert st_martin["UID"] == "parro-calendaritem-7000000151@parro-api-client"
    assert st_martin["DTSTART"] == "20261111T163000Z", "17:30 +01:00 in UTC"
    assert st_martin["DTEND"] == "20261111T180000Z"
    assert st_martin["LOCATION"] == "Schoolplein"
    assert st_martin["SUMMARY"] == "Sint-Maartenviering"
    assert st_martin["CATEGORIES"] == "Basisschool De Linde"
    assert st_martin["DTSTAMP"] == "20261105T110000Z", "the (frozen) export time, in UTC"

    museum = by_title["Excursie Natuurmuseum"]
    assert museum["DTSTART;VALUE=DATE"] == "20261112"
    assert museum["DTEND;VALUE=DATE"] == "20261113", "all day: DTEND is the next day"
    assert "Reply needed in Parro." in museum["DESCRIPTION"]
    assert (
        "Helpers wanted\\, sign up in Parro.\\nRijden naar het museum: 1 of 2 signed up."
        in museum["DESCRIPTION"]
    ), "RFC 5545 escapes the comma and the line break"
    assert museum["LOCATION"] == "Natuurmuseum Voorbeeldstad"

    christmas = by_title["Kerstvakantie"]  # 5 per-day entries in the API: one event here
    assert christmas["DTSTART;VALUE=DATE"] == "20261221"
    assert christmas["DTEND;VALUE=DATE"] == "20261226"
    projects = by_title["Projectweken: de ruimte"]  # half over on "today", still listed
    assert projects["DTSTART;VALUE=DATE"] == "20261102"
    assert projects["DTEND;VALUE=DATE"] == "20261114"


def test_ics_file_is_private_and_the_cli_reports_it(environment, capsys):
    target = environment / "export" / "parro.ics"
    exit_code, out, _ = run(capsys, "calendar", "--ics", str(target), "--format", "json")
    report = json.loads(out)
    assert exit_code == 0 and report == {"ics_file": str(target), "events": 7, "period": "upcoming"}
    assert len(events(target.read_bytes().decode("utf-8"))) == 7  # bytes: keep the CRLFs
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    _, markdown, _ = run(capsys, "calendar", "--ics", str(target), "--format", "markdown")
    assert markdown.startswith("# Calendar exported") and "calendar-link" in markdown


def test_ics_of_past_items_and_usage_errors(environment, capsys):
    _, out, _ = run(capsys, "calendar", "--ics", "-", "--past")
    assert {e["SUMMARY"] for e in events(out)} == {"Bezoek bibliotheek", "Eerste schooldag"}
    exit_code, _, err = run(capsys, "calendar", "--ics", "-", "--raw")
    assert exit_code == 2 and "--ics" in err


def test_ics_uids_are_stable_so_a_new_export_updates_events(environment, capsys):
    first = {e["UID"] for e in events(run(capsys, "calendar", "--ics", "-")[1])}
    second = {e["UID"] for e in events(run(capsys, "calendar", "--ics", "-")[1])}
    assert first == second


def test_escaping_and_folding():
    assert icalendar.escape("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"
    long_line = "DESCRIPTION:" + "é" * 100  # 2 octets each: folding must not split them
    folded = icalendar.fold(long_line)
    assert folded.replace("\r\n ", "") == long_line
    for piece in folded.split("\r\n"):
        assert len(piece.encode("utf-8")) <= 75
        piece.encode("utf-8").decode("utf-8")  # no broken characters
