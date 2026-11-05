# Parro API client and OpenAPI spec

An unofficial, **read-only** client and API description for [Parro](https://talk.parro.com), the
Dutch parent–school communication app by Topicus (ParnasSys). The client reads your announcements,
newsletters, calendar, chats and class info, **including the text inside PDF attachments**.

**→ Browse the API in Swagger UI: https://chris-swift-dev.github.io/parro-api-client/**

> Not affiliated with or endorsed by Topicus, ParnasSys or Parro. Behaviour was observed, not
> documented by the vendor, and may change at any time. Only documented `GET` endpoints and the
> standard OAuth2 login flow are used and described.

| | |
| --- | --- |
| `parro_cli.py` | a command-line client: readable markdown at a terminal, JSON when piped (`jq`) |
| `parro_mcp.py` | an MCP server over stdio for Claude and other MCP clients |
| `parro/` | the library both use: login, API calls, summaries, attachments |
| `openapi/parro.public.openapi.json` | the OpenAPI 3.0.3 description of the API (contract version 224) |

Standard library only (Python 3.10+). PyMuPDF / pypdf (PDF text) and Pillow (photo downscaling) are
optional. The client only ever **reads**: the Parro API only receives `GET`, and `POST` goes only to
the login server's token, revoke and login-form endpoints. Nothing can be posted, changed or deleted.

Download a release from the [Releases page](https://github.com/chris-swift-dev/parro-api-client/releases):
unpack it and run `python3 parro_cli.py --help`. No installation step. `docs/CODE-TOUR.md` walks
through the code.

## What it does

The Parro web app is a Flutter app talking to a Topicus "geon" REST API at
`https://rest-v2.parro.com/rest/v2`. This client speaks that API and adds three things:

1. **It strips the geon boilerplate.** Raw responses bury every field under `permissions` / `links`
   / `dtype` blocks. A three-group list is 2.8 KB of JSON carrying about 300 bytes of information.
   Every command returns a compact summary; use `--raw` (MCP: `raw: true`) for the untouched payload.
2. **It reads attachments.** School newsletters arrive as PDFs. `attachment` / `parro_attachment`
   downloads them and returns plain text. Photos come back as images (MCP) or can be saved (CLI).
3. **It shows the data the way the app does.** Announcements once each with author and groups, an
   agenda grouped by day, conversations in reading order, and an overview of what is new, as
   readable markdown. Every id stays visible, so the next command is always at hand.

### Readable output

At a terminal the CLI prints markdown; piped into another program it prints JSON. `--format` (or
`PARRO_FORMAT`) chooses explicitly. MCP tools answer in JSON unless called with `format: "markdown"`.
Example, made from the invented test data in `tests/fixtures/`:

```
$ python3 parro_cli.py overview
# Overview

## Unread
● 2 announcements, 1 calendar item, 1 chat

## Latest announcements
- 📌 Studiedag vrijdag 13 november ● new · Lotte Bakker · Mon 2 Nov 2026 12:28 · #5000000102
- Foto's herfstwandeling · Lotte Bakker · Sat 31 Oct 2026 18:39 · #5000000103
…
→ parro_cli.py announcements

## Coming up
- Wed 11 Nov 2026, 17:30-19:00  Sint-Maartenviering · Basisschool De Linde · #7000000101
- Thu 12 Nov 2026, all day  Excursie Natuurmuseum · Groep 6 - meester Tom · RSVP needed · #7000000301
…
```

`tests/snapshots/` holds the output of every view; it is the quickest way to see what they look
like. Dates are shown in the time zone the school's data uses, labels are English, and content is
shown as written.

## Command line

```bash
python3 parro_cli.py --help
python3 parro_cli.py login --prompt              # type the password once; tokens then refresh themselves
python3 parro_cli.py status
python3 parro_cli.py overview                    # what is new, like the app's home screen
python3 parro_cli.py announcements --limit 5 --unread-only
python3 parro_cli.py attachment <announcement-id> --text
python3 parro_cli.py calendar --details          # agenda with location and description
python3 parro_cli.py calendar-link               # Parro's own link to subscribe from Google/Apple/Outlook
python3 parro_cli.py calendar --ics parro.ics --details   # or: an .ics file to import
python3 parro_cli.py announcements --format json | jq '.announcements[].title'
python3 parro_cli.py get /accountsettings
python3 parro_cli.py token                       # paste into Swagger UI → Authorize → bearerToken
```

Commands: `login [--prompt]`, `logout`, `status`, `token`, `login-url`, `login-finish <url>`,
`overview`, `me`, `children`, `groups [--previous]`, `unread`, `system-news [--full]`,
`announcements [--group ID] [--limit N] [--unread-only] [--full]`, `announcement <id>`,
`calendar [--group ID] [--limit N] [--details] [--past] [--ics FILE]`, `calendar-link`,
`attachment <event-id> [--attachment-id ID | --all] [--save-to DIR] [--text]`, `chatrooms`,
`chat-messages <chatroom-id>`, `cache info|clear`,
`get <path> [--param k=v ...] [--limit N] [--offset N]`.
Global options: `--format auto|json|markdown`, `--login-method`, `--raw`, `--compact`,
`--no-cache`, `--verbose`. `--full` shows whole texts instead of a 3-line preview.

Exit codes: `0` ok · `1` API/network error · `2` usage · `3` not logged in · `4` login halted.

## MCP server

| Tool | What it gives you |
| --- | --- |
| `parro_auth_status` | Login state, account, role, token expiry, whether automatic login is halted. Start here when something fails. |
| `parro_login` | Log in with `PARRO_USERNAME` and the password; optional `method`. |
| `parro_login_url` / `parro_login_finish` | Browser login without a stored password (OAuth2 + PKCE). |
| `parro_logout` | Revoke the tokens at the IdP and forget them. |
| `parro_me` | Account and school. |
| `parro_children` | Children linked to the account. |
| `parro_groups` | Classes and school-wide groups, with the ids other tools need. |
| `parro_announcements` | The main feed. Merges all groups, newest first, full text + attachment list. |
| `parro_announcement` | One announcement by id, with author. |
| **`parro_attachment`** | **Downloads an attachment of an announcement or calendar item and returns its text (PDF/docx/txt/csv/html) or the image.** |
| `parro_calendar` | Calendar items from today on, soonest first; `details: true` adds location and description, `past: true` earlier items. |
| `parro_chatrooms` / `parro_chat_messages` | Conversations. |
| `parro_unread` | Unread counts per category. |
| `parro_get` | Escape hatch: GET any `/rest/v2` path not covered above. |
| `parro_overview` | What is new: unread counts, latest announcements, coming up, unread chats. |
| `parro_calendar_link` | The personal link to subscribe to the Parro agenda (keep it secret). |

Every tool takes an optional `format`: `json` (default) or `markdown`, a readable view that keeps
every id. The first 16 tools have the same names and arguments as the original server, so existing
MCP configurations keep working; only optional arguments were added (`method`, `details`,
`format`). `parro_mcp.py` needs the `parro/` folder next to it.

```bash
claude mcp add parro -s user -- python3 /path/to/parro-api-client/parro_mcp.py
```

Or in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "parro": {
      "command": "python3",
      "args": ["/path/to/parro-api-client/parro_mcp.py"],
      "env": { "PARRO_USERNAME": "you@example.com", "PARRO_PASSWORD_FILE": "/path/to/password-file" }
    }
  }
}
```

Testing without an MCP client:

```bash
python3 parro_mcp.py tools
python3 parro_mcp.py call parro_auth_status
python3 parro_mcp.py call parro_announcements '{"limit": 5}'
```

PDF text needs **PyMuPDF** or **pypdf**; photo downscaling needs **Pillow**. Without them
everything else works, and the attachment tool says what to install:

```bash
python3 -m pip install pymupdf pillow
```

## Logging in

Everything is OAuth2 against the ParnasSys IdP. Tokens are stored in `~/.parro-mcp/tokens.json`
(mode 0600) and refreshed automatically. The scope is `openid offline_access`. The web app asks only
for `openid`, which is why its refresh token expires after 8 hours. With `offline_access` a login
lasts far longer, so later runs only refresh and the password is not checked again until the
refresh token dies.

### Login methods (`PARRO_LOGIN_METHOD`, CLI `--login-method`, MCP `method`)

| Value | What happens | Password checks per login |
| --- | --- | --- |
| `login-form` (**default**) | Exactly what a browser does: login page → form POST → code → token exchange | 1 |
| `password-grant` | OAuth2 password grant only, no fallback | 1 |
| `auto` | Password grant; on failure the login form once | up to 2 |

`login-form` is the default because some accounts answer `invalid_grant` to the password grant
anyway, so `auto` would waste an attempt on every login. A changed login page fails *before* the
password is sent (no form found: clear error, no attempt spent).

### The lockout latch

> **The IdP locks the account after a few failed logins** ("Account has N attempts remaining").

When a password is rejected, the client saves that in the token file and **stops logging in on its
own**. A typo therefore costs one attempt, not one per call. `status` / `parro_auth_status` then
shows `automatic_login_halted`. Fix the password, then run `parro_cli.py login` (MCP: `parro_login`).
That explicit call clears the latch and spends exactly one attempt. A response the client cannot
interpret after the password was sent counts as a rejection too: it is the safe side. A 401 from the
API never triggers a password login: the client refreshes once, and otherwise reports the error.

### Credentials

* `PARRO_USERNAME` plus `PARRO_PASSWORD_FILE` (preferred) or `PARRO_PASSWORD`;
* or `parro_cli.py login --prompt` (hidden input, nothing stored);
* or no password at all: `login-url`, open the URL, log in, then hand the address you land on to
  `login-finish` (MCP: `parro_login_url` / `parro_login_finish`). Copy it promptly: the Parro web app
  also tries to redeem the code, and each code works only once.

### Why not a proper loopback redirect?

The tidy modern pattern (RFC 8252: spin up `http://127.0.0.1:PORT/callback`, let the browser deliver
the code automatically) needs a client registered with that redirect URI. This IdP:

