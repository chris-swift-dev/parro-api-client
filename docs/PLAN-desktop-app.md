# Plan 12: a cross-platform desktop app

*Status: planned (2026-11-09); decisions taken in §8. No phase started yet.*

**Goal:** `parro-client-gui`, a desktop app for Windows, macOS and Linux that does what the CLI does,
on top of the existing `parro` package. No second implementation of login, API calls or safety rules.

---

## 1. What this project needs from a UI library

| Need | Why here |
| --- | --- |
| **No new way in** | The app holds login tokens and children's data, and can speak in the parent's name. It should not add a network listener |
| **`parro/` stays standard library only** | That is a founding rule. The GUI has to be an optional extra, so the CLI and the MCP server install as small as they are now |
| **Installs with one command on all three systems** | Today: `pipx install parro-api-client`, in an isolated environment that cannot see system packages |
| **Few dependencies** | Every release is verified by hand, and a parent's data is at stake |
| **Works with blocking calls** | `ParroClient` uses blocking `urllib`, and that must not freeze the window |
| **Shows text written by others, safely** | Announcements and chats are untrusted: no scripts, no remote images |
| **Testable without a display, on CI** | The project has 853 tests on three systems, and the GUI must fit in |

## 2. The candidates, tried on this machine (Fedora, aarch64, Python 3.14)

| | **PySide6 (Qt)** | **NiceGUI native** | Flet | Toga | CustomTkinter |
| --- | --- | --- | --- | --- | --- |
| How it draws | native toolkit, in-process | web page in a webview, served by a local web server | Flutter | native widgets | Tk |
| Packages installed | **2** | 53 to 56 | 54 | failed here: needs to compile PyGObject | 3, plus system Tk |
| Installed size | 295 MB | 165 MB | not measured | - | small |
| Network listener | **none** | `127.0.0.1`, on a port from 8000–8999 | not checked | none | none |
| Works from `pipx` on Linux | **yes**: one wheel, Python 3.10+ | **not as is**: `[native]` installs `pywebview`, but no GTK or Qt binding, so there is no window | not checked | no | needs the system's Tk |
| Licence | LGPLv3 / GPL / commercial | MIT (pulls in FastAPI, uvicorn, socket.io and more) | Apache-2.0 | BSD-3 | CC0 |
| Rich text, tables, dialogs | **built in** | built in, as web components | built in | basic | basic, no rich text |
| Offscreen tests | **`QT_QPA_PLATFORM=offscreen`** | a simulated user, no real webview | not checked | - | needs a display |

Checked by installing, not by reading: the package counts, sizes, the failed Toga install and the missing
webview binding. NiceGUI's defaults come from its documentation. A real window was not opened on any
system yet: the Qt test ran offscreen.

## 3. Recommendation: PySide6 (`PySide6-Essentials`)

- **No server.** NiceGUI's native mode is a browser page talking to a local web server. Any other program
  or user on the same computer could reach that port, and it would have the parent's login behind it,
  so we would have to add and maintain our own access control. Qt has nothing to protect.
- **Two packages instead of more than fifty.** The dependency is large in megabytes but small to
  verify: one vendor, one wheel, and the `--only-binary` install works.
- **It installs from `pipx` the same way everywhere.** A webview depends on what each system has. On
  Linux, NiceGUI's route needs GTK bindings (system packages an isolated environment cannot see) or Qt
  anyway, and `pywebview[qt]` picks PyQt6, which is GPL, so we would carry Qt *and* the web stack.
- **Safe text comes for free.** In the spike, `QTextBrowser` showed the project's own agenda Markdown,
  ignored a `<script>` tag and did not load a remote image.

**What we give up, honestly:** NiceGUI is less code, looks modern by default and has good AI-readable
documentation, and the same code could later serve a phone browser. Qt takes more code per screen and
adds 295 MB. If "reach it from a phone, or host it in Docker" is a goal, that changes the answer: see
decision 1.

**Licence:** the app stays MIT. It uses Qt as a separately installed, replaceable library, which is what
the LGPL allows. A bundled installer needs more care, so it is out of scope here (§7).

## 4. The design

```
parro_gui/          new, optional: only imported through the [gui] extra
  app.py            entry point `parro-client-gui`
  worker.py         one background thread, one queue
  views/            overview, announcements, calendar, chats, children, privacy, archive, login
parro/              unchanged rules: standard library only, knows nothing about Qt
```

1. **Only through `parro.operations`.** Views call the same functions as the CLI and show the same
   summaries. A test forbids importing Qt in `parro/`, and `HttpRequest` or urllib in `parro_gui/`.
