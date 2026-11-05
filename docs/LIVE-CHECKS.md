# Live checks

Each release was checked once against the real Parro API, with the account owner present and at
most one password check. Personal data is left out. Back to the [README](../README.md).

## Live check (2026-11-04)

Run once against the real API with `.venv/bin/python` (pypdf + Pillow installed). Personal data is
left out here.

| Step | Result |
| --- | --- |
| `login --prompt --login-method login-form` | OK on the first try: **1 password check**, access + refresh token (`offline_access`), role `GUARDIAN:<id>` derived |
| `status` | OK, no request beyond `/account/me`; token valid ~58 min |
| `me` | OK: account, school (`ROrganisationPrimer`); `children` is null for a guardian identity (children come from `children`) |
| `announcements --limit 5` | OK: 5 newest, merged over 3 groups, photo attachments listed as `readable: false` |
| `attachment <newsletter id>` | OK: `GET /event/{id}?dtype=event.RAnnouncementEventPrimer` answered 200 (fix 2); PDF of 1.5 MB, 9 pages, 12,888 characters via pypdf. The log shows only the CDN host, never the URL (fix 7) |
| `attachment <letter id> --text` | OK: a .docx letter read as text |
| `parro_mcp.py call parro_unread` / `parro_groups` | OK: same core, live |
| `token` → Swagger UI **bearerToken** | OK: "Try it out" works with it |
| `logout` | OK: IdP answered 200 for refresh and access token; token file removed; `me` then exits 3 |

## Live check (2026-11-05, release 0.2.0)

Readable output, the cache and the overview against the real API, with one password check
(personal data left out):

| Check | Result |
| --- | --- |
| `login --prompt` at a terminal | OK, 1 password check; `auto` printed markdown |
| `overview`, `announcements`, `calendar --details`, `chat-messages` | OK |
| An announcement sent to several groups | The API returns it once per group (2 of 71 events); the feed lists it once with both groups |
| Order of chat messages | Newest first (the newest 30 of 89); the conversation view shows them in reading order |
| Order of calendar items | **Furthest future first**: a group's first 50 of 100 items were 6-9 months ahead. Fixed: the client now pages to today (the overview had missed near-term whole-school events) |
| Newsletter PDF read twice | Second read from the cache, same text; folders 0700, files 0600, no links stored |
| `calendar-link` | Returns the subscription link; it answers `200 text/calendar` without login, refreshes hourly, works without `noCache`, and its token is stable |
| Multi-day calendar items | The API lists them **once per day** (one 40-day item: 40 entries). Fixed: merged by calendar item; afterwards our agenda, our `.ics` and Parro's own feed agree on all 44 upcoming items (title and start day) |

## Live check (2026-11-05, release 0.3.0: `sync`)

| Check | Result |
| --- | --- |
| First `sync` (this school year, documents only) | 69 announcements, 106 calendar items, 7 chats, 10 documents (5.4 MB; one taken from the cache); 140 API requests, 16 s |
| `sync --previous` | 606 announcements, 385 calendar items, 95 documents (113.5 MB); 418 API requests, 69 s |
| Second `sync` | Everything unchanged; **11 requests, all lists** (no details, messages or downloads), 2 s |
| Calendar against Parro's own feed | Same items, except multi-day timed items (one item here, one event per day there) and 3 summer items posted in last year's groups, which `sync --previous` archives |
| On disk | Folders 0700, files 0600; no download or avatar links (the only links are ones written in messages) |
