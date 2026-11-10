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

## Live check (2026-11-05, release 0.4.0: privacy and helper slots)

No password check: the stored refresh token was used. Personal data is left out here.

| Check | Result |
| --- | --- |
| `privacy` | OK, one request: 2 children, parents can change the choices, state `OPEN`, last changed in May 2024 by a school staff member (not the parent) |
| `privacy --link CHILD_ID` | OK: a `start.parnassys.net/bao/privacy?signedpermission=…` link with a 168-character signature, **different on every call** (probably short-lived). The page opens without a login (one redirect that sets a session cookie, then the consent form). Only read, nothing saved. The link was never printed, and was not in the `-vv` log or anywhere under `~/.parro` and `~/.parro-mcp` |
| Calendar item types | Upcoming 44: 34 `SCHOOLWIDE_ACTIVITY`, 9 `VOLUNTEER`, 1 `SCHOOLWIDE_VOLUNTEER`. Past 62 also had `ACTIVITY` and one `TIMESLOT` (probably parent–teacher talks) |
| **Found and fixed** | School-wide helper requests have their own type, `SCHOOLWIDE_VOLUNTEER`; the client only knew `VOLUNTEER`, so they were not marked and their details were cached. Now every type ending in `VOLUNTEER` counts |
| `calendar --details` | Every helper item has slots: one each for `VOLUNTEER`, four for the school-wide one (e.g. 10 wanted, 4 signed up); some also need an RSVP. The agenda marked 6 *helpers wanted* and 4 *helpers: full*, with 13 slot lines; the overview marked 5 |
| Cache | Helper items are fetched fresh on every run and their cache entries are neither read nor rewritten (entries from before 0.4.0 stay unused until `cache clear` or the size limit removes them) |

## Live check (2026-11-06, release 0.5.0: installing as a command)

One password check, at the start (the stored login had expired; see the last row).

| Check | Result |
| --- | --- |
| TestPyPI | 0.5.0 (wheel and sdist) uploaded by *Publish to PyPI*, run by hand on `main`. `pipx install --index-url https://test.pypi.org/simple/` fails on a fresh pipx (it upgrades its own pip from that index); `--pip-args="--extra-index-url …"` works, now in the docs |
| Installed with pipx (TestPyPI) | `parro-client` and `parro-client-mcp` on the PATH; the wheel identical to TestPyPI's |
| `parro-client login --prompt` | OK on the first try: 1 password check |
| `status`, `overview`, `privacy`, `calendar` | OK; hints name `parro-client`, never `parro_cli.py` |
| `parro-client-mcp` | 19 tools; `parro_auth_status`, `parro_overview` (markdown) and a stdio session (`initialize`, then a tool call) OK |
| Release draft | All four files equal the release job's output; the wheel is byte-identical to the TestPyPI wheel tested above; sdists differ only in timestamps (setuptools stamps the build time) |
| PyPI | After publishing: wheel and sdist byte-identical to the GitHub release; `pipx install parro-api-client` works; all 13 pictures on the project page load |
| **How long a login lasts** | The previous login (5 Nov) was refused on 6 Nov: "Token has expired". The new refresh token (a JWT) expires **8 hours after the login**; after a refresh, the new one keeps the same `iat` and expiry, only `refresh_count` goes up. So a login lasts at most 8 hours, `offline_access` or not. The docs said "far longer"; corrected |

## Live check (2026-11-07, release 0.6.0: marking as read)

With the account owner present, who picked the item to mark. **No password check**: the existing
login was refreshed with its refresh token. Personal data is left out.

| Check | Result |
| --- | --- |
| `overview` | OK: only the unread announcements (3); calendar "Nothing new.", no unread chats |
| `mark-read announcement <id>` (picked by the owner) | OK: one `PUT /event/{id}/read`, accepted; "Marked as read" |
| the same again | OK: "Already read", no PUT |
| `unread` / `overview` afterwards | OK: Parro's own count went from 3 to 2 unread announcements; the item is gone from the overview |
| Parro app | OK: the owner saw the item shown as read in the app |
| `mark-read calendar <id>` / `mark-read chat <id>` | OK: found and already read, nothing sent (2 GETs each, no PUT). `GET /chatroom/{id}` works with the chat's own id. Nothing was unread, so `PUT /event/{id}/read` for a calendar item and `PUT /chatroom/{id}/read` are **not checked live yet**; both are the calls the web app sends (captures) |
| `mark-read group <id>` without `--yes` | OK: the count (2) and the titles, nothing marked (3 GETs, no PUT). Bulk marking was not run |

## Live check (2026-11-08, release 0.7.0: sending a chat message)

With the account owner present, who picked the chat and the text and approved the preview. **One
password check** (`login --prompt`, by the owner; the previous login had expired). One real message
was sent, in a chat with one other person. Personal data is left out.

