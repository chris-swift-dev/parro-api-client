# Plan 1 — OpenAPI 3.0.3 specification for the Parro API

**Deliverable:** `openapi/parro.openapi.json`. It imports cleanly into Swagger Editor
(editor.swagger.io) and passes a linter with zero errors.
**Inputs:** `parro_mcp.py` (behaviour and headers), `README.md` (verified endpoint list),
sanitized response samples you will add to `samples/`.
**Decisions taken:** OpenAPI **3.0.3**, JSON format, schemas built from **real sanitized samples**.

---

## 0. Sample intake (you do this; the implementation session checks it)

Drop one JSON file per call into `samples/`, named `<operationId>.<status>.json`, or `<operationId>_<variant>.<status>.json` when one operation has several shapes (e.g. `listEvents_calendar-items.200.json`)
(the operationIds are in §3). Each file holds the response **body** only, and a file
`samples/_headers.md` lists the response headers seen on a collection call (`Content-Range`, `Content-Type`).

| Priority | Samples |
| --- | --- |
| Must | `getAccountMe`, `listChildren`, `listGroups` (both `dtype=identity.RHomeGroup` and `scope=PREVIOUS_ACTIVE`), `listEvents` with an **announcement** that has a **PDF** and a **photo** attachment, `getEvent` (same announcement), `listEvents` with calendar items, `listChatrooms`, `listChatMessages`, `getUnreadCounts` |
| Should | `getAccountSettings`, `getAbsenceSetting`, `listSystemNews`, `getOrganisation`, token endpoint response (with tokens redacted), IdP discovery document (`/idp/.well-known/openid-configuration`) |
| Errors | one each: `401`, `406 EVENT_BAD_TYPE` (`/event/{id}` without `dtype`), `400 invalid_grant` from the token endpoint |

**Redaction rules.** The schema needs the *shape*, not your family's data. Apply the same
replacement everywhere so references between files still line up:
- names → `Voornaam` / `Achternaam`; e-mail → `ouder@example.com`; school name → `Basisschool Voorbeeld`
- ids → keep the **digit count** but replace consistently (e.g. `12345678901` → `10000000001`).
  Length matters: ids above 2^31 decide `int64` vs `int32`.
- CloudFront URLs → keep host and path shape, replace the query string with `?Signature=REDACTED`
- tokens, `Authorization` values, cookies → `REDACTED`
- message text → short dummy text, but **keep any HTML markup** (it decides whether `contents` is HTML)
- **Never put the raw HAR in the folder.** It holds your password in plain text.

*Optional helper (Phase 0b):* `tools/redact_har.py`, stdlib only. It reads a HAR you pass
as an argument, keeps only `rest-v2.parro.com` / IdP JSON responses, applies the rules
above, and writes `samples/*.json`. It's worth building if hand-redacting looks tedious.

---

## 1. Skeleton

- `info`: title, version `221` (the contract version), description of the geon conventions (§2).
- `servers`: `https://rest-v2.parro.com/rest/v2` (production). Acceptance goes in as a second
  server with a `{host}` variable, since the README says it exists but gives no URL.
- IdP operations override the server per path (`servers:` on the path item):
  `https://inloggen.parnassys.net/idp/oauth2`.
- `tags`: `Auth`, `Account`, `Groups`, `Events`, `Chat`, `Misc`, `Unverified`.

## 2. Shared components

**Security schemes**
- `parnassysOAuth`: type `oauth2` with flows `authorizationCode` (authorize/token URLs,
  scopes `openid`, `offline_access`) and `password`. The description notes PKCE S256 is
  **required**. OAS 3.0 can't express that, but Swagger UI has `usePkceWithAuthorizationCodeGrant`.
- `bearerToken`: type `http`, scheme `bearer`. **This is the one that actually works in
  Swagger UI**, because the IdP pins `redirect_uri` to `https://talk.parro.com/oauth2` and the API
  doesn't send CORS headers for other origins. Document this in `info.description`:
  "paste an access token from `parro auth-status`".
- Global `security: [{bearerToken: []}, {parnassysOAuth: [openid]}]`. IdP paths override this with `security: []`.

**Reusable parameters** (`components/parameters`)
| Name | In | Notes |
| --- | --- | --- |
| `AppVersion` | header `parro-app-version` | required, example `web:2.25.4` |
| `Role` | header `parro-authorization-role` | required on everything **except** `/account/me`; pattern `^(GUARDIAN\|TEACHER):\d+$` |
| `Range` | header `Range` | pattern `^items=\d+-\d+$`; triggers `206` |
| `RangeCount` | header `topicus-Range-Count` | enum `[Exact]` |
| `Dtype` | query `dtype` | string; per-operation enums |
| `GroupId` | query `group` | int64 |

**Media type.** Every API response uses content type `application/vnd.topicus.geon+json;version=221`.
OAS 3.0 has no Accept parameter, so the media type key itself carries it, and Swagger
UI sends it as `Accept`.

