# Architecture: one core, three front ends

## Contents

1. The layers and why
2. Boundary tests that keep the layers apart
3. Packaging with pyproject.toml
4. The CLI
5. The MCP server
6. Actions that change something
7. Secrets, logs and privacy

## 1. The layers and why

- **Core (`mytool/`), standard library only.** HTTP (`urllib`), auth, token store, cache, the
  API client, and `operations.py`: one function per user-visible action, taking the client and
  plain arguments and returning plain data. Optional heavy libraries (PDF, images) are imported
  lazily and their absence is a normal, reported case.
- **Rendering (`rendering.py`)** turns operation results into text/Markdown/JSON. The CLI and the
  MCP server share it, so their output matches.
- **Front ends** parse input, call one operation, render. They contain no business logic.
- **Desktop app (`mytool_gui/`)** is a separate package behind the `gui` extra. It calls the same
  operations on a worker thread. It never talks to the network itself.

Why: the core is audited once; a fix reaches all front ends; tests run without Qt or a network.

## 2. Boundary tests that keep the layers apart

Write these early; they are cheap and stop drift:

- the core never imports Qt or the GUI package (regex over `mytool/*.py`);
- the GUI never contains network code (regex for `urllib|http.client|requests|socket` over
  `mytool_gui/**.py`). Careful: the regex matches words in comments too ("too many requests"
  failed this test); reword the comment rather than weakening the test;
- `dependencies = []` in pyproject (the core needs nothing);
- a self-check module may hold a transport that *refuses* every request; allow that one file
  explicitly and assert the refusal is in it.

When the GUI needs something network-shaped (for example "did GitHub answer at all?"), add it to
the core (an error subclass such as `GitHubRefused(NetworkError)` with the status) and keep the
GUI code to `except GitHubRefused`.

## 3. Packaging with pyproject.toml

```toml
[project]
name = "mytool"
requires-python = ">=3.10"
dependencies = []
# Briefcase reads authors[0].name as the installers' publisher/manufacturer. No e-mail:
# the MSI would show it to anyone.
authors = [{ name = "your-github-name" }]
license = "MIT"            # SPDX; add AND ... when docs/icons have other licences

[project.optional-dependencies]
attachments = ["pypdf", "pillow"]
# Qt only from 3.12: PySide6 crashes on 3.10/3.11 (see desktop-qt.md).
gui = ['PySide6-Essentials>=6.11; python_version >= "3.12"',
       'truststore>=0.10; python_version >= "3.12"']

[project.scripts]
mytool = "mytool.cli:run"
mytool-mcp = "mytool.mcp_server:run"
mytool-gui = "mytool_gui.app:run"

[project.urls]
# "Homepage" with a capital H is the key Briefcase reads (Windows: the support link).
Homepage = "https://you.github.io/mytool/"
```

- `PySide6-Essentials` instead of `PySide6`: a third of the size, enough for widgets.
- Keep the version in exactly two places (`pyproject.toml`, `mytool/__init__.py`) and test that
  they match; the release script checks the tag against it.
- Exclude tests from the sdist unless their fixtures go with them.
- Users install with `pipx install mytool` or `pipx install "mytool[gui]"`; document
  `--python python3.12` for the GUI when pipx defaults to an older Python.
- An install smoke test in CI: build the wheel, install it into a fresh venv with an empty
  HOME, run each console script.

## 4. The CLI

- argparse, one subcommand per operation; `--format text|markdown|json`.
- Tab completion generated from the argparse parser itself (`mytool completion bash|zsh|fish`);
  it must not read settings or contact the server.
- Errors: one line for the user, exit codes per error class; never a traceback for an expected
  failure.
- The command name used in help and hints comes from one place (`naming.py`), so the same core
  can say `mytool login` or `python3 mytool_cli.py login` depending on how it was started.

## 5. The MCP server

- Hand-written JSON-RPC 2.0 over stdio with the standard library: `initialize`,
  `tools/list`, `tools/call`. stdout carries only protocol messages; logs go to stderr.
- One tool per operation; output equals the CLI's rendering of the same operation.
- **Declare each tool's hints in its own definition** (`readOnlyHint`, `destructiveHint`,
  `idempotentHint`, `openWorldHint`, plus a `title`), not in a loop at import time: scanners
  that read the source (registries, security scores) saw no hints otherwise. Add a test that
  reads the file with `ast` and checks every tool has all four.
- Manual testing without a client: `mytool-mcp tools`, `mytool-mcp call NAME '{json}'`.
- Claude Desktop does not see the shell's PATH: document the full path of the command
  (`which mytool-mcp`), or `uvx --from mytool mytool-mcp`.

## 6. Actions that change something

- Read-only by default. Each write action is a separate operation, behind an explicit switch in
  the MCP server (an environment variable such as `MYTOOL_ALLOW_SEND=1`; the tool does not exist
  otherwise), and behind a preview + **Confirm** in the GUI (Enter must not confirm).
- After a timeout or a server error on a write, say it "may or may not have gone through" and
  offer no retry button.
- Disable a button that starts a request until the answer is in, and run one action per section
  at a time: a quick double click once opened two previews and sent a message twice.
- Login: if the server locks accounts after failed attempts, make one attempt per click, never
  retry automatically, and latch "do not log in by itself" after a rejected password until a
  manual login succeeds.

## 7. Secrets, logs and privacy

- Never log tokens, passwords, cookies or full signed URLs; log the request's label, not its URL.
- Unexpected exceptions in the GUI worker: report only the exception **type** to the user
  ("Something went wrong (PermissionError)"); the text could contain anything. But do not let
  that be the normal path: turn expected OS errors into per-item results (see desktop-qt.md).
- Store only what is needed: e.g. the *path* of a password file (mode 600 checked), never the
  password. Check a remembered password file holds the typed password before remembering it.
- Samples and fixtures use invented data; a privacy scan in CI checks names, addresses and
  signed links in fixtures and the spec are placeholders, and reports places, never values.
