# Plan 6: install it like a normal command

*Status: planned (2026-11-05); decisions taken as recommended (§5). Nothing implemented yet.*

**Goal:** on Windows, macOS and Linux, one install command, after which the client is a normal
command: `parro-client announcements` instead of `python3 parro_cli.py announcements` from an
unpacked folder. The same for the MCP server, so an MCP configuration needs no path to a script.

---

## 1. Challenging the idea

**What is the actual problem?** Not Python: the client needs nothing but Python 3.10+, which macOS
and Linux mostly have and which Windows installs in a minute. The friction is that there is no
*command*: you have to remember where you unpacked the release, type `python3 parro_cli.py`, and
update by downloading again. That is solved by packaging, not by a binary.

**A Python package with entry points already gives an "executable".** `pipx`, `uv tool` and `pip`
create a real `parro-client.exe` on Windows and a `parro-client` script on macOS and Linux, put it
on the PATH, and update it with one command (`pipx upgrade parro-api-client`). For MCP clients,
`uvx` even runs it without a separate install step.

**Why not a standalone binary (PyInstaller, Nuitka)?**

| | Python package (pipx / uv) | Standalone binary |
| --- | --- | --- |
| Needs Python | yes (3.10+) | no |
| Builds | one wheel for every OS | one per OS and CPU: Windows x64, macOS arm64 + x64, Linux x64 + arm64 |
| Size | ~120 KB | 10–30 MB each (a whole Python inside) |
| First start | normal | macOS: blocked by Gatekeeper unless signed and notarized (Apple Developer, $99/year); Windows: SmartScreen warning, and PyInstaller one-file builds are often flagged by antivirus |
| Trust | readable source, the same files as the tag | an opaque file that handles your Parro password; needs build provenance to be trusted |
| Updates | `pipx upgrade` | download again |
| Optional PDF / photo libraries | `pipx install "parro-api-client[attachments]"` | baked in (bigger) or missing |
| Reproducible, verifiable | yes (what this project does today) | hardly |

For a small, security-sensitive tool whose users run it from a terminal or an AI assistant, the
binary costs far more than it gives. It can be added later if people without Python ask for it.

