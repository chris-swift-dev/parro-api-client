# Plan 18: three additions to 0.13.0, before the release

*Status: built (2026-11-14) on branch `media-0.13`, in the same pull request as
[Plan 17](PLAN-media-and-chat-0.13.md). Still to check by the account owner: *Open* in the Flatpak,
and the first real deletion (section 4).*

**Goal:** after the live check of the installers on Windows, macOS and Linux:

1. *Open* on a video does nothing in the Flatpak app. Find out why and fix it.
2. Delete a chat message of your own.
3. A photo opens at its full size, so you see a corner of it. Show it scaled to fit.

---

## 1. *Open* in the Flatpak app

### 1.1 Why nothing happens

The app fetches the video into a folder made with `tempfile`, which is `/tmp`, and asks the desktop
to open it. On Windows and macOS that is all it takes. Inside a Flatpak:

- the app cannot start another program; Qt asks the desktop's *portal* to open the file, and hands
  it the open file;
- the portal must find that file **on the computer itself**, to pass it on to the player;
- a Flatpak's `/tmp` is private: a folder in memory that exists only inside the sandbox. The portal
  cannot reach the file, refuses, and Qt reports nothing back. So: no player, no dialog, no error.

This is a reading of how the portal works, not something measured: the Flatpak is not installed in
the session that built this, so it could not be tried here. The retest in section 4 decides.

### 1.2 The fix

- In a Flatpak (`FLATPAK_ID` is set), the folder for fetched media is in the app's cache folder
  (`$XDG_CACHE_HOME`, on disk `~/.var/app/<id>/cache/parro-media`). That folder is the same folder
  inside and outside the sandbox, so the portal can pass the file on. No extra permission is needed.
- Elsewhere nothing changes: the system's temporary folder, as checked on Windows and macOS.
- The folder is still removed when the app closes. In a Flatpak it is also emptied when the app
  starts to use it, in case the app was killed and left a film behind.
- The message after *Open* no longer claims the player opened, which the app cannot know there:
  "Handed IMG_0001.MOV to your computer to open. If nothing opens, use Save…".

---

## 2. Deleting a chat message

### 2.1 What the captures say

`delete-chat-message-options.har` and `delete-chat-message.har` (2026-11-14, from the web app):

```
DELETE /rest/v2/chatroom/{chatroomId}/chatmessage/{messageId}      no body   →  204, no body
```

with the usual headers. The preflight allows `DELETE, POST, GET, OPTIONS, PUT`. Afterwards the
message is still in the list, with `deleted: true` and without its text or attachment (seen live:
6 such messages), and everyone in the chat sees that a message was deleted.

Live look (read-only, 339 messages): a message's `permissions` name only `READ`, for your own
messages too. So the API does not say which messages you may delete; the client decides.

### 2.2 The rules

This is a **fifth kind of write**, so the same care as for sending:

- **Only your own messages**: the message's author is one of your ids from `GET /account/me`.
  Anything else is refused before a request is sent. (A teacher may be allowed more in Parro; this
  client does not try.)
- Not a message that is already deleted, and not a "joined / left" line.
- **Read first, then ask.** `prepare_chat_message_deletion` fetches the one message and returns what
  would be deleted: the chat, when it was written, its text (shortened) and its file. Only a yes
  deletes it.
- **Once.** After a timeout or a `5xx` the client says the outcome is unknown and does not try
  again; look at the chat. A `404` means it is gone or never was.
- It cannot be undone, and says so.

### 2.3 Where

| Where | How |
| --- | --- |
| CLI | `chat-delete <chatroom-id> <message-id> [--yes]`: shows the message, asks `Delete this message? [y/N]`. Without a terminal and without `--yes`, nothing is deleted |
| CLI, to find the id | `chat-messages` shows `#<id>` on your own messages too (today only on messages with a file), and marks them `yours` in JSON |
| MCP | `parro_delete_chat_message(chatroom_id, message_id, confirm)`, listed only with `PARRO_ALLOW_DELETE_CHAT=1`; without `confirm: true` it only shows the preview |
| Desktop app | a small *Delete* link in each of your own messages; it opens the usual dialog with the message, and only **Confirm** deletes. Then the chat is loaded again |
| Spec | `deleteChatMessage` on `/chatroom/{id}/chatmessage/{messageId}` |
| Tests | the fake API accepts only this `DELETE`, without a body, on a message of your own; any other write still fails the test |

Texts that say "four things" (README, help, `SECURITY.md`, `CHANGING-THINGS.md`, the code tour, the
desktop app's page) become five.

---

## 3. A photo scaled to fit

- The window that shows a photo scales it to the room it has, keeping its shape, and scales it
  again when you resize the window. It is never enlarged beyond its own size.
- A button switches between **Actual size** (with scroll bars, as it was) and **Fit to window**.
- The photo the app shows is the one the core already limits in size; nothing else is fetched.

---

## 4. Checks

- Tests for each part; the checks of Plan 17.
- **To retest by you, on Linux:** *Open* on a video with the Flatpak that CI builds from this
  branch. If it still does nothing, the next step is to look at the portal's own log
  (`journalctl --user -u xdg-desktop-portal -f` while clicking *Open*).
- Deleting is checked against the fake API only. The first real deletion is yours to do, on a
  message you can miss.
