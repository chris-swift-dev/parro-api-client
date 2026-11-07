# Plan 7: read state, filters and more endpoints

*Status: planned (2026-11-07); all six decisions taken as recommended (§7). Nothing implemented yet.*

**Goal:** (1) describe the newly found endpoints, (2) let the client mark announcements, calendar
items and chats as read, so the overview shows only what is new, and (3) describe and use the
filters the API supports. Sources: your notes, `findings/*.har` (three captures, git-ignored) and two
new samples.

---

## 1. What we know

| # | Call | Evidence | Answer |
| --- | --- | --- | --- |
| 1 | `GET /chatroom?chatRoom.type=…&read=false&chatRoom.createdInSchoolyear=2025` | your notes | types `SINGLE`, `BOT`, `CALENDAR`, `GROUP`, `FAMILY` |
| 2 | `GET /chatroom?archived=TRUE` | your notes | – |
| 3 | `GET /chatroom?read=false` | your notes | – |
| 4 | `GET /chatroom/{id}` | your notes | – |
| 5 | `PUT /chatroom/{id}/read` | capture 3 | `204`, no body |
| 6 | `GET /chatroom/{id}/chatmessage/{messageId}` | your notes | – |
| 7 | `GET /chatroom/{id}/scheduledchatmessage?state=SCHEDULED` | capture 3 | `206`, empty list |
| 8 | `GET /chatroom/{id}/chatroommember?isActive=true` | capture 3, sample | `chat.RChatRoomMember` (muted, unreadCount, admin, guardian …) |
| 9 | `GET /chatroom/schoolyears` | capture 3 | `identity.RSchoolyear {schoolyear}` × 3 |
| 10 | `GET /event/{id}/attachment/{attachmentId}` | your notes | – |
| 11 | `GET /event/{id}/attachment/{id}/attachmententry/{id}` | your notes | – |
| 12 | `GET /identity/{id}` | your notes | – |
| – | `GET /chatroom/{id}/chatmessage?sort=desc-stream&modifiedSince=…&createdSince=…` | capture 3 | new filters on a known call |
| – | `PUT /event/{id}/read` | capture 2 | `204`, no body |
| – | `PUT /event/markannouncementsasread?group={id}` | capture 1 | `204`, no body: **all** announcements of a group |
| – | sending a chat message | sample | out of scope (§5) |

The three captures are clean (placeholder `Authorization`, no cookies, no JWTs, placeholder ids).
Two things in the new samples to fix before they feed the spec: `send-chatmessage.200.json` holds a
`cachedAvatarUrl` that is not redacted (the privacy scan only knows the `bao/image` avatar links),
and a short real chat text.

## 2. Challenging (2): writing to Parro

**The overview does not need writes to show only unread items.** Every announcement and calendar
item already carries `read`, and chats an `unreadCount`. Showing only unread items is a read-only
change. What writes add: after you have read something *through this client*, it stops being new,
here and in the Parro app on your phone.

**What marking as read means beyond this client:**

- **The school sees it.** Announcements have read counts that teachers see ("read by 31 of 45"),
  and chats have read receipts (`allRead`). Marking an item read tells the teacher you read it. Doing
  that for something you have not read misleads them.
- **The Parro app changes too.** Read state is shared: an item marked here is no longer highlighted
  on your phone, so it is easy to miss something that was marked by accident or in bulk.
- **An assistant could do it in passing.** Through MCP, Claude could mark items read while
  summarising them, without you having looked at them.
- **It ends the project's core promise.** "Read-only" is in the README (intro, badge, FAQ),
  `SECURITY.md` (a write to Parro is listed as a security problem), the spec's title, the CLI and
  MCP help and the User-Agent; in code, `ParroClient.get()` is the only way to reach the API.

**Recommendation: do it, narrowly.** The promise becomes: *it reads; the only change it can make is
marking items as read, and only when you ask*. Concretely:

1. **Exactly three writes**, the captured `PUT …/read` calls, through one allowlisted method
   (`ParroClient.mark_read`). No generic `put()`; `get()` stays GET-only. A test fails if any other
   method or path ever reaches the API.
2. **Never automatic.** Showing an announcement or a chat never marks it read. Only an explicit
   command does (decision 2).
