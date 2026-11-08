"""Sending a chat message (PLAN-send-chat-message, phase 2).

Real people receive it, so these tests are mostly about when nothing goes out: without a
confirmation, to a closed chat, or a second time after an unclear outcome. The fake API accepts
only the exact body of the capture and raises ForbiddenWrite for anything else.
"""

import io
import json
import logging
import os
import time
from pathlib import Path

import pytest

from parro import cli as parro_cli
from parro import mcp_server as parro_mcp
from parro.api_client import ParroClient
from parro.errors import ConfigurationError
from parro.http import HttpRequest
from parro.settings import Settings
from tests import fakes
from tests.conftest import load_sample

CHAT = 8000000001  # active; Tom (teacher), Sanne (you), Joris, Fatima; Kees has left
ARCHIVED_CHAT = 8000000002
CHAT_MEMBERSHIP_ID = 8000000501  # the chat's first link (`koppeling`): 403
TEXT = "Ik rijd graag mee naar het museum"


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


@pytest.fixture
def api() -> fakes.FakeParroApi:
    return fakes.FakeParroApi(load_sample)


def run(api, capsys, *argv: str) -> tuple[int, str, str]:
    try:
        code = parro_cli.main(list(argv), make_client=lambda s: ParroClient(s, transport=api))
    except SystemExit as stop:
        code = int(stop.code or 0)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def posts(api) -> list[HttpRequest]:
    return [r for r in api.api_requests() if r.method == "POST"]


@pytest.fixture
def terminal(monkeypatch):
    """A person at a terminal who answers the question with `terminal.answer`."""

    class Terminal:
        answer: str | None = "y"
        asked = 0

    def fake_input(prompt: str) -> str:
        Terminal.asked += 1
        assert prompt == "Send this message? [y/N] "
        if Terminal.answer is None:
            raise EOFError
        return Terminal.answer

    monkeypatch.setattr(parro_cli, "someone_can_answer", lambda: True)
    monkeypatch.setattr("builtins.input", fake_input)
    return Terminal


# ---------------------------------------------------------------------- asking first


def test_at_a_terminal_it_shows_the_message_and_asks(api, capsys, terminal):
    code, out, _ = run(api, capsys, "chat-send", str(CHAT), TEXT, "--format", "markdown")
    assert code == 0 and terminal.asked == 1
    assert api.sent_messages == [(CHAT, TEXT)]
    assert out.startswith(f"# Message to: Rijden naar het Natuurmuseum\ncalendar chat · #{CHAT}\n")
    assert f"> {TEXT}" in out
    to = next(line for line in out.splitlines() if line.startswith("**To"))
    assert to.startswith("**To (3 people):** Tom Smit · teacher; Joris Peters · parent of Sem;")
    assert "Sanne" not in to, "you do not receive your own message"
    assert "Kees" not in to, "members who left do not receive it"
    assert "# Sent to: Rijden naar het Natuurmuseum" in out
    assert f"chat-messages {CHAT}" in out


@pytest.mark.parametrize("answer", ["n", "", "yes please", "Y es", None], ids=repr)
def test_anything_but_y_sends_nothing(api, capsys, terminal, answer):
    terminal.answer = answer
    code, out, _ = run(api, capsys, "chat-send", str(CHAT), TEXT, "--format", "markdown")
    assert code == 0 and out.rstrip().endswith("Nothing was sent.")
    assert posts(api) == [] and api.sent_messages == []


def test_without_a_person_to_ask_nothing_is_sent(api, capsys):
    code, out, err = run(api, capsys, "chat-send", str(CHAT), TEXT)
    assert code == 2 and out == "" and "Not sent" in err and "--yes" in err
    assert posts(api) == []


def test_yes_sends_without_asking(api, capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("asked"))
    code, out, _ = run(api, capsys, "chat-send", str(CHAT), TEXT, "--yes")
    result = json.loads(out)
    assert code == 0 and result["sent"] is True and result["chatroom_id"] == CHAT
    assert result["message_id"] == 8400000001 and result["created_at"].startswith("2026-11-03")
    assert "text" not in result
    assert api.sent_messages == [(CHAT, TEXT)]


# ---------------------------------------------------------------------- the request


def test_the_request_is_the_captured_one(api, capsys):
    text = "Één regel\nen 🚗 nog een"
    run(api, capsys, "chat-send", str(CHAT), text, "--yes")
    (request,) = posts(api)
    assert request.url == f"{fakes.API}/rest/v2/chatroom/{CHAT}/chatmessage"
    expected = (
        '{"items":[{"dtype":"chat.RChatTextMessage","links":[],"deleted":false,'
        f'"text":{json.dumps(text, ensure_ascii=False)},"allRead":false}}]}}'
    )
    assert request.body == expected.encode("utf-8")
    assert request.headers["Authorization"] == f"Bearer {fakes.ACCESS_TOKEN}"
    assert request.headers["parro-authorization-role"].startswith("GUARDIAN:")
    assert request.headers["Content-Type"] == request.headers["Accept"]
    assert "Range" not in request.headers
    assert request.follow_redirects is False, "a write is never repeated at another address"


