# Plan 14: version 0.11.0, a better desktop app and hints a scanner can read

*Status: in progress (2026-11-12): phases 1–7 done on branch `desktop-0.11`, live check in `docs/LIVE-CHECKS.md`; the release is next. Decisions in §7.*

**Goal:** five changes. Four are in the desktop app: details that always fit, saving all attachments at
once, less waiting when you switch sections, and logging in by itself when you set that up. The fifth
makes the MCP tool hints visible to services that read the code, such as M8ven.

---

## 1. Details that fit in the window (your item 1)

**What happens now.** The right-hand side of Announcements and Calendar is one column, in this order:

| Part | Grows or shrinks | Scrolls |
| --- | --- | --- |
| The text (`SafeTextBrowser`) | gives up all its height first | yes |
| The attachments card, one row per file | never, always its full height | no |
| The answer and helper rows (Calendar) | never | no |
| *Mark as read* | never | no |

Each row below the text claims its full height. With many attachments or helper slots, the text gets
squeezed to a few lines. When even that is not enough, the column becomes taller than the window, and
the rows at the bottom fall off the screen. *Mark as read* is the last row, so it goes first. That is
what you saw.

**The change:**

1. **A row of actions, always visible,** directly under the text: *Mark as read* and *Save all
   attachments…* (item 4). It does not scroll away (your 1.4).
2. **A lower panel that can scroll,** under the actions: the attachments and the answer and helper rows
   (your 1.2).
3. **The text and the lower panel share the height through a splitter** that you can drag. The lower
   panel takes the height it needs, up to half; anything beyond that scrolls (your 1.1, see
   decision 1).
4. **Nothing may make the section taller than the window** (your 1.3): the text and the lower panel
   have a small minimum height, and everything else scrolls.

**Tests**, offscreen and with invented data: an item with 30 attachments and 10 helper slots in a
1000 × 680 window. *Mark as read* lies inside the window and can be clicked, the section is no taller
than the window, and both parts scroll. Then the same test with no attachments: the lower panel takes
no room.

## 2. Saving all attachments at once (your item 4)

The core can do this already. `operations.read_attachments(…, read_all=True)`, with a folder to save
into, is what `attachment ID --all --save-to DIR` uses.

- **A button *Save all attachments…*** in the action row, next to *Mark as read*. It is only enabled
  when the item has attachments.
- **One question:** which folder. Then the files download one after another, in the background, through
  the one worker. Files already in the cache are not downloaded again.
- **What it reports:** "Saved 7 files in …". If some fail, it names which ones failed and why. A file
  with the same name must not be overwritten. I have not checked yet what the core does there; if it
  overwrites, that changes for the CLI too, with a test.
- **No retry,** as everywhere: a file that failed is reported, and you can click again.

## 3. Less waiting, and showing how old the data is (your item 2)

**What happens now.** I expected reloading on every switch, but the code does something else, which
explains part of the waiting:

- **Each section loads once per session.** Switching away and back does not load it again; *Refresh*
  does.
- **Changing a filter loads again,** every time, also when you go back to a choice you saw a minute
  ago (*All groups* → *Group 5* → *All groups* is three loads).
- **Choosing an announcement fetches it in full,** every time, also one you opened a minute ago.
  Calendar details come from the disk cache when the item has not changed.
- **After logging in again,** all sections forget what they showed.

I will measure this on the live check before building, because the cause may be somewhere I have not
looked yet.

**Why not the CLI's cache.** The disk cache deliberately holds no lists (`parro/cache.py`): lists are how
the client learns what is new or read, and a stale list on disk would hide that. It caches only files
and calendar details, and only while they cannot be out of date. The app already uses that cache.

**The change: a short memory, in the app only, never on disk:**

- **The answer for each section and filter choice** is kept for **5 minutes** (decision 2). Going back to
  a choice within that time shows the kept answer at once.
- **The full text of an announcement** is kept for the same time.
- **"Fetched at 14:32"** next to each section's title, and in the detail view. It shows the time of the
  answer that is shown, kept or fresh. Older than 5 minutes: a new load starts by itself when you come
  back.
- ***Refresh* always fetches,** and so does every change you make: after *Mark as read*, an answer or a
  sign-up, that section's kept answers are dropped. Logging out drops everything.
- **Unread counts:** the Overview may show a count up to 5 minutes old. The time next to it says so.

## 4. Logging in by itself (your item 3)

**What happens now.** Your login survives a restart: the app uses the same token file as the CLI. But a
login lasts at most 8 hours (`docs/LOGIN.md`), so after a night you type the password again. The CLI
and the MCP server log in again by themselves when `PARRO_USERNAME` and `PARRO_PASSWORD_FILE` are set,
**once**, and stop for good after a rejected password (the latch).

**What I think.** Yes, with the same rules as the CLI, and without the app ever storing the password
itself:

