"""Phase 2: login methods, the authenticator and the lockout latch (PLAN-api-client §3, §7).

Everything runs against FakeParnasSys; nothing touches the network.
"""

import logging
import urllib.parse

import pytest

from parro.authenticator import Authenticator
from parro.errors import (
    ConfigurationError,
    CredentialsRejected,
    LoginFailed,
    LoginHalted,
    NotLoggedIn,
)
from parro.login_methods import (
    extract_error_message,
    find_login_form_action,
    read_redirect_parameters,
)
from parro.settings import LoginMethod, Settings
from parro.token_store import TokenStore
from tests import fakes

SECRETS = (
    fakes.CORRECT_PASSWORD,
    "wrong-password-SECRET",
    fakes.ACCESS_TOKEN,
    fakes.REFRESHED_ACCESS_TOKEN,
    fakes.REFRESH_TOKEN,
    fakes.AUTHORIZATION_CODE,
)


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def make_authenticator(
    tmp_path,
    idp: fakes.FakeParnasSys,
    method: LoginMethod = "login-form",
    password: str | None = fakes.CORRECT_PASSWORD,
    username: str | None = fakes.USERNAME,
) -> tuple[Authenticator, TokenStore, Clock]:
    settings = Settings(
        username=username,
        password_from_env=password,
        token_file=tmp_path / "tokens.json",
        login_method=method,
    )
    clock = Clock()
    store = TokenStore(settings.token_file, clock=clock)
    return Authenticator(settings, idp, store, clock=clock), store, clock


# ---------------------------------------------------------------------- login form parsing


def test_finds_the_form_action_on_the_real_login_page():
    action = find_login_form_action(fakes.LOGIN_PAGE_HTML, fakes.LOGIN_PAGE_URL)
    parts = urllib.parse.urlsplit(action)
    assert parts.netloc == "inloggen.parnassys.net"
    assert parts.path == "/idp/"
    assert "signInForm" in parts.query
    assert "&amp;" not in action, "HTML entities in the action are decoded"


@pytest.mark.parametrize(
    "page",
    [
        "<html><body>Kies een account</body></html>",
        '<form action="./?x"><input name="emailadres"></form>',  # no password field
        '<form action="./?signInForm"><input name="email"><input name="pw"></form>',
    ],
)
def test_a_changed_login_page_fails_before_the_password_is_sent(page, tmp_path):
    with pytest.raises(LoginFailed, match="No password was sent"):
        find_login_form_action(page, fakes.LOGIN_PAGE_URL)
    idp = fakes.FakeParnasSys(login_page_html=page)
    authenticator, store, _ = make_authenticator(tmp_path, idp)
    with pytest.raises(LoginFailed):
        authenticator.login()
    assert idp.credential_posts() == []
    assert store.get_login_halted_reason() is None, "no attempt spent, so no latch"


def test_error_message_is_read_from_the_feedback_panel():
    assert extract_error_message(fakes.REJECTED_PAGE_HTML) == (
        "Onjuiste inloggegevens. Account has 2 attempts remaining"
    )
    assert extract_error_message(fakes.LOGIN_PAGE_HTML) is None


def test_redirect_parameters():
    parsed = read_redirect_parameters("https://talk.parro.com/oauth2?code=abc&state=xyz")
    assert (parsed.code, parsed.state, parsed.error) == ("abc", "xyz", None)
    assert read_redirect_parameters(" abc ").code == "abc"
    denied = read_redirect_parameters("https://talk.parro.com/oauth2?error=access_denied")
    assert denied.error == "access_denied" and denied.code is None


# --------------------------------------------------------------------- one password check


def test_login_form_makes_exactly_one_credential_post(tmp_path):
    idp = fakes.FakeParnasSys()
    authenticator, store, _ = make_authenticator(tmp_path, idp)
    assert authenticator.get_access_token() == fakes.ACCESS_TOKEN
    assert len(idp.credential_posts()) == 1
    post = idp.credential_posts()[0]
    assert post.follow_redirects is False
    assert fakes.form_of(post) == {
        "aanmelden": "x",
        "emailadres": fakes.USERNAME,
        "wachtwoord": fakes.CORRECT_PASSWORD,
    }
    assert store.get_tokens().refresh_token == fakes.REFRESH_TOKEN


def test_code_exchange_uses_query_parameters_and_an_empty_body(tmp_path):
    idp = fakes.FakeParnasSys()
    authenticator, _, _ = make_authenticator(tmp_path, idp)
    authenticator.login()
    exchange = next(r for r in idp.requests if "grant_type=authorization_code" in r.url)
    assert exchange.body == b""
    query = fakes.query_of(exchange.url)
    assert query["code"] == fakes.AUTHORIZATION_CODE
    assert query["redirect_uri"] == "https://talk.parro.com/oauth2"
    authorize = idp.requests[0]
    challenge = fakes.query_of(authorize.url)["code_challenge"]
    from parro.pkce import create_challenge

    assert create_challenge(query["code_verifier"]) == challenge


