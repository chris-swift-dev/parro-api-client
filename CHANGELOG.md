# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/),
and versions follow [Semantic Versioning](https://semver.org/). The release workflow publishes the
section of a version as its GitHub release notes, so write each section for users.

## [0.4.0] - 2026-11-05

Helper requests in the agenda, your children's privacy choices, and a spec without guesses: every
path the spec listed as *unverified* was called once in the Parro web app.

### Added
- **Helpers wanted**: calendar items that ask parents to help (driving, reading aloud) are marked in
  the agenda and the overview. `calendar --details` (MCP `details: true`) shows each slot with how
  many parents signed up and whether you did; the `.ics` export and the `sync` archive name them
  too. Their details are always fetched fresh (sign-ups change), and an existing archive updates
  such items once.
- **`privacy`** (MCP `parro_privacy`): per child, whether you can still change the privacy choices
  (photos, data) and when and by whom they were last changed. `privacy --link CHILD_ID` (MCP
  `link: true`) gives the link to the ParnasSys page where you set them. That link opens the page
  without a login: it is never logged, cached or archived, and the output says to keep it private.
- Spec: `GET /calendaritem/{id}` (with the helper slots), `GET /child/{id}/privacy`, the privacy
  variant of `GET /child`, `GET /absence`, `GET /media-export` and `GET /media-export/settings`.

### Changed
- Spec: `/conversations` and `/timeslot` answered `404` and are removed, and so is the *Unverified*
  section. The guess that the CORS preflight shows extra methods for `/calendar/sync` is gone: it
  allows every method on every path.
- The spec's privacy scan also checks that names, addresses and signed links in its examples and
  samples are placeholders.

## [0.3.0] - 2026-11-05

An archive: `parro_cli.py sync` keeps a local copy of everything your Parro account can see, as
files you can read, search and keep.

### Added
- `sync` writes every announcement, calendar item and chat as a markdown file (with a small YAML
  header) plus a JSON file, and saves the documents that come with them. `index.md` lists
  everything, newest first.
  - Repeat it to update: unchanged items are not rewritten, and a saved file is never downloaded
    again (files already in the cache are copied from there).
  - A renamed item gets renamed files; an item that disappears from Parro stays in the archive and
    is marked *(no longer in Parro)* in `index.md`.
  - `--photos` also saves photos (off by default: a school year of photos can be several GB),
    `--previous` archives last school year, `--to DIR` picks the folder (default
    `PARRO_DATA_DIR/archive`, so `~/.parro/data/archive`).
  - A download that fails is reported and tried again on the next run.
- Folders are readable only by you (0700/0600), and no file holds a download or avatar link.

### Changed
- The cache and the archive never store any `…Url` field (also avatar links), not only `url`.

## [0.2.0] - 2026-11-05

Readable output: the CLI and the MCP server can show the data the way the Parro app does, and a
small cache stops the same newsletter from being downloaded again and again.

### Added
- **Readable markdown** for every command: an announcement feed with author, groups and a preview,
  an agenda grouped by day (all-day and multi-day items, RSVP), chat lists and conversations in
  reading order, attachments, and more. Every id stays visible, with the next command to run.
  - CLI: `--format auto|json|markdown` (also `PARRO_FORMAT`). `auto`, the default, prints markdown
    at a terminal and JSON when the output is piped, so scripts keep getting JSON.
  - MCP: every tool takes an optional `format` (`json` by default, or `markdown`).
- `overview` command and `parro_overview` tool: unread counts, the latest announcements, what is
  coming up, and chats with unread messages, like the app's home screen.
- `calendar --details` (MCP: `details: true`) adds location, description and attachments.
- `calendar --past` (MCP: `past: true`) lists earlier items, latest first.
- `calendar-link` command and `parro_calendar_link` tool: Parro's own link to subscribe to the
  agenda from Google, Apple or Outlook calendar (`GET /calendar/sync`, now in the spec and so in
  Swagger UI). The link is a secret; it is never logged.
- `calendar --ics FILE` exports calendar items as an iCalendar file (RFC 5545) to import into
  another calendar app; stable UIDs, so a newer export updates the same events.
- `--full` for `announcements` and `system-news`: whole texts instead of a 3-line preview.
- A cache for attachment files, their text, and calendar details in `PARRO_DATA_DIR` (default
  `~/.parro/data`), readable only by you and never holding download links. Lists are never cached.
  `cache info`, `cache clear`, `--no-cache`, `PARRO_CACHE=off`, `PARRO_CACHE_MAX_MB`.

### Changed
- The CLI prints markdown when its output goes to a terminal. Use `--format json` or
  `PARRO_FORMAT=json` to keep JSON there too; piped output is JSON as before.
- An announcement or calendar item that reaches you through several groups is listed once.
  Announcements then carry `groups` with every group's name; `from` keeps the first one.
- JSON additions: `author` and `pinned` on announcements, `readCount` on a single announcement,
  `chatroom_id` on chat messages. Nothing was removed or renamed.
- Calendar details list attachments without their download link; `attachment <id>` fetches one.
- `PARRO_CACHE_MAX_MB` counts 1 MB as 1,000,000 bytes, like the sizes shown.

### Fixed
- **The calendar now shows what is coming up.** The API lists calendar items with the furthest
  future first, so the first page can hold only items months ahead. `calendar` and the overview now
  read page by page until today and list upcoming items soonest first (JSON: `period: "upcoming"`).
  Before, they sorted the first page, which missed the coming weeks (also in the original server).
- **A multi-day calendar item is listed once.** The API returns one entry per day (each with its
  own id and `dayNumber`); the agenda, the overview and the .ics export now merge them by calendar
  item. The .ics UIDs are built from the calendar item, so they stay stable between exports.
- Previews stop at 300 characters as well as 3 lines; long group lists are shortened ("+5 more").
- Default paths (`~/.parro-mcp/tokens.json`, the data folder) follow `HOME` when it changes, instead
  of being fixed when the program starts.

## [0.1.0] - 2026-11-04

First public release of the client: a read-only Parro API client in Python (standard library only),
usable as a command-line tool and as an MCP server. It is an independent implementation based on the
OpenAPI specification in this repository, inspired by
[fobatai/parro-mcp](https://github.com/fobatai/parro-mcp).

### Added
- `parro_cli.py`: a command-line client with JSON output (`login`, `status`, `me`, `groups`,
  `announcements`, `attachment`, `calendar`, `chatrooms`, `get`, `token`, and more). Exit codes
  0 ok, 1 API/network error, 2 usage, 3 not logged in, 4 login halted.
- `parro_mcp.py`: an MCP server over stdio with the same 16 tools and argument schemas as the
  original server, so existing MCP configurations keep working. `parro_login` takes an optional
  `method`.
- Login methods `login-form` (default, one password check), `password-grant` and `auto`
  (`PARRO_LOGIN_METHOD`, `--login-method`).
- `login --prompt` asks for the password with hidden input and stores nothing.
- Attachments of calendar items are found and read, not only those of announcements.
- `--save-to DIR` and `--text` for `attachment`.

### Changed
- Defaults follow the API as observed in 2026: contract version `224`, app version `web:2.27.0`.
- A single announcement is fetched with `dtype=event.RAnnouncementEventPrimer`; the old type answered
  401, which broke the announcement and attachment tools.
- `--unread-only` filters before applying the limit and looks further back per group.
- The reader for an attachment is chosen by its content type (also `image/jpg`).

### Fixed: account safety
- The lockout latch now engages on *any* failed password submission, not only on recognised error
  wording. After one rejected password nothing logs in automatically until you run `login` again.
- A 401 from the API no longer deletes the token file (refresh token and latch included). The client
  refreshes once, retries once, and otherwise reports the error. It never starts a password login.
- `status` never spends a password check.
- The browser flow checks the OAuth `state`.
- Attachment download links (unsigned CDN URLs) are never logged, and the Parro token is never sent
  to the CDN or to any host other than the configured API.

[0.3.0]: https://github.com/chris-swift-dev/parro-api-client/releases/tag/v0.3.0
[0.2.0]: https://github.com/chris-swift-dev/parro-api-client/releases/tag/v0.2.0
[0.1.0]: https://github.com/chris-swift-dev/parro-api-client/releases/tag/v0.1.0