def test_it_writes_nothing_else(api, capsys):
    run(api, capsys, "chat-send", str(CHAT), TEXT, "--yes")
    assert api.writes() == [f"POST /chatroom/{CHAT}/chatmessage"]
    assert api.read_chats == set(), "sending does not mark the chat as read"


@pytest.mark.parametrize(
    ("chatroom_id", "text"),
    [(0, "x"), (-1, "x"), (True, "x"), ("1", "x"), (CHAT, ""), (CHAT, " \n"), (CHAT, None)],
)
def test_the_client_refuses_before_sending(api, chatroom_id, text):
    client = ParroClient(Settings(role_override="GUARDIAN:1"), transport=api)
    client.token_store.save_token_response({"access_token": fakes.ACCESS_TOKEN})
    with pytest.raises(ConfigurationError):
        client.send_chat_message(chatroom_id, text)
    assert api.api_requests() == []


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (f"/chatroom/{CHAT}/other", None),
        (f"/chatroom/{CHAT}/chatmessage", b"{}"),
        (f"/chatroom/{CHAT}/chatmessage", b'{"items":[]}'),
        (
            f"/chatroom/{CHAT}/chatmessage",
            b'{"items":[{"dtype":"chat.RChatFileMessage","links":[],"deleted":false,'
            b'"text":"x","allRead":false}]}',
        ),
        (
            f"/chatroom/{CHAT}/chatmessage",
            b'{"items":[{"dtype":"chat.RChatTextMessage","links":[],"deleted":false,'
            b'"text":"  ","allRead":false}]}',
        ),
        ("/chatroom", b"{}"),
        ("/event/1/read", b""),
    ],
)
def test_the_fake_refuses_every_other_post(api, path, body):
    headers = {"Authorization": f"Bearer {fakes.ACCESS_TOKEN}"}
    url = f"{fakes.API}/rest/v2{path}"
    with pytest.raises(fakes.ForbiddenWrite):
        api.send(HttpRequest("POST", url, headers, body))


# ---------------------------------------------------------------------------- the text


def test_text_from_a_file(api, capsys, tmp_path):
    message = tmp_path / "bericht.txt"
    message.write_text("Eerste regel\n\nDerde regel\n", encoding="utf-8")
    code, _, _ = run(api, capsys, "chat-send", str(CHAT), "--file", str(message), "--yes")
    assert code == 0 and api.sent_messages == [(CHAT, "Eerste regel\n\nDerde regel")]


def test_text_from_standard_input(api, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO("Via stdin é\n".encode())))
    code, _, _ = run(api, capsys, "chat-send", str(CHAT), "--file", "-", "--yes")
    assert code == 0 and api.sent_messages == [(CHAT, "Via stdin é")]


def test_a_piped_message_still_needs_yes(api, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"Via stdin\n")))
    code, _, _ = run(api, capsys, "chat-send", str(CHAT), "--file", "-")
    assert code == 2 and posts(api) == []


@pytest.mark.parametrize(
    "argv",
    [
        ["chat-send", str(CHAT), "--yes"],  # no text
        ["chat-send", str(CHAT), TEXT, "--file", "x.txt", "--yes"],  # both
        ["chat-send", str(CHAT), "", "--yes"],
        ["chat-send", str(CHAT), " \n\t", "--yes"],
        ["chat-send", str(CHAT), "--file", "/no/such/file", "--yes"],
        ["chat-send", "not-a-number", TEXT, "--yes"],
        ["chat-send", str(CHAT), "ongeldig \udce9", "--yes"],  # a shell's invalid bytes
    ],
    ids=range(7),
)
def test_bad_input_is_a_usage_error_and_sends_nothing(api, capsys, argv):
    code, _, _ = run(api, capsys, *argv)
    assert code == 2 and posts(api) == []


def test_a_file_that_is_not_text(api, capsys, tmp_path):
    binary = tmp_path / "foto.jpg"
    binary.write_bytes(b"\xff\xd8\xff\xe0 not utf-8")
    code, _, err = run(api, capsys, "chat-send", str(CHAT), "--file", str(binary), "--yes")
    assert code == 2 and "not a UTF-8 text file" in err and posts(api) == []