def test_password_grant_makes_exactly_one_credential_post_with_a_form_body(tmp_path):
    idp = fakes.FakeParnasSys()
    authenticator, _, _ = make_authenticator(tmp_path, idp, method="password-grant")
    authenticator.login()
    assert len(idp.credential_posts()) == 1
    form = fakes.form_of(idp.credential_posts()[0])
    assert form["grant_type"] == "password"
    assert form["scope"] == "openid offline_access"


def test_password_grant_never_falls_back_to_the_form(tmp_path):
    idp = fakes.FakeParnasSys(password_grant_enabled=False)
    authenticator, store, _ = make_authenticator(tmp_path, idp, method="password-grant")
    with pytest.raises(CredentialsRejected):
        authenticator.login()
    assert len(idp.credential_posts()) == 1
    assert store.get_login_halted_reason()


def test_auto_falls_back_to_the_form_once_and_makes_at_most_two_posts(tmp_path):
    idp = fakes.FakeParnasSys(password_grant_enabled=False)
    authenticator, store, _ = make_authenticator(tmp_path, idp, method="auto")
    assert authenticator.get_access_token() == fakes.ACCESS_TOKEN
    assert len(idp.credential_posts()) == 2
    assert store.get_login_halted_reason() is None, "the form worked, so the latch is cleared"


def test_auto_with_a_wrong_password_stops_after_two_posts(tmp_path):
    idp = fakes.FakeParnasSys()
    authenticator, store, _ = make_authenticator(
        tmp_path, idp, method="auto", password="wrong-password-SECRET"
    )
    with pytest.raises(CredentialsRejected):
        authenticator.get_access_token()
    assert len(idp.credential_posts()) == 2
    assert store.get_login_halted_reason()


def test_auto_uses_one_post_when_the_password_grant_works(tmp_path):
    idp = fakes.FakeParnasSys()
    authenticator, _, _ = make_authenticator(tmp_path, idp, method="auto")
    authenticator.get_access_token()
    assert len(idp.credential_posts()) == 1


# --------------------------------------------------------------------------------- latch


def test_a_rejected_password_sets_the_latch_and_reports_the_page_message(tmp_path):
    idp = fakes.FakeParnasSys()
    authenticator, store, _ = make_authenticator(tmp_path, idp, password="wrong-password-SECRET")
    with pytest.raises(CredentialsRejected, match="attempts remaining") as raised:
        authenticator.get_access_token()
    assert raised.value.exit_code == 4
    assert "attempts remaining" in (store.get_login_halted_reason() or "")
    assert TokenStore(store.path).get_login_halted_reason(), "the latch is on disk"


@pytest.mark.parametrize("method", ["login-form", "password-grant", "auto"])
def test_with_the_latch_set_automatic_login_sends_zero_requests(tmp_path, method):
    idp = fakes.FakeParnasSys()
    authenticator, store, _ = make_authenticator(tmp_path, idp, method=method)
    store.halt_logins("rejected earlier")
    for _ in range(3):
        with pytest.raises(LoginHalted, match="halted"):
            authenticator.get_access_token()
    assert idp.requests == []


def test_after_a_rejection_further_automatic_calls_send_nothing(tmp_path):
    idp = fakes.FakeParnasSys()
    authenticator, _, _ = make_authenticator(tmp_path, idp, password="wrong-password-SECRET")
    with pytest.raises(CredentialsRejected):
        authenticator.get_access_token()
    sent = len(idp.requests)
    for _ in range(5):
        with pytest.raises(LoginHalted):
            authenticator.get_access_token()
    assert len(idp.requests) == sent
    assert len(idp.credential_posts()) == 1


def test_explicit_login_clears_the_latch_and_spends_exactly_one_attempt(tmp_path):
    idp = fakes.FakeParnasSys()
    authenticator, store, _ = make_authenticator(tmp_path, idp)
    store.halt_logins("rejected earlier")
    authenticator.login()
    assert len(idp.credential_posts()) == 1
    assert store.get_login_halted_reason() is None


def test_explicit_login_with_a_wrong_password_sets_the_latch_again(tmp_path):
    idp = fakes.FakeParnasSys()
    authenticator, store, _ = make_authenticator(tmp_path, idp, password="wrong-password-SECRET")
    store.halt_logins("rejected earlier")
    with pytest.raises(CredentialsRejected):
        authenticator.login()
    assert len(idp.credential_posts()) == 1
    assert store.get_login_halted_reason()


def test_no_answer_after_the_password_counts_as_a_rejection(tmp_path):
    idp = fakes.FakeParnasSys(fail_network_on_form_post=True)
    authenticator, store, _ = make_authenticator(tmp_path, idp)
    with pytest.raises(CredentialsRejected, match="may have been checked"):
        authenticator.login()
    assert store.get_login_halted_reason()


