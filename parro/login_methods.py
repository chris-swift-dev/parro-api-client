"""One function per OAuth step against the ParnasSys IdP (spec: the "Auth" operations).

    build_authorize_url()          the browser login URL (authorization code + PKCE)
    login_with_login_form()        what a browser does: login page → form POST → code → tokens
    login_with_password_grant()    OAuth2 password grant (RFC 6749 §4.3)
    exchange_authorization_code()  code + PKCE verifier → tokens
    refresh_access_token()         refresh token → new tokens
    revoke_tokens()                logout (RFC 7009)

These functions return the IdP's token response as a dict and never store anything: the
Authenticator decides what to save and when to set the lockout latch.

How a rejected password is reported: CredentialsRejected. It is raised whenever a password left
this process and no tokens came back, unless the IdP's answer proves the password was never
checked. Unclear outcomes count as rejections on purpose: the IdP locks the account after a few
failures, so guessing "probably fine" could cost the user their account.

Passwords, codes, verifiers and tokens are never logged and never put into error messages.
"""

import http.cookiejar
import logging
import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from .errors import CredentialsRejected, LoginFailed, NetworkError
from .http import HttpRequest, HttpResponse, HttpTransport, add_query_parameters
from .pkce import CHALLENGE_METHOD, PkcePair, create_pkce_pair, create_state
from .settings import Settings

log = logging.getLogger(__name__)

FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"
# Field names of the ParnasSys login form (spec: POST /oauth2/token, fallback description).
# `aanmelden=x` is what the page's "Inloggen" button adds before submitting.
USERNAME_FIELD = "emailadres"
PASSWORD_FIELD = "wachtwoord"
SUBMIT_FIELD, SUBMIT_VALUE = "aanmelden", "x"
# Wicket names the form's action after its component path, which ends in "signInForm".
LOGIN_FORM_ACTION_MARKER = "signInForm"
# OAuth error codes that prove the IdP refused the request *before* looking at the password.
ERRORS_BEFORE_PASSWORD_CHECK = frozenset(
    {"invalid_request", "invalid_client", "unauthorized_client", "unsupported_grant_type"}
)
MAX_REASON_LENGTH = 200


@dataclass(frozen=True)
class RevocationResult:
    token_kind: str
    status: int


# --------------------------------------------------------------------------- browser login


def build_authorize_url(settings: Settings, pkce_pair: PkcePair, state: str) -> str:
    """The URL that starts a login in a browser. Only the challenge goes out, never the verifier."""
    return add_query_parameters(
        settings.authorize_endpoint,
        {
            "client_id": settings.client_id,
            "response_type": "code",
            "redirect_uri": settings.redirect_uri,
            "scope": settings.scope,
            "state": state,
            "code_challenge": pkce_pair.challenge,
            "code_challenge_method": CHALLENGE_METHOD,
        },
    )


@dataclass(frozen=True)
class RedirectResult:
    """What the IdP put in the redirect back to talk.parro.com."""

    code: str | None
    state: str | None
    error: str | None


def read_redirect_parameters(redirect_url_or_code: str) -> RedirectResult:
    """Parse 'https://talk.parro.com/oauth2?code=…&state=…', or accept a bare code."""
    text = redirect_url_or_code.strip()
    if "?" not in text and "=" not in text:
        return RedirectResult(code=text or None, state=None, error=None)
    query = urllib.parse.urlsplit(text).query if "?" in text else text
    parameters = dict(urllib.parse.parse_qsl(query))
    error = parameters.get("error")
    if error and parameters.get("error_description"):
        error = f"{error}: {parameters['error_description']}"
    return RedirectResult(
        code=parameters.get("code") or None, state=parameters.get("state"), error=error
    )


# ------------------------------------------------------------------------------ token calls


def exchange_authorization_code(
    settings: Settings, transport: HttpTransport, code: str, verifier: str
) -> dict[str, Any]:
    """Trade an authorization code for tokens."""
    parameters = {
        "grant_type": "authorization_code",
        "client_id": settings.client_id,
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": settings.redirect_uri,
    }
    response = _post_to_token_endpoint_with_query(settings, transport, parameters)
    if response.status != 200:
        raise LoginFailed(f"The code could not be exchanged for tokens: {_oauth_error(response)}")
    return _token_response(response)


def refresh_access_token(
    settings: Settings, transport: HttpTransport, refresh_token: str
) -> dict[str, Any]:
    """Get a new access token with the refresh token. Never involves the password."""
    parameters = {
        "grant_type": "refresh_token",
        "client_id": settings.client_id,
        "refresh_token": refresh_token,
    }
    response = _post_to_token_endpoint_with_query(settings, transport, parameters)
    if response.status != 200:
        raise LoginFailed(f"Refreshing the access token failed: {_oauth_error(response)}")
    return _token_response(response)