- publishes **no `registration_endpoint`**: no Dynamic Client Registration, so we cannot register one;
- validates redirect URIs strictly. Asking for `http://localhost:8765/callback` on the Parro client
  returns `invalid_client — Callback url does not match one of [registered]`;
- advertises **no device authorization grant**, so that route is out too.

So a local tool must borrow the web client's `client_id`, which is pinned to
`https://talk.parro.com/oauth2`. Hence the copy-paste step, or the login form.

## Configuration

| Variable | Default |
| --- | --- |
| `PARRO_USERNAME` | (none; enables password login) |
| `PARRO_PASSWORD_FILE` / `PARRO_PASSWORD` | (none; the file wins; only trailing line breaks are stripped) |
| `PARRO_LOGIN_METHOD` | `login-form` (or `password-grant`, `auto`) |
| `PARRO_TOKEN_FILE` | `~/.parro-mcp/tokens.json` |
| `PARRO_ROLE` | derived from `/account/me`, e.g. `GUARDIAN:1234567890` |
| `PARRO_ACCESS_TOKEN` | bootstrap with an existing token (no refresh, not stored) |
| `PARRO_BASE_URI` | `https://rest-v2.parro.com` |
| `PARRO_LOGIN_URI` | `https://inloggen.parnassys.net` |
| `PARRO_CLIENT_ID` / `PARRO_REDIRECT_URI` | the talk.parro.com web client |
| `PARRO_CONTRACT_VERSION` | `224` |
| `PARRO_APP_VERSION` | `web:2.27.0` |
| `PARRO_SCOPE` | `openid offline_access` |
| `PARRO_TIMEOUT` | `30` (seconds) |
| `PARRO_MAX_DOWNLOAD` | `62914560` (60 MB) |
| `PARRO_MAX_IMAGE_PX` | `1400` |
| `PARRO_FORMAT` | `auto` (CLI: markdown at a terminal, JSON when piped), `json` or `markdown` |
| `PARRO_DATA_DIR` | `~/.parro/data` (the cache lives in `cache/` inside it) |
| `PARRO_CACHE` | `on` (`off` = never read or write the cache; CLI: `--no-cache`) |
| `PARRO_CACHE_MAX_MB` | `500` |

