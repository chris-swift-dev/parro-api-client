#!/usr/bin/env python3
"""Build the desktop app's installer for this computer, check that it starts, and put it in dist/.

    python3 tools/build_installer.py windows   # dist/installers/Parro-Client-<version>-windows-x64.msi
    python3 tools/build_installer.py macos     # dist/installers/Parro-Client-<version>-macos.dmg
    python3 tools/build_installer.py flatpak   # dist/installers/Parro-Client-<version>-linux-<cpu>.flatpak

Needs Briefcase (`pip install -r requirements-installers.txt`), and for the Flatpak `flatpak` and
`flatpak-builder`. It builds from a clean copy of the last commit (`git archive HEAD`), so files
that are not committed (samples/, a token file) can never end up in an installer, and Briefcase's
build/ and logs/ folders stay out of the checkout. See docs/PLAN-desktop-0.12.md.

After building, it runs the built app with `--self-check`: Qt starts without a screen, the whole
window is built, and nothing is sent. The Flatpak is installed for this user first, as people do.
Installers are unsigned; signing comes later (plan §1.4).
"""

import argparse
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "dist" / "installers"
APP = "parro-gui"
FLATPAK_ID = "io.github.chrisswiftdev.parro-gui"
FLATPAK_BRANCH = "stable"  # not the version: a newer bundle then replaces the older one
FLATHUB = "https://flathub.org/repo/flathub.flatpakrepo"
SELF_CHECK_OK = "self-check: ok"
# Each built app runs both: the offline self-check, and one HTTPS request to GitHub (the update
# check's), which an installer without the system's certificate check fails (live check of 0.12.0).
CHECKS = (("--self-check", SELF_CHECK_OK), ("--check-connection", "connection: ok"))
TARGETS = ("windows", "macos", "flatpak")


# Reads one property of an MSI through Windows Installer's own COM interface (no extra tools).
MSI_PROPERTY = r"""
$installer = New-Object -ComObject WindowsInstaller.Installer
$database = $installer.GetType().InvokeMember("OpenDatabase", "InvokeMethod", $null, $installer, @($args[0], 0))
$query = "SELECT Value FROM Property WHERE Property='" + $args[1] + "'"
$view = $database.GetType().InvokeMember("OpenView", "InvokeMethod", $null, $database, @($query))
$view.GetType().InvokeMember("Execute", "InvokeMethod", $null, $view, $null)
$record = $view.GetType().InvokeMember("Fetch", "InvokeMethod", $null, $view, $null)
if ($record) { $record.GetType().InvokeMember("StringData", "GetProperty", $null, $record, 1) }
"""


def project() -> dict[str, Any]:
    import tomllib  # Python 3.11 and newer; the builds use 3.14

    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def version() -> str:
    text = (ROOT / "parro" / "__init__.py").read_text(encoding="utf-8")
    found = re.search(r'^__version__ = "([^"]+)"$', text, re.MULTILINE)
    if not found:
        raise SystemExit("No __version__ in parro/__init__.py")
    return found.group(1)


def cpu() -> str:
    machine = platform.machine().lower()
    return {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)


def installer_name(target: str, release: str, processor: str) -> str:
    """The file name on the release page: says what it is for, without spaces."""
    if target == "windows":
        return f"Parro-Client-{release}-windows-x64.msi"
    if target == "macos":
        return f"Parro-Client-{release}-macos.dmg"
    if target == "flatpak":
        return f"Parro-Client-{release}-linux-{processor}.flatpak"
    raise ValueError(target)


def briefcase_commands(target: str) -> list[list[str]]:
    """create, build and package; for the Flatpak only create (see FLATPAK_BUILDER)."""
    platform_args = {
        "windows": ["windows", "app"],
        "macos": ["macOS", "app"],
        "flatpak": ["linux", "flatpak"],
    }[target]
    commands = [["create", *platform_args]]
    if target != "flatpak":
        commands.append(["build", *platform_args])
    if target == "windows":
        commands.append(["package", *platform_args, "-p", "msi", "--adhoc-sign"])
    elif target == "macos":
        commands.append(["package", *platform_args, "-p", "dmg", "--adhoc-sign"])
    return [[sys.executable, "-m", "briefcase", *command, "--no-input"] for command in commands]


