"""The one place where HTTP requests leave the process.

All network traffic goes through an HttpTransport. Production code uses UrllibTransport; tests pass
a fake transport, so no test ever touches the network.

Rules for this module:
  * It never raises for an HTTP status: 4xx/5xx come back as an HttpResponse, and the caller
    decides. Only "no answer at all" (DNS, refused connection, timeout) raises NetworkError.
  * It never logs a query string, a request body or a URL path: query strings carry OAuth codes
    and refresh tokens, bodies carry passwords, and attachment paths on the CDN are unsigned
    download links. Callers can pass a safe `log_label` instead.
"""

import http.cookiejar
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import __version__
from .errors import NetworkError

log = logging.getLogger(__name__)

USER_AGENT = f"parro-api-client/{__version__} (+reads; marks as read on request)"


@dataclass(frozen=True)
class HttpRequest:
    """One request. `follow_redirects=False` returns a 3xx response as-is (for its Location)."""

    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes | None = field(default=None, repr=False)
    follow_redirects: bool = True
    cookie_jar: http.cookiejar.CookieJar | None = field(default=None, repr=False)
    log_label: str | None = None


@dataclass(frozen=True)
class HttpResponse:
    """The answer to one request. Header names are stored in lower case."""

    status: int
    headers: dict[str, str]
    body: bytes = field(repr=False)
    final_url: str = field(repr=False)

    def header(self, name: str) -> str | None:
        """Look up a header case-insensitively."""
        return self.headers.get(name.lower())

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        """Parse the body as JSON. An empty body gives None."""
        text = self.text()
        return json.loads(text) if text.strip() else None


class HttpTransport(Protocol):
    """Anything that can send an HttpRequest. Tests implement this with canned responses."""

    def send(self, request: HttpRequest) -> HttpResponse: ...


class UrllibTransport:
    """HttpTransport backed by urllib from the standard library."""

    def __init__(self, timeout_seconds: float, user_agent: str = USER_AGENT) -> None:
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

    def send(self, request: HttpRequest) -> HttpResponse:
        return send_http_request(request, self.timeout_seconds, self.user_agent)


class _DoNotFollowRedirects(urllib.request.HTTPRedirectHandler):
    """Make urllib hand back a 3xx instead of following it.

    Returning None here makes urllib raise HTTPError for the 3xx, which send_http_request()
    turns into a normal HttpResponse, Location header included.
    """

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def send_http_request(
    request: HttpRequest, timeout_seconds: float, user_agent: str
) -> HttpResponse:
    """Send one request with urllib and return the answer, whatever its status."""
    opener = _build_opener(request)
    urllib_request = urllib.request.Request(
        request.url, data=request.body, method=request.method, headers=request.headers
    )
    if "User-Agent" not in request.headers:
        urllib_request.add_header("User-Agent", user_agent)
    label = request.log_label or describe_url_for_log(request.method, request.url)
    log.debug("HTTP %s", label)
    try:
        with opener.open(urllib_request, timeout=timeout_seconds) as answer:
            return HttpResponse(
                status=answer.status,
                headers=_lower_case_headers(answer.headers.items()),
                body=answer.read(),
                final_url=answer.geturl(),
            )
    except urllib.error.HTTPError as error_answer:
        # Not an error for us: the caller decides what a 4xx/5xx/3xx means.
        return HttpResponse(
            status=error_answer.code,
            headers=_lower_case_headers(error_answer.headers.items()),
            body=error_answer.read(),
            final_url=error_answer.geturl() or request.url,
        )
    except (TimeoutError, urllib.error.URLError, ConnectionError) as failure:
        reason = getattr(failure, "reason", failure)
        raise NetworkError(f"No answer for {label}: {reason}") from None


def _build_opener(request: HttpRequest) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = []
    if request.cookie_jar is not None:
        handlers.append(urllib.request.HTTPCookieProcessor(request.cookie_jar))
    if not request.follow_redirects:
        handlers.append(_DoNotFollowRedirects())
    return urllib.request.build_opener(*handlers)


def _lower_case_headers(pairs: Any) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, value in pairs:
        headers[str(name).lower()] = str(value)
    return headers


def describe_url_for_log(method: str, url: str) -> str:
    """A log-safe description of a request: method and host only, e.g. 'POST idp.example'.

    The path is left out on purpose: on the attachment CDN the path *is* the download key.
    """
    host = urllib.parse.urlsplit(url).hostname or "?"
    return f"{method} {host}"


def add_query_parameters(url: str, parameters: dict[str, Any]) -> str:
    """Append parameters to a URL, skipping None values, keeping any query already present."""
    present = {name: value for name, value in parameters.items() if value is not None}
    if not present:
        return url
    separator = "&" if urllib.parse.urlsplit(url).query else "?"
    return url + separator + urllib.parse.urlencode(present)
