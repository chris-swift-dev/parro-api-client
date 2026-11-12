# Plan 15: version 0.12.0, the desktop app without Python, and chats that open at the newest message

*Status: approved (2026-11-12). Decisions in §5: as recommended, except 5 (an update check against
GitHub, §1.7) and 3 (Linux gets a Flatpak, not an AppImage: §1.8); the message order is checked again
on the live check (§2).*

**Goal:** two changes to the desktop app.

1. Installers for people who do not know what Python is: Windows, macOS and Linux.
2. A chat opens scrolled down, at the newest message, like other chat apps.

---

## 1. Installers for people without Python (your item 1)

### 1.1 What "for average users" asks for

- **One download, one double-click.** No terminal, no Python, no `pipx`.
- **The usual form for each system:** an installer on Windows, a disk image to drag to Applications
  on macOS, one file on Linux (a Flatpak, §1.8).
- **A start menu, Launchpad or app-menu entry with an icon,** so the app is found like any other.
- **A first start that does not look dangerous.** This is the hard part; see §1.4.

The app itself needs no change for this. Its settings, the login and the data folder already work
when it is started from a menu (0.11.0 added logging in by itself for that case).

### 1.2 The tools I compared

| | Briefcase (BeeWare) | PyInstaller | pyside6-deploy (Nuitka) |
| --- | --- | --- | --- |
| What it makes | installers: **MSI** (Windows), **DMG** (macOS), **AppImage** or Flatpak (Linux) | a folder or one `.exe`; installers need other tools (Inno Setup, `create-dmg`, `appimagetool`) | a compiled program; installers need other tools |
| How Python is bundled | a standalone Python and the installed wheels, as normal files | frozen into an archive; one-file builds unpack to a temporary folder at every start | compiled to C, then to machine code |
| Antivirus | normal program layout | one-file builds are often flagged by antivirus | rarely flagged |
| Signing and notarization (macOS) | built in, `briefcase package` | by hand | by hand |
| Configuration | `[tool.briefcase]` in `pyproject.toml`; it reads the project's own dependencies | a `.spec` file | a `pysidedeploy.spec` file |
| Build time | minutes | minutes | long (C compilation) |
| CI | documented GitHub Actions workflow | many examples | few examples |

**My recommendation: Briefcase.** It is the only one of the three that makes all three installers
itself, with menu entries and icons. It ships Python as normal files instead of a self-unpacking
archive, which is less likely to be flagged by antivirus. And macOS signing is built in, if you
choose to sign (§1.4). PyInstaller would work, but it needs three more packaging tools on top, and
its one-file `.exe` is the form antivirus programs distrust most. Qt's own pyside6-deploy makes a
fast program, but no installer.

What Briefcase costs: one more build tool in the release (not in `parro/`, which stays standard
library only), and its conventions. It wants the app as a package with a `__main__.py`, an icon in
each system's format, and a few lines of configuration.

### 1.3 What gets built

| System | File | Processors |
| --- | --- | --- |
| Windows 10 and 11 | `Parro-0.12.0.msi` | x64 |
| macOS 13 or newer | `Parro-0.12.0.dmg` | Apple silicon and Intel: one universal file if the Qt wheels allow it, else two |
| Linux | `Parro-0.12.0-x86_64.flatpak`, `…-aarch64.flatpak` | x86_64, aarch64 |

- **The size** will be roughly 60–100 MB each. A whole Python and Qt are inside.
- **macOS 13** because PySide6 6.10 and newer needs it.
- **The command-line client and the MCP server are not in these files.** They stay with `pipx`, as
  now. People who use a terminal or an AI assistant already have Python.
- **The attachment libraries:** pypdf and Pillow are bundled, so PDFs and photos show text and size.
  PyMuPDF is left out, because its licence (AGPL) would apply to the whole bundle (decision 4).

### 1.4 The first start: signing (decision 2)

Both Windows and macOS warn about programs from unknown publishers:

- **Windows (SmartScreen):** "Windows protected your PC", with *More info → Run anyway*. People can
  get past it, but it looks alarming. The warning only goes away with a code-signing certificate,
  which costs money every year, and even then only after the program has a reputation.
