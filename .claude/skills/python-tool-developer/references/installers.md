# Installers: Briefcase for Windows, macOS and Linux

## Contents

1. Choosing the formats
2. Briefcase configuration
3. Flatpak in detail
4. Publisher and author on each system
5. HTTPS certificates in a bundled Python
6. Checks every built installer runs
7. Building from a clean copy
8. What users see the first time (unsigned)

## 1. Choosing the formats

| System | Format | Notes |
| --- | --- | --- |
| Windows 10/11 | `.msi` | Briefcase's WiX template; installs per user, appears under *Installed apps*. |
| macOS 14+ | `.dmg` | `universal_build = true` (Apple silicon and Intel in one). |
| Linux | `.flatpak` (x86_64 and aarch64) | One file per CPU, own Python and Qt, sandboxed. |

Rejected for Linux, and why:
- **AppImage:** Briefcase discourages it (built on an old base system to run everywhere; Qt's
  system libraries are a constant source of breakage).
- **deb/rpm:** Briefcase's system packages use the **distribution's** Python, so one package per
  distribution release and Python version, and Qt from pip on top. Too many combinations.

Flatpak's cost: users need Flatpak (Ubuntu/Debian: `sudo apt install flatpak
gnome-software-plugin-flatpak`), a runtime download the first time, and a sandbox to configure.

## 2. Briefcase configuration

Pin Briefcase (`briefcase==0.4.x` in `requirements-installers.txt`); its templates change between
versions and each detail below was found against one version.

```toml
[tool.briefcase]
bundle = "io.github.yourname"           # reverse-DNS prefix

[tool.briefcase.app.mytool-gui]
formal_name = "My Tool"
description = "One line"
sources = ["mytool", "mytool_gui"]
# Exact pins; a test checks they equal requirements-gui.txt.
requires = ["PySide6-Essentials==6.12.0", "truststore==0.10.5"]
icon = "packaging/icon"                 # icon-16.png ... icon-512.png, icon.ico, icon.icns

[tool.briefcase.app.mytool-gui.macOS]
min_os_version = "14.0"                 # what the PySide6 wheels need
universal_build = true
requires = ["std-nslog~=2.0.0"]         # print()/logging reach macOS's Console

# Briefcase's macOS template writes no author or copyright into Info.plist.
[tool.briefcase.app.mytool-gui.macOS.info]
NSHumanReadableCopyright = "Copyright © 2026 yourname"
```

- Briefcase reads PEP 621 metadata: `authors[0].name` → author (MSI *Manufacturer*; the default
  is "Anonymous", shown as "Unknown publisher"), `urls["Homepage"]` (exact key, capital H) → the
  MSI's support link (`ARPURLINFOABOUT`).
- The app needs an entry point Briefcase can run: `mytool_gui/__main__.py` calling `app.run()`.
- macOS sends the app's output to the system log, not the terminal; checks there rely on exit
  codes.

## 3. Flatpak in detail

**The ID.** A Flatpak ID allows `-` only in its last part, and Briefcase rejects `_`. So
`io.github.your-name.app` is invalid; use the account name without dashes
(`io.github.yourname`) as the Flatpak `bundle`, set separately under `linux.flatpak`. The app's
desktop file and metainfo use this full ID; call `QGuiApplication.setDesktopFileName(ID)`.

**Runtime.** Briefcase's PySide6 template uses KDE's runtime (`org.kde.Platform` / `org.kde.Sdk`),
which holds the system libraries Qt needs. Use a version that is still supported on Flathub (6.9
went end-of-life during the project; 6.11 was current).

**Branch.** Briefcase writes the app version as the manifest's `default-branch`, so every release
would be a different branch and updates would install side by side. Patch the generated
manifest to `default-branch: stable` (fail the build if the line is not found), and build the
bundle yourself:

```bash
flatpak-builder --force-clean --disable-rofiles-fuse --install-deps-from=flathub \
  --user --repo repo --install build manifest.yml
