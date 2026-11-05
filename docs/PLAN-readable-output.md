# Plan 3: human-readable output for the CLI and the MCP server

*Status (2026-11-05): phases 0–6 released as 0.2.0. Phase 7 (archive) done on the `archive-sync` branch;
phase 8: docs and version 0.3.0 done, live `sync` and release pending.*

**Goal:** besides JSON, `parro_cli.py` and `parro_mcp.py` can show the data the way the Parro app does:
a feed of announcements with author and photos, an agenda grouped by day, chat conversations, and an
overview of what is new.

---

## 1. Challenging the idea

**"They only return raw JSON" is not quite right.** Raw JSON is only what `--raw` returns. The default
output is already a *summary*: geon bookkeeping removed, groups merged, newest first. What is missing
is *presentation*: dates people can read, things grouped the way people think (per day, per
conversation), and noise left out. So this is a rendering layer on top of the existing summaries, not
a new data layer.

**Who reads the output decides whether it helps.**

| Reader | Today | With a readable format |
| --- | --- | --- |
| A person at a terminal | Reads JSON with ids, ISO dates and `\n` escapes. Tiring | Much better: this is the real win |
| A script (`jq`, cron) | Exactly what it needs | Must not change. JSON stays available, and stays the default when stdout is not a terminal |
| An LLM through MCP | Reads JSON well, and uses the ids for follow-up calls (`parro_attachment`) | Mixed. Markdown costs fewer tokens and is what the model shows the user anyway, **but** it must keep every id the follow-up tools need. Otherwise the model can no longer chain calls |

So: **opt-in for MCP, default for a person at a terminal, never by surprise for scripts.**

**"Markdown?": yes for MCP and for files, but only partly for the terminal.** A terminal shows
markdown as plain text: `**bold**` shows its asterisks. Two ways around it:
- write *light* markdown that reads well raw: `#` headings, `-` lists, `>` quotes for message text,
  no tables and no `**`. This works in a terminal, in a file, in `glow`, and for an LLM;
- or have a separate terminal renderer with ANSI colours. More code, and it duplicates every view.

Recommended: **one light-markdown renderer**. Terminal colours can come later, as a thin pass over
the same output (respecting `NO_COLOR`), if they are missed.

**"Like the app does" has limits, and we should say so.**
- No pictures: photos become "28 photos" plus the command to save or view them, not 28 lines.
- No interaction: no tapping into a thread. Every view ends with the command for the next step
  (`parro_cli.py announcement 23087273268`, `attachment … --save-to DIR`).
- The app loads details lazily. For us, each calendar item's location and description is **one
  extra request per item** (the list endpoint does not return them). That stays opt-in (`--details`).

**Real aggregation is needed in a few places, and it is the valuable part:**
1. **Duplicates:** the feed is fetched per group. An announcement sent to two groups probably arrives
   twice (same id). The app shows it once, with both groups. *To verify against the live API.*
2. **Author:** list items already include `owner`, but the summary drops it. The app shows who
   posted.
3. **Calendar:** group items by day, recognise all-day items (`00:00`) and multi-day items
   (`numberOfDays`, `dayNumber`), and mark items that need an answer (`rsvpRequired`).
4. **Chats:** messages grouped by day with sender names and in reading order. The order the API
   sends them in is **unknown** (the only sample has one message), so check it live first.
5. **Overview:** unread counts, recent announcements and the next calendar items in one view. That
   is the app's home screen, and it is a new command, not a format of an existing one.

**Things that cost more than they look:**
- **Dates and language.** Content is Dutch, our labels are English. Month and weekday names in
  Dutch would need the system locale (unreliable in Docker) or our own small tables. Recommended:
  English labels and dates like `Tue 3 Nov 18:39`, in the offset the API sends (school time), *not*
  the machine's timezone. A Docker container runs in UTC and would show wrong times.
- **HTML:** system news is HTML. Reuse `attachments.extract_html_text()`.
- **Length:** 20 full announcements make a long terminal page. List views show a preview (first
  3 lines), and the single-item commands show everything. For MCP the model wants full text, so
  "full" is the default there.
