# Plan 17: media attachments, links and a readable chat (0.13.0)

*Status: accepted (2026-11-14), all six decisions as recommended; `calendarItem.url` also goes into the spec. Being built on branch `media-0.13`.*

**Goal:** four changes for the next release:

1. Photo, video and audio in a chat are shown, instead of an "empty" message.
2. The same media in announcements and calendar items.
3. Links in texts: check that they work, and fix what does not.
4. A chat that is easier to read.

---

## 0. What the code and the captures say today

| Fact | Where |
| --- | --- |
| A chat message carries **one** `attachment` (singular) and then has no `text` at all | `findings/attachment-text-message.json` |
| That attachment has three `entries`: `SOURCE` (the original, `video/quicktime`, 12 MB), `VIDEO` (a `video-hls/…` stream) and `THUMBNAIL` (`image/jpg`, 720×1280) | same |
| `message_text()` returns `text` or `""`, so the CLI, the MCP tool and the app all show nothing | `parro/rendering.py:640` |
| `find_attachments()` knows `attachments[]` and `calendarItem.attachments[]`, not a message's `attachment` | `parro/attachments.py:78` |
| The spec's `ChatTextMessage` has no `attachment`, and there is no `ChatMessageAttachment` schema | `openapi/…json`, `tools/build_spec.py` |
| Announcements and calendar items already have a row per attachment with *Read* and *Save…*. *Read* turns a file into text or shows a picture; for a video it can only fail | `parro_gui/views/attachments.py` |
| The app's text pane loads no pictures at all, on purpose (`loadResource` returns nothing) | `parro_gui/widgets.py:101` |
| The app turns `http(s)://…` addresses in any text into links, and asks before opening one | `parro_gui/text.py`, `SafeTextBrowser._follow` |
| Only `VIDEO` was captured. Photo, audio, a message with text **and** an attachment, and any link are not in `findings/` | — |

So items 1 and 2 are one piece of work in the core, shown in two places.

---

## 1. Phase 1: the live look (done, 2026-11-14, read-only)

One session against the real API: 8 chats (339 messages), 79 announcements, 113 calendar items
with details. Only shapes were read; nothing was marked as read, and no sample was saved (the test
fixtures of phase 2 are written by hand from these shapes).

**Chats**

| Found | Meaning for the plan |
| --- | --- |
| 17 messages with an attachment: 13 `IMAGE`, 3 `DOCUMENT` (.docx), 1 `VIDEO`. **No audio anywhere** | Audio is handled by kind and content type, without a sample; it gets a line and *Open*, no picture |
| 8 of the 17 have **text and an attachment**; 9 have no `text` key at all | Show both |
| `IMAGE`: two entries, `SOURCE` (up to 2100 px, **no `filename`**) and `THUMBNAIL` (`image/jpg`, at most 900 px). The order of the entries varies | Pick an entry by `type`, never by position; make a name such as `photo-<id>.jpg` |
| `DOCUMENT`: one `SOURCE` entry with a `filename`, no thumbnail | *Read* and *Save…* as in announcements |
| **29 messages are `chat.RChatStatusMessage`** with `status` `ENTER`, `LEAVE` or `TITLE_CHANGED` (+ `title`), and no text. They are a second cause of "empty" messages | Show "… joined", "… left", "… renamed the chat to …" as a small centred line (new, phase 2 and 6) |
| 5 deleted messages have neither text nor attachment | Already shown as "(message deleted)" |
| `message.identity`'s id is one of the ids in `GET /account/me` for 28 messages | Your own messages can be told apart: phase 6 can put them on the right |
| Links: only plain `https://` addresses | Already work |

**Calendar items**

| Found | Meaning for the plan |
| --- | --- |
| The item with "In de link is een klein filmpje" has **no attachment and no address in its text**. The link is a separate field, **`calendarItem.url`**, only in the detail call (`GET /event/{id}`), absent in the list | The client never reads it and the spec does not have it. Show it as *Link* (new, phase 4) |
| 1 calendar attachment in 113 items, an `IMAGE` | Same handling as announcements |