flatpak build-bundle repo MyTool-1.2.0-linux-x86_64.flatpak io.github.yourname.mytool-gui stable
```

So run `briefcase create linux flatpak` only, patch, then run flatpak-builder as above.
`--disable-rofiles-fuse`: with an AppStream metainfo present, flatpak-builder's compose step
failed with `icon-write-error` through the rofiles-fuse layer.

**Metainfo and categories.** Briefcase writes no AppStream metainfo and no `Categories=`, so
software centres show no developer, licence or links, and menus file the app under "Other".
Keep `packaging/<ID>.metainfo.xml` (id, name, summary, `<developer id=...><name>`, CC0
metadata licence, project licence as SPDX, a description with any "unofficial" disclaimer,
categories, `<launchable type="desktop-id">ID.desktop</launchable>`, homepage/vcs/bugtracker
URLs, `<content_rating type="oars-1.1"/>`). Add a manifest step that installs it to
`/app/share/metainfo/` and appends `Categories=...;` to the desktop file. Check it with
`appstreamcli validate`. Test that the metainfo's id, developer and homepage equal pyproject.

**The sandbox.** Start from nothing and open only what is needed:

```toml
[tool.briefcase.app.mytool-gui.linux.flatpak.finish_arg]
"socket=x11" = false
"socket=wayland" = true
"socket=fallback-x11" = true
"socket=pulseaudio" = false
"filesystem=xdg-cache" = false
"filesystem=xdg-config" = false
"filesystem=xdg-data" = false
"filesystem=xdg-documents" = false
"persist=.mytool" = true          # every folder the app writes to in $HOME
```

The sandbox's home is temporary: anything not `persist`ed is gone when the app closes. The login
tokens were written to a second folder that was not kept, so every start needed a new login.
Write a test that collects every path the app writes to (settings, token file, data dir, cache)
and asserts each is persisted. Files chosen in dialogs come through the file portal and need no
filesystem permission. Keep `share=ipc`, `share=network`, `device=dri`.

**Fonts:** see desktop-qt.md (settings portal).

**Installing and updating.**
- `flatpak install --user file.flatpak` refuses when the app is already installed (also with
  `--reinstall` on Flatpak 1.14): uninstall first (`flatpak uninstall --user ID`, data stays).
- A double-click opens the software centre, which installs **system-wide** by default. If the
  user once installed with `--user`, there are now two copies with the same ID; the menu opens
  the user copy, which may be the older one. `flatpak list --app` shows both; remove one. Put
  this in the install guide.
- `flatpak uninstall --delete-data` removes `~/.var/app/ID/` too.
- Inside the sandbox: `flatpak run --command=sh ID -c '...'` to inspect the installed files.

## 4. Publisher and author on each system

| System | Where users see it | Source | How CI checks it |
| --- | --- | --- | --- |
| Windows | *Installed apps* → publisher, support link | `authors[0].name`, `urls.Homepage` | Read MSI properties `Manufacturer`, `ARPURLINFOABOUT` |
| macOS | Finder *Get Info*, About box | `macOS.info.NSHumanReadableCopyright` | `plistlib` on the built app's `Info.plist` |
| Linux | Software centre | metainfo `<developer>` | `flatpak run --command=cat ID /app/share/metainfo/ID.metainfo.xml` |

Reading an MSI property on Windows: write the PowerShell to a `.ps1` file and run it with
`powershell -NoProfile -ExecutionPolicy Bypass -File script.ps1 <msi> <property>`. With
`-Command "<script>" arg1 arg2` the arguments are glued onto the script text and `$args` is
empty, so the query silently returns nothing. Fail the build when PowerShell fails.

```powershell
$installer = New-Object -ComObject WindowsInstaller.Installer
$db = $installer.GetType().InvokeMember("OpenDatabase", "InvokeMethod", $null, $installer, @($args[0], 0))
$view = $db.GetType().InvokeMember("OpenView", "InvokeMethod", $null, $db, @("SELECT Value FROM Property WHERE Property='" + $args[1] + "'"))
$view.GetType().InvokeMember("Execute", "InvokeMethod", $null, $view, $null)
$record = $view.GetType().InvokeMember("Fetch", "InvokeMethod", $null, $view, $null)
if ($record) { $record.GetType().InvokeMember("StringData", "GetProperty", $null, $record, 1) }
```

A name in the MSI does not remove the "Unknown publisher" warning *before* installing; only a
code-signing signature does (an OV/EV certificate, or a free one for open source from the
SignPath Foundation). The name does show in *Installed apps*.

## 5. HTTPS certificates in a bundled Python

The installers carry their own Python, whose `ssl` module uses OpenSSL with its own list of
root certificates. On macOS that list is empty; on Windows it holds only roots Windows has
already fetched. Result: `[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer
certificate`, sometimes for one host and not another (it worked against the API, failed for
GitHub and the CDN on Windows; failed for everything on macOS). A pip-installed app on a
developer machine does not show it.

Fix: `truststore` (MIT, small, Python 3.10+) makes `ssl` ask the operating system (Windows'
certificate service, macOS Keychain, OpenSSL's system store on Linux), which also honours
company-installed roots:

```python
def use_system_certificates() -> str:
    try:
        import truststore
    except ImportError:
        return "Python's own"
    truststore.inject_into_ssl()
    return "the operating system's (truststore)"
```

Call it in `app.run()` before anything connects; add `truststore` to the `gui` extra and to
Briefcase `requires`; make the self-check fail in an installer when truststore is missing. Keep
the core standard-library only: the injection lives in the GUI package.

## 6. Checks every built installer runs

The offline self-check cannot see certificate problems, and the macOS build cannot show
output. So `tools/build_installer.py` runs, on the **installed/built** app:

1. `--self-check`: builds the window offscreen with a transport that refuses requests, prints
   versions, Qt platform, optional libraries and which certificate check is used; exit 0.
2. `--check-connection`: one real HTTPS request (the update check's GET to GitHub). Count **any
   HTTP answer** as success, printing the status: what is checked is the TLS connection, and
   shared CI runners get 403 rate-limit answers from GitHub's API. Only "no answer" (certificate,
   DNS, timeout) fails.
3. The publisher checks from section 4.

For the Flatpak: uninstall any installed copy, install the built bundle exactly as a user would,
then run the checks through `flatpak run`.

## 7. Building from a clean copy

Build from `git archive HEAD` extracted into a temp folder, not from the working tree, so
untracked files cannot leak into an installer. Name outputs with the version and system:
`MyTool-<version>-windows-x64.msi`, `-macos.dmg`, `-linux-x86_64.flatpak`,
`-linux-aarch64.flatpak`, and keep that naming in one function shared by the build script, the
release notes and the landing page.

To build locally from uncommitted changes, copy `git ls-files -co --exclude-standard` into a
scratch folder and point the build script's clean-copy step at it.

## 8. What users see the first time (unsigned)

- **Windows:** SmartScreen "Windows protected your PC" → *More info* → *Run anyway*.
- **macOS:** "Apple could not verify ..." → *Done*, then *System Settings → Privacy & Security →
  Open Anyway*. Terminal shortcut for advanced users (no `sudo` needed for own files):
  `xattr -d com.apple.quarantine ~/Downloads/MyTool-1.2.0-macos.dmg`, or
  `xattr -dr com.apple.quarantine "/Applications/My Tool.app"`. Tell them to verify the
  download first.
- Every release: `SHA256SUMS` and GitHub build attestations
  (`gh attestation verify FILE --repo OWNER/REPO`); document both.
