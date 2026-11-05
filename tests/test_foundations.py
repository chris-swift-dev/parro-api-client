"""Phase 1: settings, errors, http helpers, PKCE, token store and geon helpers."""

import json
import os
import stat
from pathlib import Path

import pytest

from parro import errors, geon, pkce
from parro.http import HttpResponse, add_query_parameters, describe_url_for_log
from parro.settings import Settings, parse_login_method
from parro.token_store import EXPIRY_SAFETY_MARGIN_SECONDS, PendingBrowserLogin, TokenStore
from tests.conftest import load_sample

# ------------------------------------------------------------------------------- settings


def test_settings_defaults_follow_the_spec():
    settings = Settings.from_environment({})
    assert settings.contract_version == "224"
    assert settings.app_version == "web:2.27.0"
    assert settings.login_method == "login-form"
    assert settings.scope == "openid offline_access"
    assert settings.geon_media_type == "application/vnd.topicus.geon+json;version=224"
    assert settings.api_root == "https://rest-v2.parro.com/rest/v2"
    assert settings.token_endpoint == "https://inloggen.parnassys.net/idp/oauth2/token"
    assert settings.token_file == Path.home() / ".parro-mcp" / "tokens.json"


def test_settings_read_every_parro_variable(tmp_path):
    environment = {
        "PARRO_USERNAME": "parent@example.com",
        "PARRO_PASSWORD": "from-env",
        "PARRO_TOKEN_FILE": str(tmp_path / "t.json"),
        "PARRO_ROLE": "GUARDIAN:42",
        "PARRO_ACCESS_TOKEN": "bootstrap",
        "PARRO_BASE_URI": "https://api.example.test/",
        "PARRO_LOGIN_URI": "https://idp.example.test/",
        "PARRO_CONTRACT_VERSION": "230",
        "PARRO_APP_VERSION": "web:9.9.9",
        "PARRO_CLIENT_ID": "client",
        "PARRO_REDIRECT_URI": "https://example.test/cb",
        "PARRO_SCOPE": "openid",
        "PARRO_LOGIN_METHOD": "AUTO",
        "PARRO_TIMEOUT": "5",
        "PARRO_MAX_DOWNLOAD": "1000",
        "PARRO_MAX_IMAGE_PX": "800",
    }
    settings = Settings.from_environment(environment)
    assert settings.api_root == "https://api.example.test/rest/v2"
    assert settings.revoke_endpoint == "https://idp.example.test/idp/oauth2/revoke"
    assert settings.login_method == "auto"
    assert settings.http_timeout_seconds == 5.0
    assert settings.max_download_bytes == 1000
    assert settings.max_image_pixels == 800
    assert settings.role_override == "GUARDIAN:42"
    assert settings.read_password() == "from-env"
    assert settings.has_credentials()


def test_settings_repr_hides_secrets():
    settings = Settings.from_environment(
        {"PARRO_PASSWORD": "hunter2-secret", "PARRO_ACCESS_TOKEN": "token-secret"}
    )
    assert "hunter2-secret" not in repr(settings)
    assert "token-secret" not in repr(settings)


def test_password_file_wins_and_keeps_inner_spaces(tmp_path):
    password_file = tmp_path / "pw"
    password_file.write_text(" pass # word \n", encoding="utf-8")
    settings = Settings.from_environment(
        {"PARRO_PASSWORD": "env-loses", "PARRO_PASSWORD_FILE": str(password_file)}
    )
    assert settings.read_password() == " pass # word "


def test_unreadable_password_file_is_a_configuration_error(tmp_path):
    settings = Settings.from_environment({"PARRO_PASSWORD_FILE": str(tmp_path / "missing")})
    with pytest.raises(errors.ConfigurationError, match="cannot be read"):
        settings.read_password()


def test_invalid_settings_give_clear_errors():
    with pytest.raises(errors.ConfigurationError, match="Unknown login method"):
        parse_login_method("magic")
    with pytest.raises(errors.ConfigurationError, match="PARRO_TIMEOUT must be a number"):
        Settings.from_environment({"PARRO_TIMEOUT": "soon"})
    with pytest.raises(errors.ConfigurationError, match="greater than zero"):
        Settings.from_environment({"PARRO_MAX_DOWNLOAD": "0"})


def test_with_overrides_ignores_flags_that_were_not_given():
    settings = Settings.from_environment({}).with_overrides(login_method="auto", scope=None)
    assert settings.login_method == "auto"
    assert settings.scope == "openid offline_access"


# --------------------------------------------------------------------------------- errors


