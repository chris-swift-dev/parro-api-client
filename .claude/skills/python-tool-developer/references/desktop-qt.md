# The desktop app with PySide6

## Contents

1. Versions: Python, Qt, macOS
2. Start-up order
3. Theming: light, dark, one look everywhere
4. Threads: the worker
5. Layout rules
6. Messages, dialogs and the update check
7. Fonts, icons and the app's identity
8. Testing Qt code

## 1. Versions: Python, Qt, macOS

- **Python 3.12+ for the app.** On 3.10/3.11 PySide6 (6.8.3 to 6.12) loses references to
  `None`/`True`/`False` each time a signal reaches a Python method; the count can reach zero and
  abort the interpreter, during the run and at exit. Ten lines reproduce it. 3.12 made those
  objects immortal. So: the `gui` extra requests Qt only for 3.12+, and `run()` checks
  `sys.version_info` and exits with a clear message (exit code 2) on older Pythons.
- **macOS minimum = the PySide6 wheels' minimum** (6.12: macOS 14). Set it in Briefcase, the
  docs and the download table.
- Pin the exact PySide6 version in the installers (`requires` in Briefcase); allow a range in
  the pip extra.

## 2. Start-up order

In `app.run()`, in this order, because each step must happen before the next can fail:

1. `--version` (no imports beyond the core).
2. The Python version gate.
3. Options that need no Qt, such as `--check-connection` (installers' CI check).
4. `truststore.inject_into_ssl()` (if installed) **before** anything connects.
5. Import Qt; on `ModuleNotFoundError` for PySide6/shiboken6 print how to install the extra; on
   another `ImportError` (Qt present, a system library missing) list the libraries
   (`libegl1 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1` on Debian/Ubuntu).
6. `--self-check`: build the window offscreen with a transport that refuses requests, print
   versions and optional libraries, exit 0.
7. Create `QApplication`, set the window icon, `setDesktopFileName(<flatpak id>)` (Wayland uses it
   to match the window to its desktop entry and icon), apply the desktop font (Flatpak), apply
   the theme, show the window, schedule start-up checks with `QTimer.singleShot(0, ...)`.

## 3. Theming: light, dark, one look everywhere

- `application.setStyle("Fusion")` for the same look on Windows, macOS and Linux.
- One `Colours` dataclass per scheme (background, surface, sidebar, text, muted, line, accent,
  accent_text, selected, selected_text, control, hover, disabled). Build both a `QPalette` and a
  stylesheet from it.
- **Spin boxes, combo boxes and check boxes take colours from the palette only**: styling them in
  the stylesheet loses their arrows and tick marks.
- Follow the system: `styleHints().colorScheme()` for the current scheme, and
  `colorSchemeChanged` to re-apply palette and stylesheet. Widgets with drawn content (icons
  coloured per theme) get a `restyle()` method that the refresh calls on every widget.
- `QTextDocument` understands only part of CSS; give it its own default stylesheet; text colour
  comes from the palette.
- Test contrast: every text/background pair meets WCAG AA (4.5:1) in both schemes.
- Text from others (HTML from the server) stays text: a `QTextBrowser` subclass that loads no
  remote resources, runs no scripts, and opens links only after showing the full address.

## 4. Threads: the worker

- One `QThreadPool` worker that runs **one task at a time**: the API client has no locks, and two
  token refreshes at once can burn a refresh token.
- A task is `Callable[[Client], Any]`; read widget values on the window's thread *before*
  submitting (the task must not touch widgets).
- The result returns through a signal to the window's thread with the `done`/`failed` callbacks.
  **Connect to bound methods**, not lambdas: a lambda slot ran on the worker thread.
- Catch the core's error classes and give each a user-facing sentence; catch `Exception` last so
  one broken call does not end the app (report the type only).
- `submit_from(worker, button, task, done, failed)`: disable the button until the answer is in.
- Long jobs (a sync) need a stop flag the task checks; stopping frees the worker for others.
- A short in-memory cache per section and filter (e.g. 5 minutes, never on disk), dropped on
  refresh, on any write and on login/logout; show "Fetched at 14:32" next to the title.

## 5. Layout rules

These came from windows that broke on real data:

- **Minimum window size:** an explicit `setMinimumSize` wins over what the layout needs. On
  Windows' wider text that squeezed buttons. Set the minimum after building the window:

  ```python
  def fit_minimum_size(self) -> None:
      needed = self.minimumSizeHint()
      self.setMinimumSize(max(MINIMUM[0], needed.width()), max(MINIMUM[1], needed.height()))
  ```

  Test at the minimum size, in every section, that every visible control is inside the window
  and no `QPushButton` is narrower than its `sizeHint()`; repeat with the app font 1.3x larger.
- **Long single-line text** (file names): a `QLabel` subclass with
  `QSizePolicy.Ignored` horizontally, a small minimum width, `fontMetrics().elidedText(...,
  ElideMiddle, width)` on resize, and the full text as tooltip.
- **Details that can be long** (an item with text, attachments, answer rows): the text on top; a
  row of actions (*Save all…*, *Mark as read*) that never scrolls away; below it a scroll area
  for attachments and answer rows. Share the height with a `QSplitter` the user can drag; the
  lower part takes what it needs, up to half, until dragged.
- **Chats open at the newest message:** after setting the text, follow the end while the
  scroll bar's range changes (layout happens later, and width changes height), until the user
  scrolls up (`rangeChanged` + `valueChanged` on the vertical scroll bar).
- Plain-text labels (`setTextFormat(PlainText)`) for anything from the server.

## 6. Messages, dialogs and the update check

- **The message area above a section** (loading, done, error): at most two lines, measured with
  `QTextLayout`, ending in "…" when cut; a *Details…* button opens a read-only, scrollable,
  copyable dialog with everything; a close button (use Qt's standard
  `SP_TitleBarCloseButton` icon rather than a "×" character). Summaries count reasons instead of
  listing items: "Saved 0 of 20 files. 20 not saved: could not be written: Permission denied (20)".
- **Per-item failures:** wrap file writes in `except OSError` and record the reason on that
  item; the other items continue. Domain errors and OS errors are different classes: catching
  only the domain error let `PermissionError` end the whole run.
- **Modal dialogs never stack.** Anything shown at start (a question, a notice) waits for a
  quiet moment: the first login check is done and `QApplication.activeModalWidget()` is None;
  retry with a timer otherwise.
- **The update check** (opt-in, asked once): one GET to
  `api.github.com/repos/OWNER/REPO/releases/latest` with no token or cookie, at most once a day,
  on its own thread. Use only the version number from the answer (`^v?\d+\.\d+\.\d+$`, skip
  drafts and pre-releases) and build the link yourself. Show a button "Version X is available";
  open the browser only after asking. Never download or install. A Help menu holds the switch,
  *Check for updates now* and *About*. Store the answer in the app's settings file (mode 600).
- **Login dialog:** show the common way only (password form); put rarer ways behind
  "Other ways to log in…", not remembered between openings (except a started, unfinished one).

## 7. Fonts, icons and the app's identity

- **Flatpak font:** inside the sandbox Qt cannot read the desktop's font configuration and falls
  back to a smaller default. Ask the settings portal (`org.freedesktop.portal.Settings`, keys
  `org.kde.kdeglobals.General font`, then `org.gnome.desktop.interface font-name`) and apply it
  with `QApplication.setFont`, through `QDBusInterface` on `org.freedesktop.portal.Desktop`
  (`ReadOne`, falling back to `Read` on older portals, which wraps the value in variants). Only
  inside a Flatpak: the `FLATPAK_ID` environment variable is set there.
- **Icons:** draw the app icon once in code (`QPainter` at several sizes) and generate
  `.png`/`.ico`/`.icns` files for packaging with a tool script; section icons drawn per theme.
- Window title "App name version"; *Help → About* names the version and the licence.

## 8. Testing Qt code

- `QT_QPA_PLATFORM=offscreen` before importing Qt; `pytest.importorskip("PySide6.QtWidgets",
  exc_type=ImportError)` at the top of Qt test modules.
- **One `QApplication` per test run** as a session fixture in `conftest.py`, which itself calls
  `pytest.importorskip` so that tests using it skip where Qt is not installed (CI jobs that test
  the core without extras). Shut it down properly at the end, or Qt can crash at exit.
- Helpers: `wait_until(condition)` that pumps `processEvents()` with a deadline; `dispose(widget)`
  that closes, `deleteLater()`s and flushes `DeferredDelete` events so windows do not pile up.
- Give the window a fake API transport (`MainWindow(make_client)`), fake tokens with an expiry,
  and a temp data dir via environment variables.
- Tests that call `app.run()` must lower the version gate for themselves
  (`monkeypatch.setattr(app, "MINIMUM_PYTHON", (3, 0))`), or they fail on Python 3.10 CI jobs.
- For every button that starts a request, a test that clicks it twice quickly and asserts one
  request (or one preview).
- Simulate Windows' wider text with a fixture that sets the application font 1.3x larger.
