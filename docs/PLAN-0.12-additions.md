# Plan 16: five additions to 0.12.0, before the release

*Status: approved (2026-11-13), all decisions as recommended; the publisher and author is the
GitHub name `chris-swift-dev`, as in the licence. Phase 7 of [Plan 15](PLAN-desktop-0.12.md) (the
release) waits until these are done.*

**Goal:** five changes, added to the same release:

1. A name as the installers' publisher (and what it takes to remove "Unknown publisher").
2. An error area that cannot take over the window, and a minimum window size.
3. The browser login behind an "advanced" switch.
4. A shortcut past Gatekeeper on macOS, for people who use a terminal.
5. A landing page on GitHub Pages, next to the Swagger UI.

---

## 1. A publisher for the installers (your item 1)

### 1.1 Where Windows shows "Unknown publisher", and why

There are two different places, with two different causes:

| Where | What it shows now | Where it comes from |
| --- | --- | --- |
| *Settings → Apps → Installed apps*, the install folder, the registry | "Anonymous" | the MSI's *Manufacturer*, which Briefcase fills from the project's **author**. There is none, so its template writes `Anonymous` |
| The security prompts: SmartScreen ("Windows protected your PC") and the prompt for administrator rights ("Publisher: Unknown") | "Unknown publisher" | the **code signature** (Authenticode). Without one, Windows never shows a name there, whatever the metadata says |

So there are two parts. The first is a small change that can go into 0.12.0. The second costs money
or an application, and is your decision.

### 1.2 Part A, the metadata (in 0.12.0)

- **`authors` in `[project]`** in `pyproject.toml`, with the name you choose (decision 1). Briefcase
  uses it for:
  - Windows: the MSI's *Manufacturer*, shown as "Publisher" in the list of installed apps, and the
    registry key;
  - macOS: the copyright line in the app's *Get Info*;
  - Linux: the developer name in the software centre.

  The same name appears on the PyPI page, which today shows no author.
- **A homepage link** (`Homepage` in `[project.urls]`): the landing page (§5). Windows shows it as the
  app's support link in *Installed apps*.
- **No e-mail address.** Briefcase would put one in the MSI's contact field, which anyone with the
  installer can read.
- **A check in CI:** after building the MSI, the build script reads its *Manufacturer* and fails if
  it is not the chosen name, using Windows Installer's own COM interface from PowerShell. The other
  systems get a test against the generated files.

### 1.3 Part B, a signature (decision 2, not needed for 0.12.0)

Only a signature removes "Unknown publisher" from the security prompts. Even then, SmartScreen keeps
warning until the signed file has built up a reputation (enough downloads, over some weeks).