2. **One worker thread, one request at a time.** `ParroClient` has no locks, and two token refreshes at
   once could use up a refresh token. All calls go through one queue; the window never blocks.
3. **Installed as an extra:** `pipx install "parro-api-client[gui]"`. The CLI, the MCP server and the plain
   install gain nothing and lose nothing.
4. **The same login and files:** the same token file as the CLI (`token_store.reload()` picks up logins
   made elsewhere), the same cache and archive folders.
5. **Lists are real widgets, built from summaries.** The spike showed that reusing the Markdown views
   for lists folds detail lines together. Markdown is used for bodies of text only.

### Safety rules (the same promises as the CLI)

| Rule | How |
| --- | --- |
| **The lockout latch** | `login` runs once per click, never retries, and the app shows *login halted* with what to do. The password field is never saved or logged |
| **Nothing changes on its own** | Opening an item never marks it as read. Marking is a button |
| **See it before it happens** | Sending, signing up, withdrawing and answering use `prepare_…`, show the same preview in a dialog, and only *Confirm* calls `apply_…`. There is no `--yes` equivalent. Marking as read also asks once |
| **Never repeated** | After an unknown outcome, the dialog says so and offers no retry button |
| **Text from others is untrusted** | `setOpenLinks(False)`; only `http(s)` links open, in the system browser, after showing the address; remote resources are not loaded |
| **Other people's answers** | No view for the list of respondents |
| **Secrets** | The calendar and privacy links are shown only on request, with the warning. Download links are never logged |

## 5. Feature map

| Area | CLI commands | In the app |
| --- | --- | --- |
| Login | `login`, `logout`, `status`, `login-url`, `login-finish` | login dialog (password or browser), status bar with time left |
| Home | `overview`, `unread` | start page, unread badges |
| News | `announcements`, `announcement`, `system-news`, `attachment` | list, filter, detail; attachments shown as text or image, and saved |
| Agenda | `calendar`, `calendar-link`, `calendar --ics` | agenda with details, export, subscription link |
| Chats | `chatrooms`, `chat-messages`, `chat-members` | list with filters, conversation, members |
| Changing things | `mark-read`, `chat-send`, `helper`, `rsvp` | buttons in context, each with its dialog |
| Family | `me`, `children`, `groups`, `privacy` | account page |
| Local data | `sync`, `cache` | archive page with progress, cache size and clear |
| Left out (decision 3) | `token`, `get`, `--raw` | developer tools; `get` also reaches the list of respondents |

The one change expected in `parro/`: `sync_archive` reports only at the end, so it gets an optional
progress callback. The CLI's behaviour stays the same.

## 6. Phases

| # | Phase | Done when |
| --- | --- | --- |
| 1 | **Skeleton:** the `[gui]` extra, entry point, window, worker, import-boundary tests, offscreen tests in CI on all three systems | **a real window opens on Windows, macOS and Linux**, which you check where I cannot; CI is green |
| 2 | **Login and status:** both ways of logging in, the latch, expiry | tests against the fake login server; never more than one password check per click |
| 3 | **Reading:** home, news with attachments, agenda, chats, account | every read command has its view, tested against the fake API; the window stays responsive |
| 4 | **Changing things:** the four writes, in dialogs | tests: nothing happens without *Confirm*, refusals, no retry, opening never marks as read |
| 5 | **Local data:** `sync` with progress, cache, `.ics`, secrets | tests; a cancelled or failed sync leaves the archive intact |
| 6 | **Docs and packaging:** a README section and picture, `docs/DESKTOP-APP.md`, `SECURITY.md` scope, changelog | links and pictures checked; install from a built wheel works |
| 7 | **Live check with you:** log in, read everything, one write of your choice | in `docs/LIVE-CHECKS.md` |
| 8 | Release **0.10.0** | published |

## 7. Out of scope

Standalone installers (`.exe`, `.dmg`, AppImage), signing and notarisation, auto-update, tray icons and
notifications, a web or phone version, and Dutch labels (labels stay English, as in the CLI).

## 8. Decisions (2026-11-09)

1. **Library:** PySide6 (`PySide6-Essentials`).
2. **How it ships:** the `[gui]` extra on PyPI, which needs Python on the computer.
3. **Scope:** `token`, `get` and raw JSON are left out.
4. **Marking as read:** asks once, because the school sees it.

Sources: [NiceGUI configuration and deployment](https://nicegui.io/documentation/section_configuration_deployment),
[pywebview installation](https://pywebview.flowrl.com/guide/installation.html),
[PySide6 README](https://code.qt.io/cgit/pyside/pyside-setup.git/tree/README.pyside6_addons.md).