def _post_to_token_endpoint_with_query(
    settings: Settings, transport: HttpTransport, parameters: dict[str, str]
) -> HttpResponse:
    # The token endpoint takes code and refresh grants as query parameters with an empty body,
    # exactly like the web client sends them (spec: POST /oauth2/token, "Two request shapes").
    request = HttpRequest(
        method="POST",
        url=add_query_parameters(settings.token_endpoint, parameters),
        headers={"Accept": "*/*", "Content-Type": FORM_CONTENT_TYPE},
        body=b"",
        log_label=f"POST token endpoint ({parameters['grant_type']})",
    )
    return transport.send(request)


def login_with_password_grant(
    settings: Settings, transport: HttpTransport, username: str, password: str
) -> dict[str, Any]:
    """OAuth2 password grant: one password check. Raises CredentialsRejected unless it worked."""
    form = {
        "grant_type": "password",
        "client_id": settings.client_id,
        "username": username,
        "password": password,
        "scope": settings.scope,
    }
    # Unlike the other grants, this one sends a normal form body (spec: POST /oauth2/token).
    request = HttpRequest(
        method="POST",
        url=settings.token_endpoint,
        headers={"Accept": "application/json", "Content-Type": FORM_CONTENT_TYPE},
        body=urllib.parse.urlencode(form).encode("utf-8"),
        log_label="POST token endpoint (password)",
    )
    response = _send_after_password(transport, request)
    if response.status == 200:
        return _token_response(response)
    error_code = _oauth_error_code(response)
    if error_code in ERRORS_BEFORE_PASSWORD_CHECK:
        raise LoginFailed(f"The IdP refused the password grant: {_oauth_error(response)}")
    # invalid_grant means a wrong password, or an account the IdP will not put through this
    # grant (spec). Either way the attempt may have counted toward the lockout.
    raise CredentialsRejected(f"password grant rejected: {_oauth_error(response)}")


def revoke_tokens(
    settings: Settings, transport: HttpTransport, tokens_by_kind: dict[str, str | None]
) -> list[RevocationResult]:
    """Revoke each given token at the IdP (RFC 7009). Returns the HTTP status per token kind."""
    results = []
    for token_kind, token in tokens_by_kind.items():
        if not token:
            continue
        form = {"token": token, "token_type_hint": token_kind, "client_id": settings.client_id}
        request = HttpRequest(
            method="POST",
            url=settings.revoke_endpoint,
            headers={"Content-Type": FORM_CONTENT_TYPE},
            body=urllib.parse.urlencode(form).encode("utf-8"),
            log_label=f"POST revoke endpoint ({token_kind})",
        )
        results.append(RevocationResult(token_kind, transport.send(request).status))
    return results


# ------------------------------------------------------------------------------- login form


def login_with_login_form(
    settings: Settings, transport: HttpTransport, username: str, password: str
) -> dict[str, Any]:
    """Log in like a browser does: exactly one password check.

    Everything that can go wrong with the page layout is detected *before* the password is sent,
    so a changed login page costs no attempt (LoginFailed). After the POST, anything but a code
    counts as a rejection (CredentialsRejected).
    """
    pkce_pair, state = create_pkce_pair(), create_state()
    cookies = http.cookiejar.CookieJar()  # the login page is bound to a session cookie
    login_page = fetch_login_page(
        transport, build_authorize_url(settings, pkce_pair, state), cookies
    )
    form_action = find_login_form_action(login_page.text(), login_page.final_url)
    answer = submit_login_form(transport, form_action, username, password, cookies)
    location = answer.header("Location") or ""
    redirect = read_redirect_parameters(location) if "?" in location else None
    if redirect is None or redirect.code is None:
        raise CredentialsRejected(_describe_missing_code(transport, answer, location, cookies))
    if redirect.state != state:
        # The password was accepted, so this is not a rejection; but the code is not ours.
        raise LoginFailed("The login redirect carried an unexpected state. Please try again.")
    return exchange_authorization_code(settings, transport, redirect.code, pkce_pair.verifier)


def fetch_login_page(
    transport: HttpTransport, authorize_url: str, cookies: http.cookiejar.CookieJar
) -> HttpResponse:
    """GET the authorize URL, following redirects to the session-bound login page."""
    request = HttpRequest(
        method="GET",
        url=authorize_url,
        headers={"Accept": "text/html"},
        cookie_jar=cookies,
        log_label="GET authorize endpoint (login page)",
    )
    page = transport.send(request)
    if page.status != 200:
        raise LoginFailed(
            f"The login page did not load (HTTP {page.status}). No password was sent."
        )
    return page


def find_login_form_action(login_page_html: str, login_page_url: str) -> str:
    """The absolute URL the login form posts to. Raises LoginFailed if the page looks different.

    The action is relative to the page we ended up on after redirects, hence `login_page_url`.
    """
    finder = _LoginFormFinder()
    finder.feed(login_page_html)
    finder.close()
    candidates = [form for form in finder.forms if form.has_login_fields()]
    preferred = [form for form in candidates if LOGIN_FORM_ACTION_MARKER in form.action]
    chosen = (preferred or candidates)[0] if candidates else None
    if chosen is None or not chosen.action:
        raise LoginFailed(
            "The ParnasSys login page has no recognisable login form (the layout may have changed, "
            "or an extra step such as an account chooser is in the way). No password was sent."
        )
    return urllib.parse.urljoin(login_page_url, chosen.action)


