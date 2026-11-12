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
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "dist" / "installers"
APP = "parro-gui"
FLATPAK_ID = "io.github.chrisswiftdev.parro-gui"
FLATPAK_BRANCH = "stable"  # not the version: a newer bundle then replaces the older one
FLATHUB = "https://flathub.org/repo/flathub.flatpakrepo"
SELF_CHECK_OK = "self-check: ok"
TARGETS = ("windows", "macos", "flatpak")


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
    """create, build, and (not for the Flatpak, see set_flatpak_branch) package."""
    platform_args = {
        "windows": ["windows", "app"],
        "macos": ["macOS", "app"],
        "flatpak": ["linux", "flatpak"],
    }[target]
    commands = [["create", *platform_args], ["build", *platform_args]]
    if target == "windows":
        commands.append(["package", *platform_args, "-p", "msi", "--adhoc-sign"])
    elif target == "macos":
        commands.append(["package", *platform_args, "-p", "dmg", "--adhoc-sign"])
    return [[sys.executable, "-m", "briefcase", *command, "--no-input"] for command in commands]


def set_flatpak_branch(manifest: str) -> str:
    """Briefcase writes the version as the Flatpak branch; every release would then install next
    to the previous one. One branch for all versions makes a newer bundle replace the older."""
    changed, count = re.subn(
        r"^default-branch: .*$", f"default-branch: {FLATPAK_BRANCH}", manifest, flags=re.MULTILINE
    )
    if count != 1:
        raise SystemExit("The Flatpak manifest has no default-branch line; Briefcase changed?")
    return changed


def run(command: list[str], folder: Path) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command), flush=True)
    return subprocess.run(command, cwd=folder, text=True, capture_output=True, check=False)


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


def checked(result: subprocess.CompletedProcess[str], what: str, need_text: bool) -> None:
    output = (result.stdout or "") + (result.stderr or "")
    print(output.strip())
    if result.returncode != 0:
        raise SystemExit(f"The self-check failed in {what} (exit {result.returncode}).")
    if need_text and SELF_CHECK_OK not in output:
        raise SystemExit(f"The self-check in {what} did not say {SELF_CHECK_OK!r}.")
    print(f"Self-check passed: {what}")


def self_check_windows(folder: Path) -> None:
    source = folder / "build" / APP / "windows" / "app" / "src"
    stub = next(p for p in source.glob("*.exe") if not p.name.lower().startswith("python"))
    # The app's own program has no console, so only its exit code tells; the bundled Python
    # with the same files shows what it found.
    checked(run([str(stub), "--self-check"], source), stub.name, need_text=False)
    python = source / "python.exe"
    if python.exists():
        checked(run([str(python), "-m", "parro_gui", "--self-check"], source), "python.exe", True)


def self_check_macos(folder: Path) -> None:
    bundle = next((folder / "build" / APP / "macos" / "app").glob("*.app"))
    program = next(p for p in (bundle / "Contents" / "MacOS").iterdir() if p.is_file())
    checked(run([str(program), "--self-check"], folder), bundle.name, need_text=False)


def self_check_flatpak(bundle: Path, folder: Path) -> None:
    # `briefcase build` has installed the app already. Installing a bundle over an installed copy
    # stops with "already installed" (with --or-update too, and with --reinstall on Flatpak 1.14), so
    # the copy goes first; its data (the login) stays. Then the bundle, as people install it.
    quiet = ["-y", "--noninteractive"]
    run(["flatpak", "uninstall", "--user", *quiet, FLATPAK_ID], folder)
    run_or_stop(["flatpak", "install", "--user", *quiet, str(bundle)], folder)
    result = run(["flatpak", "run", "--user", FLATPAK_ID, "--self-check"], folder)
    checked(result, bundle.name, need_text=True)


def build(target: str) -> Path:
    release, folder = version(), clean_copy()
    print(f"Building {target} {release} in {folder}", flush=True)
    commands = briefcase_commands(target)
    run_or_stop(commands[0], folder)  # create
    if target == "flatpak":
        manifest = folder / "build" / APP / "linux" / "flatpak" / "manifest.yml"
        text = set_flatpak_branch(manifest.read_text(encoding="utf-8"))
        manifest.write_text(text, encoding="utf-8")
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
    print(f"Built {result} ({result.stat().st_size // (1024 * 1024)} MB)")
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", choices=TARGETS)
    build(parser.parse_args(argv).target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