**Response headers.** `Content-Range` (`items 0-49/123`) on all `206` responses.

**Geon envelope schemas**
- `GeonLink` `{rel, href, id(int64), type?}`. Exact fields come from the samples.
- `GeonPermission` (shape from samples).
- `GeonObject`: `links: GeonLink[]`, `permissions`, `dtype`, `additionalObjects`.
  Domain schemas extend it via `allOf`.
- `GeonCollection<T>`: one concrete schema per item type (`ChildCollection`, …). The samples
  decide whether collections arrive as `{items: [...]}` or as a bare array (the Python code
  copes with both). If both occur, use `oneOf`.
- `GeonError`: from the 406 / 401 samples (e.g. `{code: "EVENT_BAD_TYPE", ...}`).
- `OAuthTokenResponse`, `OAuthError` (RFC 6749 §5.1/§5.2).

**Polymorphic events.** `/event` and `/event/{id}` return different types depending on `dtype`.
Model them as `oneOf` + `discriminator: {propertyName: dtype, mapping: {...}}` over
`AnnouncementEventPrimer`, `AnnouncementEvent`, `CalendarItemEventPrimer` (more as samples show them).

## 3. Paths — verified (from README, confirmed by samples)

| Method + path | operationId | Notes |
| --- | --- | --- |
| `GET /account/me` | `getAccountMe` | **no** `Role` header (the role is derived from this response) |
| `GET /accountsettings` | `getAccountSettings` | |
| `GET /child` | `listChildren` | Range |
| `GET /group` | `listGroups` | `dtype=identity.RHomeGroup` **or** `scope=PREVIOUS_ACTIVE`; Range |
| `GET /identity/unreadcounts` | `getUnreadCounts` | |
| `GET /absence/setting` | `getAbsenceSetting` | |
| `GET /systemnews` | `listSystemNews` | |
| `GET /organisation/{id}` | `getOrganisation` | id from `/account/me` |
| `GET /event` | `listEvents` | `dtype` enum `[event.RAnnouncementEventPrimer, event.RCalendarItemEventPrimer]` (required), `group` (required), Range |
| `GET /event/{id}` | `getEvent` | `dtype` **required**; describe the `406 EVENT_BAD_TYPE` response |
| `GET /chatroom` | `listChatrooms` | Range |
| `GET /chatroom/{id}/chatmessage` | `listChatMessages` | Range |

**Auth (IdP server override, `security: []`)**
| Method + path | operationId | Notes |
| --- | --- | --- |
| `GET /authorize` | `authorize` | PKCE params; `302` to `redirect_uri?code&state` |
| `POST /token` | `token` | **Two shapes:** `authorization_code` and `refresh_token` send their parameters in the **query string with an empty body**; `password` sends a form-encoded body. Document both: query params marked optional, plus `requestBody` `application/x-www-form-urlencoded`, with the quirk spelled out in `description` |
| `POST /revoke` | `revoke` | form body `token`, `token_type_hint`, `client_id` |
| `GET /.well-known/openid-configuration` | `discovery` | path on `/idp`, so it needs its own server override |

The Wicket login form (`signInForm`, fields `aanmelden`/`emailadres`/`wachtwoord`) is an
HTML scrape, not an API. It stays out of `paths` and gets a short section in `info.description`.

**Attachment download.** It isn't a Parro path: `AttachmentEntry.url` is a pre-signed CloudFront
URL. Document it on the schema: `format: uri`, plus a description saying it is time-limited and
must be fetched **without** `Authorization`.

## 4. Domain schemas (fill from samples; minimum fields the Python code relies on)

- `Account`: `email`, `username`, `accountType`, `identity: Identity`, `organisation: Organisation`
- `Identity`: `firstname`, `surname`, `role`, `guardians[]`, `teachers[]`, `children[]`
- `Child`: `firstname`, `surname`, `archived`, `enrolledSince`, `numberOfGuardians`
- `Group`: `name`, `schooljaar`, `type`, `stamgroep`, `unreadCount`, `memberMuted`,
  `childAvatars[]`, `numberOfChildren/Guardians/Teachers`
- `AnnouncementEventPrimer` / `AnnouncementEvent`: `title`, `contents`, `sortDate`, `createdAt`,
  `read`, `liked`, `owner`, `attachments: Attachment[]`
- `Attachment`: `attachmentType`, `entries: AttachmentEntry[]` (or a single `entry`)
- `AttachmentEntry`: `type` (enum incl. `SOURCE` + resized variants), `filename`, `contentType`, `size`, `url`
- `CalendarItemEventPrimer`, `ChatRoom`, `ChatMessage`, `UnreadCount` (`numberOfUnread*` ×5, `guardian`)

Rules:
- ids `int64`; dates `format: date-time` only if the samples are ISO-8601, otherwise
  `string` + `example`.
- `nullable: true` where samples show `null`.
- Leave `additionalProperties` at its default (open). Geon adds fields across contract versions.
- Every schema gets an `example` taken from the samples.