def submit_login_form(
    transport: HttpTransport,
    form_action: str,
    username: str,
    password: str,
    cookies: http.cookiejar.CookieJar,
) -> HttpResponse:
    """POST the credentials once. The redirect is not followed: its Location holds the code."""
    form = {SUBMIT_FIELD: SUBMIT_VALUE, USERNAME_FIELD: username, PASSWORD_FIELD: password}
    request = HttpRequest(
        method="POST",
        url=form_action,
        headers={"Content-Type": FORM_CONTENT_TYPE, "Accept": "text/html"},
        body=urllib.parse.urlencode(form).encode("utf-8"),
        follow_redirects=False,
        cookie_jar=cookies,
        log_label="POST login form",
    )
    return _send_after_password(transport, request)


def _describe_missing_code(
    transport: HttpTransport,
    answer: HttpResponse,
    location: str,
    cookies: http.cookiejar.CookieJar,
) -> str:
    """Explain why no code came back, using the page's own error message when there is one."""
    page_html = answer.text()
    if 300 <= answer.status < 400 and location:
        # A redirect back to the login page: load it (a plain GET, no password) to read its message.
        follow_up = HttpRequest(
            method="GET",
            url=urllib.parse.urljoin(answer.final_url, location),
            headers={"Accept": "text/html"},
            cookie_jar=cookies,
            log_label="GET login page (reading the error message)",
        )
        try:
            page_html = transport.send(follow_up).text()
        except NetworkError:
            page_html = ""
    message = extract_error_message(page_html)
    detail = f": {message}" if message else " (the page gave no reason)"
    return (
        f"the login form did not accept the login{detail}. It may also need an extra step "
        "such as two-factor authentication"
    )[: MAX_REASON_LENGTH * 2]


def extract_error_message(page_html: str) -> str | None:
    """Visible text of the page's error/feedback elements, e.g. 'Account has 2 attempts left'."""
    collector = _ErrorTextCollector()
    collector.feed(page_html)
    collector.close()
    text = " ".join(" ".join(collector.parts).split())
    return text[:MAX_REASON_LENGTH] or None


@dataclass
class _HtmlForm:
    action: str
    input_names: set[str]

    def has_login_fields(self) -> bool:
        return {USERNAME_FIELD, PASSWORD_FIELD} <= self.input_names


class _LoginFormFinder(HTMLParser):
    """Collects every <form> with its action and the names of its <input> fields."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[_HtmlForm] = []
        self._current: _HtmlForm | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form":
            self._current = _HtmlForm(action=attributes.get("action") or "", input_names=set())
            self.forms.append(self._current)
        elif tag == "input" and self._current is not None and attributes.get("name"):
            self._current.input_names.add(attributes["name"] or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._current = None


class _ErrorTextCollector(HTMLParser):
    """Collects text inside elements that look like error messages (class or role based)."""

    MARKERS = ("error", "feedback", "alert", "melding", "fout")
    VOID_TAGS = frozenset({"br", "img", "input", "meta", "link", "hr", "source", "wbr"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._open_tags: list[bool] = []  # per open element: is it (inside) an error element?

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.VOID_TAGS:
            return
        attributes = dict(attrs)
        describing = f"{attributes.get('class') or ''} {attributes.get('role') or ''}".lower()
        inside_error = bool(self._open_tags and self._open_tags[-1])
        self._open_tags.append(inside_error or any(m in describing for m in self.MARKERS))

    def handle_endtag(self, tag: str) -> None:
        if tag not in self.VOID_TAGS and self._open_tags:
            self._open_tags.pop()

    def handle_data(self, data: str) -> None:
        if self._open_tags and self._open_tags[-1] and data.strip():
            self.parts.append(data.strip())


# ----------------------------------------------------------------------------------- helpers


def _send_after_password(transport: HttpTransport, request: HttpRequest) -> HttpResponse:
    """Send a request that carries the password. No answer counts as a possible rejection."""
    try:
        return transport.send(request)
    except NetworkError as failure:
        raise CredentialsRejected(
            f"no answer after the password was sent ({failure}); it may have been checked"
        ) from None


def _token_response(response: HttpResponse) -> dict[str, Any]:
    try:
        parsed = response.json()
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict) or not parsed.get("access_token"):
        raise LoginFailed("The token endpoint answered 200 but sent no access token.")
    return parsed


def _oauth_error_code(response: HttpResponse) -> str | None:
    try:
        parsed = response.json()
    except ValueError:
        return None
    return parsed.get("error") if isinstance(parsed, dict) else None


def _oauth_error(response: HttpResponse) -> str:
    """'HTTP 400 invalid_grant: description' from an RFC 6749 §5.2 error body."""
    try:
        parsed = response.json()
    except ValueError:
        parsed = None
    if isinstance(parsed, dict) and parsed.get("error"):
        description = parsed.get("error_description")
        text = f"{parsed['error']}: {description}" if description else str(parsed["error"])
    else:
        text = "no OAuth error in the answer"
    return f"HTTP {response.status} {text}"[:MAX_REASON_LENGTH]
