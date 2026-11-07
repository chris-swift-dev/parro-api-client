"""ParroClient: read-only access to the Parro REST API (https://rest-v2.parro.com/rest/v2).

get() is the one low-level call; every endpoint in the spec has a small method on top of it
(get_account, list_groups, list_events, get_event, ...). They return the API's own JSON, untouched;
summaries.py shapes it for people.

Rules for this module:
  * Only GET. There is no method that could change anything at Parro.
  * Requests only go to the configured API host, so a token can never be sent elsewhere.
  * A 401 leads to one refresh and one retry, never to a password login (PLAN-api-client §4, fix 3).
    A second 401 raises TokenRejected, which explains the `dtype` pitfall of GET /event/{id}.
"""

import logging
import urllib.parse
from dataclasses import dataclass
from typing import Any, Literal

from .authenticator import Authenticator
from .cache import Cache
from .errors import ApiError, ConfigurationError, TokenRejected
from .geon import (
    build_range_header,
    get_collection_items,
    get_object_id,
    parse_total_from_content_range,
)
from .http import HttpRequest, HttpResponse, HttpTransport, UrllibTransport, add_query_parameters
from .settings import Settings
from .token_store import TokenStore

log = logging.getLogger(__name__)

# dtype values that select what an endpoint returns (spec: GET /event, GET /event/{id}, GET /group).
ANNOUNCEMENT_LIST_DTYPE = "event.RAnnouncementEventPrimer"
CALENDAR_LIST_DTYPE = "event.RCalendarItemEventPrimer"
# RAnnouncementEvent answers 401 (not 406) on GET /event/{id}; the Primer type works (fix 2).
ANNOUNCEMENT_DTYPE = "event.RAnnouncementEventPrimer"
CALENDAR_ITEM_DTYPE = "event.RCalendarItemEvent"
CURRENT_GROUPS_DTYPE = "identity.RHomeGroup"
PREVIOUS_GROUPS_SCOPE = "PREVIOUS_ACTIVE"
# The groups request of the official client asks for 50; enough for any family.
GROUPS_PAGE_SIZE = 50
PRIVACY_CHILD_DTYPE = "identity.RPrivacySettingChild"

EventKind = Literal["announcement", "calendar"]


@dataclass(frozen=True)
class ApiResponse:
    """A parsed answer: the JSON payload and, for collections, the Content-Range header."""

    payload: Any
    content_range: str | None

    @property
    def items(self) -> list[Any]:
        return get_collection_items(self.payload)

    @property
    def total(self) -> int | None:
        return parse_total_from_content_range(self.content_range)


@dataclass(frozen=True)
class FeedEvent:
    """One event from a group's feed, with the name of the group it was listed under."""

    event: dict[str, Any]
    group_name: str | None