- **Tests in CI:** `samples/` is git-ignored, so most output tests would skip in CI (as 119 of 219
  tests already do). This work needs *synthetic* fixtures that can be committed, and they also
  close that existing gap.

**Not worth doing (now):** a TUI, terminal images, HTML output, a second renderer for colours.

## 2. Design

```
operations.py  ──returns──▶  summary dicts (JSON-ready)  ──▶  JSON (as today)
                                    │
                                    └──▶  parro/rendering.py  ──▶  light markdown text
```

- **`parro/rendering.py`** (new): pure functions, one per view:
  `render_announcement_feed(summary) -> str`, `render_agenda`, `render_chatrooms`,
  `render_conversation`, `render_groups`, `render_unread`, `render_account`, `render_attachment`,
  `render_overview`, plus a fallback for `get` (a fenced JSON block). A table
  `RENDERERS[command] = function` connects them to commands. Helpers: `format_date()`,
  `format_day_heading()`, `preview()`, `quote()`, `plural()`.
- **The input is the summary dict, not the raw payload.** That keeps one data model. Where a view
  needs more, the summary gains fields (**additive only**: `author`, `pinned`, `groups`,
  `photo_count`, …), so JSON users see richer output and nothing breaks. The parity tests learn
  to allow these additions.
- **Aggregation goes into summaries / operations, not into the renderer:** deduplication, grouping
  by day and the overview belong to the data, so JSON users get them too. The renderer only lays
  out text.
- **Ids always stay visible** in the markdown, e.g. `#23087273268`, together with the follow-up
  command. That keeps it usable for an LLM.

### Switches

| Where | Switch | Values | Default |
| --- | --- | --- | --- |
| CLI | `--format` (global) | `auto`, `json`, `markdown` | `auto`: markdown when stdout is a terminal, JSON otherwise (like `gh`). `PARRO_FORMAT` overrides it |
| MCP | `format` argument on each reading tool | `json`, `markdown` | `json`, so existing clients see no change |

`--raw` always means JSON (raw + markdown is a usage error). `--compact` applies only to JSON.
`token` and `attachment --text` stay plain text. The MCP `format` argument is an *additive, optional*
schema change, like `method` was. The interface test grows with it.

## 3. Views (what each one shows)

| Command / tool | Markdown view |
| --- | --- |
| `announcements` | `## <title>` · `<author> → <group(s)> · <date>` · preview (3 lines, full for MCP) · `📎 Newsletter.pdf (1.5 MB)` / `🖼 28 photos` · unread marked `● new` · pinned first · the follow-up command |
| `announcement <id>` | The same item with full text, likes/read counts and the attachment list with `attachment` commands |
| `calendar` | Agenda: `### Tue 3 Nov` headings; per item time range or "all day", title, group(s), `RSVP needed`; `--details` adds location and description (N extra requests) |
| `chatrooms` | One line each: title, members, unread count, time and preview of the last message; archived ones at the end or hidden (`--archived`) |
| `chat-messages <id>` | Day headings, `**Name** 16:28` followed by the message as a quote, in reading order |
| `groups`, `children`, `me`, `unread` | Short lists / key-value lines |
| `attachment` | Metadata line (`Newsletter.pdf · 9 pages · pypdf`) followed by the text as is |
| `overview` (new) | Unread counts, the 5 newest announcements (titles), the next 5 calendar items, unread chats |
| `get` | Fenced JSON (no generic markdown for unknown shapes) |

## 3b. Local data: a cache and an archive

The wish "save the data as markdown files, and use them so the same data is not fetched again" is
two different features. They are built separately.

**Why markdown files cannot be the cache:**
- Markdown is a *rendered view*. JSON output, `--raw` and a changed layout cannot be produced from it
  again. A cache has to store the source data (JSON) or the original files.
- Parro data changes: read/unread flips when something is opened in the app, announcements are
  edited, likes change, new posts arrive. A cached list shows `● new` for things already read and
  misses new posts until it expires.