def test_exit_codes_match_the_plan():
    assert errors.ApiError("x", status=500).exit_code == 1
    assert errors.ConfigurationError("x").exit_code == 2
    assert errors.NotLoggedIn("x").exit_code == 3
    assert errors.LoginHalted("x").exit_code == 4
    assert errors.CredentialsRejected("x").exit_code == 4
    assert isinstance(errors.TokenRejected("x", status=401), errors.ApiError)


# ----------------------------------------------------------------------------------- http


def test_http_response_header_lookup_is_case_insensitive():
    response = HttpResponse(200, {"content-range": "items 0-1/2"}, b'{"a": 1}', "https://x")
    assert response.header("Content-Range") == "items 0-1/2"
    assert response.json() == {"a": 1}
    assert HttpResponse(401, {}, b"", "https://x").json() is None


def test_log_description_never_contains_path_or_query():
    url = "https://d3jdv0f7ba4m2l.cloudfront.net/application/secretkey/1-abc.pdf?x=1"
    assert describe_url_for_log("GET", url) == "GET d3jdv0f7ba4m2l.cloudfront.net"


def test_add_query_parameters_skips_none_and_extends_existing_query():
    assert add_query_parameters("https://x/a", {"b": None}) == "https://x/a"
    assert add_query_parameters("https://x/a?b=1", {"c": 2}) == "https://x/a?b=1&c=2"
    assert add_query_parameters("https://x/a", {"q": "a b"}) == "https://x/a?q=a+b"


# ----------------------------------------------------------------------------------- pkce


def test_pkce_challenge_matches_rfc_7636_appendix_b():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert pkce.create_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_pkce_rfc_7636_appendix_b_octets_give_the_published_verifier():
    octets = bytes(
        [116, 24, 223, 180, 151, 153, 224, 37, 79, 250, 96, 125, 216, 173, 187, 186,
         22, 212, 37, 77, 105, 214, 191, 240, 91, 88, 5, 88, 83, 132, 141, 121]
    )  # fmt: skip
    expected = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert pkce.base64url_without_padding(octets) == expected


def test_fresh_pkce_pairs_are_valid_and_unique():
    first, second = pkce.create_pkce_pair(), pkce.create_pkce_pair()
    assert len(first.verifier) == 43
    assert set(first.verifier) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    )
    assert first.challenge == pkce.create_challenge(first.verifier)
    assert first.verifier != second.verifier
    assert first.verifier not in repr(first)


# ---------------------------------------------------------------------------- token store


class FixedClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_token_store_round_trip_and_file_mode(tmp_path):
    path = tmp_path / "dir" / "tokens.json"
    store = TokenStore(path, clock=FixedClock())
    tokens = store.save_token_response(
        {"access_token": "A", "refresh_token": "R", "expires_in": 3599}
    )
    assert tokens.expires_at == 1_000_000 + 3599 - EXPIRY_SAFETY_MARGIN_SECONDS
    assert tokens.has_fresh_access_token(1_000_000)
    assert not tokens.has_fresh_access_token(1_000_000 + 3599)
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    on_disk = json.loads(path.read_text())
    assert on_disk["access_token"] == "A" and on_disk["refresh_token"] == "R"
    assert TokenStore(path).get_tokens().refresh_token == "R"


def test_token_store_reads_a_file_written_by_the_original_server(tmp_path):
    path = tmp_path / "tokens.json"
    path.write_text(
        json.dumps(
            {
                "access_token": "A",
                "refresh_token": "R",
                "expires_at": 2_000_000.5,
                "obtained_at": 1_000_000.5,
                "login_failed": "the login form rejected these credentials",
                "something_new": 1,
            }
        )
    )
    store = TokenStore(path)
    assert store.get_tokens().expires_at == 2_000_000.5
    assert store.get_login_halted_reason() == "the login form rejected these credentials"
    store.save_token_response({"access_token": "B", "expires_in": 60})
    on_disk = json.loads(path.read_text())
    assert on_disk["refresh_token"] == "R", "refresh responses without a refresh token keep it"
    assert on_disk["something_new"] == 1, "unknown keys are preserved"
    assert "login_failed" in on_disk, "storing tokens does not clear the latch by itself"


def test_latch_survives_logout_and_reload(tmp_path):
    path = tmp_path / "tokens.json"
    store = TokenStore(path)
    store.save_token_response({"access_token": "A", "refresh_token": "R"})
    store.halt_logins("wrong password")
    store.forget_tokens()
    reloaded = TokenStore(path)
    assert reloaded.get_tokens().access_token is None
    assert reloaded.get_tokens().refresh_token is None
    assert reloaded.get_login_halted_reason() == "wrong password"
    reloaded.clear_login_halt()
    reloaded.forget_tokens()
    assert not path.exists(), "an empty token file is removed"