3. **MCP: off by default.** The tool `parro_mark_read` exists only with `PARRO_ALLOW_MARK_READ=1`;
   its description says the school sees it, and it carries MCP's `readOnlyHint: false` annotation so
   clients ask before calling it.
4. **Bulk only in the CLI and only with confirmation:** marking a whole group's announcements shows
   how many unread items it affects and needs `--yes` (not in MCP).

## 3. Filters (3)

| Call | Filters | Spec | Client |
| --- | --- | --- | --- |
| `GET /chatroom` | `chatRoom.type`, `read`, `archived`, `chatRoom.createdInSchoolyear` | yes | `chatrooms --unread --archived --type GROUP --schoolyear 2025` |
| `GET /chatroom/{id}/chatmessage` | `sort=desc-stream`, `modifiedSince`, `createdSince` | yes | `chat-messages ID --since DATE` |
| `GET /chatroom/{id}/chatroommember` | `isActive` | yes | via `chat-members` |
| `GET /chatroom/{id}/scheduledchatmessage` | `state` | yes | – |
| `GET /event` | unknown: is there a `read` filter? | after the live check | if it exists: the overview asks only for unread items |

Values such as `TRUE` vs `true` and the exact date format get checked live, not guessed.

## 4. Endpoints in the client

| Endpoint | In the client? | Why |
| --- | --- | --- |
| chat filters, `chatroommember` | **yes**: `chatrooms` filters, `chat-members ID` | who is in a group chat; find unread or archived chats |
| `/chatroom/schoolyears` | inside `--schoolyear` | to check the value and offer the list |
| `/chatroom/{id}` | maybe, for chat titles | the list already has the same data |
| `chatmessage/{id}`, `scheduledchatmessage` | spec only | single messages; scheduled messages are for senders |
| `event/…/attachment…` | spec only | the client already reads attachments from the event |
| `/identity/{id}` | spec only | needed later for starting chats (out of scope) |

## 5. Out of scope

Sending chat messages and browsing people to message. That is a different kind of tool (it speaks
for you), with its own risks; worth its own plan once marking-as-read has settled.

## 6. Phases

| # | Phase | Done when |
| --- | --- | --- |
| 1 | **Live probe with you, GET only:** samples for every new GET and filter variant (types, `read`, `archived`, school year, member/message filters), single-item calls (4, 6, 10, 11, 12), and whether `/event` accepts a `read` filter | each call has a sample or a documented answer |
| 2 | **Privacy:** sanitize the new samples (avatar link, chat text); widen the scan to every `…Url` field and to chat `text` | scan fails on the raw values, passes on the samples |
| 3 | **Spec:** new GETs and filters; the three `PUT …/read` calls in a new tag *Read state*, saying what the school sees; title without "read-only" | spec validates; examples match |
| 4 | **Client, still read-only:** chat filters, `chat-members`, overview with unread items only (decision 5) | tests, snapshots |
| 5 | **Client, marking as read:** `ParroClient.mark_read`, the commands of decision 2, MCP tool behind `PARRO_ALLOW_MARK_READ`, the test that only the allowlist writes, nothing marks automatically | tests |
| 6 | **Docs:** README promise and badge, FAQ, `SECURITY.md` scope, User-Agent, CODE-TOUR, CHANGELOG **0.6.0** | links and pictures checked |
| 7 | **Live check with you:** one write each on items *you* pick (one announcement, one calendar item, one chat), then unread counts and the Parro app agree; bulk on a group only if you want | in `docs/LIVE-CHECKS.md` |
| 8 | Release **0.6.0** (new features and a changed promise: a minor version) | published |

## 7. Decisions needed

1. **Writes at all:** yes, narrowly as in §2 (*recommended*), or stay read-only and only filter the
   overview to unread items.
2. **How to mark as read:** an explicit `mark-read announcement|calendar|chat ID` command plus a
   `--mark-read` flag on `announcement ID` and `chat-messages ID` that marks after showing
   (*recommended*); never automatically.
3. **MCP:** the tool only with `PARRO_ALLOW_MARK_READ=1` (*recommended*), or always available.
4. **Bulk (`markannouncementsasread` for a group):** CLI only, with a count and `--yes`
   (*recommended*), or leave it out.
5. **Overview:** list only unread announcements and new calendar items, with `--all` for the
   current view (*recommended*), or keep today's view and add `--unread-only`.
6. **Sending messages:** out of scope for now (*recommended*).
