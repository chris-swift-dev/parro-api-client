#!/usr/bin/env python3
"""Build openapi/parro.openapi.json for the Parro "geon" REST API.

Operations, parameters, auth and descriptions are written by hand below.
Response schemas are INFERRED from the sanitized samples in samples/: one
component schema per geon `dtype`, with only the fields that occur in a sample.
Every sample is also embedded as a response example, so tools/validate_spec.py
can check the schemas against the real data.

Standard library only.  Usage:
    python3 tools/build_spec.py [--samples samples] [--out openapi/parro.openapi.json]
    python3 tools/build_spec.py --public --out _site/parro.openapi.json

--public leaves out every value copied from a sample (response examples and
property examples), for publishing. Schemas and descriptions are identical.
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT = "224"
APP_VERSION = "web:2.27.0"
GEON = "application/vnd.topicus.geon+json;version=" + CONTRACT
INT32_MAX = 2 ** 31 - 1

DATETIME_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d(:\d\d(\.\d{1,9})?)?(Z|[+-]\d\d:\d\d)$")
DATE_RE = re.compile(r"^\d{4}-\d\d-\d\d$")
CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

REF = "#/components/schemas/"
SPECIAL_FIELDS = {
    "links": {"type": "array", "items": {"$ref": REF + "GeonLink"},
              "description": "Hypermedia links; the `rel: self` entry carries the object's id."},
    "permissions": {"type": "array", "items": {"$ref": REF + "GeonPermission"},
                    "description": "What the caller may do with this object."},
    "additionalObjects": {"type": "object", "additionalProperties": True,
                          "description": "Side-loaded objects; empty in every sample."},
}


def ref(name):
    return {"$ref": REF + name}


def schema_name(dtype):
    """event.RAnnouncementEventPrimer -> AnnouncementEventPrimer"""
    last = dtype.split(".")[-1]
    if len(last) > 1 and last[0] == "R" and last[1].isupper():
        last = last[1:]
    return last


# --------------------------------------------------------------- inference
class Obj:
    def __init__(self, name, dtype):
        self.name, self.dtype = name, dtype
        self.fields = {}
        self.count = 0
        self.files = set()


class Field:
    def __init__(self):
        self.kinds = set()
        self.strings = []
        self.ints = []
        self.first = None
        self.dtypes = set()
        self.items = None
        self.plain = None

    def observe(self, value, key, model, src):
        if self.first is None and value is not None:
            self.first = value
        if value is None:
            self.kinds.add("null")
        elif isinstance(value, bool):
            self.kinds.add("boolean")
        elif isinstance(value, int):
            self.kinds.add("integer")
            self.ints.append(value)
        elif isinstance(value, float):
            self.kinds.add("number")
        elif isinstance(value, str):
            self.kinds.add("string")
            if value not in self.strings and len(self.strings) < 500:
                self.strings.append(value)
        elif isinstance(value, list):
            self.kinds.add("array")
            if self.items is None:
                self.items = Field()
            for el in value:
                self.items.observe(el, key, model, src)
        elif isinstance(value, dict):
            self.kinds.add("object")
            dt = value.get("dtype")
            if isinstance(dt, str):
                self.dtypes.add(dt)
                model.observe(schema_name(dt), value, dt, src)
            else:
                if self.plain is None:
                    self.plain = Obj(None, None)
                model.observe_into(self.plain, value, src)

    def emit(self, key, model):
        if key in SPECIAL_FIELDS:
            return dict(SPECIAL_FIELDS[key])
        kinds = self.kinds - {"null"}
        if not kinds:
            return {"description": "Only `null` observed in the samples."}
        if len(kinds) > 1:
            return {"description": "Observed types: {}.".format(", ".join(sorted(kinds)))}
        kind = kinds.pop()
        s = {}
        if kind == "object":
            if self.dtypes:
                s = model.ref_for(self.dtypes)
            elif self.plain is not None:
                s = model.emit_obj(self.plain)
            else:
                s = {"type": "object"}
        elif kind == "array":
            items = self.items.emit(key, model) if self.items and self.items.kinds else {}
            s = {"type": "array", "items": items}
            if not items:
                s["description"] = "Always empty in the samples; item type unknown."
        elif kind == "string":
            s = {"type": "string"}
            vals = self.strings
            if vals and all(DATETIME_RE.match(v) for v in vals):
                s["format"] = "date-time"
            elif vals and all(DATE_RE.match(v) for v in vals):
                s["format"] = "date"
            elif vals and all(v.startswith(("http://", "https://")) for v in vals):
                s["format"] = "uri"
            elif vals and all(CODE_RE.match(v) for v in vals) and len(vals) <= 10:
                s["description"] = "Observed values: {}. Not a closed list.".format(
                    ", ".join("`{}`".format(v) for v in vals))
            if isinstance(self.first, str) and len(self.first) <= 200 and not model.public:
                s["example"] = self.first
        elif kind == "integer":
            big = any(abs(i) > INT32_MAX for i in self.ints)
            idish = key == "id" or key.endswith("Id") or key == "size"
            s = {"type": "integer", "format": "int64" if (big or idish) else "int32"}
            if not model.public:
                s["example"] = self.first
        elif kind == "number":
            s = {"type": "number"} if model.public else {"type": "number", "example": self.first}
        elif kind == "boolean":
            s = {"type": "boolean"} if model.public else {"type": "boolean", "example": self.first}
        if "null" in self.kinds:
            s = {"allOf": [s], "nullable": True} if "$ref" in s else dict(s, nullable=True)
        return s


class Model:
    def __init__(self, public=False):
        self.types = {}
        self.public = public

    def observe(self, name, obj, dtype, src):
        t = self.types.get(name)
        if t is None:
            t = self.types[name] = Obj(name, dtype)
        if dtype and t.dtype and t.dtype != dtype:
            sys.exit("schema name clash: {} vs {}".format(t.dtype, dtype))
        self.observe_into(t, obj, src)

    def observe_into(self, t, obj, src):
        t.count += 1
        t.files.add(src)
        for k, v in obj.items():
            t.fields.setdefault(k, Field()).observe(v, k, self, src)

    def ref_for(self, dtypes):
        dtypes = sorted(dtypes)
        if len(dtypes) == 1:
            return ref(schema_name(dtypes[0]))
        return poly(*[schema_name(d) for d in dtypes], dtypes=dtypes)

    def emit_obj(self, t):
        props = {}
        if t.dtype:
            props["dtype"] = {"type": "string", "enum": [t.dtype], "example": t.dtype,
                              "description": "Geon type discriminator."}
        for k in t.fields:
            if k == "dtype" and t.dtype:
                continue
            props[k] = t.fields[k].emit(k, self)
        s = {"type": "object", "properties": props}
        if t.dtype:
            s["required"] = ["dtype"]
            s["description"] = "Geon type `{}`. Inferred from {} object(s) in: {}.".format(
                t.dtype, t.count, ", ".join("`{}`".format(f) for f in sorted(t.files)))
        return s


def poly(*names, dtypes=None):
    """oneOf over geon types, discriminated by dtype."""
    if dtypes is None:
        dtypes = [None] * len(names)
    mapping = {}
    for n, d in zip(names, dtypes):
        mapping[d or n] = REF + n
    return {"oneOf": [ref(n) for n in names],
            "discriminator": {"propertyName": "dtype", "mapping": mapping}}


# --------------------------------------------------------------- hand-written parts
DESCRIPTION = """\
Description of the REST API behind **talk.parro.com**, the Dutch parent–school
communication app by Topicus (ParnasSys). The API is a Topicus *geon* API. Every operation reads,
except the three under **Read state**, which mark items as read, `sendChatMessage`, which sends a
message to real people, `addCommitment` and `deleteCommitment` under **Helpers**, and `answerRsvp`
under **RSVP**.
This spec was derived from the web client's traffic: a captured browser session and sanitized response
samples. Response schemas list **only fields seen in those samples**. Treat every object as
open: geon adds fields between contract versions. Every operation here was called at least once;
two paths from the web app's code, `/conversations` and `/timeslot`, answered `404` and are left out.