- **macOS (Gatekeeper):** an app that is not notarized does not open: "Apple could not verify…". Since
  macOS 15 the old right-click → *Open* no longer works. People must go to *System Settings →
  Privacy & Security → Open Anyway*. Most average users will give up there. Notarization needs an
  Apple Developer account ($99 a year), and the build then signs and notarizes by itself.
- **Linux:** no warning. A double-click on the `.flatpak` opens the software centre on Fedora, Mint
  and most others; on the command line it is `flatpak install --user Parro-….flatpak`. Ubuntu has no
  Flatpak out of the box: it needs a one-time `sudo apt install flatpak` (and, for the double-click,
  `gnome-software-plugin-flatpak`). The instructions say so.

**My recommendation:** build unsigned for 0.12.0, with clear first-start steps (and pictures) in
the instructions. Make the workflow ready to sign: the secrets for Apple and Windows are read when
present, and the build skips signing when they are not. Whether to pay for an Apple account is
your call. For macOS users it is the difference between "it just opens" and four steps in System
Settings.

### 1.5 Trust and checks

- **The same checks as now:** the files go into `SHA256SUMS`, and the release notes say how to check
  them.
- **Build provenance:** GitHub artifact attestations (`actions/attest-build-provenance`) for every
  installer. Anyone can then check that a file was built by this repository's workflow, from the tag.
  This matters more for a binary than for a wheel, because nobody can read a binary.
- **Updating** means downloading the new version and installing it over the old one. The login and
  settings are kept, because they are in the data folder, not in the app. The app can tell you when
  there is a new version (§1.7).

### 1.6 The work

1. **Make it something Briefcase can build:**
   - `parro_gui/__main__.py`;
   - `[tool.briefcase]` in `pyproject.toml`, with the app's name, bundle id, version from
     `parro/__init__.py`, and dependencies: PySide6-Essentials, pypdf, Pillow;
   - an app icon. There is none yet, only the sidebar icons. I would draw it with a small script in
     `tools/`, from one of the sidebar's licensed icons on the app's accent color, in `.png`, `.ico`
     and `.icns`;
   - the window and the taskbar use the same icon (`setWindowIcon`).
2. **A check that the built app works:** `parro-client-gui --self-check` starts Qt offscreen, builds
   the window without logging in or touching the network, prints the version and stops. CI runs it on
   every built app. A missing Qt plugin or library then fails the build instead of the user's first
   start.
3. **A local Flatpak build on Linux** (this machine, aarch64), to find the surprises before CI.
4. **A workflow `installers.yml`:** three systems, plus Linux aarch64 (`ubuntu-24.04-arm`). It can be
   started by hand, so we can try it before tagging. Each job builds, runs `--self-check` and keeps
   the file as a build artifact.
5. **The release:** `release.yml` calls it after the checks, attaches the files to the draft release,
   adds them to `SHA256SUMS` and writes the attestations. `tools/build_release.py` and its tests learn
   the new file names.
6. **The update check (§1.7):** `parro_gui/updates.py`, the question at the first start, the
   notice, and *Check now* in the *About* box.
7. **The instructions:** a page `docs/INSTALL-DESKTOP.md` for people without Python: which file to
   pick, the first start on each system, how to update, how to remove the app and its data. The
   README's install section first points to it. DESKTOP-APP.md, SECURITY.md and the CHANGELOG are
   updated too. Pictures use invented data, as before.

**Tests:**
- the icon script, the version in `[tool.briefcase]` matching `parro.__version__`, and `--self-check`
  offscreen;
- that `parro/` still imports nothing outside the standard library;
- the release tool's file list and checksums.

The installers themselves are checked by the workflow's `--self-check`, and by you on real machines
(§4).

### 1.7 Telling you about a new version (decision 5)

The releases are on GitHub, so the app asks GitHub which release is the newest:

- **One GET, nothing else:** `https://api.github.com/repos/chris-swift-dev/parro-api-client/releases/latest`,
  without a token or cookie, with a short time-out, and with the standard library (`urllib`) in
  `parro_gui/`. It sends no Parro data, no e-mail address, and not the login. GitHub sees the
  computer's IP address and the app's version in the User-Agent, nothing more.
