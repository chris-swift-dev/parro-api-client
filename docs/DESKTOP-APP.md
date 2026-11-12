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
| Announcements | filter by group or unread, read the news from Parro, read or save attachments (one or all at once), mark as read |
| Calendar | coming up or earlier, filter by group, answer invitations, sign up or withdraw as a helper, save attachments (one or all at once), export an `.ics` file, show the subscription link |
| Chats | the same filters as the command line, read a conversation (it opens at the newest message), send a message, mark as read |
| Family | the account, children, groups, the state of the privacy choices, the link to a child's privacy page |
| Archive | keep a local copy with `sync`, stop it at any time, see and empty the cache |

The commands `token` and `get` and the raw JSON output are left out: they are developer tools.

**An announcement or calendar item with a lot in it** still fits in the window. Under the text is a
row with *Save all attachments…* and *Mark as read*, which never scrolls away. Below that, the
attachments and the answer and helper rows scroll when there are more than fit. Drag the line between
the text and that lower part to give either more room; the lower part takes what it needs, up to
half, until you do.

**Save all attachments…** asks once for a folder, then saves every file of the item. It says how many
it saved, and names each file that failed and why; click again to try those. A file with the same
name is never replaced: the new one gets a number, such as `Nieuwsbrief (2).pdf`.

**Fetched at 14:32**, next to a section's title, says how old what you see is. The app keeps what it
fetched for 5 minutes, in memory only, so switching sections or going back to a filter choice is
instant. After that, coming back loads again. **Refresh** always fetches, and so does every change
you make: after *Mark as read*, an answer, a sign-up or a sent message, everything kept is dropped.
Logging in or out drops it too. The Overview's unread counts can therefore be up to 5 minutes old,
which the time next to them shows.

## Logging in

The app uses the same login as the command line and the MCP server: log in with one, and the others
are logged in too. You can type your password, or log in in your browser and paste back the address
you end up on. Your password is not stored.

The login server locks an account after a few failed attempts, so one click is one attempt and
nothing is retried. After a rejected password the app says that login has stopped.

### Logging in by itself

A login lasts at most 8 hours ([LOGIN.md](LOGIN.md)). To skip typing the password every morning, put
it in a file of its own and tick **"Log in by itself next time, with the password in this file"** in
the login dialog. The app then logs in by itself when the login has expired: at start, and when it
expires while the app is open. The rules are those of the command line:

- **One password check** each time, never two, and never a retry.
- **After a rejected password, nothing logs in by itself**, also not after a restart, until you log in
  by hand in the dialog. The status bar says so.
- **After you log out**, it waits for a login by hand too.
- The status bar says when it did: *Logged in until … · logged in by itself at 08:12*.

The app remembers only your e-mail address and **where** the file is, in `desktop-app.json` in its
data folder (readable by you only). The password stays in your file, which must be private:

```bash
printf '%s' 'your password' > ~/.parro-password   # or create it with an editor
chmod 600 ~/.parro-password
```

If others on the computer can read the file, the app does not use it and says why. Before it
remembers anything, it checks that the file holds the password you typed, so a typo cannot stop the
automatic logins later. To stop, untick the box and log in once. On Windows only "the file can be
read" is checked: keep it in your own user folder.

Started from a terminal, the app also uses `PARRO_USERNAME` and `PARRO_PASSWORD_FILE` (or
`PARRO_PASSWORD`), like the command line; they win over what the dialog remembered. The app always
uses the login form, also when `PARRO_LOGIN_METHOD` says `auto`, because `auto` can spend two
password checks.

## Changing things

The app can change the same four things as the command line:
[see the guide](CHANGING-THINGS.md).

- Nothing changes because you opened or read something.
- Sending a message, signing up or withdrawing, and answering an invitation show exactly what would
  happen, and only **Confirm** does it. Enter does not. Marking as read asks once.
- After a timeout or a server error the app says it may or may not have gone through, and offers no
  button to try again.
- A button that starts something stays off until it is done, and a section does one thing at a time,
  so a quick second click cannot open a second preview or send something twice.

## What it protects

- **There is no web server or open port.** The app is a normal window.
- **Text from others stays text.** Announcements and chats cannot run scripts or load remote images.
  A link opens in your browser only after you have seen the full address.
- **Other people's answers to invitations are not shown.**
- The calendar subscription link and privacy links work without logging in, so they are only
  fetched when you ask, and stay in their own dialog.

## Light and dark

The app follows your system's light or dark setting, also when you change it while the app is open.
It looks the same on Windows, macOS and Linux, and text uses your system's font size.

## Good to know

- Requests run one at a time, so other sections wait while a sync is running. Stopping the sync frees
  them straight away.
- The Calendar section shows up to 30 items, because each one costs a request for its details.