Switch to the acceptance environment by overriding `PARRO_BASE_URI`, `PARRO_LOGIN_URI` and
`PARRO_CLIENT_ID`.

## The agenda in your own calendar app

Two ways, depending on what you need:

- **`calendar-link`** prints Parro's own subscription link (`GET /calendar/sync`). Paste it into
  Google Calendar (*Other calendars → From URL*), Apple Calendar (*New Calendar Subscription*) or
  Outlook (*Subscribe from web*), and the calendar keeps itself up to date. **The link is a secret**:
  anyone who has it can read your Parro calendar without logging in. ParnasSys lists agenda syncing
  as a feature of the paid *Parro Ouderapp*, so not every school may offer it.
- **`calendar --ics FILE`** writes an iCalendar file of the upcoming items (`--past` for earlier
  ones, `--details` for locations and descriptions, `-` for standard output). It works without the
  subscription feature, but it is a snapshot: export again to update. Every event keeps the same
  UID, so importing a newer file updates events instead of duplicating them.

## Local data: the cache

Downloading the same newsletter again and again is slow, and an AI assistant often reads it several
times in one conversation. So two things are cached in `PARRO_DATA_DIR/cache`:

- **attachment files and their extracted text**, keyed by attachment id, upload id and size. An
  upload never changes, so these never go stale;