# What `briefcase build linux flatpak` runs, plus two switches. --disable-rofiles-fuse: with the
# metainfo, flatpak-builder runs AppStream's compose step, which failed to write the icons through
# rofiles-fuse ("icon-write-error", found building 0.12.0); without that layer it works. And
# --install-deps-from: installs the KDE runtime and SDK when they are missing, as Briefcase did.
FLATPAK_BUILDER = [
    "flatpak-builder",
    "--force-clean",
    "--disable-rofiles-fuse",
    "--install-deps-from=flathub",
    "--user",
    "--repo",
    "repo",
    "--install",
    "build",
    "manifest.yml",
]


def set_flatpak_branch(manifest: str) -> str:
    """Briefcase writes the version as the Flatpak branch; every release would then install next
    to the previous one. One branch for all versions makes a newer bundle replace the older."""
    changed, count = re.subn(
        r"^default-branch: .*$", f"default-branch: {FLATPAK_BRANCH}", manifest, flags=re.MULTILINE
    )
    if count != 1:
        raise SystemExit("The Flatpak manifest has no default-branch line; Briefcase changed?")
    return changed


METAINFO = f"{FLATPAK_ID}.metainfo.xml"
DESKTOP_INSTALL = f"      - install -D {FLATPAK_ID}.desktop /app/share/applications/{FLATPAK_ID}.desktop\n"
DESKTOP_SOURCE = f"      - type: file\n        path: {FLATPAK_ID}.desktop\n"


def add_metainfo(manifest: str) -> str:
    """Install packaging/<id>.metainfo.xml with the desktop file: Briefcase writes no metainfo, and
    without it software centres show no developer, licence or links."""
    if manifest.count(DESKTOP_INSTALL) != 1 or manifest.count(DESKTOP_SOURCE) != 1:
        raise SystemExit("The Flatpak manifest does not install the desktop file as expected")
    install = f"      - install -D {METAINFO} /app/share/metainfo/{METAINFO}\n"
    source = f"      - type: file\n        path: {METAINFO}\n"
    manifest = manifest.replace(DESKTOP_INSTALL, DESKTOP_INSTALL + install)
    return manifest.replace(DESKTOP_SOURCE, DESKTOP_SOURCE + source)


CATEGORIES = "Categories=Education;Network;\n"


def add_categories(desktop_entry: str) -> str:
    """Briefcase's desktop file has no category: menus then file the app under "Other", and the
    Flatpak build's AppStream step refuses an app without one."""
    if "\nCategories=" in desktop_entry:
        return desktop_entry
    return desktop_entry.rstrip("\n") + "\n" + CATEGORIES


def run(command: list[str], folder: Path) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command), flush=True)
    return subprocess.run(command, cwd=folder, text=True, capture_output=True, check=False)


def msi_property(msi: Path, name: str) -> str:
    script = ["powershell", "-NoProfile", "-Command", MSI_PROPERTY, str(msi), name]
    return run(script, msi.parent).stdout.strip()


def check_publisher(target: str, folder: Path, installer: Path) -> None:
    """The author from pyproject.toml is where each system shows the publisher (Plan 16 §1)."""
    meta = project()
    author, homepage = meta["authors"][0]["name"], meta["urls"]["Homepage"]
    if target == "windows":
        found = {name: msi_property(installer, name) for name in ("Manufacturer", "ARPURLINFOABOUT")}
        expected = {"Manufacturer": author, "ARPURLINFOABOUT": homepage}
    elif target == "macos":
        bundle = next((folder / "build" / APP / "macos" / "app").glob("*.app"))
        info = plistlib.loads((bundle / "Contents" / "Info.plist").read_bytes())
        found = {"author in the copyright": author in str(info.get("NSHumanReadableCopyright"))}
        expected = {"author in the copyright": True}
    else:  # read from the installed Flatpak: the file must really be in it
        command = ["flatpak", "run", "--user", "--command=cat", FLATPAK_ID]
        shown = run([*command, f"/app/share/metainfo/{METAINFO}"], folder).stdout
        found = {"developer": f"<name>{author}</name>" in shown, "homepage": homepage in shown}
        expected = {"developer": True, "homepage": True}
    print(f"Publisher: {found}")
    if found != expected:
        raise SystemExit(f"The publisher is not set as expected: {found} != {expected}")


