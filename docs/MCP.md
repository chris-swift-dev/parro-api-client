# The MCP tools

What `parro-client-mcp` offers to Claude and other MCP clients. How to add it to your client is in the
[README](../README.md#mcp-server); every setting is in [CONFIGURATION.md](CONFIGURATION.md).

| Tool | What it gives you |
| --- | --- |
| `parro_auth_status` | Login state, account, role, token expiry, whether automatic login is halted. Start here when something fails. |
| `parro_login` | Log in with `PARRO_USERNAME` and the password; optional `method`. |
| `parro_login_url` / `parro_login_finish` | Browser login without a stored password (OAuth2 + PKCE). |
| `parro_logout` | Revoke the tokens at the IdP and forget them. |
| `parro_me` | Account and school. |
| `parro_children` | Children linked to the account. |
| `parro_groups` | Classes and school-wide groups, with the ids other tools need. |
| `parro_announcements` | The main feed. Merges all groups, newest first, full text + attachment list. |
| `parro_announcement` | One announcement by id, with author. |
| **`parro_attachment`** | **Downloads an attachment of an announcement, calendar item or chat message (`chatroom_id` + `message_id`) and returns its text (PDF/docx/txt/csv/html) or the image. A video gives its small picture and details, never the film.** |
| `parro_calendar` | Calendar items from today on, soonest first; `details: true` adds location, description and helper slots, `past: true` earlier items. |
| `parro_chatrooms` / `parro_chat_messages` | Conversations: `unread`, `archived`, `type` and `schoolyear` filters; messages `since` a date. |
| `parro_chat_members` | Who is in a chat: parents (with their children) and teachers, and who is admin. |
| `parro_unread` | Unread counts per category. |
| `parro_get` | Escape hatch: GET any `/rest/v2` path not covered above, apart from the [list of everyone an invitation went to](CHANGING-THINGS.md#answering-an-invitation). |
| `parro_overview` | What is new: unread counts, unread announcements, new calendar items, unread chats; `all: true` shows everything. |
| `parro_calendar_link` | The personal link to subscribe to the Parro agenda (keep it secret). |
| `parro_privacy` | Per child: can parents change the privacy choices now, and when were they last changed; `link: true` gives the page to change them (keep it secret). |
| `parro_mark_read` | Only with `PARRO_ALLOW_MARK_READ=1`: mark one announcement, calendar item or chat as read ([the school sees it](CHANGING-THINGS.md#marking-as-read)). |
| `parro_send_chat_message` | Only with `PARRO_ALLOW_SEND_CHAT=1`: a preview of a chat message, or with `confirm: true` the message itself ([real people receive it](CHANGING-THINGS.md#sending-a-chat-message)). |
| `parro_delete_chat_message` | Only with `PARRO_ALLOW_DELETE_CHAT=1`: a preview of which of your own chat messages would be deleted, or with `confirm: true` the deletion ([it cannot be undone](CHANGING-THINGS.md#deleting-a-chat-message)). |
| `parro_helper_signup` / `parro_helper_withdraw` | Only with `PARRO_ALLOW_HELPER_SIGNUP=1`: a preview of signing up on a calendar item's helper slot (optional `count`) or withdrawing, or with `confirm: true` the change itself ([it is a promise in your name](CHANGING-THINGS.md#helping-out)). |
| `parro_rsvp` | Only with `PARRO_ALLOW_RSVP=1`: a preview of answering a calendar item's invitation, or with `confirm: true` the answer itself ([the school sees it](CHANGING-THINGS.md#answering-an-invitation)). |

Every tool has a `title` and the four hints MCP clients use to decide what to ask you first:
`readOnlyHint` (the 16 tools that only read have it set), `destructiveHint`, `idempotentHint` and
`openWorldHint`. They are written into each tool's definition in
[`parro/mcp_server.py`](https://github.com/chris-swift-dev/parro-api-client/blob/main/parro/mcp_server.py), so services that grade a server by reading its code
see them too; a test keeps them there and another checks that they are true.

Every tool takes an optional `format`: `json` (default) or `markdown`, a readable view that keeps
every id. The first 16 tools have the same names and arguments as the original server, so existing
MCP configurations keep working.