- Lists are cheap: the feed is 1 + one request per group (4 in practice), and that request is how
  we learn what is new. **Lists are never cached.**

### The cache (release 0.2.0)

Only where it saves real work, and only where staleness can be checked exactly:

| What | Key | Valid until | Saves |
| --- | --- | --- | --- |
| Attachment files and their extracted text | attachment id + `uploadId` + size | forever (an upload never changes; a new upload has a new id) | the 1.5 MB download and the PDF reading, e.g. when an LLM reads the same newsletter several times |
| Calendar item details (`--details`) | event id + `lastModifiedAt` from the list | the list shows a newer `lastModifiedAt` | the N extra requests per agenda view |

- Stored as the original bytes / JSON in `<data dir>/cache/`, never as markdown.
- `parro/cache.py` (new): `get` / `put` by key, size cap (`PARRO_CACHE_MAX_MB`, default 500), oldest
  first out. `--no-cache` and `PARRO_CACHE=off` switch it off; `cache clear` empties it.
- MCP benefits automatically; nothing changes in the tool schemas.

### The archive: `parro_cli.py sync` (release 0.3.0)

A local copy of everything the account can see, as files people can read and search:

```
<data dir>/archive/
  announcements/2026-10-22-nieuwsbrief-nr-3-5000000101.md    (+ .json, + attachments/)
  calendar/2026-11-11-sint-maartenviering-7000000101.md
  chats/<chatroom title>-<id>.md                              (whole conversation)
  index.md                                                    (newest first, links to all files)
```

- Built from the same renderers as the CLI views (so it needs phases 2–4 first). Each `.md` has a
  small header block with id, type, dates and source, and a `.json` with the summary next to it.
- **Incremental:** an item whose `lastModifiedAt` did not change is not rewritten; attachments come
  from the cache and are never downloaded twice. A second `sync` only fetches the lists.
- Also covers last school year (`--previous`), before it gets harder to reach in the app.
- File names: date + slug of the title + id (unique, sortable, stable when a title is edited: the
  old file is renamed).
- Deleted or withdrawn items are **not** removed from the archive; `index.md` marks them.
- MCP: no archive tool at first. Writing a full archive is a CLI job; it can be revisited.

### Where the data lives

- One folder, `PARRO_DATA_DIR`, default `~/.parro/data` (your suggestion), with `cache/` and
  `archive/` inside. `sync --to DIR` writes the archive elsewhere.
- The token file stays at `~/.parro-mcp/tokens.json` so existing logins keep working. Moving it under
  `~/.parro/` is a later, separate change with a migration.
- Docker: point `PARRO_DATA_DIR` at the `/data` volume (DEPLOY.md).

### Privacy and safety

- These files hold children's names, photos and school mail: folders are created with mode 0700 and
  files with 0600, like the token file.
- CDN download links are never written into archive or cache files (they are unsigned, see the spec).
  The `.json` next to an archive file is the summary *without* `url` fields.
- Nothing in the cache or archive is ever sent anywhere; still read-only towards Parro.

## 4. Phases

| # | Phase | Done when |
| --- | --- | --- |
| 0 | **Decisions** (§6). The two live questions are designed around instead of checked first: (a) the feed is always deduplicated by id, which is right whether or not the API repeats an announcement per group; (b) chat messages are sorted by `createdAt`, whatever order the API sends. Both are confirmed in the live look of phase 6 | done 2026-11-05 |
| 1 | **Synthetic fixtures** in `tests/fixtures/api/` (invented, committable), and FakeParroApi uses them when `samples/` is absent | CI runs (almost) all tests instead of skipping 119 |
| 2 | `rendering.py` skeleton, `--format` / `format` plumbing, simple views (`me`, `groups`, `children`, `unread`, `get`) | snapshot tests pass; JSON output unchanged |
| 3 | Announcements: additive summary fields, deduplication, feed and detail views | snapshot tests; JSON parity apart from the listed additions |
| 4 | Calendar agenda incl. `--details`; chat list and conversation | snapshot tests |
| 4b | Cache (§3b): `parro/cache.py`, attachment and calendar-detail caching, `--no-cache`, `cache clear`, size cap, file modes | tests: second read makes no download; a newer `lastModifiedAt` refetches; files are 0600 |
| 5 | `overview` command / `parro_overview` tool | runs against the fakes; tools/list = old + `format` + `parro_overview` |
| 6 | Docs (README with example output, CODE-TOUR, CHANGELOG), live look with you, release **0.2.0** | released |
| 7 | Archive: `sync` command (§3b): file layout, incremental updates, `index.md`, `--previous`, `--to DIR` | a second `sync` against the fakes only requests the lists; no `url` in any written file |
| 8 | Docs, live `sync` with you, release **0.3.0** | released |