**Announcements**

| Found | Meaning for the plan |
| --- | --- |
| 224 attachments: **211 `IMAGE`**, 9 `PDF`, 4 `DOCUMENT` | Photos are by far the most common, so thumbnails matter most here, not in chats |
| `contents` is plain text, never HTML. One link, a plain `https://` address | Already works; the HTML fix of phase 5 only concerns school news |
| 6 announcements also have **`richTextContents`**: a JSON string in Quill's "delta" form, with `bold`, `underline`, `blockquote` and `link` attributes. The client ignores it, and the spec does not have it | Optional: decision 6 |
| No `www.` without a scheme, no `mailto:` in any text | Decision 4 stands; the `www.` fix is cheap but has no real example |

---

## 2. Phase 2: the core (CLI and MCP get this for free)

- **`parro/attachments.py`:** `find_attachments()` also accepts a message's `attachment`. A new
  `pick_entry(attachment, type)` next to `pick_source_entry()` finds `THUMBNAIL` and `VIDEO`.
  `AttachmentFile` gets `thumbnail_url`, `width`, `height`.
- **`parro/summaries.py`:** each chat message with an attachment gets a compact `attachment`
  (`attachment_id`, `kind`, `filename`, `content_type`, `size`), in place of the raw geon object.
- **`parro/rendering.py`:** `message_text()` gives a marker line when there is an attachment:
  `[video] IMG_9999.MOV (11.4 MB)`, after the text if there is one. The chat list's "last message"
  uses the same line, so a chat no longer ends in an empty quote.
- **Status messages:** `message_text()` also covers `chat.RChatStatusMessage`: "joined the chat",
  "left the chat", "renamed the chat to …"; an unknown status shows its name.
- **The calendar link:** `summarize_event_details()` adds `link` from `calendarItem.url`; the
  calendar views of the CLI and MCP show it as a line. Only `http(s)` addresses are passed on.
- **Reading one:** `operations.read_attachments()` gets `chatroom_id` + `message_id` beside
  `event_id`. It reuses the download, the cache and `--save-to`.
  - CLI: `attachment --chat <room> --message <id> [--save-to DIR]`.
  - MCP: `parro_attachment` takes `chatroom_id` and `message_id`. A photo comes back as an image,
    as today. For a video it returns the **thumbnail** as an image plus the file's details; for
    audio only the details. No video or audio bytes go to the model (decision 2).
- **Spec:** `ChatMessageAttachment`, the `attachment` property, the entry types `VIDEO` and
  `THUMBNAIL`, `ChatStatusMessage`, `calendarItem.url` and `richTextContents`, in
  `tools/build_spec.py`.
- **Tests:** the capture becomes a fixture; `tests/fakes.py` serves it; parity test for CLI and MCP.

Rules that stay: no full attachment URL in a log or in the cache of details, downloads only from
the known CDN host, and the privacy scan covers the new fixtures.

---

## 3. Phase 3: the desktop app, chats

- **Thumbnails in the conversation.** The conversation appears at once, with a grey box where a
  picture comes. The worker then fetches the thumbnails (small, through the existing cache) and
  the pane shows them. `SafeTextBrowser` gets an explicit list of pictures it may show
  (`allow_image(name, QImage)`); `loadResource` serves only those. It still loads nothing by
  itself, so text from others cannot make the app fetch anything.
- **A message with media** shows the thumbnail (at most about 240 px wide), a play mark for video,
  and one line below it: kind, name, size. Audio has no picture: a line with a note symbol.
- **A click** on it (an internal `parro-attachment:` link, never an address from the text):
  - photo: the existing `ReadingDialog`, with a *Save…* button added;
  - video and audio: see decision 1. Recommended: download the `SOURCE` file to the cache and open
    it in the system's own player, with *Save…* beside it.
- Only thumbnails of the messages shown (at most 100) are fetched, and never the 12 MB originals
  until you click.

---

## 4. Phase 4: announcements and calendar items

- The **attachment row** learns the kind: photo, video and audio get a small thumbnail and
  *Open* in place of *Read* (same behaviour as in a chat). Documents keep *Read* and *Save…*.