- **Only when you agree.** The first start asks once: "Check for new versions at start?". The answer
  is kept in `desktop-app.json`, next to the remembered login, and can be changed in the app's
  *About* box, which also has *Check now*. Until you say yes, the app talks to no one but Parro.
- **At most once a day,** at start and in the background, through its own thread, so a slow GitHub
  never delays Parro.
- **What it shows:** a small notice, "Version 0.13.0 is available", with a button that opens the
  release page in the browser. The app downloads nothing and installs nothing; you download it
  yourself, from the page where the checksums and attestations are.
- **Drafts and pre-releases are never offered,** because `releases/latest` skips them. A version is
  newer only by comparing the numbers (0.12.0 < 0.12.1 < 0.13.0); an answer that does not parse is
  ignored.
- **When it fails** (offline, GitHub down, rate limit), nothing is shown at start; *Check now* says
  that it could not check.
- **Installed with pipx**, the notice says `pipx upgrade parro-api-client` instead of pointing to
  the installers.

**Tests,** with a fake answer and no network: the version comparison; nothing is asked before you
agreed; at most once a day; a draft or a broken answer shows nothing; the notice's text for an
installer and for pipx; no Parro data and no token in the request.

### 1.8 Linux: why a Flatpak (found in phase 3)

The plan said AppImage. Building it showed two things:

- **Briefcase advises against AppImage.** Its documentation says AppImage cannot use ready-made binary
  packages (wheels) such as Qt's, has known trouble with Qt, and should not be used for distribution.
  The first local build also failed inside Briefcase.
- **Its `.deb` and `.rpm` packages use the distribution's own Python.** Each file then works on one
  version of one distribution (Ubuntu 24.04, Debian 13, Fedora 44, …), and versions with a Python
  older than 3.12 (Ubuntu 22.04, Debian 12) cannot be served at all. Average users would have to pick
  the right file out of many.

**A Flatpak** brings its own Python and Qt and works on any distribution with Flatpak: one file per
processor. Briefcase recommends it. It must be built outside Docker, which suits GitHub's runners
(virtual machines). Later, publishing on Flathub would add an entry in the software centre and
automatic updates; that is a separate step, not part of 0.12.0.

**What the local build (phase 3, Fedora aarch64) showed, and what the workflow must do:**

- **The app id** is `io.github.chrisswiftdev.parro-gui` for the Flatpak: Flatpak allows `-` only in
  the last part, and Briefcase allows no `_`. macOS and Windows keep `io.github.chris-swift-dev`.
  (Flathub would expect `io.github.chris_swift_dev`; a matter for later.)
- **The runtime** is KDE 6.11; Briefcase's template still names 6.9, which is end-of-life.
- **The sandbox** has only network, Wayland (X11 as a fallback), the GPU, and its own `~/.parro`, kept
  in `~/.var/app/io.github.chrisswiftdev.parro-gui/`. Briefcase's defaults also opened `~/.cache`,
  `~/.config`, `~/.local/share`, `~/Documents` and sound. Files chosen in a dialog come in through the
  desktop's file portal. So the Flatpak has its own login: logging in once is a password check.
- **The branch** is `stable`, not the version. Briefcase writes the version as the Flatpak branch, so
  every release would install next to the previous one (370 MB each). The workflow sets
  `default-branch: stable` in the generated manifest after `briefcase create`, and runs
  `flatpak build-bundle … stable` itself, because `briefcase package` looks for the version's branch.
  The login survives an update: it is in the app's own folder, shared by all branches.
- **On Wayland** the window says which menu entry it belongs to (`FLATPAK_ID`), so the dock shows the
  app's icon.
- **The font:** in the sandbox Qt cannot see where some desktops keep their default font (Fedora's
  KDE: a system folder), and falls back to "Sans Serif 9", which looks smaller. In a Flatpak the app
  asks the desktop's settings portal for the font (KDE's, then GNOME's) and uses it
  (`parro_gui/desktop_font.py`). Measured: Noto Sans 10, 13 px, the same as outside the sandbox.
- **Installing a newer bundle over an older one** must replace it. Checked here with `--reinstall`;
  the live check tries it the way people do it (a double-click, or `flatpak install` without flags).