| Check | Result |
| --- | --- |
| MCP `parro_send_chat_message` without `confirm`, `PARRO_ALLOW_SEND_CHAT=1` | OK: the preview shows the chat, the one recipient (not the sender) and the exact text; nothing sent, the chat still had 6 messages |
| `chat-send` without a terminal and without `--yes` | OK: exit 2, "Not sent", nothing sent |
| `chat-send <id> "<text>" --yes` | OK: 3 GETs and **one POST**, accepted; shows the new message's id and time. The text is not in the `-vv` log |
| `chat-messages` afterwards | OK: 7 messages; the newest has that id and exactly that text; `allRead` false |
| Own unread count | Stayed 0: sending does not make the chat unread for the sender |
| Parro app | OK: the owner saw the message in the app |
| The other person's reply | OK: `unread` shows 1 chat, `overview` and `chatrooms --unread` list that chat |
| `mark-read chat <id>` | OK: 2 GETs and one `PUT /chatroom/{id}/read`; afterwards `unread` says nothing is unread and the chat is gone from `overview` and `chatrooms --unread`. **This closes the gap left by the 0.6.0 check** for chats |
| the same again | OK: "Already read", 2 GETs, no PUT |
| Not checked live | `PUT /event/{id}/read` for a calendar item (nothing unread so far), MCP `confirm: true` (same code path as `chat-send` after the preview), refusals of closed chats, a timeout, the limits listed in the spec: finding out would mean more real messages |

## Live check (2026-11-08, release 0.8.0: signing up and withdrawing as a helper)

With the account owner present, who picked the slot and the count and compared the Parro app after
each step. **No password check**: the existing login was used. One real sign-up and one real
withdrawal, on an empty slot for two helpers, about two weeks ahead. Personal data is left out.

| Check | Result |
| --- | --- |
| MCP `parro_helper_signup` without `confirm`, `PARRO_ALLOW_HELPER_SIGNUP=1` | OK: the preview shows the item, the slot, 0 of 2 places taken and the count; nothing changed |
| `helper signup <event> --slot <slot> --count 2 --yes` | OK: accepted, with the new commitment's id. **`amount: 2` works**, the value no capture shows |
| Read back | OK: `amountCommitted` 2, `commitedByMe` 2, one commitment of yours with `amount` 2; `calendar --details` says 2 of 2 signed up, including you |
| Parro app | OK: the owner saw 2 of 2 |
| MCP `parro_helper_withdraw` without `confirm` | OK: the preview shows 2 of 2 places taken; nothing changed |
| `helper withdraw <event> --slot <slot> --yes` | OK: accepted |
| Read back | OK: `amountCommitted` 0, `commitedByMe` 0, `commitments` empty |
| Parro app | OK: the owner saw 0 of 2 |
| Not checked live | MCP `confirm: true` (the same code path as the CLI after the preview), a timeout, how the API itself answers a full slot, a past item or a second sign-up (the client refuses those before writing), and whether teachers get a notification |

## Live check (2026-11-09, release 0.9.0: answering an invitation)

With the account owner present, who picked the item and the answers and compared the Parro app after
each step. **No password check**: the existing login was used. Three real answers on an item the
owner had already accepted in the web app, ending on that same answer. Personal data is left out.

| Check | Result |
| --- | --- |
| MCP `parro_rsvp` without `confirm`, `PARRO_ALLOW_RSVP=1` | OK: the preview shows the item, the current answer (accept) and the new one; nothing changed |
| `rsvp tentative <event> --yes` | OK: accepted. **`TENTATIVE` replaces `ACCEPT`**; the event's `rsvp` reads `TENTATIVE`, the agenda says `RSVP: tentative`, and the Parro app agrees |
| `rsvp decline <event> --yes` | OK: accepted. **`DECLINE` replaces `TENTATIVE`**; `rsvp` reads `DECLINE`, the agenda says `RSVP: declined`, and the Parro app agrees |
| MCP `parro_rsvp` with `confirm: true`, answer accept | OK: accepted. `ACCEPT` replaces `DECLINE`; `rsvp` reads `ACCEPT`, the agenda says `RSVP: accepted`, and the Parro app agrees. **This closes the gap of `confirm: true` for this tool** |
| `rsvp accept <event> --yes` again | OK: reports nothing changed, and no `POST` was sent |
| MCP `parro_get` on the respondents path | OK: refused before any request |
| Not checked live | A timeout, how the API itself answers a past or cancelled item or one that asks for no answer (the client refuses those before writing), whether teachers get a notification, and `confirm: true` on the other write tools |

## Live check (2026-11-09, release 0.10.0: the desktop app)

The account owner used the app on a real display (Linux, Wayland, Python 3.14), went through its
sections and reported what they saw. The previous login had expired. **One password check**, typed by
the owner in the app's login dialog. One real write, chosen by the owner. Personal data is left out.

| Check | Result |
| --- | --- |
| Starting with an expired login | OK: the login dialog opened; the failed token refresh was logged without any token (`invalid_grant`), and no password was spent |
| Logging in with a password | OK: one attempt; the login lasts 8 hours from then, and the command line sees the same login |
| Overview, Announcements, Calendar, Chats, Family, Archive | OK: the owner reports that all of them look right and work on real data |
| One write: sending a text message to a chat | OK, as reported by the owner, through the preview dialog and Confirm |
| Closing the window | OK: exit code 0 |
| Not checked live | Marking as read from the app (nothing was unread), signing up, withdrawing and answering an invitation from the app (the same core calls as the command line, checked live there), a timeout, and **a real window on Windows** (CI runs the tests there without a display) |
| macOS, on the owner's computer (2026-11-10) | OK: installed from the branch; the owner reports it looks and works the same as on Linux |
