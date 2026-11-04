"""Phase 3: ParroClient against FakeParroApi (fixes 1-3 of PLAN-api-client §4)."""

import json

import pytest

from parro.api_client import ParroClient, derive_role_header
from parro.errors import ApiError, ConfigurationError, TokenRejected
from parro.settings import Settings
from parro.token_store import TokenStore
from tests import fakes
from tests.conftest import load_sample


def make_client(tmp_path, api: fakes.FakeParroApi, **settings_changes) -> ParroClient:
    settings = Settings(token_file=tmp_path / "tokens.json", **settings_changes)
    store = TokenStore(settings.token_file)
    store.save_token_response(
        {
            "access_token": fakes.ACCESS_TOKEN,
            "refresh_token": fakes.REFRESH_TOKEN,
            "expires_in": 3599,
        }
    )
    return ParroClient(settings, transport=api, token_store=store)


@pytest.fixture
def api() -> fakes.FakeParroApi:
    return fakes.FakeParroApi(load_sample)


def test_collection_request_sends_the_documented_headers(tmp_path, api):
    client = make_client(tmp_path, api)
    response = client.list_children(limit=5)
    assert response.total == 2 and len(response.items) == 2
    me_request, child_request = api.api_requests()
    assert me_request.url.endswith("/rest/v2/account/me")
    assert "parro-authorization-role" not in me_request.headers, "/account/me goes without role"
    headers = child_request.headers
    assert headers["Authorization"] == f"Bearer {fakes.ACCESS_TOKEN}"
    assert headers["Accept"] == "application/vnd.topicus.geon+json;version=224"  # fix 1
    assert headers["Content-Type"] == headers["Accept"]
    assert headers["parro-app-version"] == "web:2.27.0"  # fix 1
    assert headers["parro-authorization-role"] == "GUARDIAN:1000000000"
    assert headers["Range"] == "items=0-4"
    assert headers["topicus-Range-Count"] == "Exact"


def test_role_and_account_are_fetched_once(tmp_path, api):
    client = make_client(tmp_path, api)
    client.list_children()
    client.list_chatrooms()
    client.get_unread_counts()
    assert sum(r.url.endswith("/account/me") for r in api.api_requests()) == 1


def test_role_override_skips_account_lookup(tmp_path, api):
    client = make_client(tmp_path, api, role_override="GUARDIAN:42")
    client.list_children()
    assert [r.url.rsplit("/", 1)[-1] for r in api.api_requests()] == ["child"]
    assert api.api_requests()[0].headers["parro-authorization-role"] == "GUARDIAN:42"


def test_derive_role_header_from_the_account_sample():
    assert derive_role_header(load_sample("getAccountMe.200.json")) == "GUARDIAN:1000000000"
    assert derive_role_header({"accountType": "GUARDIAN", "identity": {}}) is None


def test_announcement_uses_the_primer_dtype(tmp_path, api):  # fix 2
    client = make_client(tmp_path, api)
    event = client.get_announcement(11000000000)
    assert event["title"].startswith("Nieuwsbrief")
    assert api.api_requests()[-1].url.endswith(
        "/event/11000000000?dtype=event.RAnnouncementEventPrimer"
    )


def test_a_401_refreshes_once_and_retries(tmp_path, api):  # fix 3
    api.unauthorized_tokens.add(fakes.ACCESS_TOKEN)
    client = make_client(tmp_path, api, role_override="GUARDIAN:1")
    assert len(client.list_children().items) == 2
    child_calls = [r for r in api.api_requests() if r.url.endswith("/child")]
    assert [r.headers["Authorization"] for r in child_calls] == [
        f"Bearer {fakes.ACCESS_TOKEN}",
        f"Bearer {fakes.REFRESHED_ACCESS_TOKEN}",
    ]
    assert api.idp.credential_posts() == []


def test_a_persistent_401_is_reported_and_the_token_file_survives(tmp_path, api):  # fix 3
    api.unauthorized_tokens.update({fakes.ACCESS_TOKEN, fakes.REFRESHED_ACCESS_TOKEN})
    client = make_client(
        tmp_path, api, role_override="GUARDIAN:1", username="u", password_from_env="p"
    )
    client.token_store.halt_logins("kept")
    with pytest.raises(TokenRejected, match="dtype"):
        client.list_children()
    assert api.idp.credential_posts() == [], "a 401 never starts a password login"
    on_disk = json.loads(client.token_store.path.read_text())
    assert on_disk["refresh_token"] == fakes.REFRESH_TOKEN
    assert on_disk["login_failed"] == "kept"


def test_the_wrong_announcement_dtype_gives_a_clear_error_not_a_login(tmp_path, api):
    client = make_client(tmp_path, api, username="u", password_from_env="p")
    with pytest.raises(TokenRejected, match="RAnnouncementEvent"):
        client.get_event(11000000000, "event.RAnnouncementEvent")
    assert api.idp.credential_posts() == []
    assert client.token_store.get_tokens().refresh_token == fakes.REFRESH_TOKEN


def test_a_missing_dtype_gives_the_geon_error(tmp_path, api):
    client = make_client(tmp_path, api)
    with pytest.raises(ApiError) as raised:
        client.get("/event/11000000000")
    assert raised.value.status == 406
    assert raised.value.application_error == "EVENT_BAD_TYPE"
    assert "EVENT_BAD_TYPE" in str(raised.value)


def test_paths_are_relative_to_the_api_and_full_urls_are_refused(tmp_path, api):
    client = make_client(tmp_path, api)
    assert client.build_api_url("child") == "https://rest-v2.parro.com/rest/v2/child"
    assert client.build_api_url("/rest/v2/child") == "https://rest-v2.parro.com/rest/v2/child"
    for unsafe in ("https://evil.example/x", "//evil.example/x"):
        with pytest.raises(ConfigurationError):
            client.build_api_url(unsafe)


def test_query_in_the_path_is_kept(tmp_path, api):
    client = make_client(tmp_path, api)
    response = client.get("/event?dtype=event.RAnnouncementEventPrimer&group=1", limit=1)
    assert len(response.items) == 1 and response.total == 2


def test_merged_feed_queries_each_current_group(tmp_path, api):
    client = make_client(tmp_path, api)
    feed = client.collect_feed("event.RAnnouncementEventPrimer", limit_per_group=1)
    assert [item.group_name for item in feed] == [
        "Basisschool Voorbeeld",
        "1/2 Voornaam",
        "3 Voornaam/Voornaam",
    ]
    single = client.collect_feed("event.RAnnouncementEventPrimer", group_id=5, limit_per_group=2)
    assert len(single) == 2 and single[0].group_name is None


def test_the_api_only_ever_receives_get(tmp_path, api):
    client = make_client(tmp_path, api)
    client.list_children()
    client.list_groups()
    client.list_groups(previous_year=True)
    client.get_unread_counts()
    client.list_system_news()
    client.get_absence_settings()
    client.get_account_settings()
    client.get_organisation(100000)
    client.list_chatrooms()
    client.list_chat_messages(1)
    client.get_announcement(1)
    client.get_calendar_item(1)
    client.collect_feed("event.RCalendarItemEventPrimer")
    assert {r.method for r in api.api_requests()} == {"GET"}