**A client for this API:** [parro-api-client](https://github.com/chris-swift-dev/parro-api-client),
a command-line client and MCP server in plain Python that reads, and only when you ask marks items
as read and sends chat messages
([download a release](https://github.com/chris-swift-dev/parro-api-client/releases/latest)).

Inspired by [fobatai/parro-mcp](https://github.com/fobatai/parro-mcp), a read-only MCP server for Parro
whose working login and API calls were the starting point for this specification.

## Conventions
* **Media type**: `Accept: application/vnd.topicus.geon+json;version=224`. The official client also
  sends the same value as `Content-Type`, even on GET. Responses sometimes omit `;version=…`.
* **Client headers**: `parro-app-version: web:2.27.0` and `parro-authorization-role: GUARDIAN:<guardianId>`.
  Derive the role from `GET /account/me`, which is called *without* the role header:
  the id is the `rel: self` link id of the first entry in `identity.guardians`.
* **Polymorphism**: every object carries a `dtype` (e.g. `event.RAnnouncementEventPrimer`). Several
  endpoints select the returned type with a `dtype` query parameter.
* **Ids** are 64-bit integers, found in `links[rel=self].id`. `href` values point at item resources
  (`/child/{id}`, `/group/{id}`, …) that are not described here.
* **Collections** come as `{"items": [...]}`. They are paged with `Range: items=<from>-<to>` and answer
  `206 Partial Content` with `Content-Range: items 0-1/2`, **even without a `Range` header**
  (the server's default page size is unknown). Add `topicus-Range-Count: Exact` to get an exact total.
* **Dates** are ISO-8601 with an offset. Fractional seconds vary from none to 3 digits.
* **CORS preflights** answer `Access-Control-Allow-Methods: DELETE, POST, GET, OPTIONS, PUT` on
  every path, even read-only ones such as `/child`. It is a server-wide setting and says nothing
  about which methods a path supports.

## Authentication
OAuth2 against the ParnasSys IdP (`https://inloggen.parnassys.net`, see the **Auth** operations).
The public client `MQygAaSBUcAgPU2WInKt` is pinned to the redirect URI `https://talk.parro.com/oauth2`.
There is no dynamic client registration or device grant, and loopback redirects are rejected.
* **Authorization code + PKCE (S256)**: browser login. Copy the `code` from the redirect URL quickly,
  because the web app also tries to redeem it and a code works only once.
* **Password grant**: `grant_type=password`, enabled for this client.
* A login lasts at most **8 hours**: the refresh token expires 8 hours after the login, also with scope
  `openid offline_access`, and a refresh returns a new refresh token with the same expiry (measured
  2026-11-06). The access token lasts 1 hour.
* The IdP **locks the account after a few failed logins**. Never retry a rejected password automatically.

## Attachments
Attachment entries carry a CloudFront `url`. It is **unsigned and needs no authentication**: anyone holding
it can download the file, so treat these URLs as secrets. Never send the Parro `Authorization` header to the CDN.
Document entries also carry `expiresAt`, exactly one year after the announcement in the sample. Whether the CDN
enforces it is unknown.
Announcements keep attachments in `attachments[]`; calendar items in `calendarItem.attachments[]`.
Choose the parser by `contentType`, not by the entry's `dtype`: a photo's SOURCE entry can be a
`RAttachmentDocumentEntry`.

## Trying it out
Paste an access token into **Authorize → bearerToken**. "Try it out" then works for the API operations,
including from a Swagger UI hosted on GitHub Pages: the API accepts cross-origin requests. The generated
curl commands include the token as well.

> ⚠️ **Logging in does not work from Swagger UI.** Leave the **parnassysOAuth** scheme and the **Auth**
> operations alone in the browser, and get the token outside it (see `/oauth2/token`):
> * *Authorization code*: the redirect URI is pinned to `https://talk.parro.com/oauth2`, so Swagger UI never
>   receives the code.
> * *Password*: the IdP answers `invalid_grant` for accounts it will not put through the password grant
>   (seen in practice), and cross-origin calls to the IdP are untested. **Every rejected attempt can count
>   toward the account lockout**, including the "Request body" variant, whose response the page may not
>   even be allowed to read.
"""

ERR_DESC = ("Geon error body, e.g. `406` with `applicationError: EVENT_BAD_TYPE` when `/event/{id}` "
            "is called without a usable `dtype`.")


def build(samples_dir, public=False):
    model = Model(public)
    samples, used = {}, set()
    for fn in sorted(os.listdir(samples_dir)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(samples_dir, fn)
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        samples[fn] = json.loads(raw) if raw.strip() else None

    def walk(x, src):
        if isinstance(x, dict):
            dt = x.get("dtype")
            if isinstance(dt, str):
                model.observe(schema_name(dt), x, dt, src)
                return
            for v in x.values():
                walk(v, src)
        elif isinstance(x, list):
            for v in x:
                walk(v, src)

    plain_roots = {"discovery.200.json": "OpenIDConfiguration",
                   "token.200.json": "OAuthTokenResponse",
                   "getEvent.406.json": "GeonError"}
    for fn, data in samples.items():
        if data is None:
            continue
        if fn in plain_roots:
            model.observe(plain_roots[fn], data, None, fn)
        else:
            walk(data, fn)

    def examples(*files):
        out = {}
        for fn in files:
            if fn not in samples:
                sys.exit("missing sample: " + fn)
            used.add(fn)
            if samples[fn] is not None:
                out[fn.rsplit(".", 2)[0]] = {"summary": "samples/" + fn, "value": samples[fn]}
        return out

    def collection(item_schema):
        return {"type": "object", "required": ["items"],
                "properties": {"items": {"type": "array", "items": item_schema}}}

    def content(schema, files, media=GEON):
        c = {"schema": schema}
        ex = examples(*files) if files else {}
        if ex and not public:
            c["examples"] = ex
        return {media: c}

    std_err = {"401": {"$ref": "#/components/responses/Unauthorized"},
               "default": {"$ref": "#/components/responses/GeonErrorResponse"}}

    def op(op_id, tag, summary, schema, files, desc=None, coll=False, role=True, params=(),
           extra=None):
        p = [{"$ref": "#/components/parameters/AppVersion"}]
        if role:
            p.append({"$ref": "#/components/parameters/Role"})
        if coll:
            p += [{"$ref": "#/components/parameters/Range"},
                  {"$ref": "#/components/parameters/RangeCount"}]
        p += list(params)
        if coll:
            body = collection(schema)
            responses = {
                "206": {"description": "A page of the collection (observed even without `Range`).",
                        "headers": {"Content-Range": {"$ref": "#/components/headers/ContentRange"}},
                        "content": content(body, files)},
                "200": {"description": "Same body as 206. Not observed for paged lists, but clients should accept it.",
                        "content": {GEON: {"schema": body}}},
            }
        else:
            responses = {"200": {"description": "OK", "content": content(schema, files)}}
        responses.update(extra or {})
        responses.update(std_err)
        o = {"tags": [tag], "operationId": op_id, "summary": summary, "parameters": p,
             "responses": responses}
        if desc:
            o["description"] = desc
        return o

    def q(name, schema, desc, required=False):
        return {"name": name, "in": "query", "required": required, "schema": schema,
                "description": desc}

    id_param = {"name": "id", "in": "path", "required": True,
                "schema": {"type": "integer", "format": "int64"}}

    event_list_item = poly("AnnouncementEventPrimer", "CalendarItemEventPrimer",
                           dtypes=["event.RAnnouncementEventPrimer", "event.RCalendarItemEventPrimer"])
    event_item = poly("AnnouncementEventPrimer", "CalendarItemEvent",
                      dtypes=["event.RAnnouncementEventPrimer", "event.RCalendarItemEvent"])
    group_item = poly("HomeGroup", "GroupPrimer",
                      dtypes=["identity.RHomeGroup", "identity.RGroupPrimer"])

    paths = {
        "/account/me": {"get": op(
            "getAccountMe", "Account", "The logged-in account, its identity, school and guardian ids",
            ref("Account"), ["getAccountMe.200.json"], role=False,
            desc="Call **without** `parro-authorization-role`; the role is derived from this response.")},
        "/accountsettings": {"get": op(
            "getAccountSettings", "Account", "Notification, digest, translation and chat preferences",
            ref("AccountSettings"), ["getAccountSettings.200.json"])},
        "/organisation/{id}": {"get": op(
            "getOrganisation", "Account", "The school (organisation)", ref("OrganisationPrimer"),
            ["getOrganisation.200.json"], params=[dict(id_param, description="From `/account/me` → `organisation`.")])},
        "/child": {"get": op(
            "listChildren", "Account", "Children linked to the account",
            poly("ChildPrimer", "PrivacySettingChild",
                 dtypes=["identity.RChildPrimer", "identity.RPrivacySettingChild"]),
            ["listChildren.200.json", "listChildren_privacy.200.json"], coll=True,
            desc="Without parameters: `RChildPrimer` per child. With "
                 "`currentSchoolYear=true&dtype=identity.RPrivacySettingChild` (what the web app sends "
                 "for its privacy page): `RPrivacySettingChild`, the same fields plus `setting`, the "
                 "state of the child's privacy choices: `editableForGuardians`, `editableInPeriod`, "
                 "`state` and who changed them last. The choices themselves are not in the API; "
                 "`GET /child/{id}/privacy` gives the link to the page where they are set.",
            params=[q("dtype", {"type": "string", "enum": ["identity.RPrivacySettingChild"]},
                      "Return the privacy variant."),
                    q("currentSchoolYear", {"type": "boolean"},
                      "Sent with the privacy variant by the web app; its effect is unknown.")])},
        "/child/{id}/privacy": {"get": op(
            "getChildPrivacy", "Account", "Link to the page where a child's privacy choices are set",
            ref("PrivacySettings"), ["getChildPrivacy.200.json"],
            desc="`url` is a link to `https://start.parnassys.net/bao/privacy?signedpermission=<signature>`, "
                 "the ParnasSys page where a parent sets the child's privacy choices (photos, data). "
                 "`defined` was `true` in the capture.\n\n"
                 "⚠️ **The link is signed**: it opens the page without a login. Treat it as a secret; "
                 "do not share or log it.",
            params=[dict(id_param, description="Child id from `GET /child`.")])},
        "/identity/unreadcounts": {"get": op(
            "getUnreadCounts", "Account", "Unread counts per category, per guardian identity",
            ref("UnreadCount"), ["getUnreadCounts.200.json"], coll=True)},
        "/group": {"get": op(
            "listGroups", "Groups", "Classes and school-wide groups", group_item,
            ["listGroups.200.json", "listGroups_previous.200.json"], coll=True,
            desc="Pass **either** `dtype=identity.RHomeGroup` (current school year, returns `RHomeGroup` "
                 "with `lastAnnouncement`) **or** `scope=PREVIOUS_ACTIVE` (last school year, returns "
                 "`RGroupPrimer`). The group ids feed `GET /event?group=`.",
            params=[q("dtype", {"type": "string", "enum": ["identity.RHomeGroup"]}, "Current groups."),
                    q("scope", {"type": "string", "enum": ["PREVIOUS_ACTIVE"]}, "Previous school year.")])},
        "/event": {"get": op(
            "listEvents", "Events", "Announcements or calendar items of one group", event_list_item,
            ["listEvents_announcements.200.json", "listEvents_calendar-items.200.json"], coll=True,
            desc="The main feed. Query each group separately and merge by `sortDate`.\n\n"
                 "**Order: newest first.** For calendar items that means the *furthest future* first: "
                 "in a live check (2026-11-05) a whole-school group's first 50 of 100 items lay 6 to 9 "
                 "months ahead, so the coming weeks were on page 2. Page with `Range` until the dates "
                 "reach today.\n\n"
                 "**Duplicates:** an announcement sent to several groups is returned once per group "
                 "(same id; 2 of 71 events in that check). Merge by id.\n\n"
                 "**Multi-day calendar items come once per day**: each day is its own entry with its "
                 "own event id, `dayNumber` (1..`numberOfDays`) and `sortDate`, all sharing one "
                 "`calendarItem` (same id, `startDate`, `endDate`, `dayDates`). In that check one 40-day "
                 "item gave 40 entries. Merge by `calendarItem` id.\n\n"
                 "**No read filter:** `read=false` is accepted and ignored (live check 2026-11-07: the same "
                 "36 announcements with and without it, 3 of them unread). Filter on `read` yourself.",
            params=[q("dtype", {"type": "string", "enum": ["event.RAnnouncementEventPrimer",
                                                           "event.RCalendarItemEventPrimer"]},
                      "Which event type to list.", required=True),
                    q("group", {"type": "integer", "format": "int64"},
                      "Group id from `GET /group`.", required=True)])},
        "/event/{id}": {"get": op(
            "getEvent", "Events", "One announcement or calendar item", event_item,
            ["getEvent_announcement.200.json", "getEvent.200.json", "getEvent_attachment.200.json"],
            desc="`dtype` is required. Without it the API answers `406 EVENT_BAD_TYPE` (abstract "
                 "supertype `RAbstractEvent`). **Pitfall:** `dtype=event.RAnnouncementEvent` answers "
                 "**401**, not 406. Use `event.RAnnouncementEventPrimer` for announcements. A client that "
                 "treats every 401 as an expired token will loop through logins.",
            params=[dict(id_param, description="Event id (`links[rel=self].id` from `GET /event`)."),
                    q("dtype", {"type": "string", "enum": ["event.RAnnouncementEventPrimer",
                                                           "event.RCalendarItemEvent"]},
                      "Concrete event type.", required=True)],
            extra={"406": {"description": "Missing or abstract `dtype`.",
                           "content": content(ref("GeonError"), ["getEvent.406.json"])}})},
        "/calendar/sync": {"get": op(
            "getCalendarSync", "Events", "Personal iCalendar link for subscribing to the agenda",
            ref("Strings"), ["getCalendarSync.200.json"],
            desc="Returns the account's personal **agenda subscription link** in `strings[0]`: "
                 "`https://calendar.parro.com/ical/<calendarId>/<token>?noCache=<uuid>`. Calendar apps "
                 "(Google, Apple, Outlook) subscribe to it and update by themselves; this is what the "
                 "app's \"sync the agenda\" option copies.\n\n"
                 "⚠️ **The link is a secret**: anyone who has it can read the calendar, without logging "
                 "in. Do not share or log it.\n\n"
                 "Checked live (2026-11-05):\n"
                 "* `calendarId` is none of the account, identity, guardian or organisation ids.\n"
                 "* The token stays the same across calls; only `noCache` changes. The link works without "
                 "`noCache` (same content, same ETag).\n"
                 "* `GET` on the link needs no authentication and answers `200 text/calendar` "
                 "(iCalendar with VTIMEZONE, `REFRESH-INTERVAL` and `X-PUBLISHED-TTL` of 1 hour). It "
                 "holds the school year's items, each multi-day item once.\n\n"
                 "Not verified: ParnasSys lists agenda syncing as a feature of the paid *Parro "
                 "Ouderapp*, so with *Parro Basis* this call may fail or return no link.")},
        "/calendaritem/{id}": {"get": op(
            "getCalendarItem", "Events", "One calendar item, directly",
            ref("CalendarItem"), ["getCalendarItem.200.json"],
            desc="The same `calendar.RCalendarItem` that `GET /event/{id}` embeds as `calendarItem` "
                 "(without `lastEditedBy`), addressed by the calendar item's own id.\n\n"
                 "Items of `type: VOLUNTEER` or `SCHOOLWIDE_VOLUNTEER` (seen live) ask for helpers: "
                 "each entry in `resources[]` "
                 "(`RCalendarItemVolunteerResource`) has a `title`, `amount` (helpers wanted), "
                 "`amountCommitted`, `commitedByMe` (sic) and `commitments[]`, which lists only your own. "
                 "`numberOfTimeslots` "
                 "and the `RCalendarItemTimeslotCreate` permission point to timeslots (e.g. "
                 "parent–teacher talks) that hang off calendar items; their path is not known.",
            params=[dict(id_param, description="Calendar item id (`calendarItem.links[rel=self].id` "
                                               "from `GET /event`).")])},
        "/systemnews": {"get": op(
            "listSystemNews", "Misc", "Product news from Parro itself", ref("SystemNewsEvent"),
            ["listSystemNews.200.json"], coll=True)},
        "/absence/setting": {"get": op(
            "getAbsenceSetting", "Misc", "Absence-reporting settings",
            {"$ref": REF + "GeonObject"}, ["getAbsenceSetting.200.json"], coll=True,
            desc="Returned `{\"items\": []}` in every capture, so the item type is unknown.")},
        "/absence": {"get": op(
            "listAbsences", "Misc", "Absence reports",
            {"$ref": REF + "GeonObject"}, ["listAbsences.200.json"], coll=True,
            desc="Returned an empty page (`Content-Range: items 0-0/0`) in the only capture, so the "
                 "item type is unknown. Reporting an absence is a write and is not described.")},
        "/media-export": {"get": op(
            "getMediaExport", "Misc", "Media exports",
            {"$ref": REF + "GeonObject"}, ["getMediaExport.200.json"], coll=True,
            desc="Answered `200` with `{\"items\": []}` (no `Content-Range`) in the only capture, so "
                 "the item type is unknown. Probably the photo exports a parent has requested; "
                 "requesting one is a write and is not described.")},
        "/media-export/settings": {"get": op(
            "getMediaExportSettings", "Misc", "Whether the school allows downloading photos",
            ref("MediaExportSettings"), ["getMediaExportSettings.200.json"])},
        "/chatroom": {"get": op(
            "listChatrooms", "Chat", "Chat conversations", ref("ChatRoomPrimer"),
            ["listChatrooms.200.json", "listChatrooms_archived.200.json",
             "listChatrooms_schoolyear.200.json", "listChatrooms_type-group.200.json"], coll=True,
            desc="**The chat room's id is its `rel: self` link.** The first link is `koppeling` (your "
                 "membership); using that id answers `403 CHAT_NOT_ACTIVE_MEMBER` on every chat call.\n\n"
                 "Filters (live check 2026-11-07): `chatRoom.type`, `read`, `archived` and "
                 "`chatRoom.createdInSchoolyear`; an unknown enum value answers `400`.",
            params=[
                q("chatRoom.type", {"type": "string", "enum": ["SINGLE", "BOT", "CALENDAR", "GROUP", "FAMILY"]},
                  "Only chats of this type."),
                q("read", {"type": "boolean"}, "`false`: only chats with unread messages."),
                q("archived", {"type": "string", "enum": ["FALSE", "TRUE", "BOTH"], "default": "FALSE"},
                  "Uppercase only (`true` answers `400`). Without it: the chats that are not archived."),
                q("chatRoom.createdInSchoolyear", {"type": "integer", "example": 2025},
                  "Chats created in this school year (`GET /chatroom/schoolyears` lists them)."),
            ])},
        "/chatroom/schoolyears": {"get": op(
            "listChatSchoolyears", "Chat", "School years that have chats",
            collection(ref("Schoolyear")), ["listChatSchoolyears.200.json"],
            desc="The values `chatRoom.createdInSchoolyear` accepts, newest first. A plain list: "
                 "answered with `200` and no `Content-Range`.")},
        "/chatroom/{id}": {"get": op(
            "getChatroom", "Chat", "One chat conversation", ref("ChatRoom"), ["getChatroom.200.json"],
            desc="The full chat room, with its members.",
            params=[dict(id_param, description="Chatroom id: the `rel: self` link of `GET /chatroom`.")],
            extra={"403": {"description": "`CHAT_NOT_ACTIVE_MEMBER`: not a member, or the membership "
                                          "(`koppeling`) id was used instead of the chat room's own id."}})},
        "/chatroom/{id}/chatroommember": {"get": op(
            "listChatroomMembers", "Chat", "Members of one chat conversation", ref("ChatRoomMember"),
            ["listChatroomMembers.200.json"], coll=True,
            desc="Each member is a guardian or a teacher, with `admin`, `active`, `muted` and its own "
                 "`unreadCount`.",
            params=[dict(id_param, description="Chatroom id from `GET /chatroom`."),
                    q("isActive", {"type": "boolean"}, "Only active (or only former) members.")])},
        "/chatroom/{id}/scheduledchatmessage": {"get": op(
            "listScheduledChatMessages", "Chat", "Your messages scheduled for later in a chat",
            {"$ref": REF + "GeonObject"}, ["listScheduledChatMessages.200.json"], coll=True,
            desc="Empty in every capture, so the item type is unknown.",
            params=[dict(id_param, description="Chatroom id from `GET /chatroom`."),
                    q("state", {"type": "string", "enum": ["SCHEDULED"]}, "The web app asks for `SCHEDULED`.")])},
        "/chatroom/{id}/chatmessage": {"get": op(
            "listChatMessages", "Chat", "Messages in one chat conversation", ref("ChatTextMessage"),
            ["listChatMessages.200.json"], coll=True,
            desc="Without `sort`, only `chat.RChatTextMessage` comes back, **newest first** (live check "
                 "2026-11-05: `Range: items=0-29` returned the newest 30 of 89 messages). Reverse them for "
                 "reading order.\n\n"
                 "With `sort` (what the web app sends), status messages (`chat.RChatStatusMessage`, e.g. "
                 "someone joining) come back as well, and the names are the **opposite** of what they say: "
                 "`desc-stream` is oldest first, `asc-stream` newest first (live check 2026-11-07).\n\n"
                 "`createdSince` / `modifiedSince` (ISO 8601 with `Z`) return only messages created or "
                 "changed since then: what the web app uses to fetch only new messages.",
            params=[dict(id_param, description="Chatroom id from `GET /chatroom`."),
                    q("sort", {"type": "string", "enum": ["desc-stream", "asc-stream"]},
                      "`desc-stream`: oldest first; `asc-stream`: newest first. Both add status messages."),
                    q("createdSince", {"type": "string", "format": "date-time"}, "Only messages created since."),
                    q("modifiedSince", {"type": "string", "format": "date-time"}, "Only messages changed since.")])},
        "/chatroom/{id}/chatmessage/{messageId}": {"get": op(
            "getChatMessage", "Chat", "One chat message", ref("ChatTextMessage"), ["getChatMessage.200.json"],
            params=[dict(id_param, description="Chatroom id from `GET /chatroom`."),
                    {"name": "messageId", "in": "path", "required": True,
                     "schema": {"type": "integer", "format": "int64"},
                     "description": "Message id from `GET /chatroom/{id}/chatmessage`."}])},
        "/identity/{id}": {"get": op(
            "getIdentity", "Account", "One identity (a parent, teacher or child)", ref("Identity"),
            ["getIdentity.200.json"],
            desc="Called with your own identity id (from `GET /account/me`). The web app also uses it for "
                 "the people you can start a chat with.",
            params=[dict(id_param, description="Identity id, e.g. `identity` in `GET /account/me`.")])},
        "/event/{id}/attachment/{attachmentId}": {"get": op(
            "getEventAttachment", "Events", "One attachment of an announcement",
            ref("AnnouncementAttachment"), ["getEventAttachment.200.json"],
            desc="Like `GET /event/{id}` it needs `dtype`: without it the API answers `406 EVENT_BAD_TYPE`. "
                 "The path `…/attachment/{id}/attachmententry/{id}` from the web app's code answered `404` "
                 "(with `dtype`) and `406` (without) in the live check, so it is not described.",
            params=[dict(id_param, description="Announcement id."),
                    {"name": "attachmentId", "in": "path", "required": True,
                     "schema": {"type": "integer", "format": "int64"},
                     "description": "Attachment id from the announcement's `attachments`."},
                    q("dtype", {"type": "string", "enum": ["event.RAnnouncementEventPrimer"]},
                      "The event type, as for `GET /event/{id}`.", required=True)],
            extra={"406": {"description": "Missing `dtype`."}})},
    }


    # ---- Read state: marking as read (captured 2026-11-07)
    read_state_note = (
        "\n\n⚠️ **Others see it.** Read state is shared: the item is no longer marked new in the Parro "
        "app on your phone, and the school sees it as read (announcements show teachers how many "
        "parents read them; chats have read receipts). Mark an item only once you have read it.")

    def mark_read(op_id, summary, desc, params):
        return {"tags": ["Read state"], "operationId": op_id, "summary": summary,
                "description": desc + read_state_note,
                "parameters": [{"$ref": "#/components/parameters/AppVersion"},
                               {"$ref": "#/components/parameters/Role"}, *params],
                "responses": {"204": {"description": "Marked as read. No body."}, **std_err}}

    paths["/event/{id}/read"] = {"put": mark_read(
        "markEventRead", "Mark one announcement or calendar item as read",
        "No request body. Answered `204` in the capture (an announcement).",
        [dict(id_param, description="Event id (`links[rel=self].id` from `GET /event`).")])}
    paths["/event/markannouncementsasread"] = {"put": mark_read(
        "markGroupAnnouncementsRead", "Mark all announcements of a group as read",
        "No request body. Answered `204` in the capture. It marks **every** announcement of the group, "
        "not only the ones you have seen.",
        [q("group", {"type": "integer", "format": "int64"}, "Group id from `GET /group`.", required=True)])}
    paths["/chatroom/{id}/read"] = {"put": mark_read(
        "markChatroomRead", "Mark a chat conversation as read",
        "No request body. Answered `204` in the capture. The id is the chat room's `rel: self` link.",
        [dict(id_param, description="Chatroom id from `GET /chatroom`.")])}

    # ---- sending: speaks for the user, so it says what is known and what is not
    paths["/chatroom/{id}/chatmessage"]["post"] = {
        "tags": ["Chat"], "operationId": "sendChatMessage",
        "summary": "Send a text message to a chat conversation",
        "description":
            "Adds a text message to an existing chat, as seen in a capture of the web app. The id is the "
            "chat room's `rel: self` link. Answered `201` with the new message, and its address in "
            "`Location`.\n\n"
            "⚠️ **Real people receive this, under your name:** the teacher, or everyone in a group chat. "
            "They get a notification. The capture shows no way to take a message back (a message's "
            "`permissions` list only `READ`, also for your own), so treat sending as final.\n\n"
            "⚠️ **Do not resend blindly.** The request has no idempotency key: after a timeout there is no "
            "way to know whether the message arrived, so look at `GET /chatroom/{id}/chatmessage` first.\n\n"
            "**Not known** (finding out means messaging real people): the longest text allowed, the answer "
            "to empty text, and the answer for a chat that cannot be written to (`repliesEnabled: false`, "
            "`active: false`, archived, or `BOT`). Other kinds of message, replies and attachments were not "
            "captured.",
        "parameters": [{"$ref": "#/components/parameters/AppVersion"},
                       {"$ref": "#/components/parameters/Role"},
                       dict(id_param, description="Chatroom id from `GET /chatroom`.")],
        "requestBody": {"required": True, "content": {GEON: {"schema": collection({
            "type": "object", "required": ["dtype", "links", "deleted", "text", "allRead"],
            "description": "The web app sends exactly these five fields.",
            "properties": {
                "dtype": {"type": "string", "enum": ["chat.RChatTextMessage"]},
                "links": {"type": "array", "maxItems": 0, "items": {},
                          "description": "Empty: the message has no id yet."},
                "deleted": {"type": "boolean", "enum": [False]},
                "text": {"type": "string", "description": "The message, as the recipients will read it."},
                "allRead": {"type": "boolean", "enum": [False]},
            }})}}},
        "responses": {
            "201": {"description": "Sent. One item: the new message.",
                    "headers": {"Location": {
                        "description": "`…/chatroom/{id}/chatmessage/{messageId}` of the new message.",
                        "schema": {"type": "string", "format": "uri"}}},
                    "content": content(collection(ref("ChatTextMessage")), ["sendChatMessage.201.json"])},
            **std_err},
    }

    # ---- helper slots: a promise in the user's name, so it says what others see
    item_param = dict(id_param, description="The calendar item's **own** id "
                                            "(`calendarItem.links[rel=self].id`), not the event id: "
                                            "the event id answers `404`.")
    resource_param = {"name": "resourceId", "in": "path", "required": True,
                      "schema": {"type": "integer", "format": "int64"},
                      "description": "The slot's id (`calendarItem.resources[].links[rel=self].id`)."}
    commitment = ref("CalendarItemResourceCommitmentPrimer")
    helper_note = (
        "\n\n⚠️ **Others see it.** The school sees your name on the slot; a parent sees how many signed "
        "up, not who (`GET` answers show only your own commitment). A sign-up is a promise, and it can "
        "take the last place from another parent; withdrawing can leave the school short.")

    def helper_op(op_id, summary, desc, params, responses, body=None):
        operation = {"tags": ["Helpers"], "operationId": op_id, "summary": summary,
                     "description": desc + helper_note,
                     "parameters": [{"$ref": "#/components/parameters/AppVersion"},
                                    {"$ref": "#/components/parameters/Role"}, *params],
                     "responses": {**responses, **std_err}}
        if body:
            operation["requestBody"] = body
        return operation

    paths["/calendaritem/{id}/resource/{resourceId}/commitment"] = {"get": op(
        "listCommitments", "Helpers", "Your own commitment on a helper slot", commitment,
        ["listCommitments.200.json"], coll=True,
        desc="Lists **only your own** commitment on the slot (live check 2026-11-08), even when "
             "`amountCommitted` shows that others signed up: it is empty where you did not. The same entry "
             "is in `resources[].commitments[]` of the calendar item. The path also answers with a "
             "trailing `/`.",
        params=[item_param, resource_param])}
    paths["/calendaritem/{id}/resource/{resourceId}/commitment/"] = {"post": helper_op(
        "addCommitment", "Sign up on a helper slot",
        "Adds a commitment for the logged-in parent, as seen in a capture of the web app, with the "
        "trailing `/`. Answered `201` with the new commitment, and its address in `Location`. Slots are "
        "people (`type: VOLUNTEER`) or things to bring (`EQUIPMENT`).\n\n"
        "`amount` is how many places you take, for example how many children a parent can take along. "
        "Captures send `1`; `2` was accepted in a live check (2026-11-08), and `amountCommitted` rose "
        "by 2 and `commitedByMe` became 2.\n\n"
        "**Not known** (finding out means changing real slots): the answer for a full slot, a past item "
        "or closed sign-ups, and whether a second sign-up on the same slot adds up.",
        [item_param, resource_param],
        {"201": {"description": "Signed up. One item: the new commitment.",
                 "headers": {"Location": {
                     "description": "`…/commitment/{commitmentId}` of the new commitment.",
                     "schema": {"type": "string", "format": "uri"}}},
                 "content": content(collection(commitment), ["addCommitment.201.json"])}},
        body={"required": True, "content": {GEON: {"schema": collection({
            "type": "object", "required": ["dtype", "links", "amount"],
            "description": "The web app sends exactly these three fields.",
            "properties": {
                "dtype": {"type": "string", "enum": ["calendar.RCalendarItemResourceCommitmentPrimer"]},
                "links": {"type": "array", "maxItems": 0, "items": {},
                          "description": "Empty: the commitment has no id yet."},
                "amount": {"type": "integer", "minimum": 1, "description": "How many places you take."},
            }})}}})}
    paths["/calendaritem/{id}/resource/{resourceId}/commitment/{commitmentId}"] = {"delete": helper_op(
        "deleteCommitment", "Withdraw from a helper slot",
        "Removes your commitment. Answered `204` in a capture of the web app. No request body. The id is "
        "in `resources[].commitments[]` of the calendar item, which lists only your own.",
        [item_param, resource_param,
         {"name": "commitmentId", "in": "path", "required": True,
          "schema": {"type": "integer", "format": "int64"},
          "description": "Your commitment's id (`commitments[].links[rel=self].id`)."}],
        {"204": {"description": "Withdrawn. No body."}})}

    # ---- RSVP: an answer in the user's name; the list of respondents holds other people's data
    rsvp_answer = ref("CalendarItemRSVPPrimer")
    paths["/calendaritem/{id}/calendaritemrsvp"] = {
        "get": op(
            "listRsvpRespondents", "RSVP", "Everyone invited, with their answers", ref("Respondent"),
            ["listRsvpRespondents.200.json"], coll=True,
            desc="⚠️ **Personal data of other people.** Lists everyone the invitation went to, parents and "
                 "teachers: first name, surname, children's names, avatar and answer. Handle it with care, "
                 "and do not pass it on.\n\n"
                 "`rsvp` is `ACCEPT`, `DECLINE`, `TENTATIVE`, or `UNKNOWN` for someone who has not answered. "
                 "Seen in a live check (2026-11-09): it answered on 15 of 20 items and `403` on the other 5, "
                 "for reasons not known. You do not need it for your own answer: that is the `rsvp` field "
                 "of the event in `GET /event` and `GET /event/{id}`, absent until you answer.",
            params=[item_param]),
        "post": {
            "tags": ["RSVP"], "operationId": "answerRsvp", "summary": "Answer a calendar item's invitation",
            "description":
                "Stores your answer, as seen in a capture of the web app. Answered `201` with the answer, and "
                "its address in `Location`. Only `ACCEPT` was captured; in a live check (2026-11-09) `TENTATIVE`, "
                "`DECLINE` and `ACCEPT` each replaced the answer before them.\n\n"
                "Sending the same answer twice changes nothing: the second call answers `201` with an identical "
                "body, including `lastModifiedAt`. There is no call to remove an answer in the capture.\n\n"
                "⚠️ **Others see it.** The school sees your name and answer, and it may decide what is arranged. "
                "The Parro app does not show parents who answered what, but `GET` on this path returns it "
                "to a parent's login.\n\n"
                "**Not known** (finding out means answering real invitations): the answer for a past or cancelled "
                "item or one with `rsvpRequired: false`, and whether teachers get a notification.",
            "parameters": [{"$ref": "#/components/parameters/AppVersion"},
                           {"$ref": "#/components/parameters/Role"}, item_param],
            "requestBody": {"required": True, "content": {GEON: {"schema": collection({
                "type": "object", "required": ["dtype", "links", "rsvp"],
                "description": "The web app sends exactly these three fields.",
                "properties": {
                    "dtype": {"type": "string", "enum": ["calendar.RCalendarItemRSVPPrimer"]},
                    "links": {"type": "array", "maxItems": 0, "items": {},
                              "description": "Empty: the answer has no id yet."},
                    "rsvp": {"type": "string", "enum": ["ACCEPT", "DECLINE", "TENTATIVE"],
                             "description": "Your answer."},
                }})}}},
            "responses": {
                "201": {"description": "Stored. One item: your answer.",
                        "headers": {"Location": {
                            "description": "`…/calendaritemrsvp/{rsvpId}` of the answer.",
                            "schema": {"type": "string", "format": "uri"}}},
                        "content": content(collection(rsvp_answer), ["answerRsvp.201.json"])},
                **std_err},
        },
    }

    # ---- IdP
    idp = [{"url": "https://inloggen.parnassys.net/idp", "description": "ParnasSys IdP"}]
    form = "application/x-www-form-urlencoded"
    s = lambda **kw: dict(kw, type=kw.get("type", "string"))
    paths["/oauth2/authorize"] = {"servers": idp, "get": {
        "tags": ["Auth"], "operationId": "authorize", "security": [],
        "summary": "Start a browser login (authorization code + PKCE)",
        "parameters": [
            q("client_id", s(example="MQygAaSBUcAgPU2WInKt"), "Public client of talk.parro.com.", True),
            q("response_type", s(enum=["code"]), "", True),
            q("redirect_uri", s(format="uri", example="https://talk.parro.com/oauth2"),
              "Must be exactly the registered URI; loopback URIs are rejected (`invalid_client`).", True),
            q("scope", s(example="openid offline_access"), "`openid`; `offline_access` is granted but does not lengthen the 8-hour login.", True),
            q("state", s(), "Random value, echoed back.", True),
            q("code_challenge", s(), "base64url(SHA-256(code_verifier)).", True),
            q("code_challenge_method", s(enum=["S256", "plain"]), "Use `S256`.", True)],
        "responses": {
            "200": {"description": "The ParnasSys login page (HTML)."},
            "302": {"description": "After login: redirect to `redirect_uri?code=…&state=…`.",
                    "headers": {"Location": {"schema": s(format="uri")}}},
            "400": {"description": "Invalid request, e.g. `invalid_client — Callback url does not match one of "
                                   "[registered]` for an unregistered `redirect_uri`."}}}}
    paths["/oauth2/token"] = {"servers": idp, "post": {
        "tags": ["Auth"], "operationId": "token", "security": [],
        "summary": "Obtain or refresh tokens",
        "description": (
            "⚠️ **Not usable from Swagger UI.** Call it from a terminal or a client, and see the warning in the "
            "introduction.\n\n"
            "**Two request shapes.**\n\n"
            "* `authorization_code` and `refresh_token` send their parameters in the **query string** with an "
            "**empty body** and `Content-Type: application/x-www-form-urlencoded`, as the web client does.\n"
            "* `password` sends a normal form-encoded **body** (`grant_type, client_id, username, password, scope`).\n\n"
            "A wrong password answers `400 invalid_grant` and counts toward the account lockout. That same "
            "error also comes back for accounts the IdP will not put through the password grant. Clients "
            "then fall back to the HTML login form, once: `GET /oauth2/authorize` (PKCE, follow redirects, keep "
            "cookies) → POST `aanmelden=x&emailadres=…&wachtwoord=…` to the `signInForm` action without following "
            "the redirect → take `code` from `Location` → `authorization_code` exchange as above."),
        "parameters": [
            q("grant_type", s(enum=["authorization_code", "refresh_token"]), "Query-string shape only."),
            q("client_id", s(example="MQygAaSBUcAgPU2WInKt"), ""),
            q("code", s(), "authorization_code: the code from the redirect."),
            q("code_verifier", s(), "authorization_code: the PKCE verifier."),
            q("redirect_uri", s(format="uri"), "authorization_code: same value as in /authorize."),
            q("refresh_token", s(), "refresh_token grant.")],
        "requestBody": {"required": False, "content": {form: {"schema": {
            "type": "object",
            "properties": {"grant_type": s(enum=["password"]), "client_id": s(),
                           "username": s(), "password": s(format="password"),
                           "scope": s(example="openid offline_access")}}}}},
        "responses": {
            "200": {"description": "Tokens.", "content": content(ref("OAuthTokenResponse"),
                                                                 ["token.200.json"], "application/json")},
            "400": {"description": "RFC 6749 §5.2 error, e.g. `invalid_grant`. Not sampled.",
                    "content": {"application/json": {"schema": ref("OAuthError")}}}}}}
    paths["/oauth2/revoke"] = {"servers": idp, "post": {
        "tags": ["Auth"], "operationId": "revoke", "security": [],
        "summary": "Revoke a refresh or access token (RFC 7009)",
        "requestBody": {"required": True, "content": {form: {"schema": {
            "type": "object", "required": ["token", "client_id"],
            "properties": {"token": s(), "token_type_hint": s(enum=["refresh_token", "access_token"]),
                           "client_id": s()}}}}},
        "responses": {"200": {"description": "Revoked (empty body)."},
                      "400": {"description": "RFC 6749 error.", "content": {"application/json": {"schema": ref("OAuthError")}}}}}}
    used.add("revoke.200.json") if "revoke.200.json" in samples else None
    paths["/oauth2/logout"] = {"servers": idp, "get": {
        "tags": ["Auth"], "operationId": "endSession", "security": [], "x-parro-verified": False,
        "summary": "OIDC RP-initiated logout (unverified)",
        "description": "Advertised as `end_session_endpoint` in the discovery document; never called. "
                       "Parameters follow OpenID Connect RP-Initiated Logout 1.0.",
        "parameters": [q("id_token_hint", s(), ""), q("post_logout_redirect_uri", s(format="uri"), ""),
                       q("client_id", s(), "")],
        "responses": {"200": {"description": "Logout page (unverified)."},
                      "302": {"description": "Redirect after logout (unverified)."},
                      "4XX": {"description": "Client error (unverified)."}}}}
    paths["/.well-known/openid-configuration"] = {
        "servers": [{"url": "https://inloggen.parnassys.net", "description": "IdP issuer"}],
        "get": {"tags": ["Auth"], "operationId": "discovery", "security": [],
                "summary": "OpenID Connect discovery document",
                "description": "Location follows OIDC Discovery from `issuer`. Note: it also advertises "
                               "`introspection_endpoint`, which needs client authentication and is not described.",
                "responses": {"200": {"description": "Discovery document.",
                                      "content": content(ref("OpenIDConfiguration"),
                                                         ["discovery.200.json"], "application/json")},
                              "4XX": {"description": "Client error."}}}}
    used.add("getAccountMe.401.json") if "getAccountMe.401.json" in samples else None

    # ---- components
    schemas = {
        "GeonLink": {"type": "object", "required": ["rel"], "properties": {
            "rel": {"type": "string", "example": "self"},
            "id": {"type": "integer", "format": "int64", "example": 1000000000},
            "type": {"type": "string", "example": "identity.RChildPrimer"},
            "href": {"type": "string", "format": "uri",
                     "example": "https://rest-v2.parro.com/rest/v2/child/1000000000"}}},
        "GeonPermission": {"type": "object", "properties": {
            "full": {"type": "string", "example": "attachment.RAttachment:READ:INSTANCE(11000000000)"},
            "type": {"type": "string", "example": "attachment.RAttachment"},
            "operations": {"type": "array", "items": {"type": "string", "example": "READ"}},
            "instances": {"type": "array", "items": {"type": "string", "example": "INSTANCE(11000000000)"}}}},
        "GeonObject": {"type": "object", "additionalProperties": True,
                       "description": "The common geon envelope, used where the concrete type is unknown.",
                       "properties": {"dtype": {"type": "string"},
                                      "links": SPECIAL_FIELDS["links"],
                                      "permissions": SPECIAL_FIELDS["permissions"],
                                      "additionalObjects": SPECIAL_FIELDS["additionalObjects"],
                                      "lastModifiedAt": {"type": "string", "format": "date-time"}}},
        "OAuthError": {"type": "object", "required": ["error"], "properties": {
            "error": {"type": "string", "example": "invalid_grant"},
            "error_description": {"type": "string"}},
            "description": "RFC 6749 §5.2. Not sampled; modelled on the standard (`error`, `error_description`)."},
    }
    for name in sorted(model.types):
        if name in schemas:
            sys.exit("inferred schema would overwrite hand-written " + name)
        schemas[name] = model.emit_obj(model.types[name])
    schemas["GeonError"]["description"] = ERR_DESC
    schemas["OAuthTokenResponse"]["description"] = "RFC 6749 §5.1 token response (sample values redacted)."
    schemas["OpenIDConfiguration"]["additionalProperties"] = True

    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Parro REST API (unofficial)", "version": CONTRACT,
                 "description": DESCRIPTION + ("\n## About this build\nPublic build: response and property "
                                               "examples taken from samples are left out.\n" if public else ""),
                 "license": {"name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
                 "x-parro-app-version": APP_VERSION},
        "servers": [
            {"url": "https://rest-v2.parro.com/rest/v2", "description": "Production"},
            {"url": "https://{host}/rest/v2", "description": "Other environment (e.g. acceptance; host not documented)",
             "variables": {"host": {"default": "rest-v2.parro.com"}}}],
        "tags": [
            {"name": "Auth", "description": "ParnasSys IdP (OAuth2 / OpenID Connect)."},
            {"name": "Account", "description": "Account, school, children, unread counts."},
            {"name": "Groups", "description": "Classes and school-wide groups."},
            {"name": "Events", "description": "Announcements (mededelingen) and calendar items, incl. attachments."},
            {"name": "Chat", "description": "Conversations with teachers."},
            {"name": "Misc", "description": "System news, absence and photo-export settings."},
            {"name": "Read state", "description": "Mark announcements, calendar items and chats as "
                                                  "read."},
            {"name": "Helpers", "description": "Sign up on a calendar item's helper slot, or withdraw."},
            {"name": "RSVP", "description": "Answer a calendar item's invitation."}],
        "security": [{"bearerToken": []}, {"parnassysOAuth": ["openid"]}],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "bearerToken": {"type": "http", "scheme": "bearer",
                                "description": "Paste an access token. This is the only scheme usable from Swagger UI; "
                                               "\"Try it out\" works with it."},
                "parnassysOAuth": {"type": "oauth2",
                                   "description": "⚠️ **Documentation only: do not use it from Swagger UI.** The code flow "
                                                  "cannot complete there, because the redirect URI is pinned to "
                                                  "https://talk.parro.com/oauth2 and PKCE (S256) is required. The password "
                                                  "flow is refused (`invalid_grant`) for some accounts, and each failed "
                                                  "attempt can count toward the IdP's account lockout. Obtain a token outside "
                                                  "the browser and use **bearerToken**.",
                                   "flows": {
                                       "authorizationCode": {
                                           "authorizationUrl": "https://inloggen.parnassys.net/idp/oauth2/authorize",
                                           "tokenUrl": "https://inloggen.parnassys.net/idp/oauth2/token",
                                           "scopes": {"openid": "OpenID Connect",
                                                      "offline_access": "Granted; the refresh token still expires 8 hours after the login"}},
                                       "password": {
                                           "tokenUrl": "https://inloggen.parnassys.net/idp/oauth2/token",
                                           "scopes": {"openid": "OpenID Connect",
                                                      "offline_access": "Granted; the refresh token still expires 8 hours after the login"}}}}},
            "parameters": {
                "AppVersion": {"name": "parro-app-version", "in": "header", "required": False,
                               "schema": {"type": "string", "example": APP_VERSION},
                               "description": "Client version. Every official client sends it; it is unknown whether the server enforces it."},
                "Role": {"name": "parro-authorization-role", "in": "header", "required": False,
                         "schema": {"type": "string", "pattern": "^[A-Z]+:[0-9]+$", "example": "GUARDIAN:1000000000"},
                         "description": "`<ACCOUNTTYPE>:<id>` derived from `GET /account/me`. The web client sends it on every call except `/account/me`."},
                "Range": {"name": "Range", "in": "header", "required": False,
                          "schema": {"type": "string", "pattern": "^items=[0-9]+-[0-9]+$", "example": "items=0-49"},
                          "description": "Zero-based, inclusive item range."},
                "RangeCount": {"name": "topicus-Range-Count", "in": "header", "required": False,
                               "schema": {"type": "string", "enum": ["Exact"]},
                               "description": "Ask for an exact total in `Content-Range`."}},
            "headers": {"ContentRange": {"schema": {"type": "string", "pattern": "^items [0-9]+-[0-9]+/[0-9]+$",
                                                    "example": "items 0-1/2"},
                                         "description": "Returned range and total."}},
            "responses": {
                "Unauthorized": {"description": "Missing, expired or invalid token. Empty body, no Content-Type. "
                                                "**Also returned for `GET /event/{id}?dtype=event.RAnnouncementEvent`.**"},
                "GeonErrorResponse": {"description": "Error.", "content": {GEON: {"schema": ref("GeonError")}}}},
            "schemas": dict(sorted(schemas.items())),
        },
    }
    unused = sorted(set(samples) - used)
    return spec, unused


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=os.path.join(ROOT, "samples"))
    ap.add_argument("--out", default=os.path.join(ROOT, "openapi", "parro.openapi.json"))
    ap.add_argument("--public", action="store_true",
                    help="omit all sample-derived examples (for publishing)")
    a = ap.parse_args()
    spec, unused = build(a.samples, public=a.public)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print("wrote {} ({} paths, {} schemas)".format(
        a.out, len(spec["paths"]), len(spec["components"]["schemas"])))
    if unused:
        print("WARNING: samples not used:", ", ".join(unused))


if __name__ == "__main__":
    main()