Snapshot tests: each view is rendered from the synthetic fixtures and compared with a committed
`.md` file, so a layout change shows up as a readable diff.

### Implementation notes (2026-11-05)

- Additions to the MCP interface: `format` on every tool, `details` on `parro_calendar`, and a new
  17th tool `parro_overview` (at the end; the original 16 keep their names, arguments and order).
- JSON additions: `author`, `pinned`, `groups` on feed items; `readCount` on the announcement detail;
  `chatroom_id` on chat messages; `details` on calendar items with `--details`. The feed and the
  agenda list each item once. Calendar details never carry download links, cached or fresh.
- Chat messages are sorted only in the markdown view; JSON keeps the API's order.
- The group list is not cached (a long-running MCP server would keep it stale); the overview
  fetches it once per call and passes it to both feeds.
- Live look (2026-11-05): announcements do come back once per group, chat messages come newest
  first, and calendar lists come **furthest future first**. The last one was a bug in the
  original design: `calendar` and the overview now page to today (`--past` for earlier items).
- Archive (phase 7) decisions: photos are opt-in (`--photos`), documents always saved; every list
  is read in full on each run (edits and removals are only noticed that way), unchanged items are
  skipped; `.md` files start with a YAML header; a saved file counts as complete because files are
  written in one step; an item with a failed download is marked `|incomplete` and retried; the
  archive and the cache also drop every `…Url` field (avatar links carry an access key).
- `parse_timestamp()` lives in `geon.py` (needed by summaries and rendering) and accepts every
  fraction length, which Python 3.10's `fromisoformat` does not.

## 5. Risks

- **Changing the CLI default** could break someone who runs the CLI under a pseudo-terminal and
  parses its output. Mitigation: `auto` only looks at whether stdout is a terminal, `--format json`
  and `PARRO_FORMAT=json` always win, and the CHANGELOG says so. Alternative: keep JSON as the
  default for 0.2.0 and switch in 0.3.0.
- **Ids lost in markdown** would break MCP follow-up calls. Mitigation: a test that every id in the
  JSON summary also appears in its markdown.
- **Layout bikeshedding.** Mitigation: snapshot files make every change visible; agree on the
  announcement feed first, then copy its style.
- **Personal data on disk** (cache, archive). Mitigation: 0700/0600, no download links in files,
  `cache clear`, and the README says what is stored where.
- **A wrong cache entry served as fresh.** Mitigation: only data with an exact validity check is
  cached (ids that never change, or `lastModifiedAt` from a fresh list), never lists.

## 6. Decisions (2026-11-05)

1. **CLI default:** `auto`: markdown when stdout is a terminal, JSON otherwise.
2. **MCP default:** JSON, with an optional `format: "markdown"` argument.
3. **Label language:** English; dates in the offset the API sends (school time).
4. **Markers:** emoji (📎 🖼 ●).
5. **Saving data to files:** split into a **cache** (JSON and original files; attachments and
   calendar details only; release 0.2.0) and an **archive** (`sync` writes markdown + JSON +
   attachments; release 0.3.0), both under `PARRO_DATA_DIR` (default `~/.parro/data`). Lists are
   never cached; the token file stays where it is.