def test_explicit_login_with_a_prompted_password(tmp_path):
    idp = fakes.FakeParnasSys()
    authenticator, _, _ = make_authenticator(tmp_path, idp, password=None)
    authenticator.login(password=fakes.CORRECT_PASSWORD)
    assert len(idp.credential_posts()) == 1


def test_missing_credentials(tmp_path):
    idp = fakes.FakeParnasSys()
    authenticator, _, _ = make_authenticator(tmp_path, idp, password=None)
    with pytest.raises(NotLoggedIn) as raised:
        authenticator.get_access_token()
    assert raised.value.exit_code == 3
    with pytest.raises(ConfigurationError):
        authenticator.login()
    assert idp.requests == []


# ------------------------------------------------------------------- refresh and the 401


def test_expired_access_token_is_refreshed_without_a_password(tmp_path):
    idp = fakes.FakeParnasSys()
    authenticator, _, clock = make_authenticator(tmp_path, idp)
    authenticator.login()
    clock.now += 4000
    assert authenticator.get_access_token() == fakes.REFRESHED_ACCESS_TOKEN
    assert len(idp.credential_posts()) == 1, "only the original login"


def test_a_401_refreshes_but_never_logs_in_with_a_password(tmp_path):
    idp = fakes.FakeParnasSys(refresh_works=False)
    authenticator, store, _ = make_authenticator(tmp_path, idp)
    authenticator.login()
    posts_before = len(idp.credential_posts())
    assert authenticator.refresh_after_unauthorized() is None
    assert len(idp.credential_posts()) == posts_before
    assert store.get_tokens().refresh_token == fakes.REFRESH_TOKEN, "refresh token is kept"


def test_a_401_with_a_working_refresh_returns_a_new_token(tmp_path):
    idp = fakes.FakeParnasSys()
    authenticator, _, _ = make_authenticator(tmp_path, idp)
    authenticator.login()
    assert authenticator.refresh_after_unauthorized() == fakes.REFRESHED_ACCESS_TOKEN


# ------------------------------------------------------------------- browser flow, logout


def test_browser_login_round_trip_checks_the_state(tmp_path):
    idp = fakes.FakeParnasSys()
    authenticator, store, _ = make_authenticator(tmp_path, idp, password=None)
    url = authenticator.start_browser_login()
    assert url.startswith("https://inloggen.parnassys.net/idp/oauth2/authorize?")
    state = fakes.query_of(url)["state"]
    with pytest.raises(LoginFailed, match="another login attempt"):
        authenticator.finish_browser_login(
            f"https://talk.parro.com/oauth2?code={fakes.AUTHORIZATION_CODE}&state=other"
        )
    authenticator.finish_browser_login(
        f"https://talk.parro.com/oauth2?code={fakes.AUTHORIZATION_CODE}&state={state}"
    )
    assert store.get_tokens().access_token == fakes.ACCESS_TOKEN
    assert store.get_pending_browser_login() is None
    assert idp.credential_posts() == []


def test_browser_login_finish_without_start(tmp_path):
    authenticator, _, _ = make_authenticator(tmp_path, fakes.FakeParnasSys())
    with pytest.raises(NotLoggedIn, match="login-url"):
        authenticator.finish_browser_login("abc")


def test_logout_revokes_both_tokens_and_keeps_the_latch(tmp_path):
    idp = fakes.FakeParnasSys()
    authenticator, store, _ = make_authenticator(tmp_path, idp)
    authenticator.login()
    store.halt_logins("kept on purpose")
    results = authenticator.logout()
    assert [(r.token_kind, r.status) for r in results] == [
        ("refresh_token", 200),
        ("access_token", 200),
    ]
    revokes = [fakes.form_of(r) for r in idp.requests if r.url.endswith("/revoke")]
    assert revokes[0]["token"] == fakes.REFRESH_TOKEN
    assert store.get_tokens().access_token is None
    assert store.get_login_halted_reason() == "kept on purpose"


# -------------------------------------------------------------------------- no secrets


def test_tokens_and_passwords_never_appear_in_logs_or_messages(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    messages: list[str] = []

    idp = fakes.FakeParnasSys(password_grant_enabled=False)
    authenticator, store, clock = make_authenticator(tmp_path, idp, method="auto")
    authenticator.login()
    clock.now += 4000
    authenticator.get_access_token()  # refresh
    authenticator.start_browser_login()
    authenticator.logout()

    wrong = fakes.FakeParnasSys()
    failing, _, _ = make_authenticator(tmp_path / "b", wrong, password="wrong-password-SECRET")
    for attempt in (failing.get_access_token, failing.get_access_token, failing.login):
        try:
            attempt()
        except Exception as error:
            messages.append(str(error))
            messages.append(repr(error))

    everything = caplog.text + "\n".join(messages) + repr(store.get_tokens())
    assert caplog.text, "the flows did log something"
    for secret in SECRETS:
        assert secret not in everything