- **calendar-item details** (`calendar --details`), used only while the list still shows the same
  `lastModifiedAt`.

Lists (announcements, agenda, chats, unread counts) are **never** cached: they are cheap, and they
are how the client learns what is new or read. The cache holds children's photos and school letters,
so its folders are created with mode 0700 and its files with 0600, and download links are never
written to it. `parro_cli.py cache info` shows its size; `cache clear` empties it; `--no-cache` or
`PARRO_CACHE=off` switches it off.

## The OpenAPI specification

`openapi/parro.public.openapi.json` describes the API as observed from the web client:

- **Account, children, groups, announcements, calendar items, chats, unread counts, system news**:
  13 verified operations (incl. the agenda subscription link), plus 6 paths that appear in the web app's code but were never called
  (tagged *Unverified*).
- **Authentication** against the ParnasSys IdP: authorization code + PKCE, password grant,
  refresh, revoke, OIDC discovery.
- **The non-obvious parts**: the geon media type and client headers, `Range`-based paging (`206`
  even without `Range`), `dtype` polymorphism, the `dtype` that answers `401` instead of `406`,
  and where attachments live and how their CDN links behave.

Response schemas contain **only fields seen in real responses**. They were inferred from sanitized
samples, which are not part of this repository, so the published spec carries no example payloads.
`openapi/README.md` explains how the spec is generated, validated and published.

- **Swagger Editor / other tools:** import `openapi/parro.public.openapi.json`.
- **"Try it out"** works once you paste an access token into **Authorize → bearerToken**
  (`python3 parro_cli.py token` prints one).
- **Logging in through Swagger UI does not work.** Don't use the OAuth2 scheme there: the code
  flow can't complete, and failed password attempts count toward the account lockout.
- **Local preview:** `npm ci --ignore-scripts && npm run preview`, then open http://localhost:8000.

## API facts the client relies on

All in the spec; the important ones:

