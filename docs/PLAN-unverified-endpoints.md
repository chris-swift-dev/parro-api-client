# Plan 5: the unverified endpoints

*Status: phases 1–7 done (2026-11-05), on branch `unverified-endpoints`; release 0.4.0 is next. Decisions taken as recommended (§6). The live check found `SCHOOLWIDE_VOLUNTEER` (fixed) and a `TIMESLOT` item type.*

**Goal:** every path the spec lists as *Unverified* is either described from real responses or
removed, and the client gains what is useful to a parent. Source: three HAR captures from the web
app (`tmp/part1.har` … `part3.har`, git-ignored, 17 requests, 2026-11-05).

---

## 1. What the captures show

| Path in the spec today | Called as | Answer | Verdict |
| --- | --- | --- | --- |
| `/calendaritem/{id}` | `GET /calendaritem/{id}` | `200`, a `calendar.RCalendarItem` | **exists**: the same object as `calendarItem` in `GET /event/{id}` |
| `/absence` | `GET /absence` | `206`, `{"items": []}`, `Content-Range: items 0-0/0` | **exists**, a collection; item type unknown (empty) |
| `/media-export` | `GET /media-export` | `200`, `{"items": []}` (no `Content-Range`) | **exists**; item type unknown (empty) |
| (not in the spec) | `GET /media-export/settings` | `200`, `mediaexport.RMediaExportSettings {downloadEnabled}` | **exists**, new |
| `/privacy` | `GET /child/{id}/privacy` | `200`, `identity.RPrivacySettings {url, defined}` | **exists, at another path**: per child |
| (not in the spec) | `GET /child?currentSchoolYear=true&dtype=identity.RPrivacySettingChild` | `206`, children with a `setting` (`privacy.RPrivacyCentreSetting`) | **exists**: a new `dtype` variant of `listChildren` |
| `/conversations` | `GET /conversations` | `404` (`jakarta.ws.rs.NotFoundException`) | **does not exist** (old) |
| `/timeslot` | `GET /timeslot` | `404` | **does not exist at this path** |
| `/absence/setting` (already verified) | same | `200`, `{"items": []}` | unchanged |

Details worth keeping:

- **`/calendaritem/{id}`** returns all fields of the embedded calendar item, minus `lastEditedBy`.
  This capture adds a calendar item of `type: VOLUNTEER` (until now only `ACTIVITY` was seen),
  with `resources[]` of `calendar.RCalendarItemVolunteerResource`: `title`, `amount` (helpers
  wanted), `amountCommitted`, `commitedByMe` (sic), `type`, `commitments[]`. Its permissions also
  name `calendar.RCalendarItemTimeslotCreate`. So timeslots hang off calendar items, not off
  `/timeslot`.
- **Privacy:** the list variant tells per child whether the privacy choices can be changed
  (`editableForGuardians`, `editableInPeriod`, `state: OPEN`, `lastEditedBy`, `lastModifiedAt`).
  `/child/{id}/privacy` answers `defined: true` and a `url` to
  `https://start.parnassys.net/bao/privacy?signedpermission=…`: a **signed link** to the page where
  a parent sets the choices. The choices themselves are not in the API.
- **CORS preflights** allow `DELETE, POST, GET, OPTIONS, PUT` on every path, including `/child`.
  That is a server-wide setting and says nothing about which methods a path supports. The spec
  should stop reading meaning into it (it does for `/calendar/sync`).

## 2. Sensitive data in the captures

- **No secrets:** every `Authorization` header is an 8-character placeholder; there are no cookies,
  no POST bodies, no JWTs, no e-mail addresses, no CDN or calendar links. Ids are the placeholders
  `1000000000` / `11000000000`; names are `Voornaam` / `Achternaam`; the avatar link and the signed
  privacy link end in `REDACTED`.
- **Not sanitized — must not reach any committed file:**
  1. **a real person's name** in `setting.lastEditedBy` (both children, `part2.har`), probably a
     staff member who last changed the privacy setting;
  2. the calendar item's `description` (one sentence of school text) and two `resources[].title`
     strings (school text, not personal, but real);
  3. real-looking dates: the children's `enrolledSince` and the event's date;
  4. the `errorID` UUIDs in the two 404 answers (server request ids).
- The HARs are git-ignored (`*.har`). The plan turns them into **sanitized samples** in `samples/`
  (also git-ignored), from which only schemas reach the public spec. Invented fixtures for the
  tests come from `make_api_fixtures.py`, never from the captures.
- **The spec's privacy scan would not have caught item 1:** `tools/validate_spec.py` looks for
  e-mail addresses, tokens and CloudFront paths, not for names. Phase 1 extends it.

## 3. What goes where

**Spec: everything verifiable.**

| Change | Tag |
| --- | --- |
| `GET /calendaritem/{id}` → `CalendarItem` (verified), with the volunteer fields | Events |
| `GET /child`: new query parameters `currentSchoolYear` and `dtype` (`identity.RPrivacySettingChild`); response `oneOf` child primer / privacy variant | Account |
| `GET /child/{id}/privacy` → `PrivacySettings` (`url` marked as a secret signed link, `defined`) | Account |
| `GET /absence` → collection, item type unknown | Misc |
| `GET /media-export` → collection, item type unknown; `GET /media-export/settings` → `MediaExportSettings` | Misc |
| Remove `/conversations`, `/timeslot`, `/privacy`; one line in the *Unverified* tag description: "answered 404 when called (2026-11-05)" | – |
| `/calendar/sync`: drop the guess about `POST/PUT/DELETE` from the CORS preflight | Events |

