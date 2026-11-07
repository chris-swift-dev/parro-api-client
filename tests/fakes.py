"""Fake HTTP transports, so no test touches the network.

FakeParnasSys plays the IdP: authorize → login page → form POST → code → token exchange, plus the
password grant, refresh and revoke. Switches on the instance choose how it behaves.
FakeParroApi plays rest-v2.parro.com from the samples/ files.
Both record every request in `.requests`.
"""

import dataclasses
import json
import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from parro.errors import NetworkError
from parro.geon import get_object_id
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

# Chat room types the API accepts in `chatRoom.type` (spec).
CHAT_TYPES = ("SINGLE", "BOT", "CALENDAR", "GROUP", "FAMILY")

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
# Ids from tests/fixtures/make_api_fixtures.py.
SCHOOLWIDE_GROUP, GROUP_3, GROUP_6 = 4000000001, 4000000002, 4000000003
DEFAULT_GROUP = GROUP_3  # its feed: 2 announcements, 1 calendar item
NEWSLETTER_ID = 5000000101  # announcement with a PDF
MUSEUM_TRIP_ID = 7000000301  # calendar item with a photo
DEFAULT_CALENDAR_EVENT = MUSEUM_TRIP_ID
GROUPS = (SCHOOLWIDE_GROUP, GROUP_3, GROUP_6)

# The only writes the client may send (parro.api_client.READ_STATE_WRITES). Any other method or
# path to the API fails the test that caused it, so every test checks the allowlist.
ALLOWED_WRITE_PATHS = re.compile(
    r"^/(event/\d+/read|chatroom/\d+/read|event/markannouncementsasread)$"
)


class ForbiddenWrite(AssertionError):
    """The client sent the API a request that is neither a GET nor an allowed PUT."""


