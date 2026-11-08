# Plan 8: sending a chat message to an existing chat

*Status: done (2026-11-08): phases 1–5 merged in #12, released as 0.7.0 (phase 6). Decisions in §6
(decision 2 changed: an MCP tool behind its own switch). What was not checked live is in
`docs/LIVE-CHECKS.md`.*

**Goal:** the spec describes sending a text message to an existing chat, and the client can do it.
Sources: `findings/send-chatmessage.har` and `findings/send-chatmessage.200.json` (git-ignored).

---

## 1. What the capture shows

| | |
| --- | --- |
| Call | `POST /chatroom/{id}/chatmessage`, no query parameters |
| Headers | the usual ones: bearer token, role, `parro-app-version`, geon `Accept` and `Content-Type` |
| Body | `{"items":[{"dtype":"chat.RChatTextMessage","links":[],"deleted":false,"text":"…","allRead":false}]}` |
| Answer | **`201`** (the sample's file name says 200), `Location: …/chatroom/{id}/chatmessage/{messageId}`, body `{"items":[<the new message>]}` |
| Id | as for every chat call, the chat's `rel: self` id (the `koppeling` id answers 403) |

The capture is clean: placeholder token, role and ids, no cookies, no JWTs. The sample passes the
privacy scan.

**What it does not show**, and what we cannot find out without sending real messages to real people:

- the longest message allowed, and how empty text is answered;
- how a chat that cannot be written to answers (`repliesEnabled: false`, `active: false`, archived,
  `BOT`);
- whether a sent message can be taken back. The capture has no `DELETE`, and a message's
  `permissions` list only `READ`, also for your own. **Treat sending as final.**
- whether sending changes the chat's unread count for yourself (checked in phase 5).

## 2. Challenging it: this is a different kind of write

Marking as read changes a flag. Sending **speaks for you**:

- **Real people read it**, under your name: teachers, or every parent in a group chat. They get a
  notification, and it cannot be recalled (as far as we know).
- **A wrong id reaches the wrong people.** Ids are long numbers that are easy to mix up.
- **Sending twice is visible.** The request has no idempotency key: after a timeout the client
  cannot know whether the message arrived.
- **It weakens the promise again.** README, FAQ ("cannot post, send or delete"), `SECURITY.md`, the
  help text, the User-Agent and the code's own rules all say otherwise today.
- **An assistant is the biggest risk.** Through MCP, Claude reads messages written by other people
  and could send messages too. Text in a chat or a newsletter could then steer it into writing to a
  chat ("reply to this with…"). Private data, untrusted input and a way to send are the combination
  to avoid. An approval prompt helps, but people auto-approve tools.

**Recommendation: do it, narrowly.** (First proposed for the CLI only; see decision 2.) The new promise: *it reads; the only changes
it can make are marking items as read and sending a text message to a chat you are in, and only when
you ask.*

## 3. The design

1. **One new write, nothing generic.** `ParroClient.send_chat_message(chatroom_id, text)` builds the
   captured body itself. No generic `post()`. The fake API's allowlist gets exactly this path and
   body shape, so any other write still fails every test.
2. **Never automatic, never a side effect.** Only the new command sends.
3. **See it before it goes.** `chat-send ID TEXT` first fetches the chat and shows the title, the
   kind of chat, who will receive it (names from `chatroommember`) and the exact text.
   - At a terminal it then asks `Send this message? [y/N]`; anything but `y` sends nothing.
   - `--yes` skips the question (for scripts). Without a terminal and without `--yes` nothing is sent.
   - Text from an argument, or `--file PATH` / `--file -` (standard input) for longer messages.
4. **Refuse what cannot be right, before sending:** empty or only whitespace; a chat that is archived,
   not `active`, has `repliesEnabled: false`, or is of type `BOT`. No guessed length limit: the API's
   answer is shown as it is.
5. **Never sent twice.** The client does not retry a send. After a timeout or a network error it says
   the message *may* have arrived and to check with `chat-messages ID`. The one exception is the
   existing refresh after a `401`, because the server refused that request.
6. **The text stays private.** It is never logged, cached or stored; logs name the method and host,
   as now. Sending does not mark the chat as read.

## 4. Out of scope

Starting new chats, browsing people to message, replies to a specific message, attachments, scheduled
messages, editing or deleting. None of these is in the capture.

## 5. Phases

| # | Phase | Done when |
| --- | --- | --- |
| 1 | **Spec and privacy:** sanitized sample `sendChatMessage.201.json` (git-ignored); `POST …/chatmessage` in the *Chat* section with request body, `201`, `Location`, what is unknown, and a warning that real people receive it | spec validates; privacy scan passes |
| 2 | **Client:** `send_chat_message`, the checks of §3, `chat-send` with preview, question, `--yes`, `--file`; the fake API accepts exactly this write and keeps the message | tests: nothing sent without confirmation, refusals, no retry on a network error, text absent from logs, no other write possible |
| 3 | **MCP:** `parro_send_chat_message`, only with `PARRO_ALLOW_SEND_CHAT=1`, `destructiveHint: true`; without `confirm: true` it only returns the preview | tests: off by default, independent of the mark-read switch, nothing sent without `confirm: true` |
| 4 | **Docs:** README promise, badge, a *Sending a chat message* section, FAQ; `SECURITY.md` scope; help text, User-Agent, package description, CODE-TOUR, API-NOTES; CHANGELOG **0.7.0** | links and pictures checked |
| 5 | **Live check with you:** **one** message, in a chat *you* pick, with a text *you* choose; it appears in the Parro app and in `chat-messages`; note what happens to the unread count | in `docs/LIVE-CHECKS.md` |
| 6 | Release **0.7.0** (a new feature and a changed promise: a minor version) | published |

Pick a chat in phase 5 where a test message bothers nobody, for instance one with just your partner.
If that person replies, the chat is unread, and `mark-read chat` can also close the gap left by
Plan 7: `PUT /chatroom/{id}/read` has not been checked live yet.

## 6. Decisions (2026-11-08)

1. **How to confirm:** the question at a terminal plus `--yes` for scripts, as in §3 (*recommended*);
   or always `--yes`, like `mark-read group`.
2. **MCP (changed on 2026-11-08):** `parro_send_chat_message`, only with its own
   `PARRO_ALLOW_SEND_CHAT=1`, marked `readOnlyHint: false` and `destructiveHint: true`. The risk of §2
   is accepted for those who switch it on, and the docs must say so. As an assistant has no terminal
   to ask at, the tool returns the preview unless called with `confirm: true`.
3. **Which chats:** every kind that can be written to except `BOT` (*recommended*); or only chats with
   one person (`SINGLE`), so nothing can go to a whole group.