The *Unverified* tag is then empty and disappears.

**Client: only what a parent gains from.**

| Endpoint | In the client? | Why |
| --- | --- | --- |
| Privacy (list variant + `/child/{id}/privacy`) | **yes** (decision 1) | Schools ask parents every year to set photo and data choices. "Is it set, can I still change it, where do I do that" is a real question. |
| Volunteer slots of calendar items | **yes**, from data the client already fetches (decision 2) | "2 helpers wanted, 0 signed up, you: no" is exactly what a parent needs to see. `GET /event/{id}` already returns `resources[]`; no new call. |
| `/calendaritem/{id}` | no new command | Same data as `GET /event/{id}`, which the client uses. |
| `/absence`, `/absence/setting` | no | Empty and of unknown shape; reporting an absence is a write, which this client never does. `parro_get /absence` still works. |
| `/media-export`, `/media-export/settings` | no | An export is something you start (a write); `sync --photos` already saves the photos. |

## 4. Client design

**Privacy**

- CLI `parro_cli.py privacy` and MCP `parro_privacy`: per child, the state of the privacy
  choices. One request: `GET /child?currentSchoolYear=true&dtype=identity.RPrivacySettingChild`.
  ```
  # Privacy choices (2)
  - Mila · can be changed by you · open · last changed Wed 13 May 2026 · #1000000001
  - Daan · can be changed by you · open · last changed Wed 13 May 2026 · #1000000002
  → parro_cli.py privacy --link 1000000001   (opens the page where you set them)
  ```
- `privacy --link CHILD_ID` (MCP: `link: true` with `child_id`): `GET /child/{id}/privacy` and
  print the signed link. Treated like the calendar link: **a secret**, never logged, never cached or
  archived (`remove_urls` already drops `url`), the output says so.
- `lastEditedBy` (a staff member's name) is shown as "changed by the school" or "changed by you"
  only if that can be told reliably; otherwise left out. To be decided with real data in the
  live check; the fixtures use an invented name.

**Volunteer slots**

- `summarize_calendar_details` adds `helpers: [{title, wanted, signed_up, you}]` for
  `type: VOLUNTEER` (or whenever `resources[]` is not empty).
- Agenda line: `· helpers wanted: 2 (0 signed up)`; with `--details` one line per resource, and
  "you signed up" when `commitedByMe` > 0. Also in the `.ics` description and the archive markdown.
- The overview's *Coming up* shows "helpers wanted" like "RSVP needed".

## 5. Phases

| # | Phase | Done when |
| --- | --- | --- |
| 1 | **Samples and privacy scan.** Sanitized samples from the HARs (`getCalendarItem.200.json`, `listChildren_privacy.200.json`, `getChildPrivacy.200.json`, `listAbsences.200.json`, `getMediaExport.200.json`, `getMediaExportSettings.200.json`): invented `lastEditedBy`, description, titles and dates. `validate_spec.py`: every `firstname` / `surname` / `lastEditedBy` / `guardianNames` value must be a placeholder, every `signedpermission=` / `ical/` link `REDACTED` | scan fails on the raw HAR values, passes on the samples |
| 2 | **Spec.** The changes of §3 in `tools/build_spec.py`; rebuild both specs; validate; Swagger UI screenshots retaken | 20 + 6 examples valid; public spec has no `Unverified` tag |
| 3 | **Fixtures.** `make_api_fixtures.py`: a volunteer calendar item, the privacy list and link for the invented children; contract tests against the public spec | fixtures match the spec |
| 4 | **Client: volunteer slots** in summaries, agenda, overview, `.ics`, archive; snapshots | tests and snapshots |
| 5 | **Client: privacy** command and MCP tool (19 tools); never logs, caches or archives the link | tests incl. "link never in logs / cache / archive" |
| 6 | **Docs:** README (command, tool table, FAQ), `docs/API-NOTES.md`, CODE-TOUR, CHANGELOG 0.4.0, README pictures regenerated | `make_readme_images.py --check` passes |
| 7 | **Live check with you** (you are logged in, so no password check): `privacy`, `privacy --link` (link validated without printing it), a volunteer item in `calendar --details` | results in `docs/LIVE-CHECKS.md` |
| 8 | Release **0.4.0** | published |

## 6. Decisions needed

1. **Privacy in the client:** a `privacy` command + tool with `--link` (*recommended*), or the spec
   only.
2. **Volunteer slots** in the agenda, overview, `.ics` and archive (*recommended*), or the spec only.
3. **The 404 paths:** remove them from the spec with a one-line note (*recommended*), or keep them as
   *Unverified* with "404 when called".
4. **Timeslots** (parent–teacher talk slots): out of scope for now (*recommended*). To find their
   real path, a capture of opening a calendar item with timeslots in the web app would be needed
   (e.g. *Oudergesprekken*, when the school schedules them).