class ParroClient:
    """Talks to the Parro API on behalf of one logged-in account."""

    def __init__(
        self,
        settings: Settings,
        transport: HttpTransport | None = None,
        token_store: TokenStore | None = None,
        authenticator: Authenticator | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibTransport(settings.http_timeout_seconds)
        self.token_store = token_store or TokenStore(
            settings.token_file, bootstrap_access_token=settings.bootstrap_access_token
        )
        self.authenticator = authenticator or Authenticator(
            settings, self.transport, self.token_store
        )
        # Attachments and calendar details only (PLAN-readable-output §3b); lists never.
        self.cache = Cache(
            settings.data_dir / "cache", settings.cache_max_bytes, enabled=settings.cache_enabled
        )
        self._account: dict[str, Any] | None = None
        self._role_header: str | None = None

    @classmethod
    def from_environment(cls) -> "ParroClient":
        return cls(Settings.from_environment())

    # ------------------------------------------------------------------------- low level

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
        count_total: bool = False,
        send_role: bool = True,
        allow_password_login: bool = True,
        refresh_on_unauthorized: bool = True,
    ) -> ApiResponse:
        """GET an API path such as '/child' or '/event?dtype=...&group=1'.

        `limit` sends a Range header (and `count_total` asks for an exact total). `send_role`
        False leaves out parro-authorization-role, which GET /account/me must be called without.
        `refresh_on_unauthorized` False reports a 401 at once (for probing a dtype).
        """
        url = add_query_parameters(self.build_api_url(path), params or {})
        label = f"GET {urllib.parse.urlsplit(url).path}"
        headers = self._build_headers(limit, offset, count_total, send_role, allow_password_login)
        response = self._send_with_one_refresh(url, headers, label, refresh_on_unauthorized)
        if response.status not in (200, 206):
            raise _api_error(label, response)
        return ApiResponse(response.json(), response.header("Content-Range"))

    def download_from_api_host(self, url: str) -> HttpResponse:
        """GET a file that lives on the API host itself (not the CDN), with the Parro headers."""
        if not url.startswith(self.settings.api_base_uri + "/"):
            raise ConfigurationError("Only URLs on the configured Parro API host get a token.")
        headers = self._build_headers(None, 0, False, True, True)
        headers["Accept"] = "*/*"
        response = self._send_with_one_refresh(url, headers, "GET file on the API host", True)
        if response.status not in (200, 206):
            raise _api_error("GET file on the API host", response)
        return response

    def _send_with_one_refresh(
        self, url: str, headers: dict[str, str], label: str, refresh_on_unauthorized: bool
    ) -> HttpResponse:
        """Send; on a 401 refresh once and resend once (fix 3). A 401 never leads to a login."""
        response = self._send(url, headers, label)
        if response.status == 401 and refresh_on_unauthorized:
            new_access_token = self.authenticator.refresh_after_unauthorized()
            if new_access_token is not None:
                headers["Authorization"] = f"Bearer {new_access_token}"
                response = self._send(url, headers, label)
        if response.status == 401:
            raise TokenRejected(
                f"{label} answered 401 Unauthorized. Either the login is no longer valid (log "
                "in again), or this endpoint refuses the requested `dtype` (GET /event/{id} "
                "answers 401 for dtype=event.RAnnouncementEvent).",
                status=401,
            )
        return response

    def build_api_url(self, path: str) -> str:
        """Turn '/child' (or '/rest/v2/child') into a full URL on the configured API host."""
        cleaned = path.strip()
        if "://" in cleaned or cleaned.startswith("//"):
            raise ConfigurationError(
                "Give an API path such as /accountsettings, not a full URL: the token is only "
                "ever sent to the configured Parro API host."
            )
        if not cleaned.startswith("/"):
            cleaned = "/" + cleaned
        if cleaned.startswith("/rest/"):
            return self.settings.api_base_uri + cleaned
        return self.settings.api_root + cleaned

    def _build_headers(
        self,
        limit: int | None,
        offset: int,
        count_total: bool,
        send_role: bool,
        allow_password_login: bool,
    ) -> dict[str, str]:
        access_token = self.authenticator.get_access_token(allow_password_login)
        # The web client sends the geon media type as Accept *and* Content-Type, even on GET.
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": self.settings.geon_media_type,
            "Content-Type": self.settings.geon_media_type,
            "parro-app-version": self.settings.app_version,
        }
        if send_role:
            role = self.get_role_header(allow_password_login)
            if role:
                headers["parro-authorization-role"] = role
        if limit is not None:
            headers["Range"] = build_range_header(offset, limit)
            if count_total:
                headers["topicus-Range-Count"] = "Exact"
        return headers

    def _send(self, url: str, headers: dict[str, str], label: str) -> HttpResponse:
        return self.transport.send(HttpRequest("GET", url, dict(headers), log_label=label))

    # ---------------------------------------------------------------------- account and role

    def get_account(self, allow_password_login: bool = True) -> dict[str, Any]:
        """GET /account/me (cached). Called without the role header, which is derived from it."""
        if self._account is None:
            response = self.get(
                "/account/me", send_role=False, allow_password_login=allow_password_login
            )
            self._account = response.payload if isinstance(response.payload, dict) else {}
        return self._account

    def get_role_header(self, allow_password_login: bool = True) -> str | None:
        """'GUARDIAN:<id>' for parro-authorization-role: PARRO_ROLE, else derived and cached.

        The id is that of the first guardian (or teacher, or child) identity of the account
        (spec: Conventions → Client headers).
        """
        if self.settings.role_override:
            return self.settings.role_override
        if self._role_header is None:
            self._role_header = derive_role_header(self.get_account(allow_password_login))
        return self._role_header

    # -------------------------------------------------------------------- simple endpoints

    def get_account_settings(self) -> ApiResponse:
        return self.get("/accountsettings")

    def get_organisation(self, organisation_id: int) -> ApiResponse:
        return self.get(f"/organisation/{int(organisation_id)}")

    def list_children(self, limit: int = 20) -> ApiResponse:
        return self.get("/child", limit=limit, count_total=True)

    def get_unread_counts(self) -> ApiResponse:
        return self.get("/identity/unreadcounts")

    def list_groups(
        self, previous_year: bool = False, limit: int = GROUPS_PAGE_SIZE
    ) -> ApiResponse:
        """Current groups (dtype=identity.RHomeGroup) or last year's (scope=PREVIOUS_ACTIVE)."""
        params = (
            {"scope": PREVIOUS_GROUPS_SCOPE} if previous_year else {"dtype": CURRENT_GROUPS_DTYPE}
        )
        return self.get("/group", params, limit=limit, count_total=True)

    def list_system_news(self, limit: int = 20) -> ApiResponse:
        return self.get("/systemnews", limit=limit, count_total=True)

    def get_calendar_link(self) -> str | None:
        """GET /calendar/sync: the personal iCalendar subscription link, or None if there is none.

        The link is a secret (anyone holding it can read the calendar), so it is never logged.
        """
        payload = self.get("/calendar/sync").payload
        strings = payload.get("strings") if isinstance(payload, dict) else None
        links = [
            link for link in strings or [] if isinstance(link, str) and link.startswith("http")
        ]
        return links[0] if links else None

    def list_children_privacy(self) -> ApiResponse:
        """GET /child, privacy variant: per child, the state of the privacy choices (spec)."""
        params = {"currentSchoolYear": "true", "dtype": PRIVACY_CHILD_DTYPE}
        return self.get("/child", params, count_total=True)

    def get_privacy_link(self, child_id: int) -> str | None:
        """GET /child/{id}/privacy: the signed link to the page where the choices are set.

        Like the calendar link it is a secret (it opens the page without a login), so it is never
        logged, cached or archived.
        """
        payload = self.get(f"/child/{int(child_id)}/privacy").payload
        link = payload.get("url") if isinstance(payload, dict) else None
        return link if isinstance(link, str) and link.startswith("https://") else None

    def get_absence_settings(self) -> ApiResponse:
        return self.get("/absence/setting")

    def list_chatrooms(
        self, limit: int = 25, offset: int = 0, filters: dict[str, str] | None = None
    ) -> ApiResponse:
        """GET /chatroom. Without filters the API leaves out archived chats (spec: `archived`)."""
        return self.get("/chatroom", filters or None, limit=limit, offset=offset, count_total=True)

    def list_chat_messages(
        self,
        chatroom_id: int,
        limit: int = 30,
        offset: int = 0,
        created_since: str | None = None,
    ) -> ApiResponse:
        """Messages of one chat, newest first (spec); `created_since` (ISO 8601) only newer ones."""
        params = {"createdSince": created_since} if created_since else None
        return self.get(
            f"/chatroom/{int(chatroom_id)}/chatmessage",
            params,
            limit=limit,
            offset=offset,
            count_total=True,
        )

    def list_chatroom_members(
        self, chatroom_id: int, active_only: bool = True, limit: int = 100
    ) -> ApiResponse:
        """GET /chatroom/{id}/chatroommember: who is in a chat (spec)."""
        params = {"isActive": "true"} if active_only else None
        return self.get(
            f"/chatroom/{int(chatroom_id)}/chatroommember", params, limit=limit, count_total=True
        )

    # ---------------------------------------------------------------------------- events

    def list_events(
        self,
        group_id: int,
        event_dtype: str,
        limit: int = 20,
        offset: int = 0,
        count_total: bool = False,
    ) -> ApiResponse:
        """GET /event for one group. `event_dtype` picks announcements or calendar items.

        Both come newest first. For calendar items that means the furthest future first: the
        coming weeks can be several pages in (see operations.collect_calendar).
        """
        return self.get(
            "/event",
            {"dtype": event_dtype, "group": int(group_id)},
            limit=limit,
            offset=offset,
            count_total=count_total,
        )

    def get_event(self, event_id: int, event_dtype: str) -> dict[str, Any]:
        """GET /event/{id}. The dtype is required: without it the API answers 406."""
        payload = self.get(f"/event/{int(event_id)}", {"dtype": event_dtype}).payload
        return payload if isinstance(payload, dict) else {}

    def get_announcement(self, announcement_id: int) -> dict[str, Any]:
        return self.get_event(announcement_id, ANNOUNCEMENT_DTYPE)

    def get_calendar_item(self, event_id: int) -> dict[str, Any]:
        return self.get_event(event_id, CALENDAR_ITEM_DTYPE)

    def get_announcement_or_calendar_item(self, event_id: int) -> dict[str, Any]:
        """The event behind an id when the caller does not know its type (e.g. `attachment`).

        Tries the announcement type first without the usual refresh-on-401, because the API may
        answer a wrong dtype with 401 (spec) and that is not a reason to touch the tokens. Then
        tries the calendar-item type the normal way.
        """
        try:
            payload = self.get(
                f"/event/{int(event_id)}",
                {"dtype": ANNOUNCEMENT_DTYPE},
                refresh_on_unauthorized=False,
            ).payload
        except ApiError as first_failure:
            log.info(
                "event is not an announcement (%s); trying calendar item", first_failure.status
            )
            return self.get_calendar_item(event_id)
        return payload if isinstance(payload, dict) else {}

    def list_current_group_names(self) -> dict[int, str | None]:
        """{group id: group name} for this school year's groups, in the API's order."""
        names: dict[int, str | None] = {}
        for group in self.get(
            "/group", {"dtype": CURRENT_GROUPS_DTYPE}, limit=GROUPS_PAGE_SIZE
        ).items:
            group_id = get_object_id(group)
            if group_id is not None:
                names[group_id] = group.get("name")
        return names

    def collect_feed(
        self,
        event_dtype: str,
        group_id: int | None = None,
        limit_per_group: int = 20,
        groups: dict[int, str | None] | None = None,
    ) -> list[FeedEvent]:
        """Events of one group, or of every current group (the spec: query each group separately).

        Events carry the group's name only when several groups were merged. Not sorted: the caller
        decides the order. `groups` ({id: name}) saves the group request when the caller already
        has them, e.g. the overview, which reads two feeds.
        """
        if group_id is not None:
            chosen: dict[int, str | None] = {int(group_id): None}
        else:
            chosen = groups if groups is not None else self.list_current_group_names()
        collected: list[FeedEvent] = []
        for one_group_id, group_name in chosen.items():
            page = self.list_events(one_group_id, event_dtype, limit=limit_per_group)
            collected.extend(FeedEvent(event, group_name) for event in page.items)
        return collected


def derive_role_header(account: dict[str, Any]) -> str | None:
    """'<ACCOUNTTYPE>:<id>' from GET /account/me, or None when the account has no identities."""
    identity = account.get("identity") or {}
    account_type = str(account.get("accountType") or identity.get("role") or "GUARDIAN").upper()
    for identity_list in ("guardians", "teachers", "children"):
        for linked_identity in identity.get(identity_list) or []:
            identity_id = get_object_id(linked_identity)
            if identity_id is not None:
                return f"{account_type}:{identity_id}"
    log.warning("could not derive the role header from /account/me")
    return None


def _api_error(label: str, response: HttpResponse) -> ApiError:
    """An ApiError with the geon error details (applicationError, message) when there are any."""
    try:
        body = response.json()
    except ValueError:
        body = None
    application_error = None
    detail = ""
    if isinstance(body, dict):
        application_error = body.get("applicationError")
        parts = [str(part) for part in (application_error, body.get("message")) if part]
        detail = f": {' - '.join(parts)}" if parts else ""
    elif response.body:
        detail = f": {response.text()[:200]}"
    return ApiError(
        f"{label} answered HTTP {response.status}{detail}",
        status=response.status,
        application_error=application_error,
    )