| Option | Cost | Shown as publisher | Notes |
| --- | --- | --- | --- |
| [SignPath Foundation](https://signpath.org/) | free, for open-source projects | "SignPath Foundation", not your name | an application and approval; MFA on GitHub and SignPath for everyone on the project; a public signing-policy page; signing runs from GitHub Actions |
| An open-source certificate from a CA (for example Certum) | low, per year | your name | identity check; the key lives on a smart card or in the CA's cloud, which makes signing in CI harder. Current price and conditions still to check |
| [Azure Artifact Signing](https://azure.microsoft.com/products/artifact-signing) | about $10 a month | your name | individuals only in the USA and Canada (as of 2026): not available to you |
| An ordinary OV certificate | a few hundred euros a year | your name | as above, plus the reputation wait |

**My recommendation:** Part A now. For Part B, apply to the SignPath Foundation for a later release,
if a free signature is worth the publisher reading "SignPath Foundation". The macOS side (an Apple
Developer account, $99 a year) stays as Plan 15 §1.4 left it.

### 1.4 What phase 10 found

- **Briefcase writes no AppStream metainfo for the Flatpak,** and puts the author nowhere in it. So
  `packaging/io.github.chrisswiftdev.parro-gui.metainfo.xml` (checked with `appstreamcli validate`)
  is installed by tools/build_installer.py through the manifest, next to the desktop file. It gives
  software centres the developer, summary, licence, links and the "unofficial" line.
- **The desktop file had no category,** so AppStream's compose step refused it and menus filed the
  app under "Other": the build adds `Categories=Education;Network;`.
- **With metainfo, flatpak-builder runs AppStream's compose step,** which failed to write the icons
  through `rofiles-fuse` ("icon-write-error"); a plain copy and a build without that layer work. The
  build script now runs flatpak-builder itself (what `briefcase build` ran) with
  `--disable-rofiles-fuse` and `--install-deps-from=flathub`.
- **The checks:** Windows reads the MSI's *Manufacturer* and support link; macOS the copyright in
  `Info.plist`; Linux the metainfo inside the installed Flatpak.

## 2. The error area, and a minimum window size (your item 2)

### 2.1 What happens now

Above each section is one label, `notice`, for "Loading…", "Marked as read." and errors. It wraps
its text and grows to whatever height that takes. *Save all attachments…* writes every failed file
into it: "Not saved: a.pdf (…); b.pdf (…); …". With 20 failures the label is taller than the window.
That squeezes the list and the details (2.1), and the label cannot scroll, so part of the text is
cut off (2.2).

### 2.2 The change

1. **The notice is at most two lines.** Longer text is cut off with "…", and a **Details…** button
   appears next to it.
2. **Details…** opens a small dialog with the whole text. It scrolls, the text can be selected and
   copied, and it has a *Close* button.
3. **Save all reports by reason, not by file:** "Saved 3 of 20 files in Downloads. 17 not saved:
   certificate verify failed (17)." The file names are in the details.
4. **The same goes for every section and every message:** errors from Parro, failed logins, the
   archive.
5. **A message can be closed** (×), so an old error does not stay above the content.

### 2.3 A minimum window size (2.3)

Yes, a minimum size makes sense. Today the window can be dragged smaller than its parts fit, and
then buttons are cut off. Qt can work out the smallest size at which everything still fits, but not
by itself here, because the detail splitter and the lists scroll. I would:

- **measure** the smallest size at which every section still shows its action row, filters and
  buttons in full (in a test, for all six sections);
- set that as the window's minimum, probably around **820 × 540**. Below that, the content does not
  shrink further, and the window cannot be made smaller;
- give the dialogs (login, confirm, reading, details) a sensible minimum too, and make their content
  scroll if a small screen still cuts it off.

**Tests:** a notice with 30 failed files keeps the details at their minimum height and stays at two
lines; *Details…* shows all 30. At the minimum window size, every section's buttons are inside the
window and can be clicked, and the window cannot be made smaller.

## 3. The browser login behind an "advanced" switch (your item 3)

**Now:** the login dialog has two tabs, *With a password* and *In the browser*. The second is for
people whose password login does not work. It takes copying an address back from the browser, which
most people will never need.

**The change:**

- The dialog opens with **only the password form**. No tabs.
- Under it is a small link-style button: **"Other ways to log in…"**. It shows the browser login
  steps in the same dialog, with a line explaining when you would need them.
- **Not remembered** (decision 5): the next login shows the password form again. The one exception
  is a browser login that has been started but not finished; then the dialog opens on it.
- The command line and the MCP server are unchanged: `login --browser` and `parro_login_url` stay as
  they are.

**Tests:** the browser part is hidden at first and can be shown; a started browser login opens on
it; logging in with a password works as before. DESKTOP-APP.md and LOGIN.md say where the option
went.

## 4. Past Gatekeeper with the terminal (your item 4)

A section **"For people who use a terminal"** in [INSTALL-DESKTOP.md](INSTALL-DESKTOP.md), under
macOS. Your command needs two corrections: the program is `xattr`, not `xcattr`, and it needs no
`sudo` for a file in your own Downloads folder.

**Before opening the downloaded DMG:**

```bash
xattr -d com.apple.quarantine ~/Downloads/Parro-Client-0.12.0-macos.dmg
```

The app copied out of it is then not marked as downloaded either, and opens without the steps in
System Settings. **If the app is already in Applications:**

```bash
xattr -dr com.apple.quarantine "/Applications/Parro Client.app"
```

- I suggest `-d com.apple.quarantine` rather than your `-cr`: it removes only the "downloaded" mark.
  `-c` clears every extended attribute, which is more than needed.
- `sudo` is only needed if the app belongs to another user.
- **A warning in the guide:** this skips macOS's check for this one file. Check the download first
  with `SHA256SUMS` or `gh attestation verify`, which the guide already explains.

## 5. A landing page next to the Swagger UI (your item 5)

### 5.1 Can both live on GitHub Pages? Yes

A repository has one Pages site, but the site can hold any number of pages. The workflow builds the
folder `_site/` and publishes it. Today `tools/build_site.sh` puts Swagger UI at its root. The
proposal:

| Address | What |
| --- | --- |
| `https://chris-swift-dev.github.io/parro-api-client/` | **the landing page** (new) |
| `…/parro-api-client/api/` | **Swagger UI**, moved here, unchanged |
| `…/parro-api-client/api/parro.openapi.json` | the public spec |

- **Old links keep working.** Swagger UI's links to an operation look like `…/#/Chats/listChatMessages`.
  The landing page sends any address with such a `#/…` part on to `api/`, with the same part, so links
  already shared elsewhere still arrive at the right operation.
- **Links in this repository** (the README, `pyproject.toml`, API-NOTES.md,
  `tools/swagger_screenshots.py`) are updated to point to `api/` where they mean the spec.

Other options I considered and do not recommend:
- a separate repository for the page, which would mean a second site to maintain;
- keeping Swagger UI at the root and putting the landing page at `/home/`, so the main address would
  not show the main page.

### 5.2 What is on it

One page, light and dark (it follows the system), readable on a phone:

1. **At the top:** what it is in one sentence, with the app's picture (invented data) and the
   **"Unofficial; not affiliated with Topicus, ParnasSys or Parro"** line close by. No Parro logo,
   colours or name styled as the official app.
2. **Download the desktop app:** a button per system. The page recognises your system and shows its
   button first. Small print: macOS 14+, unsigned (with a link to the install guide), the size.
3. **Three ways to use it:** cards for the desktop app, the command line (`pipx install
   parro-api-client`, copy button) and the MCP server (the configuration snippet for Claude Desktop),
   each with a picture from `docs/images/`.
4. **The API specification:** what it covers, and a button to the Swagger UI (`api/`) and to the JSON.
5. **Safety and privacy, briefly:** it runs on your computer, it changes things in Parro only when you
   ask, there's no telemetry, and the update check is optional. Links to SECURITY.md and LOGIN.md.
6. **Footer:** licence, GitHub, the disclaimer again.

**Nothing from elsewhere:** no web fonts, analytics or scripts from other sites. The page itself
sends no request to any other site; only the download buttons and links go to GitHub. The pictures
are copied from `docs/images/`.

### 5.3 Download links that are always right

The installers' names contain the version (`Parro-Client-0.12.0-…`), so a fixed link to
`releases/latest/download/<name>` would break with every release. The page is **built with the
latest release's version and file names filled in**:

- `tools/build_landing.py` (standard library) asks GitHub for the latest release when the site is
  built, and writes the buttons with that version's file names (from `build_release.installer_names`)
  and their sizes;
- the Pages workflow also runs when a release is **published**, so the page follows each release
  within minutes;
- if there is no release with installers yet, the buttons link to the releases page.

### 5.4 The work and the tests

- `site/landing/`: `index.html` as a template, `style.css`, a little JavaScript for the system
  detection and the old-link forwarding. `tools/build_site.sh` puts the landing page at the root and
  Swagger UI in `api/`.
- **Tests:**
  - every link on the page works, or points to github.com;
  - the download names equal `build_release.installer_names(version)`;
  - nothing is loaded from another site;
  - the disclaimer is there;
  - `#/…` addresses are forwarded to `api/`;
  - the page is built correctly without a release too.
- **Before it goes live:** I build the site and show it to you in the browser pane, on a wide screen
  and a phone width.

## 6. Order of work

| Phase | What | Ends with |
| --- | --- | --- |
| 8 | §2: the error area, *Details…*, the save-all report, minimum sizes | pytest, ruff, mypy |
| 9 | §3: the login dialog | pytest, ruff, mypy |
| 10 | §1 Part A and §4: the publisher name, the MSI check in CI, the macOS terminal hint | CI: the MSI's *Manufacturer* is the chosen name |
| 11 | §5: the landing page and the move of Swagger UI | the site built here and shown to you; then pushed |
| 12 | Live check: the error area with many failures, the login dialog, the publisher in *Installed apps* (Windows), the landing page on Pages | `LIVE-CHECKS.md` |
| 7 | The release 0.12.0 (Plan 15), now last | the draft release, for you to publish |

Phases 8 to 10 are small and independent. Phase 11 is the largest.

## 7. Decisions

1. **The name shown as publisher and author:** your name, your GitHub name (`chris-swift-dev`), or a
   project name. It becomes public: on PyPI, in the installers, and on the landing page. *(Your
   choice; no e-mail address recommended.)*
2. **A signature:** none for 0.12.0 *(recommended)*; apply to the SignPath Foundation for a later
   release, or buy a certificate in your name. See §1.3.
3. **Long messages:** two lines plus *Details…* *(recommended)*, or a scrolling area of fixed height
   above the content.
4. **The minimum window size:** the measured size, about 820 × 540 *(recommended)*.
5. **The browser login:** "Other ways to log in…" in the dialog, not remembered *(recommended)*, or a
   switch in the Help menu that is remembered.
6. **The site's layout:** landing page at the root, Swagger UI at `api/` with the old links forwarded
   *(recommended)*.
7. **Download buttons:** filled in when the site is built, rebuilt on every release *(recommended)*,
   or looked up by the visitor's browser when the page opens.
