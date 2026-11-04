"""Fake HTTP transports, so no test touches the network.

FakeParnasSys plays the IdP: authorize → login page → form POST → code → token exchange, plus the
password grant, refresh and revoke. Switches on the instance choose how it behaves.
FakeParroApi plays rest-v2.parro.com from the samples/ files.
Both record every request in `.requests`.
"""

import json
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from parro.errors import NetworkError
from parro.http import HttpRequest, HttpResponse

IDP = "https://inloggen.parnassys.net"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
LOGIN_PAGE_HTML = (FIXTURES_DIR / "parnassys_login_page.html").read_text(encoding="utf-8")
# Where the authorize redirect chain ends (a session-bound page, see the fixture).
LOGIN_PAGE_URL = f"{IDP}/idp/?auth=REDACTED-SESSION-TOKEN"
REJECTED_PAGE_HTML = (
    '<html><body><ul class="feedbackPanel"><li class="feedbackPanelERROR">'
    "<span>Onjuiste inloggegevens. Account has 2 attempts remaining</span></li></ul>"
    "</body></html>"
)

# Values tests look for in logs and error messages: none of them may ever show up there.
USERNAME = "parent@example.com"
CORRECT_PASSWORD = "correct horse battery staple"
ACCESS_TOKEN = "access-token-SECRET-1"
REFRESHED_ACCESS_TOKEN = "access-token-SECRET-2"
REFRESH_TOKEN = "refresh-token-SECRET"
AUTHORIZATION_CODE = "authorization-code-SECRET"


def query_of(url: str) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


def form_of(request: HttpRequest) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl((request.body or b"").decode("utf-8")))


def json_response(status: int, payload: Any, url: str = IDP) -> HttpResponse:
    body = json.dumps(payload).encode("utf-8")
    return HttpResponse(status, {"content-type": "application/json"}, body, url)


@dataclass
class FakeParnasSys:
    """A scriptable ParnasSys IdP."""

    password: str = CORRECT_PASSWORD
    password_grant_enabled: bool = True  # False: invalid_grant even for the right password
    login_page_html: str = LOGIN_PAGE_HTML
    refresh_works: bool = True
    fail_network_on_form_post: bool = False
    requests: list[HttpRequest] = field(default_factory=list)
    _issued_state: str | None = None

    # --------------------------------------------------------------------------- counters

    def credential_posts(self) -> list[HttpRequest]:
        """Requests that carried a password: each one is a password check at the IdP."""
        return [r for r in self.requests if "password" in form_of(r) or "wachtwoord" in form_of(r)]

    # ---------------------------------------------------------------------------- routing

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        path = urllib.parse.urlsplit(request.url).path
        if request.method == "GET" and path == "/idp/oauth2/authorize":
            return self._login_page(request)
        if request.method == "POST" and "signInForm" in request.url:
            return self._form_post(request)
        if request.method == "GET" and path == "/idp/":
            return HttpResponse(200, {}, REJECTED_PAGE_HTML.encode(), request.url)
        if request.method == "POST" and path == "/idp/oauth2/token":
            return self._token(request)
        if request.method == "POST" and path == "/idp/oauth2/revoke":
            return HttpResponse(200, {}, b"", request.url)
        return HttpResponse(404, {}, b"not found", request.url)

    def _login_page(self, request: HttpRequest) -> HttpResponse:
        self._issued_state = query_of(request.url).get("state")
        return HttpResponse(200, {}, self.login_page_html.encode("utf-8"), LOGIN_PAGE_URL)

    def _form_post(self, request: HttpRequest) -> HttpResponse:
        if self.fail_network_on_form_post:
            raise NetworkError("No answer for POST login form: timed out")
        form = form_of(request)
        if form.get("wachtwoord") != self.password or form.get("aanmelden") != "x":
            return HttpResponse(302, {"location": "./?2"}, b"", request.url)
        location = (
            f"https://talk.parro.com/oauth2?code={AUTHORIZATION_CODE}&state={self._issued_state}"
        )
        return HttpResponse(302, {"location": location}, b"", request.url)

    def _token(self, request: HttpRequest) -> HttpResponse:
        query, form = query_of(request.url), form_of(request)
        grant = query.get("grant_type") or form.get("grant_type")
        if grant == "password":
            if self.password_grant_enabled and form.get("password") == self.password:
                return self._tokens(ACCESS_TOKEN)
            return json_response(
                400, {"error": "invalid_grant", "error_description": "Bad credentials"}
            )
        if grant == "authorization_code" and query.get("code") == AUTHORIZATION_CODE:
            return self._tokens(ACCESS_TOKEN)
        if (
            grant == "refresh_token"
            and self.refresh_works
            and query.get("refresh_token") == REFRESH_TOKEN
        ):
            return self._tokens(REFRESHED_ACCESS_TOKEN)
        return json_response(400, {"error": "invalid_grant"})

    @staticmethod
    def _tokens(access_token: str) -> HttpResponse:
        return json_response(
            200,
            {
                "access_token": access_token,
                "refresh_token": REFRESH_TOKEN,
                "token_type": "Bearer",
                "expires_in": 3599,
                "scope": "openid offline_access",
            },
        )


# -------------------------------------------------------------------------------- the API

