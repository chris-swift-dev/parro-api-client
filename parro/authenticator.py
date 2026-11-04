"""Authenticator: hands out a valid access token, and is the only place that decides to log in.

get_access_token() tries, in this order:
  1. the cached access token, while it is fresh;
  2. the refresh token (no password involved);
  3. an automatic login with the configured username and password, using the chosen method
     (PARRO_LOGIN_METHOD / --login-method: login-form, password-grant or auto).

The lockout latch (PLAN-api-client §3). The ParnasSys IdP locks the account after a few failed
logins. So when a password is rejected, the latch is saved in the token file at once, and from then
on every *automatic* login refuses with LoginHalted, before any request is sent. Only an explicit
login() (CLI `login`, MCP `parro_login`) clears the latch, and it then spends exactly one attempt
with the chosen method (`auto`: at most two, the password grant and then the form once).

Things this class never does:
  * log in with a password because the API answered 401 (see refresh_after_unauthorized());
  * log a token, password, code or verifier.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import login_methods
from .errors import (
    ConfigurationError,
    CredentialsRejected,
    LoginFailed,
    LoginHalted,
    NotLoggedIn,
    ParroError,
)
from .http import HttpTransport
from .pkce import create_pkce_pair, create_state
from .settings import LoginMethod, Settings
from .token_store import PendingBrowserLogin, TokenSet, TokenStore

log = logging.getLogger(__name__)

HOW_TO_LOG_IN = (
    "Log in first: set PARRO_USERNAME and PARRO_PASSWORD_FILE (or PARRO_PASSWORD) and run "
    "`parro_cli.py login` / call parro_login, or use the browser flow: `parro_cli.py login-url` "
    "then `parro_cli.py login-finish <redirect-url>` (MCP: parro_login_url, parro_login_finish)."
)


@dataclass(frozen=True)
class LoginStatus:
    """A snapshot for `status` / parro_auth_status. Holds no secrets."""

    token_file: str
    has_access_token: bool
    has_refresh_token: bool
    access_token_expires_in_seconds: int | None
    credentials_configured: bool
    login_method: LoginMethod
    login_halted_reason: str | None


class Authenticator:
    """Owns the token lifecycle for one Settings + TokenStore + HttpTransport."""

    def __init__(
        self,
        settings: Settings,
        transport: HttpTransport,
        token_store: TokenStore,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.token_store = token_store
        self.clock = clock

    # ----------------------------------------------------------------------- normal requests

    def get_access_token(self, allow_password_login: bool = True) -> str:
        """A usable access token: cached → refreshed → automatic login (if allowed).

        `allow_password_login=False` stops before step 3; `status` uses it, so that looking at
        the login state never spends a password check.
        """
        tokens = self.token_store.get_tokens()
        if tokens.access_token and tokens.has_fresh_access_token(self.clock()):
            return tokens.access_token
        refreshed = self._try_refresh(tokens)
        if refreshed is not None:
            return refreshed
        if not allow_password_login:
            raise NotLoggedIn(f"No valid token. {HOW_TO_LOG_IN}")
        return self._log_in_automatically()

    def refresh_after_unauthorized(self) -> str | None:
        """Called when the API answered 401: refresh once, never log in with a password.

        Returns the new access token, or None when no refresh was possible. The caller then
        reports the 401 instead of retrying (spec: a wrong `dtype` also answers 401).
        """
        return self._try_refresh(self.token_store.get_tokens())

    def _try_refresh(self, tokens: TokenSet) -> str | None:
        if not tokens.refresh_token:
            return None
        log.info("refreshing the access token")
        try:
            token_response = login_methods.refresh_access_token(
                self.settings, self.transport, tokens.refresh_token
            )
        except ParroError as failure:
            # Keep the refresh token: deleting it would lose a login over a temporary failure.
            log.warning("refresh failed: %s", failure)
            return None
        return self._store(token_response).access_token

    def _log_in_automatically(self) -> str:
        if not self.settings.has_credentials():
            raise NotLoggedIn(f"Not logged in to Parro. {HOW_TO_LOG_IN}")
        self.refuse_if_login_halted()
        log.info("logging in automatically with method %s", self.settings.login_method)
        tokens = self._log_in_once(self.settings.login_method, self._require_credentials())
        assert tokens.access_token  # _store() guarantees it
        return tokens.access_token

    def refuse_if_login_halted(self) -> None:
        """Raise LoginHalted while the latch is set. Sends nothing."""
        reason = self.token_store.get_login_halted_reason()
        if reason:
            raise LoginHalted(
                f"Automatic login is halted: the last login was rejected ({reason}). "
                "The IdP locks the account after a few failed attempts, so nothing is retried. "
                "Fix the password, then run `parro_cli.py login` (MCP: parro_login) to try once."
            )

    # ------------------------------------------------------------------------ explicit login

    def login(
        self,
        method: LoginMethod | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> TokenSet:
        """An explicit login by the user: clears the latch and spends one attempt.

        `username` / `password` override the configured ones (CLI `login --prompt`).
        """
        chosen_method = method or self.settings.login_method
        credentials = (
            (username or self.settings.username or "", password)
            if password is not None
            else self._require_credentials()
        )
        if not credentials[0]:
            raise ConfigurationError("No username: set PARRO_USERNAME (or use --prompt).")
        self.token_store.clear_login_halt()
        log.info("explicit login with method %s", chosen_method)
        return self._log_in_once(chosen_method, credentials)

    def _require_credentials(self) -> tuple[str, str]:
        password = self.settings.read_password()
        if not self.settings.username or not password:
            raise ConfigurationError(
                "PARRO_USERNAME and a password (PARRO_PASSWORD_FILE or PARRO_PASSWORD) are not "
                "both set. Use the browser flow (login-url / login-finish) instead, or "
                "`parro_cli.py login --prompt`."
            )
        return self.settings.username, password

    def _log_in_once(self, method: LoginMethod, credentials: tuple[str, str]) -> TokenSet:
        """One login with `method`. Sets the latch the moment a password is rejected."""
        username, password = credentials
        try:
            if method == "login-form":
                response = login_methods.login_with_login_form(
                    self.settings, self.transport, username, password
                )
            elif method == "password-grant":
                response = login_methods.login_with_password_grant(
                    self.settings, self.transport, username, password
                )
            else:
                response = self._log_in_with_auto(username, password)
        except CredentialsRejected as rejection:
            self.token_store.halt_logins(str(rejection))
            raise CredentialsRejected(
                f"Login rejected: {rejection}. Automatic logins are now halted so the account "
                "cannot be locked; fix the password, then run `parro_cli.py login` "
                "(MCP: parro_login) to try once more."
            ) from None
        self.token_store.clear_login_halt()
        return self._store(response)

    def _log_in_with_auto(self, username: str, password: str) -> dict[str, Any]:
        """Password grant first; if it fails, the login form exactly once (≤ 2 password checks)."""
        try:
            return login_methods.login_with_password_grant(
                self.settings, self.transport, username, password
            )
        except CredentialsRejected as grant_rejection:
            # invalid_grant also comes back for accounts that may only use the form (spec), so
            # the form gets one chance. Latch first, so a crash in between cannot lose it.
            self.token_store.halt_logins(str(grant_rejection))
            first_problem: ParroError = grant_rejection
        except LoginFailed as grant_failure:
            first_problem = grant_failure
        log.info("password grant did not work (%s); trying the login form once", first_problem)
        try:
            return login_methods.login_with_login_form(
                self.settings, self.transport, username, password
            )
        except LoginFailed as form_failure:
            if isinstance(first_problem, CredentialsRejected):
                raise CredentialsRejected(f"{first_problem}; then {form_failure}") from None
            raise

    # ------------------------------------------------------------------------- browser flow

    def start_browser_login(self) -> str:
        """Create a PKCE pair, remember it in the token file, return the URL to open."""
        pkce_pair, state = create_pkce_pair(), create_state()
        self.token_store.save_pending_browser_login(
            PendingBrowserLogin(verifier=pkce_pair.verifier, state=state)
        )
        return login_methods.build_authorize_url(self.settings, pkce_pair, state)

    def finish_browser_login(self, redirect_url_or_code: str) -> TokenSet:
        """Exchange the code from the redirect URL the user copied from the address bar.

        The latch is left alone: this login used a password typed in the browser, which says
        nothing about the configured one.
        """
        pending = self.token_store.get_pending_browser_login()
        if pending is None:
            raise NotLoggedIn("No browser login is in progress. Run login-url first.")
        redirect = login_methods.read_redirect_parameters(redirect_url_or_code)
        if redirect.error:
            raise LoginFailed(f"The IdP reported an error in the redirect: {redirect.error}")
        if not redirect.code:
            raise LoginFailed(
                "No `code` found. Paste the full https://talk.parro.com/oauth2?... URL."
            )
        if redirect.state is not None and pending.state and redirect.state != pending.state:
            raise LoginFailed(
                "This redirect belongs to another login attempt. Run login-url again."
            )
        response = login_methods.exchange_authorization_code(
            self.settings, self.transport, redirect.code, pending.verifier
        )
        return self._store(response)

    # ------------------------------------------------------------------------------- logout

    def logout(self) -> list[login_methods.RevocationResult]:
        """Revoke both tokens at the IdP and forget them locally. The latch stays."""
        tokens = self.token_store.get_tokens()
        results = []
        try:
            results = login_methods.revoke_tokens(
                self.settings,
                self.transport,
                {"refresh_token": tokens.refresh_token, "access_token": tokens.access_token},
            )
        finally:
            self.token_store.forget_tokens()
        return results

    # ------------------------------------------------------------------------------- status

    def get_login_status(self) -> LoginStatus:
        tokens = self.token_store.get_tokens()
        expires_in = (
            int(tokens.expires_at - self.clock()) if tokens.expires_at is not None else None
        )
        return LoginStatus(
            token_file=str(self.token_store.path),
            has_access_token=bool(tokens.access_token),
            has_refresh_token=bool(tokens.refresh_token),
            access_token_expires_in_seconds=expires_in,
            credentials_configured=self.settings.has_credentials(),
            login_method=self.settings.login_method,
            login_halted_reason=self.token_store.get_login_halted_reason(),
        )

    def _store(self, token_response: dict[str, Any]) -> TokenSet:
        return self.token_store.save_token_response(token_response)
