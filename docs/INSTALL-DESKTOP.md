# Installing the desktop app

The desktop app, without Python and without a terminal: one download for Windows, macOS or Linux.
Back to the [README](../README.md); what the app does is in [DESKTOP-APP.md](DESKTOP-APP.md).

This is an unofficial app. It is not affiliated with or endorsed by Topicus, ParnasSys or Parro.

## Which file

Download it from the [latest release](https://github.com/chris-swift-dev/parro-api-client/releases/latest),
under *Assets*:

| Your computer | The file ends in |
| --- | --- |
| Windows 10 or 11 | `-windows-x64.msi` |
| A Mac with macOS 14 (Sonoma) or newer, Apple silicon or Intel | `-macos.dmg` |
| Linux on a usual PC | `-linux-x86_64.flatpak` |
| Linux on ARM (a Raspberry Pi 5, a Mac with Asahi Linux) | `-linux-aarch64.flatpak` |

Each file has Python and Qt inside: 80 to 140 MB.

## Windows

1. Double-click the `.msi` file.
2. Windows may say **"Windows protected your PC"**. The app is not signed yet, so Windows does not
   know who made it. Click **More info**, then **Run anyway**.
3. Follow the installer. Then start **Parro Client** from the Start menu.

**Updating:** install the new `.msi`; it replaces the old version. **Removing:** *Settings → Apps →
Installed apps → Parro Client → Uninstall*. Your login and the data folder stay in `.parro` in your
user folder; delete that folder too to remove everything.

## macOS

1. Double-click the `.dmg` file, and drag **Parro Client** to **Applications**.
2. Open it from Applications. macOS says **"Apple could not verify…"**, because the app is not
   notarized yet. Click **Done**.
3. Open **System Settings → Privacy & Security**, scroll down to the message about Parro Client, and
   click **Open Anyway**. Confirm with your password or Touch ID.

You do this once. After that the app opens like any other.

**If you use the Terminal,** you can skip steps 2 and 3. Before opening the downloaded file, remove
the mark macOS puts on downloads:

```bash
xattr -d com.apple.quarantine ~/Downloads/Parro-Client-0.12.0-macos.dmg
```

The app you copy out of it then opens straight away. If it is already in Applications:

```bash
xattr -dr com.apple.quarantine "/Applications/Parro Client.app"
```

This skips macOS's own check for this one file, so [check the download](#checking-a-download)
first. No `sudo` is needed for files that are yours.

**Updating:** drag the new version to Applications and replace the old one. **Removing:** drag
Parro Client from Applications to the Trash. Your login and the data folder stay in `~/.parro`;
delete that folder too to remove everything.

## Linux

The app comes as a **Flatpak**: it works on most distributions, with its own Python and Qt, in a
sandbox.

**Flatpak first.** Fedora, Linux Mint, Pop!_OS, elementary OS, Zorin OS and the Steam Deck have it
already. On **Ubuntu** and **Debian**, install it once:

```bash
sudo apt install flatpak gnome-software-plugin-flatpak
```

**Install:** double-click the `.flatpak` file to open it in your software centre, or in a terminal:

```bash
flatpak install --user Parro-Client-0.12.0-linux-x86_64.flatpak
```

Then start **Parro Client** from your app menu.

**Updating:** double-click the new file; the software centre installs it over the old version, and
your login stays. On the command line, `flatpak install` refuses while the old version is there, so
remove that first (your login stays):

```bash
flatpak uninstall --user io.github.chrisswiftdev.parro-gui
flatpak install --user Parro-Client-0.12.1-linux-x86_64.flatpak
```

**Two copies?** A software centre installs for all users, `flatpak install --user` only for you. If
you used both ways, both copies stay, and the app menu opens the one installed with `--user`, which
may be the older one. `flatpak list --app | grep parro` shows a line per copy; remove the one you do
not want (both share the login and data, which stay):

```bash
flatpak uninstall --user io.github.chrisswiftdev.parro-gui
```

**Removing**, with the login and all data:

```bash
flatpak uninstall --user --delete-data io.github.chrisswiftdev.parro-gui
```

**The sandbox.** The app can reach the network, show its window and use the graphics card. It keeps
its login and data in its own folder, `~/.var/app/io.github.chrisswiftdev.parro-gui/`, apart from a
`parro-client` installed with pipx, so it asks you to log in once. Your login (`.parro-mcp`) and the
data folder (`.parro`) are the only folders it keeps there. Files you save or choose (an
attachment, a password file) go through your desktop's file dialog; the app sees no other files.

## Logging in

The first start asks you to log in with your Parro e-mail address and password. The login lasts up
to 8 hours. To log in by itself after that, the login dialog can remember a password file: see
[DESKTOP-APP.md](DESKTOP-APP.md#logging-in-by-itself).

## New versions

The first start asks whether the app may check for new versions. If you say yes, it asks GitHub for
the newest release when it starts, at most once a day. Nothing about you or your school goes with
it. When there is a newer one, a button at the bottom of the window says so and opens the release
page; the app never downloads or installs anything itself. *Help → Check for new versions at start*
switches it on or off, and *Help → Check for updates now* checks at once.

## Checking a download

Every release has a file `SHA256SUMS` with a checksum for each file. Compare it with:

| System | Command |
| --- | --- |
| Windows (PowerShell) | `Get-FileHash Parro-Client-0.12.0-windows-x64.msi` |
| macOS | `shasum -a 256 Parro-Client-0.12.0-macos.dmg` |
| Linux | `sha256sum Parro-Client-0.12.0-linux-x86_64.flatpak` |

GitHub also records that it built each installer from the release's code. With the
[GitHub CLI](https://cli.github.com):

```bash
gh attestation verify Parro-Client-0.12.0-macos.dmg --repo chris-swift-dev/parro-api-client
```

## With Python instead

If you use a terminal anyway, `pipx install "parro-api-client[gui]"` installs the same app, together
with the command line: see [DESKTOP-APP.md](DESKTOP-APP.md#installing).