1. **Where the password comes from: a file you choose.** The same `PARRO_USERNAME` and
   `PARRO_PASSWORD_FILE` as the CLI work when you start the app from a terminal. An app started from
   the menu or the dock does not see those variables, though. So the login dialog gets **"Log in by
   myself with this password file"**: it remembers the e-mail address and the *path* to the file, in
   the app's own settings. The password itself stays in your file (see decision 3).
2. **When:** at start, if the login has expired, and when it expires while the app is open. Each time,
   **one** password check, through the same core path the CLI uses for automatic logins.
3. **The latch decides, not the app.** After a rejected password, nothing logs in by itself until you
   log in by hand in the dialog. The status bar says why. An automatic login never clears the latch.
4. **Not silent:** the status bar says "Logged in by itself at 08:12, with the password file".
5. **The file must be private:** if others can read it, the app says so and does not use it. On Windows
   only "the file exists and can be read" is checked.

**Tests:** against the fake login server. One check at start, none when a valid login exists, none
after a rejection (also not after a restart), and never two in one start. The password is never kept in
memory longer than the call, and never written to the app's settings.

## 5. Tool hints that M8ven can see (your MCP item)

**What M8ven says.** "No tools have read-only/destructive annotations", and "20/20 tools missing one or
more hints". It also says: *"We tried to run this server and could not. The grade rests on the code we
read."*

**What the server really sends.** I ran it. `tools/list` returns all four hints, as booleans, inside
`annotations`, for all 25 tools. That is where the MCP specification puts them (`ToolAnnotations`:
`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`, and `title`). So clients such as
Claude get them already.

**Why M8ven misses them.** M8ven reads the source instead of running the server. Our tool definitions
have no hints in them. A loop at the end of the file adds them from a separate table (`TOOL_HINTS`)
when the module loads. A reader of the source sees 20 dictionaries without `annotations`, which is
exactly the report. The 5 changing tools are not counted at all: they live outside the list it read.

**The change:**

1. **The hints written into each tool's definition,** as a plain `"annotations": {…}` with `True` and
   `False` spelled out. No helper function or shared constant: a code reader may not follow names. The
   loop and `TOOL_HINTS` go away.
2. **A top-level `title` for every tool** (MCP 2025-06-18), for example "Calendar". The same title also
   stays in `annotations.title` for older clients. Today only the 5 changing tools have a title.
3. **A guard test that reads the source the way a scanner does** (Python's `ast`). Every tool
   definition must contain a literal `annotations` with the four hints as `True` or `False`. The
   existing `tests/test_tool_hints.py` keeps checking that the hints are *true*.
4. **After merging:** M8ven re-checks on every push. We look at the report again. Whether it then
   counts all 25 tools is up to M8ven.

**Not part of this:** why M8ven could not run the server. The server starts and lists its tools without
a login (I tried it), so M8ven probably did not find how to start it. If you want, this becomes its own
small task: find out what M8ven needs, for example an entry in the MCP registry (`server.json`).

## 6. Phases

| # | Phase | Done when |
| --- | --- | --- |
| 1 | ✅ **MCP hints in the source** (§5) | the `ast` guard test and `test_tool_hints.py` pass; `tools/list` is unchanged apart from the new titles |
| 2 | ✅ **Details that fit** (§1) | the tests in §1 pass |
| 3 | ✅ **Save all attachments** (§2) | tests against the fake API: one folder question, every file saved, failures named, nothing overwritten |
| 4 | ✅ **Short memory and "Fetched at"** (§3) | tests: a kept answer within 5 minutes, a new load after it, *Refresh* and every change drop what was kept, nothing written to disk |
| 5 | ✅ **Logging in by itself** (§4) | the tests in §4 pass |
| 6 | ✅ **Docs:** `docs/DESKTOP-APP.md` (screens, password file, the memory), `docs/MCP.md`, `SECURITY.md` (the remembered path), changelog **0.11.0** | links and pictures checked |
| 7 | ✅ **Live check with you:** the two items that broke the layout, switching sections, save all, and logging in by itself **once** (one password check) | in `docs/LIVE-CHECKS.md`; M8ven's report after the push |
| 8 | Release **0.11.0** | published |

Phase 1 comes first: it is small, it does not touch the app, and M8ven's report can update while we
work on the rest.

## 7. Decisions (taken 2026-11-12)

1. **How the text and the lower panel share the height:** ✅ the lower panel takes what it needs, up to
   half, and the splitter can be dragged. *Not chosen:* always half and half, also when there is only
   one attachment.
2. **How long the app keeps an answer:** ✅ 5 minutes. *Not chosen:* 2 or 15 minutes.
3. **Where the password for logging in by itself comes from:** ✅ a password file you choose, its path
   remembered by the app, plus `PARRO_USERNAME`/`PARRO_PASSWORD_FILE` as in the CLI. *Not chosen:* the
   system's keychain through the `keyring` package (extra packages in the `gui` extra, and on Linux a
   running keyring service).
4. **The MCP titles:** ✅ a top-level `title` on every tool, plus `annotations.title`. *Not chosen:* the
   hints only.