- **Size:** an 86 MB download, 370 MB installed (with KDE's runtime shared with other apps).
- **The self-check passes** in the installed Flatpak.

## 2. A chat opens at the newest message (your item 2)

**What happens now.** A chat is shown as one text in the detail pane. It holds the title, the members,
then the messages from oldest to newest. The pane starts at the top, so in a long chat you see the
oldest message, and you scroll down for the newest.

**The change:**

1. **After the messages arrive, the pane is scrolled to the end.** This happens after Qt has laid out
   the text, otherwise it scrolls to an end that is not yet final.
2. **It stays at the end while the pane changes size,** for example when you drag the splitter, resize
   the window or type a longer message. That holds only as long as you have not scrolled up yourself.
   If you have, it stays where you are.
3. **After *Send…* and the reload,** the pane is at the end again, so you see your own message.
4. **The title and members** stay at the top of the text. You see them when you scroll up. (Decision
   6: keep them there, or move them into a fixed line above the messages.)

**Which messages arrive.** The client asks for at most 100 (`limit`) and sends no `sort`. The spec
already says what that gives (`listChatMessages`, live check 2026-11-05): the **newest** messages,
newest first, text messages only. So the 100 shown are the newest 100, and the end of the pane is the
newest message. The app already puts them in reading order. With `sort`, status messages (someone
joining) come too, and the names are the opposite of what they say (`asc-stream` is newest first), so
the app keeps sending no `sort`. The live check confirms this on a chat with more than 100 messages
(§4).

**Tests,** offscreen with invented data:
- a chat with 60 messages: after it opens, the scroll bar is at its end and the last message is in
  view;
- resizing keeps it at the end; after scrolling up, resizing leaves it where it is;
- after a send, it is at the end again;
- a short chat that fits needs no scrolling and shows the title.

## 3. Order of work

| Phase | What | Ends with |
| --- | --- | --- |
| 1 | §2, the chat: the order check, the change and its tests | pytest, ruff, mypy |
| 2 | §1.6 steps 1–2: `__main__.py`, icon, Briefcase configuration, `--self-check` | pytest, ruff, mypy |
| 3 | §1.6 step 3: a local Linux Flatpak, installed here | the self-check passes in it, and it opens and logs in by itself |
| 4 | §1.6 step 4: `installers.yml`, started by hand on a branch | four installers built and checked in CI |
| 5 | §1.6 steps 5–7: the release, the update check and the instructions | pytest, ruff, mypy; docs |
| 6 | Live check, with you | §4 |
| 7 | Release 0.12.0 | the draft release with the installers, for you to publish |

Phase 1 is small and does not depend on the rest, so it comes first.

## 4. Live check (phase 6)

- **Chats, here:** a chat with more than 100 messages opens at the newest one, the same one the web
  app shows last (the order, §2). A long chat opens at the newest message, it stays there when resized, and a sent
  message shows at the end. Sending is only on your choice of chat and your approval, as always.
- **The installers:** I can run the Linux aarch64 Flatpak here. For Windows and macOS I need you, or
  someone, on those machines. Check the first start with the warnings described in the instructions,
  the menu entry and icon, logging in, and installing the next version over it. One password check at
  most per run, typed by you.

## 5. Decisions

1. **The tool:** Briefcase *(recommended)*, PyInstaller, or pyside6-deploy. See §1.2.
2. **Signing:** unsigned for now, with the workflow ready for it *(recommended)*. Or buy an Apple
   Developer account now, for notarized macOS builds. Or also a Windows certificate. See §1.4.
3. **Linux:** ~~AppImage~~, then ~~deb + rpm~~. **Chosen: Flatpak**, x86_64 and aarch64 (§1.8).
4. **PDF and photo libraries in the installers:** pypdf and Pillow, not PyMuPDF *(recommended,
   licence)*.
5. **Updates:** ~~no update check~~. **Chosen: a check against GitHub's latest release** (§1.7), asked
   once at the first start, because the app is distributed through GitHub.
6. **A chat's title and members:** at the top of the text, scrolled away *(recommended, the smallest
   change)*. Or in a fixed line above the messages.
