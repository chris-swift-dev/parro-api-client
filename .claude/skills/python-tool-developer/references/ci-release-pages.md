# CI, releases and the landing page

## Contents

1. Workflows at a glance
2. ci.yml: checks on every pull request
3. installers.yml: four installers
4. release.yml: from a tag to a draft release
5. publish.yml: PyPI after the release is published
6. The landing page on GitHub Pages
7. Waiting for and reading CI

## 1. Workflows at a glance

| Workflow | Runs on | Does |
| --- | --- | --- |
| `ci.yml` | pull requests, push to main, `workflow_call` | lint, types, tests on 3 OS × 2 Pythons, Qt tests, install smoke test |
| `installers.yml` | branch pushes that touch the app or packaging, `workflow_call` | builds and checks MSI, DMG, two Flatpaks |
| `release.yml` | tag `v*` | calls ci + installers, builds archives/wheel/sdist, attests, creates a **draft** release |
| `publish.yml` | release published | uploads wheel+sdist to PyPI (trusted publishing) |
| `pages.yml` | push to main, PRs, release published | validates the spec, builds the site, deploys from main |

The user publishes releases by hand; the workflows only prepare a draft. Most of `ci.yml` runs
only on pull requests and main, so **the first full matrix run of a release branch happens on
the release PR**: expect it to find things (it found nine failing jobs once), and open the PR
early enough to fix them.

## 2. ci.yml: checks on every pull request

- **Lint, types, tests** on one Python (newest): `ruff check`, `ruff format --check`, `mypy`,
  `pytest`, plus project checks (privacy scan, doc links).
- **Tests and install** matrix: `ubuntu-latest`, `windows-latest`, `macos-latest` × oldest and
  newest supported Python, with **only pytest installed**. This proves the core works without the
  optional extras; Qt tests must skip here (see testing-and-checks.md). Then build the wheel,
  install into a fresh venv with an empty home, and run each console script.
- **Desktop app** matrix: the three OS × Python 3.12 and newest, with the `gui` extra,
  `QT_QPA_PLATFORM=offscreen`, `pytest -k test_gui`. Windows renders text wider: layout tests
  that pass on Linux can fail here.
- `fail-fast: false` everywhere: one failing system should not hide another.

## 3. installers.yml: four installers

```yaml
on:
  push:
    branches-ignore: [main]
    paths: ["mytool/**", "mytool_gui/**", "packaging/**", "pyproject.toml",
            "requirements-installers.txt", "tools/build_installer.py",
            ".github/workflows/installers.yml"]
  workflow_dispatch:
  workflow_call:
jobs:
  installer:
    runs-on: ${{ matrix.os }}
    timeout-minutes: 60
    strategy:
      fail-fast: false
      matrix:
        include:
          - { os: windows-latest, target: windows }
          - { os: macos-latest, target: macos }
          - { os: ubuntu-24.04, target: flatpak }
          - { os: ubuntu-24.04-arm, target: flatpak }   # native aarch64 runner
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with: { python-version: "3.14" }
      - name: Flatpak tools
        if: matrix.target == 'flatpak'
        run: |
          sudo apt-get update && sudo apt-get install -y flatpak flatpak-builder
          flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
      - run: pip install -r requirements-installers.txt
      - name: Build, check and keep the installer
        env: { QT_QPA_PLATFORM: offscreen }
        run: python tools/build_installer.py ${{ matrix.target }}
      - uses: actions/upload-artifact@v7
        with:
          name: installer-${{ matrix.target }}-${{ matrix.os }}
          path: dist/installers/*
          if-no-files-found: error
```

A full run takes about 15-20 minutes. Users testing a branch build download the artifacts
(a GitHub login is needed; the zip contains the installer).

## 4. release.yml: from a tag to a draft release

1. `checks: uses: ./.github/workflows/ci.yml` and `installers: uses: ./.github/workflows/installers.yml`.
2. Build wheel and sdist with `SOURCE_DATE_EPOCH` from the commit (reproducible contents).
3. Download the installer artifacts (`pattern: installer-*`, `merge-multiple: true`).
4. `tools/build_release.py --tag "$GITHUB_REF_NAME" --packages --installers`: checks the tag
   equals the version, builds source archives, `SHA256SUMS` over everything, and release notes
   = the changelog section of that version + a "Download the desktop app" table built from the
   shared installer-name function.
5. `actions/attest-build-provenance` over packages and installers (needs `id-token: write`,
   `attestations: write`).
6. `gh release create "$TAG" files... --verify-tag --draft --notes-file dist/release-notes.md`.

Release steps for a version:
- version bump in both places, changelog section dated, plans marked done;
- one PR from the release branch to main; fix CI there; squash-merge;
- annotated tag on the merge commit: `git tag -a vX.Y.Z -m "mytool X.Y.Z" <sha>`, push the tag;
- wait for the draft (about 25 minutes with installers); check the files and notes;
- the user publishes.

