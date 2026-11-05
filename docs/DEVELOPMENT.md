# Development

Back to the [README](../README.md).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest            # no network: fake IdP and API
.venv/bin/ruff check . && .venv/bin/ruff format --check parro tests parro_cli.py parro_mcp.py
.venv/bin/mypy
```

The tests include login-safety checks (one credential POST per login, none while the latch is set,
none after a 401, no secrets in logs). They run on an invented family and school in
`tests/fixtures/api/`, written by `tests/fixtures/make_api_fixtures.py` and checked against the
public spec. `tests/snapshots/` holds the expected markdown of every view; after an intended layout
change, run `UPDATE_SNAPSHOTS=1 .venv/bin/pytest tests/test_rendering.py` and review the diff.
The checks that need git-ignored files (the real `samples/` against the full spec, and the
comparison with the original server in `legacy/`) skip without them, as in CI.

| Path | Purpose |
| --- | --- |
| `tests/` | pytest suite; `tests/fakes.py` has the fake IdP and API |
| `tools/build_spec.py`, `tools/validate_spec.py`, `tools/build_site.sh` | spec generator, validator, Swagger UI site |
| `tools/build_release.py` | builds the release archives, checksums and notes |
| `tools/make_readme_images.py`, `tools/swagger_screenshots.py` | the README pictures |
| `.github/workflows/ci.yml` | lint, types and tests on Python 3.14 and 3.10 |
| `.github/workflows/pages.yml` | validates the spec and deploys Swagger UI to GitHub Pages |
| `.github/workflows/release.yml` | on a `v*` tag: checks, archives, draft GitHub release |

## The README pictures

The terminal pictures in the README (`docs/images/terminal-*.svg`, light and dark) are drawn from
`tests/snapshots/` by `tools/make_readme_images.py`; `tests/test_readme_images.py` fails when they
are out of date. After a snapshot update:

```bash
python3 tools/make_readme_images.py
```

The Swagger UI screenshots (`docs/images/swagger-*.png`) need Firefox and the network, so they are
taken by hand after a change to the spec: `python3 tools/make_readme_images.py --swagger`, then look
at the result. Pictures only ever show invented data or documentation.

## Making a release

1. Set the version in `parro/__init__.py` and `pyproject.toml`, and add a `## [x.y.z] - date`
   section to `CHANGELOG.md` (a test checks that all three agree).
2. Optionally check the archives locally: `python3 tools/build_release.py --tag vX.Y.Z` (output in
   `dist/`).
3. Tag and push: `git tag -a vX.Y.Z -m "parro-api-client X.Y.Z" && git push origin vX.Y.Z`.
4. The release workflow creates a **draft** release with the archives, `SHA256SUMS` and the changelog
   section as notes. Review it on GitHub and press *Publish*.
