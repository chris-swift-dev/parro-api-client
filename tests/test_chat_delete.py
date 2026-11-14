"""Deleting a chat message (docs/PLAN-0.13-additions.md §2): the fifth kind of write.

Only a message you wrote yourself, that is still there; it is shown first, and only a yes deletes
it; it is sent once. The fake API fails the test for any DELETE it should not get: one for someone
else's message, a status line or a deleted message never leaves the client.
"""

import json
import os
import time

import pytest

from parro import cli as parro_cli
from parro import mcp_server as parro_mcp
from parro import operations
from parro.api_client import ParroClient
from parro.errors import ConfigurationError
from parro.http import HttpRequest
from tests import fakes
from tests.conftest import load_sample
from tests.test_attachments import make_client

CHAT = 8000000001
OWN_TEXT = 8100000002  # "Ik kan rijden, ik heb plek voor drie kinderen."
OWN_VIDEO = 8100000000  # yours, with only a file
TOMS = 8100000001  # written by the teacher
STATUS = 8099999997  # "Sanne de Vries joined the chat": yours, but not a message


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


def deletes(api) -> list[HttpRequest]:
    return [r for r in api.api_requests() if r.method == "DELETE"]


@pytest.fixture
def terminal(monkeypatch):
    """A person at a terminal who answers the question with `terminal.answer`."""

    class Terminal:
        answer = "y"
        asked = 0

    def fake_input(_prompt: str = "") -> str:
        Terminal.asked += 1
        return Terminal.answer

    monkeypatch.setattr(parro_cli, "someone_can_answer", lambda: True)
    monkeypatch.setattr("builtins.input", fake_input)
    return Terminal


# ------------------------------------------------------------------------ the request


def test_the_request_is_the_captured_one(api, capsys):
    code, out, _ = run(api, capsys, "chat-delete", str(CHAT), str(OWN_TEXT), "--yes")

    assert code == 0 and json.loads(out)["deleted"] is True
    (request,) = deletes(api)
    assert request.url.endswith(f"/rest/v2/chatroom/{CHAT}/chatmessage/{OWN_TEXT}")
    assert not request.body, "no body, as captured"
    assert request.headers["parro-authorization-role"].startswith("GUARDIAN:")
    assert api.writes() == [f"DELETE /chatroom/{CHAT}/chatmessage/{OWN_TEXT}"]


def test_afterwards_the_message_is_shown_as_deleted(api, capsys):
    run(api, capsys, "chat-delete", str(CHAT), str(OWN_TEXT), "--yes")

    _, out, _ = run(api, capsys, "chat-messages", str(CHAT), "--format", "markdown")

    assert "(message deleted)" in out and "plek voor drie kinderen" not in out
    assert f"#{OWN_TEXT}" not in out, "a deleted message offers no id to delete it with"


def test_a_message_with_only_a_file_can_be_deleted_too(api, capsys, terminal):
    code, out, _ = run(
        api, capsys, "chat-delete", str(CHAT), str(OWN_VIDEO), "--format", "markdown"
    )

    assert code == 0 and "[video] IMG_0001.MOV (12 MB)" in out
    assert api.deleted_messages == {OWN_VIDEO}


# ------------------------------------------------------------------------ asking first


def test_at_a_terminal_it_shows_the_message_and_asks(api, capsys, terminal):
    code, out, _ = run(api, capsys, "chat-delete", str(CHAT), str(OWN_TEXT), "--format", "markdown")

    assert code == 0 and terminal.asked == 1
    assert out.startswith("# Delete your message in: Rijden naar het Natuurmuseum\n")
    assert "> Ik kan rijden, ik heb plek voor drie kinderen." in out
    assert "cannot be undone" in out and "Deleted from: Rijden naar het Natuurmuseum" in out
    assert api.deleted_messages == {OWN_TEXT}


@pytest.mark.parametrize("answer", ["n", "", "nee", "yes please"])
def test_anything_but_yes_deletes_nothing(api, capsys, terminal, answer):
    terminal.answer = answer

    code, out, _ = run(api, capsys, "chat-delete", str(CHAT), str(OWN_TEXT))

    assert code == 0 and '"deleted": false' in out
    assert deletes(api) == [] and not api.deleted_messages


def test_without_someone_to_ask_and_without_yes_nothing_is_deleted(api, capsys):
    code, out, err = run(api, capsys, "chat-delete", str(CHAT), str(OWN_TEXT))

    assert code != 0 and out == "" and "nobody to ask" in err
    assert deletes(api) == []


# ----------------------------------------------------------------------- the refusals


@pytest.mark.parametrize(
    ("message_id", "reason"),
    [
        (TOMS, "you can only delete a message you wrote yourself"),
        (STATUS, "not a message someone wrote"),
        (8199999999, ""),  # not in this chat: the API answers 404
    ],
)
def test_what_is_not_yours_to_delete_is_refused_before_anything_is_sent(
    api, capsys, message_id, reason
):
    code, out, err = run(api, capsys, "chat-delete", str(CHAT), str(message_id), "--yes")

    assert code != 0 and out == "" and reason in err
    assert deletes(api) == [], "refused by the client, not by the server"


