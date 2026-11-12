"""parro/release_check.py: one GET to GitHub, nothing about the user, only the version is used."""

import json

import pytest

from parro import __version__
from parro.errors import NetworkError
from parro.http import HttpRequest, HttpResponse
from parro.release_check import (
    LATEST_RELEASE_API,
    is_newer,
    latest_release,
    release_page,
    version_numbers,
)


class GitHub:
    def __init__(self, status: int = 200, answer: object = None, body: bytes | None = None) -> None:
        self.status, self.answer, self.body = status, answer, body
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        body = self.body if self.body is not None else json.dumps(self.answer).encode()
        return HttpResponse(self.status, {}, body, request.url)


def release(tag: str, **extra: object) -> dict[str, object]:
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "html_url": "https://evil.example/x",
        **extra,
    }


@pytest.mark.parametrize(
    ("text", "numbers"),
    [("0.12.0", (0, 12, 0)), ("v1.2.3", (1, 2, 3)), (" v0.12.10 ", (0, 12, 10))],
)
def test_version_numbers(text, numbers):
    assert version_numbers(text) == numbers


@pytest.mark.parametrize("text", ["", "v1.2", "1.0.0rc1", "1.0.0.1", "latest", "v1.2.3-beta"])
def test_anything_else_is_not_a_release(text):
    assert version_numbers(text) is None


def test_newer_compares_numbers_not_text():
    assert is_newer("0.12.10", "0.12.9") and is_newer("1.0.0", "0.99.99")
    assert not is_newer("0.12.0", "0.12.0") and not is_newer("0.11.9", "0.12.0")
    assert not is_newer("nonsense", "0.12.0") and not is_newer("0.13.0", "dev")


def test_one_plain_get_without_anything_about_the_user():
    github = GitHub(answer=release("v0.13.0"))
    assert latest_release(github) is not None
    (request,) = github.requests
    assert (request.method, request.url, request.body) == ("GET", LATEST_RELEASE_API, None)
    assert set(request.headers) == {"Accept", "User-Agent"}
    assert request.headers["User-Agent"] == f"parro-client-gui/{__version__}"
    assert request.cookie_jar is None


def test_the_link_is_built_here_not_taken_from_the_answer():
    found = latest_release(GitHub(answer=release("v0.13.0")))
    assert found is not None and found.version == "0.13.0"
    assert found.page == release_page("0.13.0")
    assert found.page == "https://github.com/chris-swift-dev/parro-api-client/releases/tag/v0.13.0"


@pytest.mark.parametrize(
    "answer",
    [
        release("v0.13.0", draft=True),
        release("v0.13.0", prerelease=True),
        release("v0.13.0rc1"),
        {"message": "Not Found"},
        ["v0.13.0"],
        None,
    ],
)
def test_drafts_pre_releases_and_odd_answers_offer_nothing(answer):
    assert latest_release(GitHub(answer=answer)) is None


def test_broken_json_offers_nothing():
    assert latest_release(GitHub(body=b"<html>")) is None


def test_no_release_yet_offers_nothing():
    assert latest_release(GitHub(status=404, answer={"message": "Not Found"})) is None


def test_another_status_is_a_failure_the_caller_can_show():
    with pytest.raises(NetworkError, match="403"):
        latest_release(GitHub(status=403, answer={"message": "rate limit"}))
