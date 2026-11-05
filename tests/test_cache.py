"""The cache (PLAN-readable-output §3b): attachments and calendar details only, never stale."""

import copy
import json
import os
import stat
import time
from typing import Any

import pytest

import parro_cli
from parro import attachments, operations
from parro.api_client import ParroClient
from parro.cache import Cache, remove_urls
from parro.errors import ConfigurationError
from parro.settings import Settings
from parro.token_store import TokenStore
from tests import fakes
from tests.conftest import load_sample


def make_client(tmp_path, api: fakes.FakeParroApi, **settings_changes: Any) -> ParroClient:
    settings = Settings(
        token_file=tmp_path / "tokens.json",
        role_override="GUARDIAN:1",
        data_dir=tmp_path / "data",
        **settings_changes,
    )
    store = TokenStore(settings.token_file)
    store.save_token_response(
        {"access_token": fakes.ACCESS_TOKEN, "refresh_token": fakes.REFRESH_TOKEN}
    )
    return ParroClient(settings, transport=api, token_store=store)


def api_with_newsletter_text() -> tuple[fakes.FakeParroApi, str]:
    """The newsletter announcement, with its attachment described and served as plain text.

    Plain text keeps these tests free of the optional PDF libraries.
    """
    newsletter = copy.deepcopy(load_sample("getEvent_announcement.200.json"))
    entry = newsletter["attachments"][0]["entries"][0]
    entry["contentType"] = "text/plain"

    def with_text_newsletter(name: str) -> Any:
        return newsletter if name == "getEvent_announcement.200.json" else load_sample(name)

    api = fakes.FakeParroApi(with_text_newsletter)
    api.attachment_bodies[entry["url"]] = ("text/plain", b"Beste ouders, dit is de nieuwsbrief.")
    return api, entry["url"]


def downloads(api: fakes.FakeParroApi, url: str) -> int:
    return sum(request.url == url for request in api.requests)


# --------------------------------------------------------------------------- attachments


def test_a_second_read_of_an_attachment_downloads_and_extracts_nothing(tmp_path, monkeypatch):
    api, url = api_with_newsletter_text()
    client = make_client(tmp_path, api)
    first = operations.read_attachments(client, event_id=fakes.NEWSLETTER_ID)
    extractions: list[str] = []
    monkeypatch.setattr(
        attachments,
        "extract_text",
        lambda *args: extractions.append("called"),
    )
    second = operations.read_attachments(client, event_id=fakes.NEWSLETTER_ID)
    assert downloads(api, url) == 1
    assert extractions == [], "the text came from the cache too"
    assert second.summary["text"] == first.summary["text"] == "Beste ouders, dit is de nieuwsbrief."
    assert second.summary["contentType"] == "text/plain"


def test_max_chars_applies_to_cached_text(tmp_path):
    api, _ = api_with_newsletter_text()
    client = make_client(tmp_path, api)
    operations.read_attachments(client, event_id=fakes.NEWSLETTER_ID)
    options = attachments.ReadOptions(max_chars=5)
    short = operations.read_attachments(client, event_id=fakes.NEWSLETTER_ID, options=options)
    assert short.summary["text"] == "Beste" and short.summary["truncated"] is True


def test_cache_off_downloads_every_time(tmp_path):
    api, url = api_with_newsletter_text()
    client = make_client(tmp_path, api, cache_enabled=False)
    operations.read_attachments(client, event_id=fakes.NEWSLETTER_ID)
    operations.read_attachments(client, event_id=fakes.NEWSLETTER_ID)
    assert downloads(api, url) == 2
    assert not (tmp_path / "data").exists(), "nothing is written when the cache is off"


def test_a_direct_url_is_never_cached(tmp_path):
    api = fakes.FakeParroApi(load_sample)
    api.attachment_bodies["https://cdn.example/a.txt"] = ("text/plain", b"hello")
    client = make_client(tmp_path, api)
    operations.read_attachments(client, url="https://cdn.example/a.txt")
    operations.read_attachments(client, url="https://cdn.example/a.txt")
    assert downloads(api, "https://cdn.example/a.txt") == 2, "no id, no upload id: no cache key"


# ----------------------------------------------------------------------- calendar details


def detail_requests(api: fakes.FakeParroApi) -> int:
    return sum("/event/" in request.url for request in api.api_requests())


def test_calendar_details_are_reused_while_the_list_shows_the_same_version(tmp_path):
    api = fakes.FakeParroApi(load_sample)
    client = make_client(tmp_path, api)
    first = operations.list_calendar(client, details=True)
    assert detail_requests(api) == 4
    second = operations.list_calendar(client, details=True)
    assert detail_requests(api) == 4, "all four came from the cache"
    assert second == first