GEON_TYPE = "application/vnd.topicus.geon+json;version=224"
API = "https://rest-v2.parro.com"


@dataclass
class FakeParroApi:
    """rest-v2.parro.com answering from samples/. Unknown routes answer 404.

    `load_sample` is injected so a missing samples/ folder skips the test instead of failing.
    `unauthorized_tokens` answer 401, like an expired or revoked token.
    """

    load_sample: Callable[[str], Any]
    idp: FakeParnasSys = field(default_factory=FakeParnasSys)
    unauthorized_tokens: set[str] = field(default_factory=set)
    attachment_bodies: dict[str, tuple[str, bytes]] = field(default_factory=dict)
    # Event ids that are calendar items: the announcement dtype answers 406 for them.
    calendar_event_ids: set[int] = field(default_factory=set)
    requests: list[HttpRequest] = field(default_factory=list)

    def api_requests(self) -> list[HttpRequest]:
        return [r for r in self.requests if r.url.startswith(API)]

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        if request.url.startswith(IDP):
            return self.idp.send(request)
        if request.url in self.attachment_bodies:
            content_type, body = self.attachment_bodies[request.url]
            return HttpResponse(200, {"content-type": content_type}, body, request.url)
        if not request.url.startswith(API):
            return HttpResponse(404, {}, b"", request.url)
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token in self.unauthorized_tokens or not token:
            return HttpResponse(401, {}, b"", request.url)
        return self._route(request)

    def _route(self, request: HttpRequest) -> HttpResponse:
        parts = urllib.parse.urlsplit(request.url)
        path, query = parts.path.removeprefix("/rest/v2"), query_of(request.url)
        single = {
            "/account/me": "getAccountMe.200.json",
            "/accountsettings": "getAccountSettings.200.json",
        }
        collections = {
            "/child": "listChildren.200.json",
            "/identity/unreadcounts": "getUnreadCounts.200.json",
            "/absence/setting": "getAbsenceSetting.200.json",
            "/systemnews": "listSystemNews.200.json",
            "/chatroom": "listChatrooms.200.json",
        }
        if path in single:
            return self._one(single[path], request.url)
        if path in collections:
            return self._collection(collections[path], request)
        if path.startswith("/organisation/"):
            return self._one("getOrganisation.200.json", request.url)
        if path == "/group":
            previous = query.get("scope") == "PREVIOUS_ACTIVE"
            return self._collection(
                "listGroups_previous.200.json" if previous else "listGroups.200.json", request
            )
        if path.startswith("/chatroom/") and path.endswith("/chatmessage"):
            return self._collection("listChatMessages.200.json", request)
        if path == "/event":
            return self._event_list(query, request)
        if path.startswith("/event/"):
            event_id = int(path.rsplit("/", 1)[-1])
            if (
                event_id in self.calendar_event_ids
                and query.get("dtype") != "event.RCalendarItemEvent"
            ):
                return HttpResponse(406, {"content-type": GEON_TYPE}, b"{}", request.url)
            return self._single_event(query.get("dtype"), request.url)
        return HttpResponse(404, {}, b'{"code": 404}', request.url)

    def _event_list(self, query: dict[str, str], request: HttpRequest) -> HttpResponse:
        if query.get("dtype") == "event.RAnnouncementEventPrimer":
            return self._collection("listEvents_announcements.200.json", request)
        if query.get("dtype") == "event.RCalendarItemEventPrimer":
            return self._collection("listEvents_calendar-items.200.json", request)
        return HttpResponse(406, {"content-type": GEON_TYPE}, b"{}", request.url)

    def _single_event(self, dtype: str | None, url: str) -> HttpResponse:
        # Spec: no dtype → 406; RAnnouncementEvent → 401 (!); the two concrete types → 200.
        if dtype is None:
            body = json.dumps(self.load_sample("getEvent.406.json")).encode()
            return HttpResponse(406, {"content-type": GEON_TYPE}, body, url)
        if dtype == "event.RAnnouncementEvent":
            return HttpResponse(401, {}, b"", url)
        if dtype == "event.RAnnouncementEventPrimer":
            return self._one("getEvent_announcement.200.json", url)
        if dtype == "event.RCalendarItemEvent":
            return self._one("getEvent_attachment.200.json", url)
        return HttpResponse(406, {"content-type": GEON_TYPE}, b"{}", url)

    def _one(self, sample_name: str, url: str) -> HttpResponse:
        body = json.dumps(self.load_sample(sample_name)).encode()
        return HttpResponse(200, {"content-type": GEON_TYPE}, body, url)

    def _collection(self, sample_name: str, request: HttpRequest) -> HttpResponse:
        """Answer 206 with a Content-Range, honouring the Range header like the real API."""
        items = self.load_sample(sample_name)["items"]
        first, last = 0, len(items) - 1
        requested = request.headers.get("Range", "")
        if requested.startswith("items="):
            low, _, high = requested.removeprefix("items=").partition("-")
            first, last = int(low), min(int(high), len(items) - 1)
        page = items[first : last + 1]
        content_range = f"items {first}-{max(first, last)}/{len(items)}"
        body = json.dumps({"items": page}).encode()
        return HttpResponse(
            206, {"content-type": GEON_TYPE, "content-range": content_range}, body, request.url
        )
