# The desktop app

`parro-client-gui` is a window for Windows, macOS and Linux that does what the command line does. It
is built on the same `parro` package, so login, safety rules and data are shared. Back to the
[README](../README.md).

## Installing

The app needs **Python 3.12 or newer**, and Qt, which comes with the `gui` extra:

```bash
pipx install "parro-api-client[gui]"
```

If `pipx` uses an older Python, name a newer one with `--python python3.12`. Qt adds about 300 MB.
Then start `parro-client-gui`. The downloadable release archives do not include the app, because it
needs Qt installed.

On Linux, Qt needs a few system libraries that most desktops already have. On a minimal system these
are `libegl1`, `libgl1`, `libxkbcommon0`, `libdbus-1-3` and `libfontconfig1` (the Debian and Ubuntu
names).

**Why 3.12:** on Python 3.10 and 3.11, PySide6 (the Qt library for Python) has a bug that crashes the
interpreter, also while the app is running. The command line and the MCP server do not use Qt and
keep working on Python 3.10 or newer.

## What is in it

| Section | What you can do |
| --- | --- |
| Overview | what is new, or everything |
| Announcements | filter by group or unread, read the news from Parro, read or save attachments, mark as read |
| Calendar | coming up or earlier, filter by group, answer invitations, sign up or withdraw as a helper, export an `.ics` file, show the subscription link |
| Chats | the same filters as the command line, read a conversation, send a message, mark as read |
| Family | the account, children, groups, the state of the privacy choices, the link to a child's privacy page |
| Archive | keep a local copy with `sync`, stop it at any time, see and empty the cache |

The commands `token` and `get` and the raw JSON output are left out: they are developer tools.

## Logging in

The app uses the same login as the command line and the MCP server: log in with one, and the others
are logged in too. You can type your password, or log in in your browser and paste back the address
you end up on. Your password is not stored.

The login server locks an account after a few failed attempts, so one click is one attempt and
nothing is retried. After a rejected password the app says that login has stopped.

## Changing things

The app can change the same four things as the command line:
[see the guide](CHANGING-THINGS.md).

- Nothing changes because you opened or read something.
- Sending a message, signing up or withdrawing, and answering an invitation show exactly what would
  happen, and only **Confirm** does it. Enter does not. Marking as read asks once.
- After a timeout or a server error the app says it may or may not have gone through, and offers no
  button to try again.

## What it protects

- **There is no web server or open port.** The app is a normal window.
- **Text from others stays text.** Announcements and chats cannot run scripts or load remote images.
  A link opens in your browser only after you have seen the full address.
- **Other people's answers to invitations are not shown.**
- The calendar subscription link and privacy links work without logging in, so they are only
  fetched when you ask, and stay in their own dialog.

## Good to know

- Requests run one at a time, so other sections wait while a sync is running. Stopping the sync frees
  them straight away.
- The Calendar section shows up to 30 items, because each one costs a request for its details.