- With 211 photos in 79 announcements, a row per photo is too long: photos become a **strip of
  thumbnails** above the rows for documents; a click opens the photo. *Save all attachments…* stays.
- **The calendar item's link** (`calendarItem.url`, see phase 1): a line *Link: https://…* under
  the description, written out in full and opened after the usual question.
- CLI and MCP: the attachment list of an announcement or calendar item already names every file;
  it gains the kind (`video`, `audio`) so a model does not try to read a film as text.

---

## 5. Phase 5: links

What works today: a written-out `http://` or `https://` address in a chat, an announcement or a
calendar description is a link in the app, and opens in the browser after a question. In the CLI
and MCP the address is plain text, which is right for both.

The live look found only such plain addresses, plus the calendar link of phase 4. Two cases have
no real example in chats, announcements or calendar items; each is a small fix with a test:

- **`www.school.nl` without a scheme** is not a link. Fix: recognise `www.` and open it as `https://`.
- **HTML links** (`<a href="…">klik hier</a>`): `extract_html_text()` keeps "klik hier" and drops
  the address, in the app, the CLI and MCP alike. Fix: write it as `klik hier (https://…)`. The
  address stays visible, so a link still cannot pretend to go somewhere else.
- **`mailto:` and telephone numbers:** left as text (decision 4).

---

## 6. Phase 6: the chat layout

Suggestion: the layout people know from every messenger, inside the pane the app already has.

- **Your own messages on the right**, in a block with the theme's accent tint; **others on the
  left** in a neutral block. Blocks are at most about 70% of the width.
- **The name once per run** of messages from one person, in a colour of their own (a fixed palette
  of about six, chosen by the person's id, checked for contrast in light and dark). No name on
  your own messages, and none at all in a chat with one other person.
- **The time small**, at the end of the block; **the date as a centred line** between days
  ("Fri 13 Nov"), in place of a full date on every message.
- Alignment and a tint together, so the difference never depends on colour alone.

How: Qt's rich text can do this with a one-cell table per message (`align`, `width`, `bgcolor`,
`cellpadding`). It cannot do rounded corners. The alternative, a list view that paints real
bubbles, loses text selection, copying and clickable links, and would need its own picture
handling for phase 3. So: stay with the text pane, square blocks (decision 3).

`conversation_html()` moves to its own module (`parro_gui/views/conversation.py`) with tests for:
runs, day lines, own/other, a message with only media, a deleted message, both themes.

---

## 7. Decisions for you

| # | Question | Recommended |
| --- | --- | --- |
| 1 | Video and audio in the app: (a) open in the system's player, or (b) a player inside the app (`QtMultimedia`) | **(a)** for 0.13.0. (b) needs a trial on all three installers first: a phone's `.MOV` is often HEVC, and the installers grow. It can follow in a later release, playing the `video-hls` stream |
| 2 | MCP: a video gives the thumbnail and the details, never the film itself | Yes |
| 3 | Chat layout in the existing text pane, with square blocks | Yes |
| 4 | `mailto:` and phone numbers stay plain text | Yes |
| 6 | Announcements with `richTextContents` (6 of 79): show bold, underline and quotes in the app, and a link whose text differs from its address as `text (address)` | Leave for a later release: `contents` already holds the same words, and one sample with a link is thin |
| 5 | Show thumbnails without asking (they are fetched from Parro's CDN as soon as a chat opens), or behind a setting | Without asking; the files are already yours to see, and they go into the same cache as other attachments |

---

## 8. Order and release

1. Phase 1, the live look: done.
2. Phase 2, core + CLI + MCP + spec.
3. Phase 6, chat layout (before the thumbnails, which then drop into the new blocks).
4. Phases 3 and 4, media in the app.
5. Phase 5, links.
6. Live check of the app on a real chat, `CHANGELOG.md`, docs (`DESKTOP-APP.md`, `MCP.md`,
   `API-NOTES.md`), version 0.13.0.

One branch, `media-0.13`, one pull request per phase or one in all, as with 0.12.