def test_a_message_cannot_be_deleted_twice(api, capsys):
    run(api, capsys, "chat-delete", str(CHAT), str(OWN_TEXT), "--yes")

    code, _, err = run(api, capsys, "chat-delete", str(CHAT), str(OWN_TEXT), "--yes")

    assert code != 0 and "deleted already" in err and len(deletes(api)) == 1


def test_the_client_method_takes_only_positive_ids(tmp_path, api):
    client = make_client(tmp_path, api)

    for chat, message in ((0, 1), (1, -1), (True, 1), ("1", 1), (1, None)):
        with pytest.raises(ConfigurationError, match="positive"):
            client.delete_chat_message(chat, message)  # type: ignore[arg-type]
    assert api.api_requests() == []


# ------------------------------------------------------------------- unclear outcomes


def test_after_a_lost_answer_it_is_not_tried_again(api, capsys):
    api.delete_outcomes = ["lost"]

    code, out, err = run(api, capsys, "chat-delete", str(CHAT), str(OWN_TEXT), "--yes")

    assert code == 1 and out == ""
    assert "may or may not have been deleted" in err and "not tried again" in err
    assert len(deletes(api)) == 1


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_after_a_server_error_it_is_not_tried_again(api, capsys, status):
    api.delete_outcomes = [status]

    code, _, err = run(api, capsys, "chat-delete", str(CHAT), str(OWN_TEXT), "--yes")

    assert code == 1 and "may or may not have been deleted" in err and len(deletes(api)) == 1


def test_a_refusal_by_the_server_is_reported_as_one(api, capsys):
    api.delete_outcomes = [403]

    code, _, err = run(api, capsys, "chat-delete", str(CHAT), str(OWN_TEXT), "--yes")

    assert code != 0 and "may or may not" not in err and not api.deleted_messages


# ------------------------------------------------------------------- finding the id


def test_your_own_messages_are_marked_and_show_their_id(tmp_path, api):
    client = make_client(tmp_path, api)

    result = operations.list_chat_messages(client, CHAT, limit=30)

    yours = {m["id"] for m in result["messages"] if m.get("yours")}
    assert yours == {OWN_TEXT, OWN_VIDEO}, "not the 'joined' line, not the teacher's"


# ---------------------------------------------------------------------------- the MCP


@pytest.fixture
def server(api) -> parro_mcp.McpServer:
    return parro_mcp.McpServer(make_client=lambda s: ParroClient(s, transport=api))


ARGUMENTS = {"chatroom_id": CHAT, "message_id": OWN_TEXT}


def test_mcp_deleting_is_off_by_default_and_no_other_switch_opens_it(api, server, monkeypatch):
    for switch in ("MARK_READ", "SEND_CHAT", "HELPER_SIGNUP", "RSVP"):
        monkeypatch.setenv(f"PARRO_ALLOW_{switch}", "1")

    answer = server.call_tool("parro_delete_chat_message", {**ARGUMENTS, "confirm": True})

    assert "parro_delete_chat_message" not in [t["name"] for t in server.list_tools()]
    assert answer.is_error and "PARRO_ALLOW_DELETE_CHAT=1" in answer.content[0]["text"]
    assert api.api_requests() == []


@pytest.mark.parametrize("extra", [{}, {"confirm": False}, {"confirm": "true"}, {"confirm": 1}])
def test_mcp_only_previews_without_a_real_true(api, server, monkeypatch, extra):
    monkeypatch.setenv("PARRO_ALLOW_DELETE_CHAT", "1")

    answer = server.call_tool("parro_delete_chat_message", {**ARGUMENTS, **extra})

    result = json.loads(answer.content[0]["text"])
    assert result["preview"] is True and result["deleted"] is False
    assert result["text"].startswith("Ik kan rijden")
    assert deletes(api) == []


def test_mcp_deletes_with_confirm_and_reports_an_unknown_outcome(api, server, monkeypatch):
    monkeypatch.setenv("PARRO_ALLOW_DELETE_CHAT", "1")
    assert "parro_delete_chat_message" in [t["name"] for t in server.list_tools()]

    done = server.call_tool("parro_delete_chat_message", {**ARGUMENTS, "confirm": True})
    assert json.loads(done.content[0]["text"])["deleted"] is True
    assert api.deleted_messages == {OWN_TEXT}

    api.delete_outcomes = ["lost"]
    lost = server.call_tool(
        "parro_delete_chat_message", {"chatroom_id": CHAT, "message_id": OWN_VIDEO, "confirm": True}
    )
    assert lost.is_error and "may or may not have been deleted" in lost.content[0]["text"]
    assert len(deletes(api)) == 2


def test_mcp_refuses_someone_else_s_message(api, server, monkeypatch):
    monkeypatch.setenv("PARRO_ALLOW_DELETE_CHAT", "1")

    answer = server.call_tool(
        "parro_delete_chat_message", {"chatroom_id": CHAT, "message_id": TOMS, "confirm": True}
    )

    assert answer.is_error and "wrote yourself" in answer.content[0]["text"]
    assert deletes(api) == []
