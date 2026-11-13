# Testing, the failures CI found, and live checks

## Contents

1. Test layout and fakes
2. Tests that keep promises
3. Failures that only showed in CI, and how to reproduce them locally
4. Proving a test catches the bug
5. Live checks with the user

## 1. Test layout and fakes

- No network in tests. A fake server (`tests/fakes.py`) answers the API and the login from
  recorded, sanitized samples; the client takes a `transport` argument, so tests inject it.
- Fake tokens with an expiry in the future, and temp folders, through environment variables
  (`MYTOOL_TOKEN_FILE`, `MYTOOL_DATA_DIR`); clear every `MYTOOL_*` variable at the start of a
  fixture so the developer's own settings never leak in.
- Fix "now" with a fixture when output depends on dates.
- Writes: the fake records requests; assert `api.writes() == []` wherever nothing may change.
- Tools in `tools/` are loaded with `importlib.util.spec_from_file_location` in tests, so they
  stay plain scripts.

## 2. Tests that keep promises

Promises worth a test each, because they broke or nearly broke:

- versions equal in pyproject and `__init__`; Briefcase pins equal `requirements-gui.txt`;
- the core imports no Qt; the GUI has no network code; the core has no dependencies;
- every folder the app writes to is persisted in the Flatpak sandbox;
- metainfo matches pyproject (id, developer, homepage, licence); no e-mail address published;
- Flatpak manifest patches (branch, metainfo install, categories) and that a changed manifest
  stops the build instead of being silently skipped;
- the MSI property query passes its arguments to a script file (not `-Command`);
- every MCP tool declares its hints in its own definition (read with `ast`);
- every button that starts a request survives a double click;
- every section fits at the minimum window size, also with 1.3x larger text;
- the update check builds its link from the version, never from the answer;
- doc links point to existing files (these tests see only **tracked** files: `git add -N` new
  files before running them);
- secrets and messages never reach logs.

## 3. Failures that only showed in CI, and how to reproduce them locally

| Failure | Cause | Fix | Reproduce locally |
| --- | --- | --- | --- |
| `ModuleNotFoundError: PySide6` in "Tests and install" | a test used the `application` fixture; those jobs have no Qt | `pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)` inside the session fixture | scratch venv with only `pytest`, run the suite |
| Buttons "squeezed" at minimum size on Windows only | wider text; explicit minimum beat the layout | minimum = max(constant, `minimumSizeHint()`) | fixture with the app font ×1.3 |
| `app.run()` returned 2 on Python 3.10 | the 3.12 gate stopped before what the test checked | the test sets `app.MINIMUM_PYTHON = (3, 0)` | a pytest plugin (`-p`) that raises the gate to `(3, 99)` for the whole run |
| macOS installer `--check-connection` exit 1 | GitHub answered non-200 (rate limit on shared runners) | count any HTTP answer as a connection | a fake transport answering 403 |
| Publisher check: MSI query empty | `powershell -Command` ignored the arguments | `.ps1` + `-File` | unit test that the command uses `-File` and the script reads `$args` |
| Publisher check: macOS copyright missing | Briefcase's template has none | `macOS.info` table in pyproject | read the template from Briefcase's repository at the pinned version |
| Flatpak compose `icon-write-error` | rofiles-fuse | `--disable-rofiles-fuse` | build locally with flatpak-builder |
| Boundary test failed on a comment | regex matched "requests" in prose | reword the comment | run the boundary test |

General lesson: the matrix (3 systems × 2 Pythons × with/without extras) finds what one machine
cannot. Before pushing, at least run the suite once in a venv without the optional extras.

A scratch venv without extras:

```bash
python3 -m venv "$SCRATCH/noqt" && "$SCRATCH/noqt/bin/pip" install -q pytest
"$SCRATCH/noqt/bin/python" -m pytest -q
```

Simulating an older Python without installing one:

```bash
printf 'import mytool_gui.app as a\na.MINIMUM_PYTHON = (3, 99)\n' > "$SCRATCH/plug/old_python.py"
PYTHONPATH="$SCRATCH/plug" python -m pytest -q -p old_python
```

## 4. Proving a test catches the bug

For each bug fix, run the new test against the old code once and see it fail, then restore:

```bash
cp mytool/attachments.py "$SCRATCH/fixed.py"
git show HEAD:mytool/attachments.py > mytool/attachments.py
python -m pytest -q tests/test_attachments.py   # expect the new test to fail
cp "$SCRATCH/fixed.py" mytool/attachments.py
```

Make failures portable: e.g. a folder that cannot be written on *every* system is one below a
regular file (`tmp/a-file/out`), because `chmod 555` does not stop writes on Windows or as root.

## 5. Live checks with the user

The live checks found what no test did: the dialog deadlock, the lost tokens in the sandbox, the
small Flatpak font, the SSL failure, the stopped save, the two Flatpak copies.

How to run one:

- A short numbered list for the user, in order, with what they should see. Steps that cost
  something come first or last and are marked (a password check, logging out).
- **The user types passwords and makes real changes**; at most one password check per run when
  the server locks accounts; real writes only on items the user picks and approves.
- Before saying a fix failed, check what is installed: an old copy may be running (two Flatpak
  installs; a stale build). `flatpak info`, install dates, and grepping the installed files for
  the fix settle it in a minute.
- Prepare harmless failure conditions yourself (a read-only folder for "save fails"), and remove
  them afterwards with the user's OK.
- Record each check in `LIVE-CHECKS.md`: date, system, what was installed (commit), the checks as
  a table with OK / **Found** / **Fixed** / **Retested**, and a "not checked live yet" row.
  Personal data stays out.
- Platforms the user cannot reach easily (rebooting into macOS) can wait; say what CI covers
  instead.