## 5. Unverified endpoints

`/absence`, `/calendaritem/*`, `/media-export`, `/conversations`, `/timeslot`, `/privacy`:
these appear in the `main.dart.js` string table but have never been called. Add them as `GET`
with tag `Unverified`, `x-parro-verified: false`, and a generic `GeonObject` response, so the
spec stays honest about what is confirmed.

## 6. Validation (definition of done)

1. `npx @redocly/cli lint openapi/parro.openapi.json` → 0 errors (warnings reviewed).
2. `tools/validate_samples.py`: every `samples/<operationId>.<status>.json` validates against
   its response schema (`pip install openapi-schema-validator`, dev tool only).
3. The spec imports into editor.swagger.io without errors. Spot-check *Try it out* with
   `bearerToken` against `/account/me`. If CORS blocks it, record that in the description rather than "fixing" it.
4. Search for anything identifying (names, real ids, e-mail) in the spec and samples → none.

## 7. Out of scope

Write operations (the client is read-only), code generation (Plan 2 hand-writes its Swift
types; `swift-openapi-generator` would break the Foundation-only rule), the MCP layer.

---

## Kickoff prompt (paste into the implementation session)

```text
Work in the parro-api-client folder. Read docs/PLAN-openapi.md, parro_mcp.py and README.md.
Implement the plan phase by phase:
Phase 0: check samples/ against §0 (list missing "Must" samples and stop if any are missing;
         scan for unredacted personal data and report it, don't fix it silently).
Phases 1–5: build openapi/parro.openapi.json (OpenAPI 3.0.3, JSON).
Phase 6: run every validation step and report results.
Constraints: describe only behaviour backed by parro_mcp.py, README or a sample; mark
anything else x-parro-verified: false. Don't invent fields. No real names, ids or URLs in the spec.
```

---

## 8. Findings from the samples (2026-11-04). These override §0–§5 where they differ

- **Contract version 224** (`Accept`/`Content-Type: application/vnd.topicus.geon+json;version=224`), app
  version `web:2.27.0`. `info.version` = `224`. Response `Content-Type` sometimes omits `;version=…`
  (seen on a 206), so declare both media-type keys or describe the variance.
- **Collections are always `{items: [...]}`**: drop the bare-array alternative.
- **Lists always page.** `/child` without `Range` still answers `206` + `Content-Range: items 0-1/2`. `Range` is optional,
  `200` is not observed for collections, and the default page size is unknown (say so).
- **`GET /event/{id}` dtypes actually accepted:** `event.RAnnouncementEventPrimer` (200) and
  `event.RCalendarItemEvent` (200). **`event.RAnnouncementEvent` answers 401** (not 406). Document it as a
  known pitfall on the 401 response. A missing `dtype` → `406` with `applicationError: EVENT_BAD_TYPE`.
- **Error body** (`GeonError`): `{code:int, reason, exception, message, applicationError, errorDetails:[string]}`.
  **401** has an empty body and no `Content-Type`.
- **Attachment location differs by event type:** announcements → `attachments[]` at top level;
  calendar items → `calendarItem.attachments[]`. Attachment dtypes: `attachment.RAnnouncementAttachment`,
  `attachment.RCalendarItemAttachment`; entries `attachment.RAttachmentDocumentEntry` / `RAttachmentImageEntry`,
  `type` seen: `SOURCE`, `THUMBNAIL`; `attachmentType` seen: `IMAGE` (PDF sample shows the document value).
  An image's SOURCE entry can be a `RAttachmentDocumentEntry`, so `contentType` is authoritative. `image/jpg` (non-standard) occurs.
- **CloudFront URLs are NOT signed** (no query string). Paths look like `/{image|thumbnail|application}/<32 hex>/1-<32 hex>.<ext>`.
  The download sets `content-disposition: attachment; filename="…"` (the original filename), plus `etag` and `accept-ranges: bytes`.
  Describe them as unauthenticated, long-lived capability URLs: treat them as secrets.
- **CORS (corrected 2026-11-04):** the capture showed `access-control-allow-origin: https://talk.parro.com`,
  but that was the requesting origin. "Try it out" with a bearer token **works** from GitHub Pages.
  Logging in through Swagger UI does not (pinned redirect URI; `invalid_grant` on the password grant).
- `access-control-expose-headers` hints at extra response headers (`parro-verification-days-left`,
  `parro-used-idp`, `www-authenticate`, …). Mention them in the description, not as required headers.
- Dates: ISO-8601 with offset, fractional seconds vary (0–3 digits) → `format: date-time`. Some are plain
  dates (`enrolledSince`-like) → `format: date`.
- IdP discovery adds `end_session_endpoint` (`/idp/oauth2/logout`) and `introspection_endpoint`. Document both under Auth.
- `getAbsenceSetting` returned `{items: []}`, so its item schema stays a generic `GeonObject`.