@dataclass
class FakeParroApi:
    """rest-v2.parro.com answering from the invented fixtures in tests/fixtures/api/.

    Event lists are per group (`listEvents_announcements-<group>.200.json`), calendar details per
    event (`getEvent_calendar-<id>.200.json`); an unknown group or id gets a default file. Unknown
    routes answer 404. `unauthorized_tokens` answer 401, like an expired or revoked token.
    """

    load_sample: Callable[[str], Any]
    idp: FakeParnasSys = field(default_factory=FakeParnasSys)
    unauthorized_tokens: set[str] = field(default_factory=set)
    attachment_bodies: dict[str, tuple[str, bytes]] = field(default_factory=dict)
    # Event ids that are calendar items: the announcement dtype answers 406 for them.
    calendar_event_ids: set[int] = field(default_factory=set)
    requests: list[HttpRequest] = field(default_factory=list)
    # Read state set by the allowed PUTs; later GETs show these items as read.
    read_events: set[int] = field(default_factory=set)
    read_chats: set[int] = field(default_factory=set)

    def api_requests(self) -> list[HttpRequest]:
        return [r for r in self.requests if r.url.startswith(API)]

    def writes(self) -> list[str]:
        """'PUT /event/1/read' for every write the client sent, in order."""
        return [
            f"{r.method} {urllib.parse.urlsplit(r.url).path.removeprefix('/rest/v2')}"
            + (
                f"?{urllib.parse.urlsplit(r.url).query}"
                if urllib.parse.urlsplit(r.url).query
                else ""
            )
            for r in self.api_requests()
            if r.method != "GET"
        ]

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        if request.url.startswith(IDP):
            return self.idp.send(request)
        if request.url in self.attachment_bodies:
            content_type, body = self.attachment_bodies[request.url]
            return HttpResponse(200, {"content-type": content_type}, body, request.url)
        if not request.url.startswith(API):
            return HttpResponse(404, {}, b"", request.url)
        path = urllib.parse.urlsplit(request.url).path.removeprefix("/rest/v2")
        if request.method != "GET" and not (
            request.method == "PUT" and ALLOWED_WRITE_PATHS.match(path) and not request.body
        ):
            raise ForbiddenWrite(f"the client must never send {request.method} {path}")
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token in self.unauthorized_tokens or not token:
            return HttpResponse(401, {}, b"", request.url)
        if request.method == "PUT":
            return self._mark_read(path, query_of(request.url), request)
        return self._with_read_state(self._route(request))

    def _mark_read(self, path: str, query: dict[str, str], request: HttpRequest) -> HttpResponse:
        """The three PUT …/read calls: 204 without a body, as the real API answers."""
        if path == "/event/markannouncementsasread":
            group = query.get("group", "")
            if not group.isdigit():
                return HttpResponse(400, {"content-type": GEON_TYPE}, b'{"code": 400}', request.url)
            feed = f"listEvents_announcements-{group}.200.json"
            items = self.load_sample(feed)["items"] if self._has(feed) else []
            self.read_events.update(i for i in map(get_object_id, items) if i is not None)
        elif path.startswith("/chatroom/"):
            answer = self._chatroom_path(path.removesuffix("/read"), query, request)
            if answer.status == 403:
                return answer
            self.read_chats.add(int(path.split("/")[2]))
        else:
            self.read_events.add(int(path.split("/")[2]))
        return HttpResponse(204, {}, b"", request.url)

    def _with_read_state(self, response: HttpResponse) -> HttpResponse:
        """Show the items marked by earlier PUTs as read (`read`, `unreadCount`)."""
        if not (self.read_events or self.read_chats) or not response.body.startswith(b"{"):
            return response
        payload = json.loads(response.body)
        self._apply_read_state(payload)
        return dataclasses.replace(response, body=json.dumps(payload).encode())

    def _apply_read_state(self, value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                self._apply_read_state(item)
        elif isinstance(value, dict):
            dtype = str(value.get("dtype") or "")
            if dtype.startswith("event.") and get_object_id(value) in self.read_events:
                value["read"] = True
            if dtype.startswith("chat.RChatRoom") and get_object_id(value) in self.read_chats:
                value["unreadCount"] = 0
            for item in value.values():
                self._apply_read_state(item)

    def _route(self, request: HttpRequest) -> HttpResponse:
        parts = urllib.parse.urlsplit(request.url)
        path, query = parts.path.removeprefix("/rest/v2"), query_of(request.url)
        single = {
            "/account/me": "getAccountMe.200.json",
            "/accountsettings": "getAccountSettings.200.json",
            "/calendar/sync": "getCalendarSync.200.json",
        }
        collections = {
            "/child": "listChildren.200.json",
            "/identity/unreadcounts": "getUnreadCounts.200.json",
            "/absence/setting": "getAbsenceSetting.200.json",
            "/systemnews": "listSystemNews.200.json",
        }
        if path in single:
            return self._one(single[path], request.url)
        if path == "/child" and query.get("dtype") == "identity.RPrivacySettingChild":
            return self._collection("listChildren_privacy.200.json", request)
        if path.startswith("/child/") and path.endswith("/privacy"):
            name = f"getChildPrivacy_{path.split('/')[2]}.200.json"
            return self._one(name, request.url) if self._has(name) else self._not_found(request)
        if path.startswith("/calendaritem/"):
            item = self.load_sample("getCalendarItem.200.json")
            if path.rsplit("/", 1)[-1] == str(item["links"][0]["id"]):
                return self._one("getCalendarItem.200.json", request.url)
            return self._not_found(request)
        if path in collections:
            return self._collection(collections[path], request)
        if path.startswith("/organisation/"):
            return self._one("getOrganisation.200.json", request.url)
        if path == "/group":
            previous = query.get("scope") == "PREVIOUS_ACTIVE"
            return self._collection(
                "listGroups_previous.200.json" if previous else "listGroups.200.json", request
            )
        if path == "/chatroom":
            return self._chatrooms(query, request)
        if path.startswith("/chatroom/"):
            return self._chatroom_path(path, query, request)
        if path == "/event":
            return self._event_list(query, request)
        if path.startswith("/event/"):
            event_id = int(path.rsplit("/", 1)[-1])
            is_calendar_item = event_id in self.calendar_event_ids or self._has(
                f"getEvent_calendar-{event_id}.200.json"
            )
            if is_calendar_item and query.get("dtype") != "event.RCalendarItemEvent":
                return HttpResponse(406, {"content-type": GEON_TYPE}, b"{}", request.url)
            return self._single_event(event_id, query.get("dtype"), request.url)
        return self._not_found(request)

    def _not_found(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse(404, {}, b'{"code": 404}', request.url)

    def _event_list(self, query: dict[str, str], request: HttpRequest) -> HttpResponse:
        kinds = {
            "event.RAnnouncementEventPrimer": "announcements",
            "event.RCalendarItemEventPrimer": "calendar",
        }
        kind = kinds.get(query.get("dtype", ""))
        if kind is None:
            return HttpResponse(406, {"content-type": GEON_TYPE}, b"{}", request.url)
        specific = f"listEvents_{kind}-{query.get('group')}.200.json"
        name = specific if self._has(specific) else f"listEvents_{kind}-{DEFAULT_GROUP}.200.json"
        return self._collection(name, request)

    def _has(self, fixture_name: str) -> bool:
        try:
            self.load_sample(fixture_name)
        except FileNotFoundError:
            return False
        return True

    def _single_event(self, event_id: int, dtype: str | None, url: str) -> HttpResponse:
        # Spec: no dtype → 406; RAnnouncementEvent → 401 (!); the two concrete types → 200.
        if dtype is None:
            body = json.dumps(self.load_sample("getEvent.406.json")).encode()
            return HttpResponse(406, {"content-type": GEON_TYPE}, body, url)
        if dtype == "event.RAnnouncementEvent":
            return HttpResponse(401, {}, b"", url)
        if dtype == "event.RAnnouncementEventPrimer":
            event = self.load_sample("getEvent_announcement.200.json")
            for group in GROUPS:
                for item in self.load_sample(f"listEvents_announcements-{group}.200.json")["items"]:
                    if get_object_id(item) == event_id:
                        own_link = {**event["links"][0], "id": event_id}
                        event = {
                            **event,
                            "links": [own_link, *event["links"][1:]],
                            "read": item.get("read"),
                            "title": item.get("title"),
                        }
            body = json.dumps(event).encode()
            return HttpResponse(200, {"content-type": GEON_TYPE}, body, url)
        if dtype == "event.RCalendarItemEvent":
            specific = f"getEvent_calendar-{event_id}.200.json"
            default = f"getEvent_calendar-{DEFAULT_CALENDAR_EVENT}.200.json"
            return self._one(specific if self._has(specific) else default, url)
        return HttpResponse(406, {"content-type": GEON_TYPE}, b"{}", url)

    def _one_object(self, payload: dict[str, Any], url: str) -> HttpResponse:
        return HttpResponse(200, {"content-type": GEON_TYPE}, json.dumps(payload).encode(), url)

    def _one(self, sample_name: str, url: str) -> HttpResponse:
        body = json.dumps(self.load_sample(sample_name)).encode()
        return HttpResponse(200, {"content-type": GEON_TYPE}, body, url)

    def _chatrooms(self, query: dict[str, str], request: HttpRequest) -> HttpResponse:
        """GET /chatroom with the filters the real API applies (spec, live check 2026-11-07)."""
        rooms = self.load_sample("listChatrooms.200.json")["items"]
        archived = query.get("archived", "FALSE")
        chat_type = query.get("chatRoom.type")
        if archived not in ("FALSE", "TRUE", "BOTH") or (
            chat_type is not None and chat_type not in CHAT_TYPES
        ):
            body = b'{"code": 400, "message": "java.lang.IllegalArgumentException: No enum const"}'
            return HttpResponse(400, {"content-type": GEON_TYPE}, body, request.url)
        if archived != "BOTH":
            rooms = [r for r in rooms if r.get("archived") is (archived == "TRUE")]
        if chat_type is not None:
            rooms = [r for r in rooms if r.get("type") == chat_type]
        if query.get("read") == "false":
            rooms = [r for r in rooms if r.get("unreadCount")]
        return self._items(rooms, request)

    def _chatroom_path(
        self, path: str, query: dict[str, str], request: HttpRequest
    ) -> HttpResponse:
        """Calls on one chat room. The id must be the room's own (`rel: self`) id: the membership
        id (`koppeling`, the first link) answers 403, as the real API does."""
        room_id = int(path.split("/")[2])
        rooms = self.load_sample("listChatrooms.200.json")["items"]
        own_ids = {link["id"] for r in rooms for link in r["links"] if link["rel"] == "self"}
        if room_id not in own_ids:
            body = b'{"code": 403, "message": "CHAT_NOT_ACTIVE_MEMBER"}'
            return HttpResponse(403, {"content-type": GEON_TYPE}, body, request.url)
        if path.endswith("/chatmessage"):
            messages = self.load_sample("listChatMessages.200.json")["items"]
            since = query.get("createdSince")
            if since:
                limit = datetime.fromisoformat(since.replace("Z", "+00:00"))
                messages = [m for m in messages if datetime.fromisoformat(m["createdAt"]) >= limit]
            return self._items(messages, request)
        if path == f"/chatroom/{room_id}":
            room = next(r for r in rooms if get_object_id(r) == room_id)
            return self._one_object({**room, "dtype": "chat.RChatRoom"}, request.url)
        if path.endswith("/chatroommember"):
            members = self.load_sample("listChatroomMembers.200.json")["items"]
            if query.get("isActive") == "true":
                members = [m for m in members if m.get("active")]
            return self._items(members, request)
        return self._not_found(request)

    def _collection(self, sample_name: str, request: HttpRequest) -> HttpResponse:
        """Answer 206 with a Content-Range, honouring the Range header like the real API."""
        return self._items(self.load_sample(sample_name)["items"], request)

    def _items(self, items: list[Any], request: HttpRequest) -> HttpResponse:
        """A page of `items`: 206 with a Content-Range, honouring the Range header."""
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