def test_pending_browser_login_is_kept_until_tokens_arrive(tmp_path):
    store = TokenStore(tmp_path / "tokens.json")
    store.save_pending_browser_login(PendingBrowserLogin(verifier="v", state="s"))
    assert TokenStore(store.path).get_pending_browser_login() == PendingBrowserLogin("v", "s")
    store.save_token_response({"access_token": "A"})
    assert store.get_pending_browser_login() is None


def test_bootstrap_token_is_used_only_when_the_file_has_none(tmp_path):
    store = TokenStore(tmp_path / "tokens.json", bootstrap_access_token="BOOT")
    tokens = store.get_tokens()
    assert tokens.access_token == "BOOT" and tokens.expires_at is None
    assert tokens.has_fresh_access_token(now=10**12)
    assert not store.path.exists(), "the bootstrap token is never written to disk"


def test_corrupt_token_file_is_treated_as_empty(tmp_path):
    path = tmp_path / "tokens.json"
    path.write_text("{not json")
    assert TokenStore(path).get_tokens().access_token is None


# ----------------------------------------------------------------------------------- geon


def test_get_object_id_prefers_the_self_link():
    sample = {
        "links": [
            {"id": 7, "rel": "koppeling"},
            {"id": 9, "rel": "self"},
        ],
        "id": 3,
    }
    assert geon.get_object_id(sample) == 9
    assert geon.get_object_id({"id": 3}) == 3
    assert geon.get_object_id({"id": "x"}) is None
    assert geon.get_object_id("not an object") is None


def test_strip_geon_metadata_on_a_group_sample():
    group = load_sample("listGroups.200.json")["items"][2]
    stripped = geon.strip_geon_metadata(group)
    assert list(stripped)[:2] == ["id", "type"]
    assert stripped["id"] == 4000000003
    assert stripped["type"] == "NORMAL", "the object's own `type` field beats its dtype"
    assert "childAvatars" in stripped and stripped["childAvatars"][0]["type"] == "RAvatar"
    assert stripped["stamgroep"] is True
    assert stripped["unreadCount"] == 0, "zero and False are kept"
    text = json.dumps(stripped)
    for bookkeeping in ('"links"', '"permissions"', '"dtype"', '"additionalObjects"'):
        assert bookkeeping not in text


def test_strip_geon_metadata_drops_empty_values_and_keeps_plain_id():
    settings_sample = load_sample("getAccountSettings.200.json")
    stripped = geon.strip_geon_metadata(settings_sample)
    assert list(stripped)[:3] == ["id", "type", "email"]
    assert stripped["type"] == "RAccountSettings"
    assert geon.strip_geon_metadata({"items": []}) == {}
    assert geon.strip_geon_metadata([{"a": None, "b": [], "c": False}]) == [{"c": False}]


def test_strip_geon_metadata_shrinks_payloads_a_lot():
    payload = load_sample("listGroups.200.json")
    # Real payloads shrink by more than half (long permission lists); the fixtures by about 40%.
    assert len(json.dumps(geon.strip_geon_metadata(payload))) < len(json.dumps(payload)) * 0.7


def test_collection_items_and_totals():
    assert len(geon.get_collection_items(load_sample("listChildren.200.json"))) == 2
    assert geon.get_collection_items(None) == []
    assert geon.get_collection_items([1, 2]) == [1, 2]
    assert geon.get_collection_items({"a": 1}) == [{"a": 1}]
    assert geon.parse_total_from_content_range("items 0-1/2") == 2
    assert geon.parse_total_from_content_range("items 0-0/0") == 0
    assert geon.parse_total_from_content_range("items 0-9/*") is None
    assert geon.parse_total_from_content_range(None) is None


def test_range_header_is_zero_based_and_inclusive():
    assert geon.build_range_header(0, 50) == "items=0-49"
    assert geon.build_range_header(20, 10) == "items=20-29"
    with pytest.raises(ValueError):
        geon.build_range_header(0, 0)


def test_full_name_skips_missing_parts():
    assert geon.full_name({"firstname": "Voornaam", "surname": "Achternaam"}) == (
        "Voornaam Achternaam"
    )
    assert geon.full_name({"firstname": "Solo", "surname": None}) == "Solo"
    assert geon.full_name(None) == ""
