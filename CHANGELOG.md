# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/),
and versions follow [Semantic Versioning](https://semver.org/). The release workflow publishes the
section of a version as its GitHub release notes, so write each section for users.

## [0.12.0] - unreleased

### Added

- **The desktop app without Python:** each release has an installer for Windows (`.msi`), macOS 14 or
  newer (`.dmg`, Apple silicon and Intel) and Linux (`.flatpak`, x86_64 and aarch64), with Python and
  Qt inside. They are not signed yet; [docs/INSTALL-DESKTOP.md](docs/INSTALL-DESKTOP.md) explains the
  first start on each system. Each file is in `SHA256SUMS` and has a GitHub build attestation
  (`gh attestation verify`).
- **Desktop app: telling you about a new version,** if you agree at the first start. It asks GitHub
  at most once a day, sends nothing about you, and downloads nothing itself. A *Help* menu has the
  switch, *Check for updates now* and *About*.
- **The desktop app has its own icon,** in the window, the taskbar and the installers.
- **Desktop app: HTTPS certificates are checked by the operating system,** as a browser does it,
  through the small `truststore` library (now part of the `gui` extra and the installers). Without
  it, the installers' own Python could not verify Parro, GitHub or the attachment server on macOS and
  some Windows computers. Certificates a company installs on the computer work too. The command line
  and the MCP server are unchanged.

### Changed

- **Desktop app: a chat opens at its newest message,** like other chat apps. It stays at the end
  while the window or the splitter changes size, until you scroll up; after *Send…* it is at the end
  again, with your message.
- **Desktop app: a message above a section takes at most two lines.** The rest, such as every file
  that *Save all attachments…* could not save, is behind *Details…*, where it scrolls and can be
  copied, and the message can be closed. *Save all* counts the reasons instead of listing every file.
  Long attachment names are shortened with "…", so their buttons stay in view, and the window has a
  minimum size (760 × 520) at which every section's buttons fit.
- **Desktop app: the login dialog shows only the password form.** Logging in in the browser, which
  few people need, is under *Other ways to log in…*; a browser login that was started and not
  finished opens there directly, also after a restart. The command line and the MCP server are
  unchanged.
- **Desktop app:** `parro-client-gui --version`, and `--self-check`, which starts the app without a
  screen and without logging in, to check an installation.

## [0.11.0] - 2026-11-12

A better desktop app: details that always fit in the window, saving all attachments at once, less
waiting when you switch sections, and logging in by itself from a password file. Tab completion for
the command line. And the MCP tool hints can now be seen by services that read the code instead of
running the server.

### Added
- **Save all attachments…** in Announcements and Calendar, next to *Mark as read*: one folder
  question, then every file, with a report that names each file that failed.
- **Logging in by itself** in the desktop app: tick the box in the login dialog and choose a private
  file with your password. One password check when the login has expired, none after a rejected
  password until you log in by hand. Only the e-mail address and the file's path are remembered.
  `PARRO_USERNAME` and `PARRO_PASSWORD_FILE` work as in the command line.
- **"Fetched at 14:32"** next to each section's title, and under an opened announcement.
- Every MCP tool has a `title`.
- **Tab completion for the command line** in bash, zsh and fish: `parro-client completion bash`
  (or `zsh`, `fish`) prints a script for your shell's startup file. It completes commands, options,
  their fixed values and file names, and never contacts Parro.

### Changed
- An announcement or calendar item with long text, many attachments or many helper slots fits in the
  window: *Mark as read* stays visible under the text, the attachments and the answer and helper rows
  scroll, and a line you can drag shares the height between the two.
- The desktop app keeps what it fetched for 5 minutes, in memory only, so switching sections or going
  back to a filter choice is instant. **Refresh** and every change you make fetch again.
- The MCP tool hints (`readOnlyHint` and the others) are written into each tool's definition in the
  code, so services that read the code see them. What clients receive is unchanged.

### Fixed
- **A quick second click in the desktop app could send a chat message twice:** two clicks on *Send…*
  opened two previews, and confirming both sent it twice. Every button that starts a request now stays
  off until the answer is in, and a section runs one action at a time. The same goes for answers,
  helper sign-ups, *Mark as read* (which asked twice), *Refresh*, the subscription and privacy links,
  and reading or saving an attachment.
- In the desktop app, *Mark as read* and the last answer or helper rows could fall off the bottom of
  the window for an item with a lot in it, and could not be reached.
- Saving an attachment claims the file name and writes it in one step, so a file that appears in the
  meantime is not replaced either (also for `--save-to`).

## [0.10.0] - 2026-11-10

A desktop app: `parro-client-gui` does what the command line does, in a window on Windows, macOS and
Linux. It is optional, and it needs Python 3.12 or newer. The command line and the MCP server do not
change and keep working on Python 3.10 or newer.

### Added
- **`parro-client-gui`**, installed with `pipx install "parro-api-client[gui]"`: an overview,
  announcements with attachments, the calendar, chats, your family's details and the local archive.
- It shares its login, cache and archive with the command line.
- It follows your system's light or dark setting. The sidebar's icons are from Lucide (ISC licence),
  and their licence comes with the app.
- The four changes the client can make are all there, and need a click on **Confirm** in a dialog that
  shows exactly what would happen. Nothing changes because you opened or read something.
- `docs/DESKTOP-APP.md` explains it.

### Changed
- `sync_archive` can report its progress, for the desktop app. The command line behaves as before.

## [0.9.0] - 2026-11-09

Say whether you are coming: `rsvp` answers a calendar item's invitation with accept, decline or
tentative. **This changes the client's promise again:** it reads, and it can change four things,
only when you ask: mark items as read, send a text message, sign you up or withdraw you as a helper,
and answer an invitation. An answer is a statement in your name: the school sees it, and you can
change it but not remove it.

### Added
- **`rsvp accept|decline|tentative EVENT`**. It shows the item, your current answer and the new one,
  and asks first. `--yes` skips the question for scripts; without a terminal and without `--yes`,
  nothing changes.
- It refuses an item that does not ask for an answer, an item that is cancelled and an item in the
  past. The answer you already gave is not sent again.
- The agenda and `overview` show your answer in place of *RSVP needed*.
- The MCP tool **`parro_rsvp`**, only when you set `PARRO_ALLOW_RSVP=1` (a switch of its own). Without
  `confirm: true` it only returns the preview, and it is marked as destructive so MCP clients ask
  first. Please read the warning in the README before you switch it on.
- The spec describes answering an invitation, your own answer on the event, and the list of everyone
  an invitation went to, with a warning about the personal data in it.

### Changed
- The MCP tools `parro_get` and `parro_attachment` refuse the list of everyone an invitation went to,
  because it holds other people's names and answers. The command `get` still reaches it if you ask.
- An answer is never repeated on its own: after a timeout or a server error the client says it may
  or may not have gone through.
- The README, the help text, `SECURITY.md` and the User-Agent describe the new promise.
- The README is shorter again. The details moved to three guides that come with every download:
  `docs/CHANGING-THINGS.md`, `docs/MCP.md` and `docs/CALENDAR-AND-ARCHIVE.md`.

## [0.8.0] - 2026-11-08

Say you can help: `helper signup` and `helper withdraw` put you on a calendar item's helper slot, or
take you off it. **This changes the client's promise again:** it reads, and it can change three
things, only when you ask: mark items as read, send a text message, and sign you up or withdraw you
as a helper. A sign-up is a promise in your name: the school sees it, and you may take the last
place.

### Added
- **`helper signup EVENT`**, with `--count N` for more than one place (for example three children
  in your car) and `--slot ID` when an item has several slots, and **`helper withdraw EVENT`**. They
  show the item, the slot and the places taken, and ask first. `--yes` skips the question for
  scripts; without a terminal and without `--yes`, nothing changes.
- They refuse an item that asks for no helpers, an item in the past, a full slot, a count that does
  not fit the places left, signing up where you already have, and withdrawing where you have not.
- `calendar --details` shows the id of each helper slot.
- The MCP tools **`parro_helper_signup`** and **`parro_helper_withdraw`**, only when you set
  `PARRO_ALLOW_HELPER_SIGNUP=1` (a switch of their own). Without `confirm: true` they only return
  the preview. Please read the warning in the README before you switch them on.
- The spec describes adding, listing and removing a helper commitment, and says what is not known
  about it.

### Changed
- A helper change is never repeated on its own: after a timeout or a server error the client says
  it may or may not have gone through.
- The README, the help text, `SECURITY.md` and the User-Agent describe the new promise.
- The README's opening note no longer says only `GET` calls are used, which stopped being true in
  0.6.0.

## [0.7.0] - 2026-11-08

Reply from the terminal: `chat-send` sends a text message to a chat you are in. **This changes the
client's promise again:** it reads, and it can change two things, only when you ask: mark items as
read, and send a text message. Real people receive what you send, under your name, and as far as we
know a message cannot be taken back.

### Added
- **`chat-send ID "text"`** (or `--file PATH`, `--file -` for standard input). It shows the chat, who
  receives the message and the exact text, and asks `Send this message? [y/N]`. `--yes` skips the
  question for scripts; without a terminal and without `--yes`, nothing is sent.
- It refuses empty text and chats that are archived, that you have left, that have replies switched
  off, or that are with a bot.
- The MCP tool **`parro_send_chat_message`**, only when you set `PARRO_ALLOW_SEND_CHAT=1` (a switch of
  its own). Without `confirm: true` it only returns the preview, and it is marked as destructive so
  MCP clients ask first. An assistant also reads what others write, so please read the warning in
  the README before you switch it on.
- The spec describes `POST /chatroom/{id}/chatmessage`, and says what is not known about it.

### Changed
- A message is never sent twice on its own: after a timeout or a server error the client says it may
  or may not have arrived. The text is never logged or stored.
- The README, the help text, `SECURITY.md` and the User-Agent describe the new promise.
- Writes no longer follow redirects.
- Every MCP tool now states all four hints (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
  `openWorldHint`), matching what it does. MCP clients can use them to decide when to ask you.

## [0.6.0] - 2026-11-07

See what is new, and mark what you have read: `overview` now shows only unread announcements and
new calendar items, and `mark-read` marks an item as read. **This changes the client's promise:**
it used to be read-only; now it reads, and the one change it can make in Parro is marking items as
read, only when you ask. The school sees what you mark (read counts, read receipts), and so does
the Parro app.

### Added
- **`mark-read announcement|calendar|chat ID`** marks one item as read. It looks the item up first,
  so a wrong id is an error, not a write, and leaves items that are already read alone.
  `mark-read group ID` shows how many unread announcements a group has; with `--yes` it marks them
  all.
- **`--mark-read`** on `announcement ID` and `chat-messages ID`: show it, then mark it.
- The MCP tool **`parro_mark_read`** (one item at a time), only when you set
  `PARRO_ALLOW_MARK_READ=1`. It is marked as not read-only, so MCP clients ask before calling it.
- Chat filters: `chatrooms --unread --archived only|include --type group --schoolyear 2025`, and
  `chat-messages ID --since 2026-10-01`. The MCP tools take the same options.
- **`chat-members ID`** (MCP `parro_chat_members`): who is in a chat, parents with their children
  and teachers, and who is admin; `--former` adds members who left.
- The spec describes 10 more operations: chat details, members, scheduled and single messages,
  school years, an identity, an announcement attachment, and the three calls that mark items read
  (in their own section, *Read state*, which says what the school sees).

### Changed
- **`overview` lists only what you have not read**: unread announcements and new calendar items.
  `overview --all` (MCP `all: true`) shows the latest announcements and everything coming up, as
  before.
- `chatrooms` leaves archived chats out, as the API does by default; `--archived include` adds them.
- The README, the help text, `SECURITY.md` and the User-Agent describe the new promise. Making the
  client write anything else, or mark something without being asked, is a security problem.

### Fixed
- `sync` missed archived chats: the API leaves them out unless asked. It now archives them too.

## [0.5.1] - 2026-11-06

Know how long you stay logged in: a login lasts at most 8 hours, and `status` now says until when.

### Added
- `status` (MCP `parro_auth_status`) says until when the login lasts and what happens then, e.g.
  `Login: valid until Fri 6 Nov 2026 19:37 (7 h 40 min left); then log in again`. JSON:
  `login_valid_until`, `login_expires_in_seconds`.

### Fixed
- The docs, the help text and the spec promised that a login with `offline_access` lasts "far
  longer" than the web app's 8 hours. Measured: a login lasts at most 8 hours, however often it is
  refreshed. They now say so, and what happens after 8 hours.
- The TestPyPI install command in the docs (`--extra-index-url`, as pipx needs it).

## [0.5.0] - 2026-11-06

Install it like any other command, on Windows, macOS and Linux: `pipx install parro-api-client`
(or `uv tool install parro-api-client`), then `parro-client overview`.

### Added
- **The commands `parro-client` and `parro-client-mcp`**, from the Python package
  `parro-api-client` on PyPI. pipx and uv put them on your PATH (on Windows as `.exe` files) and
  update them with one command. The MCP server can also run without an install step:
  `uvx --from parro-api-client parro-client-mcp`.
- Releases carry the wheel and sdist next to the archives, all in `SHA256SUMS`. Publishing a
  release uploads exactly those two files to PyPI, with trusted publishing (no token stored).
- Tested on Windows, macOS and Linux, Python 3.10 and 3.14, including installing the package and
  running both commands.

### Changed
- Help, hints and messages name the command as you started it: `parro-client …` when installed,
  `parro_cli.py …` from a release archive. `python3 parro_cli.py` and `parro_mcp.py` keep working,
  so existing MCP configurations need no change.
- The code of the CLI and the MCP server moved into the package (`parro/cli.py`,
  `parro/mcp_server.py`).
- Archived files say `archived with parro-api-client (sync)` in their header.
- The README's links and pictures are absolute, so they also work on the PyPI page.

### Fixed
- On Windows: output is UTF-8 (the console could not print markers such as ● and 📌),
  `calendar --ics -` keeps single CRLF line endings, and the MCP server ends each message with a
  plain line feed.

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