# ------------------------------------------------------------------------- closed chats


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"archived": True}, "archived"),
        ({"active": False}, "no longer active"),
        ({"repliesEnabled": False}, "replies are switched off"),
        ({"type": "BOT"}, "bot"),
    ],
    ids=["archived", "inactive", "no-replies", "bot"],
)
def test_a_closed_chat_is_refused(api, capsys, override, reason):
    api.room_overrides = override
    code, _, err = run(api, capsys, "chat-send", str(CHAT), TEXT, "--yes")
    assert code == 2 and "Not sent" in err and reason in err
    assert posts(api) == []


def test_the_archived_fixture_chat_is_refused(api, capsys):
    code, _, err = run(api, capsys, "chat-send", str(ARCHIVED_CHAT), TEXT, "--yes")
    assert code == 2 and "archived" in err and posts(api) == []


def test_the_membership_id_is_an_error_and_no_message(api, capsys):
    code, _, err = run(api, capsys, "chat-send", str(CHAT_MEMBERSHIP_ID), TEXT, "--yes")
    assert code == 1 and "CHAT_NOT_ACTIVE_MEMBER" in err and posts(api) == []


# ---------------------------------------------------------------------- never twice


def test_after_a_lost_answer_it_is_not_sent_again(api, capsys):
    api.send_outcomes = ["lost"]
    code, out, err = run(api, capsys, "chat-send", str(CHAT), TEXT, "--yes")
    assert code == 1 and out == ""
    assert "may or may not have arrived" in err and "not sent again" in err
    assert len(posts(api)) == 1 and api.sent_messages == [(CHAT, TEXT)]


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_after_a_server_error_it_is_not_sent_again(api, capsys, status):
    api.send_outcomes = [status]
    code, _, err = run(api, capsys, "chat-send", str(CHAT), TEXT, "--yes")
    assert code == 1 and "may or may not have arrived" in err and len(posts(api)) == 1


@pytest.mark.parametrize("status", [400, 403, 404, 422])
def test_a_clear_refusal_says_so(api, capsys, status):
    api.send_outcomes = [status]
    code, _, err = run(api, capsys, "chat-send", str(CHAT), TEXT, "--yes")
    assert code == 1 and str(status) in err and "may or may not" not in err
    assert len(posts(api)) == 1 and api.sent_messages == []


def test_after_a_401_it_refreshes_and_sends_once(api, capsys):
    """The server refused the first request, so the one resend cannot make a duplicate."""
    api.unauthorized_tokens.add(fakes.ACCESS_TOKEN)
    code, _, _ = run(api, capsys, "chat-send", str(CHAT), TEXT, "--yes")
    assert code == 0 and api.sent_messages == [(CHAT, TEXT)]
    assert posts(api)[-1].headers["Authorization"] == f"Bearer {fakes.REFRESHED_ACCESS_TOKEN}"
    assert api.idp.credential_posts() == [], "a 401 never starts a password login"


def test_a_201_without_readable_json_still_counts_as_sent(api, capsys):
    api.send_outcomes = ["broken"]
    code, out, _ = run(api, capsys, "chat-send", str(CHAT), TEXT, "--yes")
    result = json.loads(out)
    assert code == 0 and result["sent"] is True and result["message_id"] is None
    assert len(posts(api)) == 1


# ------------------------------------------------------------------------------ privacy


@pytest.mark.parametrize("outcome", [None, "lost", 500], ids=["sent", "lost", "error"])
def test_the_text_is_never_logged_or_stored(api, capsys, caplog, tmp_path, outcome):
    secret_text = "Geheime tekst 8f3a voor de leerkracht"
    api.send_outcomes = [outcome] if outcome is not None else []
    with caplog.at_level(logging.DEBUG):
        _, out, err = run(api, capsys, "chat-send", str(CHAT), secret_text, "--yes", "-vv")
    assert secret_text not in caplog.text and secret_text not in err
    assert secret_text not in out, "the outcome does not repeat the text"
    for path in Path(tmp_path).rglob("*"):
        if path.is_file():
            assert b"8f3a" not in path.read_bytes(), path.name


def test_requests_do_not_show_the_body_in_their_repr(api, capsys):
    run(api, capsys, "chat-send", str(CHAT), TEXT, "--yes")
    assert TEXT not in repr(posts(api)[0])


# ---------------------------------------------------------------------------------- MCP


def test_no_mcp_tool_can_send(monkeypatch):
    """Decision 2 of the plan: an assistant reads other people's messages and must not send."""
    monkeypatch.setenv("PARRO_ALLOW_MARK_READ", "1")
    names = {t["name"] for t in parro_mcp.McpServer().list_tools()} | set(parro_mcp.TOOL_FUNCTIONS)
    assert not any("send" in name for name in names)
    source = (Path(parro_mcp.__file__)).read_text(encoding="utf-8")
    assert "send_chat_message" not in source and "send_prepared_message" not in source
