# Plan 19: Flathub, the update notice, and formatted announcements (0.14.0)

*Status: parts 2 and 3 built (2026-11-14) on branch `release-0.14`, as version 0.14.0; the update
notice is retested against GitHub's real answer (`docs/LIVE-CHECKS.md`). Formatted announcements are checked
against the real API by the account owner (2026-11-16). **Part 1, Flathub, is set aside for now** (decided
2026-11-14): nothing of it is built, and its decisions (section 1.3) are not taken.*

**Goal:**

1. Distribute the Flatpak through Flathub.
2. The automatic update check told nothing about 0.13.0. Find out why, fix it, and show it works.
3. Announcements with formatting (`richTextContents`): show bold, underline, quotes and links.

---

## 1. Flathub

Read on 2026-11-14 from Flathub's own pages
([requirements](https://docs.flathub.org/docs/for-app-authors/requirements),
[submission](https://docs.flathub.org/docs/for-app-authors/submission),
[MetaInfo](https://docs.flathub.org/docs/for-app-authors/metainfo-guidelines)).

### 1.1 What Flathub asks, against what we have

| Flathub's rule | Where we stand |
| --- | --- |
| **No AI in the manifest, and no AI in the submission.** "Flathub manifests must not contain AI-generated or AI-assisted content"; AI tools "must not open or automate Flathub submission pull requests, or generate their commit messages, descriptions, review comments, or replies" | The manifest and the pull request to `flathub/flathub` have to be **written and sent by you, by hand**. An assistant may not draft them, also not as a "template". This plan therefore contains no manifest |
| **Disclose AI-generated material**, with "the affected parts and approximate extent". Reviewers "may reject a submission, including without further review, based on the extent or role of generated material" | Nearly all code, documentation and packaging of this project was written with an assistant. That has to be said in the submission, and it can be the reason for a refusal |
| **A history.** "Applications that have only existed for a very short period of time will generally not be accepted"; they want "a sustained commit history", tagged versions and "evidence of real-world use" | The first version is from early November 2026. There are tags and releases, but weeks of history, not months |
| **The name must not use the vendor's name.** "A WhatsApp client or wrapper cannot have `WhatsApp` in its name or use any of the official icon, logo or artwork" | The app is called **Parro Client**. On Flathub it needs a name without "Parro". The icon is our own; it has to stay clearly different from Parro's |
| **The id** follows the code host: `io.github.<user>.<name>`, a `-` in the user name becomes `_` | Today: `io.github.chrisswiftdev.parro-gui` (Briefcase allows no `_`). For Flathub: `io.github.chris_swift_dev.<name>`. A new id means a new folder for the login and settings (`~/.var/app/<id>`): people who installed the `.flatpak` from GitHub log in once more |
| **Built from source, without network.** Every dependency is a source in the manifest; "binary or precompiled files must not be present" | Our Flatpak is built by Briefcase, which downloads Python and the PySide6 wheels while building. Flathub cannot use that. Its build needs a manifest of its own: the KDE runtime, Qt for Python from Flathub's own base app (`io.qt.PySide.BaseApp`), and our three small Python dependencies as sources |
| **MetaInfo upstream**, with screenshots (direct links to a tag), `releases`, a real content rating, and it must pass `flatpak-builder-lint` | We have a MetaInfo file without screenshots and releases. Adding those is ordinary work in this repository |
| **Icon:** SVG, or PNG of at least 256 px | To check in `tools/make_app_icon.py` |
| **Permissions** as few as possible, portals where they exist | Already so: Wayland with X11 fallback, network, two folders kept; files through the portal |
| **Licence files installed** per module | To do in the manifest (yours) |
| Reviewed by volunteers; afterwards a repository under `github.com/flathub/` that you maintain; each release is a change there | Releases then have one more step, by hand or by Flathub's own update bot |

### 1.2 What this means

Three of these are not ours to solve with code:

- **The manifest and the submission are yours to write.** I can explain Flathub's rules, review the
  *upstream* files in this repository, and build and test what you wrote on this machine. I should
  not write the manifest, its commit messages or the pull request, and I will not.
- **The amount of assistant-written code** is a judgement by Flathub's reviewers. It is honest to
  expect that it may be refused for that alone.
- **The age of the project.** Waiting a few months, with regular releases, improves the odds more
  than anything in this plan.

### 1.3 Decisions for you

| # | Question | My suggestion |
| --- | --- | --- |
| 1 | Go for Flathub now, later, or not? | **Later.** Keep the `.flatpak` on GitHub for now; submit when the project has a few months of releases. The preparations below cost little and do no harm either way |
| 2 | The name on Flathub (no "Parro" in it). For example *Schoolpost*, *Ouderpost*, *Klasbericht*; the summary can still say "Unofficial client for Parro" | Your choice. Changing the name everywhere (window title, installers, project page) or only on Flathub is part of it; one name everywhere is less confusing |
| 3 | The id: `io.github.chris_swift_dev.<name>` | Follows from 2 |
| 4 | May I do the upstream preparations now: screenshots and `releases` in the MetaInfo, the icon check, and a page `docs/FLATHUB.md` with the rules above and the state of each | Yes, once 2 and 3 are known (the MetaInfo carries the name and the id) |

Set aside on 2026-11-14: nothing of part 1 is built, and these decisions are left open.

---

## 2. The update notice that did not come

### 2.1 What happened

Reproduced on 2026-11-14 with the code of the tag `v0.12.0`, its real window, and the real answer
from GitHub (which names `v0.13.0`):

| Saved state when the app starts | What 0.12.0 does |
| --- | --- |
| Never checked | Asks GitHub; a button "Version 0.13.0 is available" appears in the status bar |
| Checked two days ago | The same |
| **Checked three hours ago** | **Nothing: no request, no button** |

So there are two causes, and you met at least the first:

1. **"At most once a day" counts from the last start, whatever it found.** 0.12.0 came out on
   13 November and 0.13.0 a day later. A start of 0.12.0 on the 14th before 0.13.0 was published
   used up that day's check; every later start that day asked nothing. *Check for updates now*
   ignores the limit, which is why that worked.
2. **The automatic check is easy to miss.** When it does find a version, it only puts a small
   button in the status bar. The manual check opens a dialog. If you expected the dialog, the
   automatic check "told nothing" even when it worked.

A third weakness, found while reading: the time of the check is saved **before** the answer is in.
A start without network, or a refusal by GitHub, also silences the check for a day.

### 2.2 The fix

- **Check at every start**, and once a day while the app stays open. The limit of once a day goes:
  it protects nobody (one small request without anything about you), and it hid a release.
- **Say it once, clearly.** The first time the automatic check finds a version, it opens the same
  dialog as the manual check, at a quiet moment (not over the login dialog). That version is then
  remembered: later starts show only the button, so the app does not nag.
- **A failed check stays quiet** and changes nothing; the next start tries again.
- The question at the first start and the Help menu change their words from "at most once a day"
  to "when it starts".
- `desktop-app.json`: `last_checked` is no longer used; `told_version` is new. An old file is read
  as it is.

### 2.3 Showing that it works

- Tests for each row of the table above, for the dialog shown once per version, for the quiet
  moment, and for a failure.
- **The same experiment again, with the fix:** the fixed window, told that it is version 0.12.0,
  against the real GitHub answer, in the three saved states. The result goes into
  `docs/LIVE-CHECKS.md`.
- What only you can check: the installed 0.13.0 finding 0.14.0 once that is released. (0.13.0
  still has the old behaviour: it will tell you at the first start that is a day after its last
  check.)

---

## 3. Formatted announcements

### 3.1 What is known

Live look of 2026-11-14: 6 of 79 announcements carry `richTextContents` next to `contents`. It is
a JSON string in Quill's "delta" form: a list of pieces `{"insert": "text", "attributes": {…}}`.
Seen: `bold` (17 pieces), `blockquote` (15), `underline` (1), `link` (1). In that form, `bold`,
`underline` and `link` belong to the piece of text; `blockquote` belongs to the line and sits on
the line break that ends it.

Not known, because the login had expired when this was written: whether the detail call
(`GET /event/{id}`) returns the field as the list does, and whether `contents` always holds the
same words. The code does not depend on either (3.3); the live check settles it.

### 3.2 What is built

- **`parro/richtext.py`** (standard library): reads the string into lines of pieces. It knows
  `bold`, `italic`, `underline`, `strike`, `link`, and per line `blockquote`, `list` and `header`:
  the four that were seen, and the ordinary others of the same editor. Anything else is ignored;
  the text itself is always kept. Pictures or other embedded things are left out.
- **A link keeps the rule of the app:** only `http(s)`, and the address is always shown in full:
  `klik hier (https://…)`. A link whose text already is its address is shown once.
- **Desktop app:** an announcement with formatting shows bold, italic, underline, quotes (indented,
  with a line of the muted colour), lists and links. Everything is still escaped text; the markup
  comes from the app, never from the announcement.
- **CLI and MCP, markdown view:** `announcement <id>` shows `**bold**`, `> quotes`, lists and
  `text (address)`. Underline has no markdown form and stays plain.
- **JSON output:** `contents` stays the plain text; an announcement with formatting gains
  `rich_text` (the API's own string), in the list and in `announcement <id>`.
- **Spec:** the field is already there since 0.13.0; its description says what it holds.

### 3.3 Never worse than today

The formatted text is used only when it can be read **and** says the same as `contents` (compared
without white space). In every other case the app shows `contents`, as it does now. So an odd
value, a newer editor, or a difference between the two can only cost the formatting, never words.

---

## 4. Order and release

1. Part 2, with its experiment. 2. Part 3. 3. Checks, docs, changelog, version 0.14.0, a pull
request. 4. Live check by you: one formatted announcement in the app and the CLI. 5. Part 1 after
your decisions.
