---
name: python-tool-developer
description: How to build and ship a cross-platform Python tool made of a standard-library core with a CLI, an optional MCP server, and an optional PySide6 (Qt) desktop app with installers for Windows (MSI), macOS (DMG) and Linux (Flatpak) built by Briefcase, plus CI, GitHub releases and a GitHub Pages landing page. Use this skill whenever the user starts, plans, extends or releases such a tool, or works on any single piece of it - a Python CLI that should also become an MCP server or a desktop app, a PySide6 window (layout, theming, dark mode, threads, minimum size, long texts), Briefcase or Flatpak packaging, SSL certificate errors in a bundled Python, installer publisher names, a GitHub Actions matrix for installers, a release workflow, or a project landing page next to Swagger UI - even if they do not mention this skill or name all the parts.
---

# Building a cross-platform Python tool: core, CLI, MCP server, desktop app

This skill holds what was learned building one such tool from a first CLI to signed-off
installers on three systems. Most of it is about the places where things went wrong in ways that
tests on one machine did not show. Use it to plan the work, to choose defaults, and to check a
change before calling it done.

## The shape that works

```
mytool/            the core: standard library only; every feature lives here
  operations.py    one function per user-visible action, used by every front end
  cli.py           argparse front end      -> console script `mytool`
  mcp_server.py    JSON-RPC over stdio     -> console script `mytool-mcp`
mytool_gui/        optional PySide6 app    -> console script `mytool-gui` (extra: `gui`)
tools/             build scripts: release archives, installers, site (standard library)
packaging/         icons, AppStream metainfo
site/              landing page template; Swagger UI goes in api/
tests/             pytest; Qt tests skip without Qt
```

Why this shape: the core is what users trust (it logs in, it changes things), so it stays small,
dependency-free and tested once; the front ends only translate. A CLI command, an MCP tool and a
button then give the same answer, and a bug is fixed once. Details, including the boundary tests
that keep it this way: [references/architecture.md](references/architecture.md).

## How to run the project

Work in **plans with phases**: a short Markdown plan per release (goal, decisions with a
recommendation each, phases that each end in a check), approved by the user before code. Each
phase ends green (pytest, ruff, mypy) and is committed only when the user asks. A release ends
with a **live check** with the user on real systems, recorded in a `LIVE-CHECKS.md`; the live
checks found every serious bug that tests could not (see the table below).

Typical order for a new tool:

1. Core + CLI, with a fake server in the tests (no network in tests).
2. Packaging: `pyproject.toml`, console scripts, `pipx install`, an install smoke test in CI.
3. MCP server on the same core (tools that change something are off unless switched on).
4. Desktop app on the same core, behind the `gui` extra.
5. Installers with Briefcase, built and checked in CI on every system.
6. Release workflow (draft release with archives, wheel, installers, checksums, attestations).
7. Landing page on GitHub Pages.

## Rules that prevent the bugs we actually had

Each line is a real failure. Read the linked reference before working in that area.

| Area | Rule | Why |
| --- | --- | --- |
| Python versions | The Qt app needs **Python 3.12+**; the core and CLI can stay on 3.10+. Gate the app at start with a clear message, and request Qt only for 3.12+ in the extra. | PySide6 signals crash the interpreter on 3.10/3.11 (refcounts of None/True/False). |
| macOS version | Set Briefcase `min_os_version` to what the PySide6 wheels need (6.12: **macOS 14**). | The macOS build failed with older minimums. |
| Threads | One worker thread for network calls; connect signals to **bound methods**, never lambdas, when the slot must run on the window's thread. | Lambda slots ran on the worker thread. |
| Modal dialogs | Never open a second modal dialog while another may be open; wait for a "quiet moment". | The update question and the login dialog blocked each other; the app had to be killed. |
| Messages | A message area takes at most two lines, with *Details…* and a close button. | Twenty failed files grew a label until it pushed everything off the window. |
| Minimum size | Minimum = max(your constant, `minimumSizeHint()`). | An explicit minimum wins over the layout; on Windows' wider text buttons were squeezed. |
| Long names | Elide in the middle with a tooltip (`QSizePolicy.Ignored`). | A long file name pushed its buttons out of the row. |
| Long details | Text on top, an action row that never scrolls, a scroll area below, a draggable splitter between them. | Items with many attachments pushed *Mark as read* out of the window. |
| Theming | Fusion style, one palette per scheme, follow `colorSchemeChanged`; colour spin/combo/check boxes via the palette only. | Stylesheet colours on those controls removed their arrows and tick marks. |
| OS errors | Turn `OSError` from writing files into a per-item failure, not a crash of the whole run. | Saving into a read-only folder stopped at the first file with "PermissionError". |
| HTTPS | Inject `truststore` at app start in the bundled app. | The installers' own Python had no root certificates: CERTIFICATE_VERIFY_FAILED on macOS and Windows. |
| Flatpak font | Read the desktop font from the settings portal. | Inside the sandbox Qt fell back to a smaller "Sans Serif 9". |
| Flatpak data | Keep (`persist=`) every folder the app writes to, and test that list. | Tokens were written to an unkept folder: the login was lost at every close. |
| Flatpak updates | Document user vs system installs; one copy per ID. | The software centre installed system-wide next to a `--user` copy, and the menu kept opening the old one. |
| Publisher | `authors[0].name` and `urls["Homepage"]` (capital H) in pyproject; set macOS copyright yourself; add AppStream metainfo. | Windows showed "Unknown publisher"; Briefcase's macOS template has no author; its Flatpak has no metainfo. |
| CI checks | Every built installer runs `--self-check` (offline) and `--check-connection` (one real HTTPS request), and counts **any** HTTP answer as a working connection. | A 403 rate limit on shared macOS runners failed an otherwise good build. |
| Tests | Qt tests skip without Qt; start-up tests bypass the version gate; run the suite once without optional extras. | CI jobs without Qt and on Python 3.10 failed only on the release PR. |

## Where the details are

- [references/architecture.md](references/architecture.md) - core/front-end split, packaging,
  extras, MCP server, safety for actions that change things, secrets and privacy.
- [references/desktop-qt.md](references/desktop-qt.md) - PySide6 versions, theming (light/dark,
  Fusion, palette), the worker thread, layout rules (splitters, scroll areas, action rows,
  elision, minimum size), dialogs, the update check, Qt testing.
- [references/installers.md](references/installers.md) - Briefcase configuration per system,
  Flatpak (IDs, runtime, branch, sandbox, metainfo, fonts, install modes), MSI and DMG publisher,
  macOS Gatekeeper, certificates, the self-check and connection check.
- [references/ci-release-pages.md](references/ci-release-pages.md) - GitHub Actions matrix,
  installer workflow, release workflow, PyPI, and the landing page with Swagger UI in `api/`.
- [references/testing-and-checks.md](references/testing-and-checks.md) - test layout, fakes,
  the failures CI found and how to reproduce them locally, and how to run a live check.

## Before calling a change done

- pytest, ruff (check and format), mypy pass; and the suite passes **without** the optional
  extras installed (make a scratch venv with only pytest) when you touched tests or imports.
- For the desktop app: the change works at the minimum window size, in light and dark, and with
  larger text (a test with a 1.3x font catches what Windows shows).
- For packaging: the installers build in CI on all runners, each starts with `--self-check`.
- Anything visible to users is in the changelog's unreleased section, written for users.
- Docs that link to files: a link to `blob/main/...` 404s until the file is merged; that is
  expected on a branch, not a bug.