The changelog is user-facing (it becomes the release notes): sections Added / Changed / Fixed,
each entry bold lead + what it means for the user; a short summary paragraph per version.

## 5. publish.yml: PyPI after the release is published

On `release: published`: download the wheel and sdist **from the release** (not rebuilt), check
them against the release's `SHA256SUMS`, upload with `pypa/gh-action-pypi-publish` using trusted
publishing (a `pypi` environment, `id-token: write`, no API token). Trial runs against TestPyPI
can only happen once the workflow is on main.

## 6. The landing page on GitHub Pages

A repository has one Pages site but any number of pages. Layout that worked:

| Address | What |
| --- | --- |
| `https://you.github.io/mytool/` | landing page |
| `.../api/` | Swagger UI (moved from the root) |
| `.../api/mytool.openapi.json` and `.../mytool.openapi.json` | the spec (old address kept) |

**Content:** one sentence of what it is, with a picture of the app (invented data) and any
"unofficial / not affiliated" line near the top; a download button per system, the visitor's
system first; cards for desktop app / CLI (`pipx install ...` with a copy button) / MCP (the
`claude mcp add` line); the API section linking to Swagger UI and the JSON; a short safety and
privacy list; footer with licences, source, issues and the disclaimer. Light and dark via
`prefers-color-scheme`, readable at 375 px wide.

**Nothing from other sites:** system fonts, no analytics, no CDN; pictures copied from the
repository. Enforce it with a CSP meta tag the browser checks:

```html
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self';
  style-src 'self'; script-src 'self'; base-uri 'none'; form-action 'none'">
```

(`default-src 'none'` also blocks `fetch`, which is the point; it also blocked a debugging
`fetch` from the browser console, which is how you know it works.)

**Download links that stay right:** installer names contain the version, so fixed links break.
`tools/build_landing.py` (standard library) asks GitHub's API for the latest release at build
time and fills in the buttons. Take only the tag (validate `^v\d+\.\d+\.\d+$`, skip drafts and
pre-releases) and the asset sizes; build every URL from the version and the shared
installer-name function, never from the answer. If any installer is missing (an older release),
all buttons go to the releases page. Use `GITHUB_TOKEN` from the environment for the API call in
Actions, and never print it. Fail the build if a `{{placeholder}}` is left (and keep the
literal `{{` out of template comments, or the check trips on its own comment).

**Rebuilding on release:** a `release: published` event runs on the tag, and the
`github-pages` environment deploys only from main. So `pages.yml` gets a small job for that
event that starts the workflow on main:

```yaml
  follow-release:
    if: github.event_name == 'release'
    runs-on: ubuntu-latest
    permissions: { actions: write }
    steps:
      - run: gh workflow run pages.yml --ref main --repo "$GITHUB_REPOSITORY"
        env: { GH_TOKEN: "${{ github.token }}" }
```

(`GITHUB_TOKEN` may start `workflow_dispatch` runs, unlike other events.) The build job skips
the release event: `if: github.event_name != 'release'`.

**Old links:** Swagger UI deep links (`.../#/Tag/operationId`) shared before the move are
forwarded by a script in `<head>` (not deferred), also on `hashchange`:

```js
function toSwaggerUi() {
  if (window.location.hash.indexOf("#/") === 0) {
    window.location.replace("api/" + window.location.hash);
  }
}
toSwaggerUi();
window.addEventListener("hashchange", toSwaggerUi);
```

**System detection** for the first button: `navigator.userAgentData.platform` or
`navigator.platform`/`userAgent`; phones and tablets get no highlighted button; Linux on
`aarch64|arm64` gets the ARM Flatpak.

**Tests:** every relative link exists in the built site; every absolute link goes to the
project's GitHub; nothing is loaded from elsewhere (src/srcset/link all relative, CSP present);
download names equal the shared function; fallback for no release, old release, draft,
pre-release, odd tags (including an HTML-injection tag); nothing from the API answer except
version and sizes reaches the page; disclaimer present; every `blob/main/...` link names a file
in the repository.

**Preview before it goes live:** build into a scratch folder, serve it locally
(`python3 -m http.server`), look at it wide and at phone width, light and dark, and test the
forwarding with a fresh page load (a hash change on an already-open page does not reload). A
browser cache can show the old CSS; use a fresh folder name rather than fighting the cache.

## 7. Waiting for and reading CI

- After a push, wait in the background (a sleep of the expected duration) instead of polling.
- `api.github.com/repos/OWNER/REPO/commits/SHA/check-runs` lists every check of a commit;
  `actions/jobs/ID` names the failing step and gives the run ID.
- Annotations often say only "exit code 1". The job page
  (`github.com/OWNER/REPO/actions/runs/RUN/job/JOB`) shows the log when signed in; raw log
  downloads need a token.
- macOS installer jobs show no app output (it goes to the system log): add checks that print
  through the build script, and rely on exit codes.
