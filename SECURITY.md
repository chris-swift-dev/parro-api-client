# Security

This client handles passwords, OAuth tokens and school data about children, so security reports are
very welcome.

## Reporting a problem

Please report privately, not in a public issue:
**[Report a vulnerability](https://github.com/chris-swift-dev/parro-api-client/security/advisories/new)**
(GitHub's private vulnerability reporting). Describe what you found, how to reproduce it, and which
version or commit you used. You will get an answer as soon as possible; a fix goes into a new
release, and the advisory is published once that release is out.

**Never include real credentials or data**: no passwords, tokens, HAR files, calendar subscription
links, or names and messages from a real Parro account. Use invented data, like the test suite does.

## What is in scope

- This repository: `parro/`, `parro_gui/`, `parro_cli.py`, `parro_mcp.py`, the release archives, the packages on
  PyPI (`parro-api-client`), the desktop app's installers on the release page, the GitHub
  Actions workflows and the published OpenAPI spec.
- For example: a token, password or download link that ends up in a log, a file or an error
  message; files written with permissions that are too open; anything that makes the client write
  to the Parro API other than the three mark-as-read calls (`PUT /event/{id}/read`,
  `PUT /event/markannouncementsasread`, `PUT /chatroom/{id}/read`) and sending one text message
  (`POST /chatroom/{id}/chatmessage`) and signing up or withdrawing as a helper
  (`POST /calendaritem/{id}/resource/{resourceId}/commitment/`,
  `DELETE /calendaritem/{id}/resource/{resourceId}/commitment/{commitmentId}`) and answering an
  invitation (`POST /calendaritem/{id}/calendaritemrsvp`), or that sends one of those without the
  user asking for it (for example through `parro_mark_read`, `parro_send_chat_message`,
  `parro_helper_signup`, `parro_helper_withdraw` or `parro_rsvp` while its switch is off, or a
  message, a helper change or an answer without confirmation); a message, a helper change or an
  answer that is sent twice by the client on its own; a way for an MCP tool to read the list of
  everyone an invitation went to (`GET /calendaritem/{id}/calendaritemrsvp`); the text of a message that ends up in a log or a file; a way
  around the lockout latch ([docs/LOGIN.md](docs/LOGIN.md)).

For the desktop app, also: a change made without a click on Confirm (or the question for marking as
read), a script or remote resource from Parro's content that gets loaded, a link that opens without
showing its address first, and for logging in by itself: a password that ends up in the app's own
`desktop-app.json` (it holds only the e-mail address and the path of your password file), a password
file used while others can read it, or more than one password check per expired login. For the
update check: a request to GitHub before you agreed, more than one a day by itself, anything about
you or Parro in it, or a link opened that was not built from the version number. For the Linux
Flatpak: a sandbox permission it does not need.

The risk that text in Parro steers an assistant while `PARRO_ALLOW_SEND_CHAT=1`,
`PARRO_ALLOW_HELPER_SIGNUP=1` or `PARRO_ALLOW_RSVP=1` is on is known and described in the README
([messages](docs/CHANGING-THINGS.md#sending-a-chat-message), [helpers](docs/CHANGING-THINGS.md#helping-out),
[invitations](docs/CHANGING-THINGS.md#answering-an-invitation)). A way to send a message, change a helper slot or
answer an invitation without the preview and `confirm: true` is in scope.

**Problems in Parro itself** (its API, the login server, the app) are not ours to fix: please
report them to Topicus / ParnasSys directly.

## Supported versions

Only the [latest release](https://github.com/chris-swift-dev/parro-api-client/releases/latest)
gets fixes.
