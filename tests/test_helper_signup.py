"""Signing up and withdrawing as a helper (PLAN-helper-signup, phase 3).

A sign-up is a promise in the user's name, so these tests are mostly about when nothing happens.
The fake API accepts only the captured calls, and answers 404 when the event id is used where the
calendar item's own id belongs, as the real API does.
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, ClassVar

import pytest

from parro import cli as parro_cli
from parro import operations
from parro.api_client import ParroClient
from parro.errors import ConfigurationError
from parro.http import HttpRequest
from parro.settings import Settings
from tests import fakes
from tests.conftest import load_sample

EVENT = fakes.MUSEUM_TRIP_ID
ITEM = fakes.MUSEUM_TRIP_CALENDAR_ITEM
SLOT = fakes.MUSEUM_TRIP_SLOT  # 2 wanted, 1 taken
ADD_PATH = f"/calendaritem/{ITEM}/resource/{SLOT}/commitment/"
BEFORE_THE_TRIP = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)
AFTER_THE_TRIP = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
MY_COMMITMENT = 8500000099


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
def signed_up(api: fakes.FakeParroApi) -> fakes.FakeParroApi:
    api.commitments[SLOT] = [{"id": MY_COMMITMENT, "amount": 1}]
    return api


def run(api, capsys, *argv: str) -> tuple[int, str, str]:
    try:
        code = parro_cli.main(list(argv), make_client=lambda s: ParroClient(s, transport=api))
    except SystemExit as stop:
        code = int(stop.code or 0)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def signup(api, capsys, *more: str) -> tuple[int, str, str]:
    return run(api, capsys, "helper", "signup", str(EVENT), "--yes", *more)


def withdraw(api, capsys, *more: str) -> tuple[int, str, str]:
    return run(api, capsys, "helper", "withdraw", str(EVENT), "--yes", *more)


def slot(slot_id: int, title: str, wanted: int | None = 5, taken: int = 0) -> dict[str, Any]:
    kind = "calendar.RCalendarItemVolunteerResource"
    return {
        "dtype": kind,
        "links": [{"id": slot_id, "rel": "self", "type": kind}],
        "title": title,
        "type": "VOLUNTEER",
        "amount": wanted,
        "amountCommitted": taken,
        "commitedByMe": 0,
        "commitments": [],
    }


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


# ------------------------------------------------------------------------- asking first


def test_at_a_terminal_it_shows_the_slot_and_asks(api, capsys, terminal):
    code, out, _ = run(api, capsys, "helper", "signup", str(EVENT), "--format", "markdown")
    assert code == 0 and terminal.questions == ["Sign up for this slot? [y/N] "]
    assert out.startswith("# Sign up: Rijden naar het museum\n")
    assert f"Excursie Natuurmuseum · Thu 12 Nov 2026 · #{EVENT}" in out
    assert f"Rijden naar het museum · #{SLOT} · 1 of 2 places taken" in out
    assert "**Your count:** 1" in out and "The school will see your name" in out
    assert "# Signed up: Rijden naar het museum" in out
    assert api.writes() == [f"POST {ADD_PATH}"]


def test_withdrawing_asks_too(signed_up, capsys, terminal):
    code, out, _ = run(signed_up, capsys, "helper", "withdraw", str(EVENT), "--format", "markdown")
    assert code == 0 and terminal.questions == ["Withdraw from this slot? [y/N] "]
    assert out.startswith("# Withdraw: Rijden naar het museum\n")
    assert "# Withdrawn: Rijden naar het museum" in out


@pytest.mark.parametrize("answer", ["n", "", "yes", None], ids=repr)
def test_anything_but_y_changes_nothing(api, capsys, terminal, answer):
    terminal.answer = answer
    code, out, _ = run(api, capsys, "helper", "signup", str(EVENT), "--format", "markdown")
    assert code == 0 and out.rstrip().endswith("Nothing was written.")
    assert api.writes() == []


def test_without_a_person_to_ask_nothing_changes(api, capsys):
    code, out, err = run(api, capsys, "helper", "signup", str(EVENT))
    assert code == 2 and out == "" and "Nothing changed" in err and "--yes" in err
    assert api.writes() == []


def test_yes_does_not_ask(api, capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("asked"))
    code, out, _ = signup(api, capsys)
    result = json.loads(out)
    assert code == 0 and result["done"] is True and result["action"] == "signup"
    assert result["count"] == 1 and result["slot_id"] == SLOT
    assert result["commitment_id"] == 8500000001


# ------------------------------------------------------------------------- the requests


def test_the_signup_is_the_captured_request(api, capsys):
    signup(api, capsys)
    (request,) = [r for r in api.api_requests() if r.method != "GET"]
    assert request.method == "POST"
    assert request.url == f"{fakes.API}/rest/v2{ADD_PATH}", "with the trailing slash"
    assert request.body == (
        b'{"items":[{"dtype":"calendar.RCalendarItemResourceCommitmentPrimer",'
        b'"links":[],"amount":1}]}'
    )
    assert request.headers["parro-authorization-role"].startswith("GUARDIAN:")
    assert request.follow_redirects is False


def test_the_withdrawal_is_the_captured_request(signed_up, capsys):
    code, _, _ = withdraw(signed_up, capsys)
    (request,) = [r for r in signed_up.api_requests() if r.method != "GET"]
    assert code == 0 and request.method == "DELETE" and request.body is None
    assert request.url == f"{fakes.API}/rest/v2{ADD_PATH}{MY_COMMITMENT}"
    assert signed_up.commitments[SLOT] == []


def test_the_event_id_never_goes_in_the_path(api, capsys):
    assert EVENT != ITEM
    signup(api, capsys)
    assert all(f"/calendaritem/{EVENT}" not in r.url for r in api.api_requests())


def test_the_fake_answers_404_for_the_event_id(api):
    headers = {"Authorization": f"Bearer {fakes.ACCESS_TOKEN}"}
    url = f"{fakes.API}/rest/v2/calendaritem/{EVENT}/resource/{SLOT}/commitment/"
    body = (
        b'{"items":[{"dtype":"calendar.RCalendarItemResourceCommitmentPrimer",'
        b'"links":[],"amount":1}]}'
    )
    assert api.send(HttpRequest("POST", url, headers, body)).status == 404


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", ADD_PATH.rstrip("/"), b"{}"),  # no trailing slash, no captured body
        ("POST", ADD_PATH, b"{}"),
        ("POST", ADD_PATH, b'{"items":[{"dtype":"x","links":[],"amount":1}]}'),
        (
            "POST",
            ADD_PATH,
            b'{"items":[{"dtype":"calendar.RCalendarItemResourceCommitmentPrimer",'
            b'"links":[],"amount":0}]}',
        ),
        ("PUT", f"{ADD_PATH}1", b""),
        ("DELETE", ADD_PATH, None),
        ("DELETE", f"{ADD_PATH}1", b"{}"),
        ("DELETE", f"/calendaritem/{ITEM}", None),
    ],
)
def test_the_fake_refuses_every_other_write(api, method, path, body):
    headers = {"Authorization": f"Bearer {fakes.ACCESS_TOKEN}"}
    with pytest.raises(fakes.ForbiddenWrite):
        api.send(HttpRequest(method, f"{fakes.API}/rest/v2{path}", headers, body))


@pytest.mark.parametrize(
    "arguments", [(0, SLOT, 1), (ITEM, -1, 1), (ITEM, SLOT, 0), (ITEM, SLOT, True), ("1", SLOT, 1)]
)
def test_the_client_refuses_bad_numbers_before_sending(api, arguments):
    client = ParroClient(Settings(role_override="GUARDIAN:1"), transport=api)
    client.token_store.save_token_response({"access_token": fakes.ACCESS_TOKEN})
    with pytest.raises(ConfigurationError):
        client.add_helper_commitment(*arguments)
    with pytest.raises(ConfigurationError):
        client.remove_helper_commitment(*arguments)
    assert api.api_requests() == []


# ---------------------------------------------------------------------------- the count


def test_a_count_above_one_reaches_the_body(api, capsys):
    api.calendar_item_overrides = {"resources": [slot(SLOT, "Kinderen meenemen", 8, 2)]}
    code, out, _ = signup(api, capsys, "--count", "3")
    assert code == 0 and json.loads(out)["count"] == 3
    (request,) = [r for r in api.api_requests() if r.method == "POST"]
    assert json.loads(request.body)["items"][0]["amount"] == 3
    assert api.commitments[SLOT][0]["amount"] == 3


def test_a_slot_without_a_limit_takes_any_count(api, capsys):
    api.calendar_item_overrides = {"resources": [slot(SLOT, "Open", None, 7)]}
    code, _, _ = signup(api, capsys, "--count", "20")
    assert code == 0 and api.commitments[SLOT][0]["amount"] == 20


def test_a_count_that_does_not_fit_is_refused(api, capsys):
    code, _, err = signup(api, capsys, "--count", "2")
    assert code == 2 and "only 1 of 2 places are left" in err and api.writes() == []


@pytest.mark.parametrize("count", ["0", "-1"])
def test_a_count_below_one_is_refused(api, capsys, count):
    code, _, err = signup(api, capsys, f"--count={count}")
    assert code == 2 and "from 1 up" in err and api.writes() == []


def test_a_count_that_is_no_number_is_a_usage_error(api, capsys):
    code, _, _ = signup(api, capsys, "--count", "drie")
    assert code == 2 and api.api_requests() == []


def test_withdraw_takes_no_count(signed_up, capsys):
    code, _, err = withdraw(signed_up, capsys, "--count", "2")
    assert code == 2 and "--count is only for signup" in err and signed_up.writes() == []


# ------------------------------------------------------------------------------ refusals


def test_signing_up_twice_is_refused(api, capsys):
    api.calendar_item_overrides = {"resources": [slot(SLOT, "Rijden", 5, 1)]}
    assert signup(api, capsys)[0] == 0
    code, _, err = signup(api, capsys)
    assert code == 2 and "already signed up" in err and "withdraw and sign up again" in err
    assert len(api.writes()) == 1


def test_a_full_slot_is_refused(api, capsys):
    api.calendar_item_overrides = {"resources": [slot(SLOT, "Rijden", 2, 2)]}
    code, _, err = signup(api, capsys)
    assert code == 2 and "full" in err and api.writes() == []


def test_a_past_item_is_refused(signed_up, capsys, monkeypatch):
    monkeypatch.setattr(operations, "current_time", lambda: AFTER_THE_TRIP)
    code, _, err = signup(signed_up, capsys)
    assert code == 2 and "past" in err
    code, _, err = withdraw(signed_up, capsys)
    assert code == 2 and "past" in err and signed_up.writes() == []


def test_on_the_day_itself_it_still_works(api, capsys, monkeypatch):
    on_the_day = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(operations, "current_time", lambda: on_the_day)
    assert signup(api, capsys)[0] == 0


def test_an_item_without_helper_slots_is_refused(api, capsys):
    code, _, err = run(api, capsys, "helper", "signup", "7000000101", "--yes")
    assert code == 2 and "asks for no helpers" in err and api.writes() == []


def test_several_slots_need_a_choice(api, capsys):
    two = [slot(SLOT, "Rijden"), slot(7000000362, "Tassen dragen")]
    api.calendar_item_overrides = {"resources": two}
    code, _, err = signup(api, capsys)
    assert code == 2 and f"Rijden (#{SLOT})" in err and "Tassen dragen (#7000000362)" in err
    assert api.writes() == []
    code, _, _ = signup(api, capsys, "--slot", "7000000362")
    assert code == 0 and api.commitments[7000000362][0]["amount"] == 1


def test_an_unknown_slot_is_refused(api, capsys):
    code, _, err = signup(api, capsys, "--slot", "123")
    assert code == 2 and "choose a slot" in err and api.writes() == []


def test_withdrawing_without_a_signup_is_refused(api, capsys):
    code, _, err = withdraw(api, capsys)
    assert code == 2 and "not signed up" in err and api.writes() == []


def test_withdrawing_twice_is_refused(signed_up, capsys):
    assert withdraw(signed_up, capsys)[0] == 0
    code, _, err = withdraw(signed_up, capsys)
    assert code == 2 and "not signed up" in err and len(signed_up.writes()) == 1


def test_several_commitments_on_one_slot_are_left_alone(api, capsys):
    api.commitments[SLOT] = [{"id": 1000001, "amount": 1}, {"id": 1000002, "amount": 1}]
    code, _, err = withdraw(api, capsys)
    assert code == 2 and "2 commitments" in err and api.writes() == []


# ------------------------------------------------------------------ never done twice


def test_after_a_lost_answer_it_is_not_repeated(api, capsys):
    api.send_outcomes = ["lost"]
    code, out, err = signup(api, capsys)
    assert code == 1 and out == "" and "may or may not have gone through" in err
    assert len(api.writes()) == 1


def test_running_it_again_after_a_lost_answer_is_safe(api, capsys):
    api.calendar_item_overrides = {"resources": [slot(SLOT, "Rijden")]}
    api.send_outcomes = ["lost"]
    signup(api, capsys)
    code, _, err = signup(api, capsys)
    assert code == 2 and "already signed up" in err
    assert len(api.writes()) == 1, "the first one arrived, so nothing is added"


def test_a_lost_withdrawal_is_not_repeated(signed_up, capsys):
    signed_up.send_outcomes = ["lost"]
    code, _, err = withdraw(signed_up, capsys)
    assert code == 1 and "may or may not have gone through" in err and len(signed_up.writes()) == 1


@pytest.mark.parametrize("status", [500, 503])
def test_after_a_server_error_it_is_not_repeated(api, capsys, status):
    api.send_outcomes = [status]
    code, _, err = signup(api, capsys)
    assert code == 1 and "may or may not have gone through" in err and len(api.writes()) == 1


@pytest.mark.parametrize("status", [400, 403, 409])
def test_a_clear_refusal_says_so(api, capsys, status):
    api.send_outcomes = [status]
    code, _, err = signup(api, capsys)
    assert code == 1 and str(status) in err and "may or may not" not in err
    assert api.commitments.get(SLOT) in (None, [])


def test_after_a_401_it_refreshes_and_signs_up_once(api, capsys):
    api.unauthorized_tokens.add(fakes.ACCESS_TOKEN)
    code, _, _ = signup(api, capsys)
    assert code == 0 and len(api.commitments[SLOT]) == 1
    assert api.idp.credential_posts() == []


def test_a_201_without_readable_json_still_counts(api, capsys):
    api.send_outcomes = ["broken"]
    code, out, _ = signup(api, capsys)
    result = json.loads(out)
    assert code == 0 and result["done"] is True and result["commitment_id"] is None


# ------------------------------------------------------------------------ reading it back


def test_the_agenda_shows_the_slot_id_and_your_signup(api, capsys):
    _, out, _ = run(api, capsys, "calendar", "--details", "--limit", "20", "--format", "markdown")
    assert f"Rijden naar het museum: 1 of 2 signed up · #{SLOT}" in out
    signup(api, capsys)
    _, out, _ = run(api, capsys, "calendar", "--details", "--limit", "20", "--format", "markdown")
    assert f"Rijden naar het museum: 2 of 2 signed up, including you · #{SLOT}" in out