def test_a_newer_last_modified_at_fetches_the_details_again(tmp_path):
    api = fakes.FakeParroApi(load_sample)
    client = make_client(tmp_path, api)
    operations.list_calendar(client, details=True)

    def edited(name: str) -> Any:
        payload = load_sample(name)
        if name == "listEvents_calendar-4000000003.200.json":
            payload = copy.deepcopy(payload)
            payload["items"][0]["lastModifiedAt"] = "2026-11-05T09:00:00.000+01:00"
        return payload

    api.load_sample = edited
    operations.list_calendar(client, details=True)
    assert detail_requests(api) == 5, "only the edited item (the museum trip) is fetched again"


def test_lists_are_never_cached(tmp_path):
    api = fakes.FakeParroApi(load_sample)
    client = make_client(tmp_path, api)
    operations.list_calendar(client, details=True)
    lists_before = sum(r.url.endswith("dtype=identity.RHomeGroup") or "/event?" in r.url
                       for r in api.api_requests())  # fmt: skip
    operations.list_calendar(client, details=True)
    lists_after = sum(r.url.endswith("dtype=identity.RHomeGroup") or "/event?" in r.url
                      for r in api.api_requests())  # fmt: skip
    assert lists_after == 2 * lists_before


# ----------------------------------------------------------------------- what is on disk


def test_files_are_private_and_hold_no_download_links(tmp_path):
    api, _ = api_with_newsletter_text()
    client = make_client(tmp_path, api)
    operations.read_attachments(client, event_id=fakes.NEWSLETTER_ID)
    operations.list_calendar(client, details=True)
    cache_dir = tmp_path / "data" / "cache"
    stored = [path for path in cache_dir.rglob("*") if path.is_file()]
    assert len(stored) == 3 + 4  # attachment: bytes, meta, text; four calendar details
    if os.name == "posix":
        for path in stored:
            assert stat.S_IMODE(path.stat().st_mode) == 0o600, path
        for folder in (cache_dir, *[p for p in cache_dir.rglob("*") if p.is_dir()]):
            assert stat.S_IMODE(folder.stat().st_mode) == 0o700, folder
    for path in stored:
        assert b"cloudfront" not in path.read_bytes() and b"https://" not in path.read_bytes()


def test_calendar_details_never_carry_links_even_when_fresh(tmp_path):
    client = make_client(tmp_path, fakes.FakeParroApi(load_sample))
    agenda = operations.list_calendar(client, details=True)
    assert "url" not in json.dumps(agenda["items"][1]["details"])
    assert agenda["items"][1]["details"]["attachments"][0]["filename"] == "Route.jpg"


def test_the_size_limit_drops_the_oldest_entries(tmp_path):
    cache = Cache(tmp_path / "cache", max_bytes=25)
    cache.put_bytes("attachments", "old.bin", b"x" * 10)
    old_time = time.time() - 100
    os.utime(tmp_path / "cache" / "attachments" / "old.bin", (old_time, old_time))
    cache.put_bytes("attachments", "middle.bin", b"y" * 10)
    cache.put_bytes("attachments", "new.bin", b"z" * 10)
    assert cache.get_bytes("attachments", "old.bin") is None
    assert cache.get_bytes("attachments", "new.bin") == b"z" * 10
    assert cache.info().bytes <= 25


def test_unsafe_keys_and_damaged_entries(tmp_path):
    cache = Cache(tmp_path / "cache", max_bytes=1000)
    cache.put_bytes("attachments", "../escape", b"no")
    assert not (tmp_path / "escape").exists()
    assert cache.get_bytes("..", "x") is None
    cache.put_bytes("events", "1.json", b"{broken")
    assert cache.get_json("events", "1.json") is None


def test_remove_urls_at_any_depth():
    nested = {"url": "u", "a": [{"url": "v", "keep": 1}], "b": {"c": {"url": "w", "d": 2}}}
    assert remove_urls(nested) == {"a": [{"keep": 1}], "b": {"c": {"d": 2}}}


# --------------------------------------------------------------------------- switches


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


def run(capsys, *argv: str) -> tuple[int, Any]:
    api = fakes.FakeParroApi(load_sample)
    exit_code = parro_cli.main(
        [*argv, "--format", "json"], make_client=lambda s: ParroClient(s, transport=api)
    )
    out = capsys.readouterr().out
    return exit_code, json.loads(out) if out else None


def test_cache_info_and_clear_commands(environment, capsys):
    run(capsys, "calendar", "--details")
    exit_code, info = run(capsys, "cache", "info")
    assert exit_code == 0 and info["files"] == 4 and info["enabled"] is True
    assert info["directory"] == str(environment / "data" / "cache")
    exit_code, cleared = run(capsys, "cache", "clear")
    assert exit_code == 0 and cleared["removed_files"] == 4
    assert run(capsys, "cache", "info")[1]["files"] == 0


def test_no_cache_flag_and_environment_switch(environment, capsys, monkeypatch):
    run(capsys, "calendar", "--details", "--no-cache")
    assert not (environment / "data").exists()
    monkeypatch.setenv("PARRO_CACHE", "off")
    run(capsys, "calendar", "--details")
    assert not (environment / "data").exists()
    with pytest.raises(ConfigurationError, match="PARRO_CACHE must be on or off"):
        Settings.from_environment({"PARRO_CACHE": "sometimes"})