def run_or_stop(command: list[str], folder: Path) -> None:
    print("+", " ".join(command), flush=True)
    if subprocess.run(command, cwd=folder, check=False).returncode != 0:
        raise SystemExit(f"Failed: {' '.join(command)}")


def clean_copy() -> Path:
    folder = Path(tempfile.mkdtemp(prefix="parro-installer-"))
    archive = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, capture_output=True, check=True
    )
    subprocess.run(["tar", "-x", "-C", str(folder)], input=archive.stdout, check=True)
    return folder


def checked(result: subprocess.CompletedProcess[str], what: str, expected: str | None) -> None:
    """Exit code 0, and the expected line when the program prints to the terminal."""
    output = (result.stdout or "") + (result.stderr or "")
    print(output.strip())
    if result.returncode != 0:
        raise SystemExit(f"The check failed in {what} (exit {result.returncode}).")
    if expected and expected not in output:
        raise SystemExit(f"The check in {what} did not say {expected!r}.")
    print(f"Check passed: {what}")


def self_check_windows(folder: Path) -> None:
    source = folder / "build" / APP / "windows" / "app" / "src"
    stub = next(p for p in source.glob("*.exe") if not p.name.lower().startswith("python"))
    for option, expected in CHECKS:
        checked(run([str(stub), option], source), f"{stub.name} {option}", expected)


def self_check_macos(folder: Path) -> None:
    bundle = next((folder / "build" / APP / "macos" / "app").glob("*.app"))
    program = next(p for p in (bundle / "Contents" / "MacOS").iterdir() if p.is_file())
    # macOS sends the app's output to its own log, not the terminal: the exit code tells.
    for option, _expected in CHECKS:
        checked(run([str(program), option], folder), f"{bundle.name} {option}", None)


def self_check_flatpak(bundle: Path, folder: Path) -> None:
    # `briefcase build` has installed the app already. Installing a bundle over an installed copy
    # stops with "already installed" (with --or-update too, and with --reinstall on Flatpak 1.14), so
    # the copy goes first; its data (the login) stays. Then the bundle, as people install it.
    quiet = ["-y", "--noninteractive"]
    run(["flatpak", "uninstall", "--user", *quiet, FLATPAK_ID], folder)
    run_or_stop(["flatpak", "install", "--user", *quiet, str(bundle)], folder)
    for option, expected in CHECKS:
        result = run(["flatpak", "run", "--user", FLATPAK_ID, option], folder)
        checked(result, f"{bundle.name} {option}", expected)


def build(target: str) -> Path:
    release, folder = version(), clean_copy()
    print(f"Building {target} {release} in {folder}", flush=True)
    commands = briefcase_commands(target)
    run_or_stop(commands[0], folder)  # create
    if target == "flatpak":
        manifest = folder / "build" / APP / "linux" / "flatpak" / "manifest.yml"
        text = add_metainfo(set_flatpak_branch(manifest.read_text(encoding="utf-8")))
        manifest.write_text(text, encoding="utf-8")
        shutil.copyfile(ROOT / "packaging" / METAINFO, manifest.parent / METAINFO)
        entry = manifest.parent / f"{FLATPAK_ID}.desktop"
        entry.write_text(add_categories(entry.read_text(encoding="utf-8")), encoding="utf-8")
        run_or_stop(FLATPAK_BUILDER, manifest.parent)
    for command in commands[1:]:
        run_or_stop(command, folder)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    result = OUTPUT / installer_name(target, release, cpu())
    if target == "flatpak":
        flatpak_folder = folder / "build" / APP / "linux" / "flatpak"
        bundle = ["flatpak", "build-bundle", "--runtime-repo", FLATHUB]
        run_or_stop([*bundle, "repo", str(result), FLATPAK_ID, FLATPAK_BRANCH], flatpak_folder)
        self_check_flatpak(result, folder)
    else:
        built = next((folder / "dist").glob("*.msi" if target == "windows" else "*.dmg"))
        shutil.copyfile(built, result)
        (self_check_windows if target == "windows" else self_check_macos)(folder)
    check_publisher(target, folder, result)
    print(f"Built {result} ({result.stat().st_size // (1024 * 1024)} MB)")
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", choices=TARGETS)
    build(parser.parse_args(argv).target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
