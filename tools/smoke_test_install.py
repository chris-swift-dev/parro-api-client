#!/usr/bin/env python3
"""Build the package, install it into a fresh virtual environment, and run its commands.

Checks what a user gets from `pipx install` / `uv tool install` / `pip install`, on any system:
  * `parro-client --help` names itself `parro-client`;
  * `parro-client-mcp tools` lists every MCP tool;
  * `parro-client privacy` without a login exits 3 and says to run `parro-client login`;
  * the MCP server answers `initialize` over stdio with one "\\n"-ended line;
  * `parro-client-gui` without the `gui` extra says what to install;
  * nothing is written to the (empty, private) home folder.
Never contacts Parro: there is no login, so every command stops before the network.

Standard library only (pip downloads setuptools to build).  Usage:
    python3 tools/smoke_test_install.py [--wheel FILE]     (default: build one from this folder)
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_TOOLS = 20


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--wheel", type=Path, help="install this wheel instead of building one")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="parro-smoke-") as temporary:
        work = Path(temporary)
        wheel = args.wheel or build_wheel(work / "wheel")
        environment_dir = work / "venv"
        venv.EnvBuilder(with_pip=True).create(environment_dir)
        scripts = environment_dir / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        quiet_pip = [str(python), "-m", "pip", "--disable-pip-version-check", "-q"]
        subprocess.run([*quiet_pip, "install", str(wheel)], check=True)
        home = work / "home"
        home.mkdir()
        problems = check_commands(scripts, private_environment(home, scripts), work)
        if any(home.rglob("*")):
            problems.append("files were written to the home folder")
    for problem in problems:
        print(f"FAIL: {problem}")
    print(f"smoke test: {'OK' if not problems else f'{len(problems)} problem(s)'} ({wheel.name})")
    return 1 if problems else 0


def build_wheel(target: Path) -> Path:
    command = [sys.executable, "-m", "pip", "--disable-pip-version-check", "-q", "wheel"]
    subprocess.run([*command, str(ROOT), "--no-deps", "-w", str(target)], check=True)
    (wheel,) = target.glob("*.whl")
    return wheel


def private_environment(home: Path, scripts: Path) -> dict[str, str]:
    """This process's environment (Windows needs SYSTEMROOT), with an empty home and no PARRO_*."""
    environment = {k: v for k, v in os.environ.items() if not k.startswith("PARRO_")}
    environment.update(HOME=str(home), USERPROFILE=str(home), PYTHONIOENCODING="")
    environment["PATH"] = str(scripts) + os.pathsep + environment.get("PATH", "")
    return environment


def command_path(scripts: Path, name: str) -> str:
    return str(scripts / (f"{name}.exe" if os.name == "nt" else name))


def check_commands(scripts: Path, environment: dict[str, str], work: Path) -> list[str]:
    def run(
        name: str, *arguments: str, stdin: bytes | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [command_path(scripts, name), *arguments], input=stdin, capture_output=True,
            cwd=work, env=environment, timeout=120, check=False,
        )  # fmt: skip

    problems = []
    help_text = run("parro-client", "--help").stdout.decode("utf-8")
    if not help_text.startswith("usage: parro-client "):
        problems.append(f"parro-client --help: unexpected start {help_text[:40]!r}")
    lines = run("parro-client-mcp", "tools").stdout.decode("utf-8").splitlines()
    tools = [line.split()[0] for line in lines if line.strip()]  # "name  description"
    if len(tools) != EXPECTED_TOOLS or "parro_privacy" not in tools:
        problems.append(f"parro-client-mcp tools: {len(tools)} tools, expected {EXPECTED_TOOLS}")
    privacy = run("parro-client", "privacy")
    if privacy.returncode != 3 or b"`parro-client login`" not in privacy.stderr:
        problems.append(f"parro-client privacy without login: exit {privacy.returncode}")
    request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    answer = run("parro-client-mcp", stdin=(json.dumps(request) + "\n").encode()).stdout
    if not answer.endswith(b"}\n") or b"\r" in answer:
        problems.append(f"parro-client-mcp: answer not one LF-ended line: {answer[-20:]!r}")
    elif json.loads(answer)["result"]["serverInfo"]["name"] != "parro":
        problems.append("parro-client-mcp: unexpected initialize answer")
    desktop = run("parro-client-gui")
    # On Python before 3.12 it says that first; either way it names the extra to install.
    if desktop.returncode != 2 or b"parro-api-client[gui]" not in desktop.stderr:
        problems.append(f"parro-client-gui without Qt: exit {desktop.returncode}")
    packaged = zipfile.ZipFile(wheel_of(work)).namelist() if wheel_of(work) else []
    if packaged and "parro_gui/icon_files/house.svg" not in packaged:
        problems.append("the desktop app's icons are not in the wheel")
    return problems


def wheel_of(work: Path) -> Path | None:
    return next(iter(sorted((work / "wheel").glob("*.whl"))), None)


if __name__ == "__main__":
    sys.exit(main())
