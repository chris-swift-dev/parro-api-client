"""Answering a calendar item's invitation (PLAN-rsvp, phase 3).

An answer is a statement in the user's name, and it can be changed but not removed, so these tests
are mostly about when nothing happens. The fake API accepts only the captured call, and answers 404
when the event id is used where the calendar item's own id belongs, as the real API does.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

import pytest

from parro import cli as parro_cli
from parro import mcp_server as parro_mcp
from parro import operations
from parro.api_client import ParroClient
from parro.errors import ConfigurationError
from parro.http import HttpRequest
from parro.settings import Settings
from tests import fakes
from tests.conftest import load_sample

EVENT = fakes.MUSEUM_TRIP_ID
ITEM = fakes.MUSEUM_TRIP_CALENDAR_ITEM
PATH = f"/calendaritem/{ITEM}/calendaritemrsvp"
ANSWER_POST = f"POST {PATH}"
BEFORE_THE_TRIP = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)
AFTER_THE_TRIP = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
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
    monkeypatch.setattr(operations, "current_time", lambda: BEFORE_THE_TRIP)


@pytest.fixture
def api() -> fakes.FakeParroApi:
    return fakes.FakeParroApi(load_sample)


@pytest.fixture
def accepted(api: fakes.FakeParroApi) -> fakes.FakeParroApi:
    api.rsvp_answers[ITEM] = "ACCEPT"
    return api


@pytest.fixture
def terminal(monkeypatch):
    class Terminal:
        answer: str | None = "y"
        questions: ClassVar[list[str]] = []

    Terminal.questions.clear()

    def fake_input(prompt: str) -> str:
        Terminal.questions.append(prompt)
        if Terminal.answer is None:
            raise EOFError
        return Terminal.answer

    monkeypatch.setattr(parro_cli, "someone_can_answer", lambda: True)
    monkeypatch.setattr("builtins.input", fake_input)
    return Terminal


def run(api, capsys, *argv: str) -> tuple[int, str, str]:
    try:
        code = parro_cli.main(list(argv), make_client=lambda s: ParroClient(s, transport=api))
    except SystemExit as stop:
        code = int(stop.code or 0)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def answer(api, capsys, word: str = "accept", *more: str) -> tuple[int, str, str]:
    return run(api, capsys, "rsvp", word, str(EVENT), *more)


def answered(api, capsys, word: str = "accept") -> tuple[int, str, str]:
    return answer(api, capsys, word, "--yes")


def body_of(api: fakes.FakeParroApi) -> dict[str, Any]:
    (request,) = [r for r in api.api_requests() if r.method == "POST"]
    result: dict[str, Any] = json.loads(request.body or b"")
    return result


# ------------------------------------------------------------------------ asking first


def test_it_shows_the_item_and_asks(api, capsys, terminal):
    code, out, _ = answer(api, capsys, "accept", "--format", "markdown")
    assert code == 0 and terminal.questions == ["Accept this invitation? [y/N] "]
    assert "# Accept this invitation" in out and "Excursie Natuurmuseum" in out
    assert "Groep 6 - meester Tom" in out, "the group, so you can tell similar items apart"
    assert "**Your answer now:** none yet" in out and "**New answer:** Accept" in out
    assert "You can change it later, but not remove it" in out
    assert "# Answered: Accept" in out
    assert api.writes() == [ANSWER_POST]


@pytest.mark.parametrize(
    ("word", "question"),
    [
        ("decline", "Decline this invitation? [y/N] "),
        ("tentative", "Answer tentative to this invitation? [y/N] "),
    ],
)
def test_each_answer_has_its_own_question(api, capsys, terminal, word, question):
    answer(api, capsys, word)
    assert terminal.questions == [question]


def test_the_tentative_preview_reads_as_a_sentence(api, capsys, terminal):
    _, out, _ = answer(api, capsys, "tentative", "--format", "markdown")
    assert "# Answer tentative to this invitation" in out and "# Tentative this" not in out


@pytest.mark.parametrize("reply", ["n", "", "yes please", None])
def test_anything_but_y_changes_nothing(api, capsys, terminal, reply):
    terminal.answer = reply
    code, out, _ = answer(api, capsys, "accept", "--format", "markdown")
    assert code == 0 and "Nothing was written." in out
    assert api.writes() == [] and api.rsvp_answers == {}


def test_without_a_terminal_and_without_yes_nothing_changes(api, capsys):
    code, _, err = answer(api, capsys)
    assert code == 2 and "nobody to ask" in err and api.writes() == []


def test_yes_skips_the_question(api, capsys):
    code, out, _ = answered(api, capsys)
    result = json.loads(out)
    assert code == 0 and result["done"] is True and result["changed"] is True
    assert result["answer"] == "ACCEPT" and result["previous"] is None


# ------------------------------------------------------------------------- the request


@pytest.mark.parametrize(
    ("word", "sent"), [("accept", "ACCEPT"), ("decline", "DECLINE"), ("tentative", "TENTATIVE")]
)
def test_the_body_is_what_the_web_app_sends(api, capsys, word, sent):
    code, _, _ = answered(api, capsys, word)
    assert code == 0 and api.rsvp_answers == {ITEM: sent}
    assert body_of(api) == {
        "items": [{"dtype": "calendar.RCalendarItemRSVPPrimer", "links": [], "rsvp": sent}]
    }


def test_the_path_has_the_calendar_items_own_id_not_the_event_id(api, capsys):
    answered(api, capsys)
    assert api.writes() == [ANSWER_POST] and ITEM != EVENT
    assert str(EVENT) not in api.writes()[0]


def test_a_wrong_word_is_a_usage_error(api, capsys):
    code, _, _ = run(api, capsys, "rsvp", "maybe", str(EVENT), "--yes")
    assert code == 2 and api.api_requests() == []


@pytest.mark.parametrize("value", ["UNKNOWN", "maybe", "", None, 1, True])
def test_only_the_three_answers_get_through(api, value):
    client = ParroClient(Settings.from_environment(), transport=api)
    with pytest.raises(ConfigurationError, match="accept, decline or tentative"):
        operations.prepare_rsvp(client, EVENT, value)
    assert api.api_requests() == []


@pytest.mark.parametrize("value", ["UNKNOWN", "accept", "", None])
def test_the_client_itself_refuses_any_other_answer(api, value):
    client = ParroClient(Settings.from_environment(), transport=api)
    with pytest.raises(ConfigurationError, match="ACCEPT, DECLINE or TENTATIVE"):
        client.answer_rsvp(ITEM, value)
    assert api.writes() == []


def test_the_fake_refuses_anything_but_the_captured_body(api):
    client = ParroClient(Settings.from_environment(), transport=api)
    headers = {"Authorization": f"Bearer {fakes.ACCESS_TOKEN}"}
    url = client.build_api_url(PATH)
    extra = {"dtype": "calendar.RCalendarItemRSVPPrimer", "links": [], "rsvp": "ACCEPT", "x": 1}
    for body in (b"", b"{}", json.dumps({"items": [extra]}).encode()):
        with pytest.raises(fakes.ForbiddenWrite):
            api.send(HttpRequest("POST", url, headers, body))


# ---------------------------------------------------------------------------- refusals


def test_an_item_that_asks_for_no_answer_is_refused(api, capsys):
    api.calendar_item_overrides = {"rsvpRequired": False}
    code, _, err = answered(api, capsys)
    assert code == 2 and "does not ask for an answer" in err and api.writes() == []


def test_a_cancelled_item_is_refused(api, capsys):
    api.event_overrides = {"cancelled": True}
    code, _, err = answered(api, capsys)
    assert code == 2 and "cancelled" in err and api.writes() == []


def test_a_past_item_is_refused(api, capsys, monkeypatch):
    monkeypatch.setattr(operations, "current_time", lambda: AFTER_THE_TRIP)
    code, _, err = answered(api, capsys)
    assert code == 2 and "in the past" in err and api.writes() == []


# ---------------------------------------------------------------- an answer you already gave


def test_the_same_answer_again_sends_nothing_and_asks_nothing(accepted, capsys, terminal):
    code, out, _ = answer(accepted, capsys, "accept", "--format", "markdown")
    assert code == 0 and "# Already answered: Accept" in out and "Nothing was sent." in out
    assert terminal.questions == [] and accepted.writes() == []


def test_the_same_answer_again_says_nothing_changed(accepted, capsys):
    _, out, _ = answered(accepted, capsys)
    result = json.loads(out)
    assert result["done"] is True and result["changed"] is False


def test_a_second_run_finds_the_first_answer(api, capsys):
    answered(api, capsys)
    answered(api, capsys)
    assert api.writes() == [ANSWER_POST]


def test_changing_an_answer_shows_old_and_new(accepted, capsys, terminal):
    code, out, _ = answer(accepted, capsys, "decline", "--format", "markdown")
    assert code == 0 and "**Your answer now:** Accept" in out and "**New answer:** Decline" in out
    assert "This replaces your earlier answer: Accept." in out
    assert accepted.rsvp_answers == {ITEM: "DECLINE"}


def test_unknown_counts_as_no_answer_yet(api):
    api.event_overrides = {"rsvp": "UNKNOWN"}
    client = ParroClient(Settings.from_environment(), transport=api)
    prepared = operations.prepare_rsvp(client, EVENT, "accept")
    assert prepared["previous"] is None and prepared["unchanged"] is False


# -------------------------------------------------------------------------- never twice


@pytest.mark.parametrize("status", [500, 502, 503])
def test_a_server_error_is_not_repeated(api, capsys, status):
    api.send_outcomes = [status]
    code, _, err = answered(api, capsys)
    assert code == 1 and "may or may not have gone through" in err and len(api.writes()) == 1


def test_a_lost_answer_is_not_repeated(api, capsys):
    api.send_outcomes = ["lost"]
    code, _, err = answered(api, capsys)
    assert code == 1 and "may or may not have gone through" in err and len(api.writes()) == 1


def test_running_again_after_a_lost_answer_adds_nothing(api, capsys):
    api.send_outcomes = ["lost"]
    answered(api, capsys)
    code, out, _ = answered(api, capsys)
    assert code == 0 and json.loads(out)["changed"] is False and len(api.writes()) == 1


@pytest.mark.parametrize("status", [400, 403])
def test_a_refusal_by_the_api_does_not_claim_an_unknown_outcome(api, capsys, status):
    api.send_outcomes = [status]
    code, _, err = answered(api, capsys)
    assert code == 1 and "may or may not" not in err and len(api.writes()) == 1


def test_after_a_401_it_refreshes_and_answers_once(api, capsys):
    api.unauthorized_tokens.add(fakes.ACCESS_TOKEN)
    code, _, _ = answered(api, capsys)
    assert code == 0 and api.rsvp_answers == {ITEM: "ACCEPT"}
    assert api.idp.credential_posts() == []


def test_a_201_without_readable_json_still_counts(api, capsys):
    api.send_outcomes = ["broken"]
    code, out, _ = answered(api, capsys)
    assert code == 0 and json.loads(out)["done"] is True


# ------------------------------------------------------------------------ reading it back


def agenda(api, capsys) -> str:
    _, out, _ = run(api, capsys, "calendar", "--limit", "20", "--format", "markdown")
    return out


def test_the_agenda_shows_your_answer_instead_of_rsvp_needed(api, capsys):
    before = next(line for line in agenda(api, capsys).split("\n") if f"#{EVENT}" in line)
    assert "RSVP needed" in before
    answered(api, capsys, "tentative")
    after = next(line for line in agenda(api, capsys).split("\n") if f"#{EVENT}" in line)
    assert "RSVP: tentative" in after and "RSVP needed" not in after


def test_no_command_reads_the_list_of_respondents(api, capsys):
    answered(api, capsys)
    agenda(api, capsys)
    run(api, capsys, "calendar", "--details", "--limit", "20", "--format", "markdown")
    run(api, capsys, "overview", "--format", "markdown")
    assert [
        r for r in api.api_requests() if r.method == "GET" and "calendaritemrsvp" in r.url
    ] == []


# ------------------------------------------------------------------------------ MCP tool


TOOL = "parro_rsvp"
SWITCH = "PARRO_ALLOW_RSVP"
RESPONDENTS = f"/calendaritem/{ITEM}/calendaritemrsvp"


@pytest.fixture
def server(api) -> parro_mcp.McpServer:
    return parro_mcp.McpServer(make_client=lambda s: ParroClient(s, transport=api))


@pytest.fixture
def switched_on(monkeypatch) -> None:
    monkeypatch.setenv(SWITCH, "1")


def tool_names(server: parro_mcp.McpServer) -> list[str]:
    return [t["name"] for t in server.list_tools() if t["name"] == TOOL]


def call(server: parro_mcp.McpServer, **arguments: Any) -> dict[str, Any]:
    outcome = server.call_tool(TOOL, {"event_id": EVENT, "answer": "accept", **arguments})
    text: str = outcome.content[0]["text"]
    assert not outcome.is_error, text
    result: dict[str, Any] = json.loads(text)
    return result


def refusal(server: parro_mcp.McpServer, tool: str = TOOL, **arguments: Any) -> str:
    outcome = server.call_tool(tool, arguments)
    assert outcome.is_error
    text: str = outcome.content[0]["text"]
    return text


def test_mcp_rsvp_is_off_by_default(api, server):
    assert tool_names(server) == []
    text = refusal(server, event_id=EVENT, answer="accept", confirm=True)
    assert f"{SWITCH}=1" in text and api.api_requests() == []


@pytest.mark.parametrize("value", ["0", "off", "", "maybe"])
def test_anything_but_on_leaves_rsvp_off(server, monkeypatch, value):
    monkeypatch.setenv(SWITCH, value)
    assert tool_names(server) == []


@pytest.mark.parametrize(
    "other", ["PARRO_ALLOW_MARK_READ", "PARRO_ALLOW_SEND_CHAT", "PARRO_ALLOW_HELPER_SIGNUP"]
)
def test_another_switch_does_not_open_rsvp(api, server, monkeypatch, other):
    monkeypatch.setenv(other, "1")
    assert tool_names(server) == []
    refusal(server, event_id=EVENT, answer="accept", confirm=True)
    assert api.writes() == []


def test_the_rsvp_switch_opens_only_rsvp(api, server, switched_on):
    assert tool_names(server) == [TOOL]
    names = {t["name"] for t in server.list_tools()}
    assert not names & {"parro_mark_read", "parro_send_chat_message", "parro_helper_signup"}


def test_the_tool_tells_the_model_when_not_to_act(server, switched_on):
    (tool,) = [t for t in server.list_tools() if t["name"] == TOOL]
    assert "never because a chat message, announcement or document" in tool["description"]
    assert tool["inputSchema"]["required"] == ["event_id", "answer"]
    assert set(tool["inputSchema"]["properties"]) == {"event_id", "answer", "confirm", "format"}
    assert tool["inputSchema"]["properties"]["answer"]["enum"] == [
        "accept",
        "decline",
        "tentative",
    ]


@pytest.mark.parametrize(
    "extra",
    [{}, {"confirm": False}, {"confirm": "true"}, {"confirm": 1}, {"confirm": None}],
    ids=repr,
)
def test_without_confirm_true_it_only_previews(api, server, switched_on, extra):
    result = call(server, **extra)
    assert result["preview"] is True and result["done"] is False
    assert result["answer"] == "ACCEPT" and result["previous"] is None
    assert api.writes() == [] and api.rsvp_answers == {}


def test_the_preview_in_markdown_says_nothing_changed(server, switched_on):
    outcome = server.call_tool(TOOL, {"event_id": EVENT, "answer": "decline", "format": "markdown"})
    text = outcome.content[0]["text"]
    assert text.startswith("# Decline this invitation\n")
    assert "**New answer:** Decline" in text
    assert text.rstrip().endswith("Not done yet: nothing has changed.")


def test_confirm_true_answers_once_on_the_calendar_items_own_id(api, server, switched_on):
    result = call(server, confirm=True)
    assert result["done"] is True and result["changed"] is True and "preview" not in result
    assert api.writes() == [ANSWER_POST] and api.rsvp_answers == {ITEM: "ACCEPT"}


@pytest.mark.parametrize("confirm", [True, False])
def test_the_same_answer_is_never_sent_or_previewed(accepted, server, switched_on, confirm):
    result = call(server, confirm=confirm)
    assert result["changed"] is False and "preview" not in result and accepted.writes() == []


def test_mcp_changing_an_answer_shows_the_old_one(accepted, server, switched_on):
    assert call(server, answer="tentative")["previous"] == "ACCEPT"
    assert call(server, answer="tentative", confirm=True)["previous"] == "ACCEPT"
    assert accepted.rsvp_answers == {ITEM: "TENTATIVE"}


@pytest.mark.parametrize("value", ["UNKNOWN", "maybe", "", None, 1, True])
def test_mcp_only_the_three_answers_get_through(api, server, switched_on, value):
    text = refusal(server, event_id=EVENT, answer=value, confirm=True)
    assert "accept, decline or tentative" in text and api.writes() == []


def test_mcp_refusals_stop_it_also_for_the_preview(api, server, switched_on):
    api.calendar_item_overrides = {"rsvpRequired": False}
    assert "does not ask" in refusal(server, event_id=EVENT, answer="accept")
    assert api.writes() == []


def test_mcp_reports_an_unknown_outcome_and_does_not_repeat(api, server, switched_on):
    api.send_outcomes = ["lost"]
    text = refusal(server, event_id=EVENT, answer="accept", confirm=True)
    assert "may or may not have gone through" in text and len(api.writes()) == 1


def test_only_the_one_tool_can_answer():
    source = Path(parro_mcp.__file__).read_text(encoding="utf-8")
    assert source.count("answer_or_preview_rsvp") == 1
    assert "apply_rsvp" not in source and "answer_rsvp(" not in source


# ------------------------------------------------------------- other people's answers stay out


SPELLINGS = [
    RESPONDENTS,
    f"{RESPONDENTS}/",
    f"{RESPONDENTS}/8600000001",
    f"{RESPONDENTS}?x=1",
    f"{RESPONDENTS}#x",
    f"{RESPONDENTS};x=1",
    f"/rest/v2{RESPONDENTS}",
    f"calendaritem/{ITEM}/calendaritemrsvp",
    f"  {RESPONDENTS}  ",
    f"/calendaritem/{ITEM}/CalendarItemRSVP",
    f"/calendaritem/{ITEM}/calendaritem%72svp",
    f"/calendaritem/{ITEM}/calendaritem%2572svp",
    f"/calendaritem/{ITEM}/%63alendaritemrsvp",
    f"/calendaritem/{ITEM}/x/../calendaritemrsvp",
    f"/calendaritem/{ITEM}/./calendaritemrsvp",
    f"\\calendaritem\\{ITEM}\\calendaritemrsvp",
    f"/calendaritem/{ITEM}/calendaritem\trsvp",
]


@pytest.mark.parametrize("path", SPELLINGS, ids=repr)
def test_parro_get_refuses_the_list_of_respondents(api, server, path):
    assert "other people's names" in refusal(server, "parro_get", path=path)
    assert api.requests == [], "the request is not even sent"


@pytest.mark.parametrize("path", SPELLINGS, ids=repr)
def test_parro_attachment_refuses_the_list_of_respondents(api, server, path):
    url = f"https://rest-v2.parro.com/rest/v2/{path.lstrip('/')}"
    assert "other people's names" in refusal(server, "parro_attachment", url=url)
    assert api.requests == [], "the login is not sent to it"


def test_the_block_does_not_depend_on_the_rsvp_switch(api, server, switched_on):
    assert "other people's names" in refusal(server, "parro_get", path=RESPONDENTS)
    assert api.requests == []


def test_parro_get_still_reads_the_calendar_item(api, server):
    outcome = server.call_tool("parro_get", {"path": f"/calendaritem/{ITEM}"})
    assert "other people's names" not in outcome.content[0]["text"]
    assert api.api_requests() != []


def test_the_cli_get_is_not_blocked(api, capsys):
    run(api, capsys, "get", RESPONDENTS)
    assert [r for r in api.api_requests() if r.url.endswith(RESPONDENTS)], (
        "you asked for it yourself"
    )