**Names.** The PyPI name `parro` is taken by another project ("Command-line interface for the Parro
school communication platform", `anneschuth/parro-cli`, v1.1.0), which most likely installs a
command called `parro`. So this client should not use `parro` (a clash) or `parro-cli` (confusing).
`parro-api-client` (the package, free on PyPI) with the commands **`parro-client`** and
**`parro-client-mcp`** is unambiguous.

**What the idea uncovers: the client has never run on Windows or macOS.** CI runs on Linux only.
Known risks:
- Output is switched to UTF-8 only when `parro_cli.py` is run as a script. An installed command
  calls `main()` directly, so on a Windows console the ● 📌 🙋 markers could raise
  `UnicodeEncodeError`.
- File permissions (0700 / 0600) mean little on Windows; privacy there comes from the user
  profile's access rights. The docs should say so instead of promising modes.
- GUI apps on macOS (Claude Desktop) do not see the shell's PATH, so `parro-client-mcp` in an MCP
  configuration may not be found; `uvx` or an absolute path avoids that.

## 2. Recommendation

1. A proper Python package `parro-api-client` with two commands, `parro-client` and
   `parro-client-mcp`. Runtime stays standard library only.
2. Installation with **pipx** or **uv** (both cross-platform, isolated, one-line upgrade):
   ```
   pipx install parro-api-client          # or: uv tool install parro-api-client
   parro-client login --prompt
   parro-client overview
   ```
   MCP, with nothing installed beforehand:
   `{"command": "uvx", "args": ["--from", "parro-api-client", "parro-client-mcp"]}`.
3. Published on **PyPI** from the release workflow with *trusted publishing* (GitHub's OIDC: no
   token stored anywhere). The wheel is also attached to the GitHub release, so
   `pipx install <wheel URL>` works without PyPI.
4. CI on **Windows, macOS and Linux**, including installing the wheel and running both commands.
5. The release archives and `python3 parro_cli.py` keep working for everyone who uses them today.
6. No standalone binaries for now.

## 3. Changes

| Area | Change |
| --- | --- |
| Code layout | Move the CLI and the MCP server into the package: `parro/cli.py`, `parro/mcp_server.py`, each with a `run()` that sets UTF-8 output and exits with `main()`'s code. `parro_cli.py` and `parro_mcp.py` stay as three-line shims, so release archives, existing MCP configs and the tests keep working. |
| `pyproject.toml` | `[build-system]` (setuptools, build time only), `[project.scripts]` `parro-client = "parro.cli:run"`, `parro-client-mcp = "parro.mcp_server:run"`, package data (none needed), classifiers (OS independent, Python 3.10–3.14). |
| Hints and help | The hints (`→ parro_cli.py calendar --details`) use the name the program was started with: `parro-client …` when installed, `parro_cli.py …` from an archive. Snapshots and README pictures show `parro-client`. |
| Windows | UTF-8 in `run()`; permission wording in the docs; check `getpass`, paths (`Path.home()`), and the `.ics` / archive writes (line endings, file names with `:`). |
| CI | A matrix of ubuntu, windows and macos × Python 3.10 and 3.14: tests, build the wheel, install it into a fresh venv, run `parro-client --help`, `parro-client-mcp tools` (19), and a fake-API command. |
| Release | Build sdist + wheel with `python -m build`; attach them to the release with their checksums in `SHA256SUMS`; a separate `pypi` job (GitHub environment `pypi`, trusted publishing) uploads them after you publish the release. |
| Docs | README Quick start (pipx / uv), MCP configuration (uvx, or `parro-client-mcp` with an absolute path for Claude Desktop), DEPLOY.md (Docker: `pip install` the wheel), CHANGELOG 0.5.0. |

## 4. Phases

| # | Phase | Done when |
| --- | --- | --- |
| 1 | Package layout and entry points; shims; UTF-8 in `run()` | `pip install .` in a fresh venv gives working `parro-client` and `parro-client-mcp`; all tests pass unchanged |
| 2 | Program name in hints; snapshots and pictures | hints say `parro-client …` when installed |
| 3 | CI on Windows and macOS (tests + wheel install + smoke test); fix what breaks | green on all three systems |
| 4 | Release workflow: wheel + sdist on the GitHub release; PyPI job with trusted publishing | a test tag (e.g. `v0.5.0rc1`) on TestPyPI installs with `pipx` |
| 5 | Docs: Quick start, MCP setup, DEPLOY.md, CHANGELOG | README pictures and links checked |
| 6 | Install check with you on your machine: `pipx install` from the wheel, `parro-client status`, the MCP server through the new command | works without a password check (existing tokens) |
| 7 | Release **0.5.0** and the first PyPI publication | `pipx install parro-api-client` works for anyone |

**What you need to do (once):** create the project on PyPI (and TestPyPI) and add this repository
as a *trusted publisher*, and add a `pypi` environment in the repository settings (optionally with
your approval required). Publishing to PyPI makes the package public and permanent under that
name; versions can be yanked but not reused.

## 5. Decisions needed

1. **Where to publish:** PyPI + GitHub release (*recommended*), or only the wheel on the GitHub
   release (`pipx install <URL>`; no PyPI account, but no `uvx` by name and no short install line).
2. **Command names:** `parro-client` and `parro-client-mcp` (*recommended*), or another pair. Not
   `parro` or `parro-cli` (taken / confusing).
3. **Standalone binaries:** not now (*recommended*), or later for people without Python.
4. **Code layout:** move the CLI and server into the package with shims (*recommended*), or keep
   the top-level modules and list them as `py-modules` (less change, but an odd package layout).
