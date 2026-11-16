# Plan 20: four additions to 0.14.0, before the release

*Status: built (2026-11-16) on branch `release-0.14`, in the same pull request as
[Plan 19](PLAN-0.14.md). The landing page was built from GitHub's real answer for 0.13.0, and its
checksums are the ones in that release's `SHA256SUMS`. Still to look at by you: the badges against
the Parro app's own counts, and one action with its confirmation switched off.*

**Goal:**

1. The version check: you had misread it; it worked as built. What to keep, and show when it last
   checked.
2. The landing page shows a checksum for each installer.
3. A setting to skip the confirmation dialog, per action.
4. An unread count on the sidebar's sections.

---

## 1. The version check

### 1.1 What to keep (my suggestion, and what is built)

0.12.0 did what it was built to do: at most one check a day, and a button when it found something.
So nothing was broken. Two things from Plan 19 are still worth keeping, and one more is added:

| | Keep? | Why |
| --- | --- | --- |
| A check at **every start** (was: at most once a day) | **Keep** | The daily limit is what made you wait without knowing why. It saved one small request a day and nothing else |
| A failed check does not count as that day's check | **Keep** | That one was a real flaw: a start without network silenced the check for a day |
| The **dialog**, once per new version | **Keep** | A button at the bottom of the window is easy to overlook; once per version does not nag |
| **When it last checked, and what it found** | **Add** | What you asked for. It answers "did it look, and when?" without guessing |

The changelog called this a fix of something broken. It now says what it is: a change.

### 1.2 Where the last check is shown

- **Help menu**, a line that cannot be clicked, under *Check for updates now*:
  `Last checked: today 14:05 · you have the newest version`, or `… · version 0.15.0 is available`,
  or `Last check failed: today 14:05`, or `Not checked yet`.
- **About**, the same line.
- It is kept in `desktop-app.json` (`last_checked`, `last_found`), so it is also there right after
  a start, before the new answer is in.

---

## 2. Checksums on the landing page

- GitHub's answer for the latest release already names a SHA-256 for every file (`digest`), the
  same values as in the release's `SHA256SUMS`. The page is built from that answer, so no extra
  request and nothing to keep in step by hand.
- Under the download buttons: a fold-out **Checksums (SHA-256)** with a row per installer (file
  name and checksum, in a fixed-width font, selectable), how to check one on each system, and a
  link to `SHA256SUMS`.
- Only a value of exactly `sha256:` plus 64 hex characters is put on the page. Without one for
  every installer, the block is left out and the line links to `SHA256SUMS` on the release.
- Honest about what it is: the page and the files come from the same GitHub account, so a
  checksum shows a download arrived whole, not who made it. The page says so in one line and
  points to the build attestation for that.

---

## 3. Skipping the confirmation, per action

- **Settings → Confirmations…** in the menu bar: a tick per action, all ticked at first ("ask
  first"). Unticking one skips its dialog.

  | Action | What is skipped |
  | --- | --- |
  | Mark as read | the yes/no question |
  | Mark a whole group as read | the dialog with the count |
  | Send a chat message | the dialog with the message and who receives it |
  | Delete a chat message | the dialog with the message |
  | Sign up or withdraw as a helper | the dialog with the slot |
  | Answer an invitation | the dialog with the answer |

- **What is never skipped:** the reading before the change. The app still fetches the chat, the
  message or the slot first and refuses what it refused before (an archived chat, someone else's
  message, a full slot). And a change is still sent once; after a timeout the app says it may or
  may not have gone through.
- Without the dialog, the outcome ("Sent.", "Deleted.", or the problem) appears in the message
  line above the section.
- The dialog itself warns once, in a line at the top: without the question a click acts at once,
  and sending and deleting cannot be undone.
- Kept in `desktop-app.json` (`skip_confirmation`). Only the desktop app: the command line keeps
  `--yes`, and an assistant's tools keep `confirm: true`.

---

## 4. Unread counts in the sidebar

- `GET /identity/unreadcounts` (already used by `unread` and `overview`) gives the counts.
  **Announcements**, **Calendar** and **Chats** get a small round badge with the number; nothing
  when it is zero, `99+` above 99. The counts of several guardian identities are added up.
- Fetched when you are logged in, every five minutes, and after anything that changes them
  (marking as read, sending, a refresh of a section), but never more than once in ten seconds.
- Reading the counts changes nothing in Parro.
- A screen reader hears it in the row's description ("Chats, 2 unread").
- If the counts cannot be fetched, the badges go away quietly; the sections work as before.

---

## 5. Checks

Tests for each part; the usual checks. To look at by you in the installed app: the badges against
the Parro app's own counts, and one action with its confirmation switched off.