- Headers: `Authorization: Bearer`, `Accept` (and `Content-Type`)
  `application/vnd.topicus.geon+json;version=224`, `parro-app-version: web:2.27.0`,
  `parro-authorization-role: GUARDIAN:{guardianId}` (not on `/account/me`, which it is derived from).
- Collections are `Range: items=0-49` paged and answer `206` with a `Content-Range` total.
- `GET /event/{id}` needs a `dtype`: without one it answers `406 EVENT_BAD_TYPE`. For announcements
  use `event.RAnnouncementEventPrimer`: `event.RAnnouncementEvent` answers **401**, which looks like
  an expired token but is not.
- Attachments: announcements keep them in `attachments[]`, calendar items in
  `calendarItem.attachments[]`. Each carries an unsigned CloudFront URL that must be fetched
  **without** the Parro `Authorization` header and is never logged.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest            # no network: fake IdP and API
.venv/bin/ruff check . && .venv/bin/ruff format --check parro tests parro_cli.py parro_mcp.py
.venv/bin/mypy
```

The tests include login-safety checks (one credential POST per login, none while the latch is set,
none after a 401, no secrets in logs). They run on an invented family and school in
`tests/fixtures/api/`, written by `tests/fixtures/make_api_fixtures.py` and checked against the
public spec. `tests/snapshots/` holds the expected markdown of every view; after an intended layout
change, run `UPDATE_SNAPSHOTS=1 .venv/bin/pytest tests/test_rendering.py` and review the diff.
The checks that need git-ignored files (the real `samples/` against the full spec, and the
comparison with the original server in `legacy/`) skip without them, as in CI.

| Path | Purpose |
| --- | --- |
| `tests/` | pytest suite; `tests/fakes.py` has the fake IdP and API |
| `tools/build_spec.py`, `tools/validate_spec.py`, `tools/build_site.sh` | spec generator, validator, Swagger UI site |
| `tools/build_release.py` | builds the release archives, checksums and notes |
| `.github/workflows/ci.yml` | lint, types and tests on Python 3.14 and 3.10 |
| `.github/workflows/pages.yml` | validates the spec and deploys Swagger UI to GitHub Pages |
| `.github/workflows/release.yml` | on a `v*` tag: checks, archives, draft GitHub release |

### Making a release

1. Set the version in `parro/__init__.py` and `pyproject.toml`, and add a `## [x.y.z] - date`
   section to `CHANGELOG.md` (a test checks that all three agree).
2. Optionally check the archives locally: `python3 tools/build_release.py --tag vX.Y.Z` (output in
   `dist/`).
3. Tag and push: `git tag -a vX.Y.Z -m "parro-api-client X.Y.Z" && git push origin vX.Y.Z`.
4. The release workflow creates a **draft** release with the archives, `SHA256SUMS` and the changelog
   section as notes. Review it on GitHub and press *Publish*.

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

## Note on the HAR

A captured `talk.parro.com.har` contains the login POST **in plaintext**, including the password,
plus valid OAuth tokens. Treat it as a secret: don't commit it (`*.har` is ignored), and consider
changing that password if it has been sitting in a file on disk.

## Credits

Inspired by **[fobatai/parro-mcp](https://github.com/fobatai/parro-mcp)**, a read-only MCP server for
Parro by fobatai. Its working login and API calls were the starting point for this follow-up. The
client here is an independent implementation based on the OpenAPI specification in this repository.

## License

- **Code** (`parro/`, `parro_cli.py`, `parro_mcp.py`, `tests/`, `tools/`): [MIT](LICENSE-CODE).
- **Specification and documentation** (`openapi/`, `docs/`, the README files):
  [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)
  (see [`LICENSE`](LICENSE)). You may share and adapt them for any purpose, provided you give
  appropriate credit (link to this repository), indicate the license and note any changes you made.

"Parro", "ParnasSys" and "Topicus" are names of their respective owners. They are used here only to
identify the API being described.
