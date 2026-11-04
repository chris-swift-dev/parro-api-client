# Plan 2 — Parro API client in Python (standalone CLI + MCP server)

> **Status (2026-11-04): implemented, phases 0–7 done.** 219 tests, live check passed with one password
> check (results in the README). Prepared for going public as release 0.1.0: code under MIT
> (`LICENSE-CODE`), spec and docs under CC BY 4.0, `.gitignore` TEMPORARY block removed.

*Replaces the Swift plan (archived in `docs/archive/PLAN-swift-client.md`).*

**Deliverable:** a readable, stdlib-only Python package `parro/` with two thin entry points.
`parro_cli.py` is a standalone command-line API client, and `parro_mcp.py` is the MCP server, a drop-in
replacement for today's file with the same tool names and the same env vars.
**Contract:** `openapi/parro.openapi.json` (Plan 1). The client follows the spec, and the tests use the same `samples/`.

**Decisions taken**
1. Python, not Swift: it runs anywhere Linux runs, with no extra crypto or zip work.
2. Usable both as a standalone API client and as an MCP server (§1).
3. Written for a reader who doesn't know Python well: self-explanatory names, comments, docstrings (§2).
4. The login method can be chosen, including the **login form only**, so there's no needless password-grant attempt (§3).
5. Credits to [fobatai/parro-mcp](https://github.com/fobatai/parro-mcp) (§9).

---

## 0. Before starting: two things to settle

**a) The repo is public now. DONE (2026-11-04):** the `TEMPORARY` block in `.gitignore` is removed, so the
client code is published with the next push.
Do it only after (b) is settled, or develop on a branch you don't push. Until then the client lives
only on your disk; CI ignores it.

**b) Licensing of the original: DECIDED, independent implementation.** Today's `parro_mcp.py` is (based on)
**fobatai/parro-mcp**, whose repository states **no license** ("all rights reserved"). So the new code is written
**independently**, from the OpenAPI spec (Plan 1), this plan and the findings in §4. Rules for the implementation session:
- **Don't copy or paraphrase code** from `parro_mcp.py`. No copied functions, regexes, docstrings or comments.
  Structure, names and wording are the new code's own (§2 makes that natural).
- **The original may only be *run* or *read for behaviour*, and only to check for problems:** does the new client
  answer the same way, did we miss an edge case? When a check finds a gap, write the fix from the spec or the observed
  API behaviour, and add the fact to the spec or §4 if it's missing there.
- **Facts about the API are not code** (endpoints, headers, field names, form field names, the token endpoint quirk),
  so using them is fine. The spec documents them.
- **The original stays local** (`legacy/`, ignored) and is never committed.
(Not legal advice; this is the practical compromise you chose instead of asking fobatai.)

---

## 1. One script or two? → One shared core, two thin entry points

Two **independent** scripts would mean two copies of the login and lockout logic. That's the most
dangerous part of the code, and the copies would drift apart. One script with both modes keeps
everything in a 1,500+ line file, which is the opposite of readable. So:

```
parro/                         # the library: everything that talks to Parro lives here
  __init__.py                  # exports ParroClient and the error classes
  settings.py                  # Settings dataclass: reads PARRO_* env vars once, CLI flags override them
  errors.py                    # ParroError and subclasses (NotLoggedIn, LoginHalted, ApiError, …)
  http.py                      # send_http_request(): one place for urllib, timeouts, redirects, cookies
  pkce.py                      # create_pkce_pair(): verifier + S256 challenge (RFC 7636)
  token_store.py               # TokenStore: load/save tokens.json, the "login halted" flag, file mode 0600
  login_methods.py             # login_with_login_form(), login_with_password_grant(), exchange_authorization_code(),
                               # refresh_access_token(), revoke_tokens(): one function per OAuth step
  authenticator.py             # Authenticator.get_access_token(): cached → refresh → login (by chosen method)
  api_client.py                # ParroClient: low-level get() + one method per endpoint (get_account, list_groups, …)
  geon.py                      # geon helpers: strip_geon_metadata(), get_object_id(), get_collection_items(), …
  attachments.py               # find_attachments(), pick_source_entry(), download_attachment(), extract_text()
  summaries.py                 # turn raw payloads into the compact dicts both CLI and MCP print
parro_cli.py                   # standalone client: argparse subcommands, prints JSON
parro_mcp.py                   # MCP server over stdio: tool list + JSON-RPC loop, calls ParroClient
tests/                         # pytest, uses samples/ as fixtures
```

- **`parro_mcp.py` keeps its name and location**, so `claude mcp add … parro_mcp.py` keeps working. It
  needs the `parro/` folder next to it. **The Docker image (Dokploy) must copy `parro/` too.** The
  Dockerfile isn't in this folder, so check it during phase 6.
- **Both entry points call the same `ParroClient` and `summaries`**, so CLI output and MCP tool output are
  identical JSON.
- **The core stays stdlib only.** PyMuPDF / pypdf / Pillow stay optional, used only for attachment text and images.
- **Python 3.10+.**

## 2. Readability rules

| Rule | Example |
| --- | --- |
| Names say what a thing *is* or *does*, no abbreviations | `_b64url` → `base64url_without_padding`, `_self_id` → `get_object_id`, `slim` → `strip_geon_metadata`, `_total` → `parse_total_from_content_range`, `_guard_lockout` → `refuse_if_login_halted`, `t_announcements` → `list_announcements` |
| No hidden global state | the `_state` dict becomes attributes of `TokenStore` / `Authenticator` / `ParroClient` instances |
| Type hints on every function | `def list_events(self, group_id: int, event_type: EventType, limit: int = 20) -> list[dict]:` |
| Small data classes instead of loose dicts/tuples | `TokenSet`, `HttpResponse(status, headers, body, final_url)`, `Settings`, `AttachmentFile` |
| Named constants, with the reason next to them | `ANNOUNCEMENT_DTYPE = "event.RAnnouncementEventPrimer"  # RAnnouncementEvent answers 401, see spec` |
| Every module starts with a docstring: what it's for, what it must never do | e.g. `token_store.py`: "never deletes the refresh token on a 401" |
| Comments explain *why*, mainly for API quirks, and point to the spec | `# Token endpoint wants query params + empty body (spec: POST /oauth2/token)` |
| One function, one job, max ~40 lines | the 120-line form login becomes `fetch_login_page()`, `find_login_form_action()`, `submit_login_form()`, `extract_code_from_redirect()` |
| Errors are specific classes with helpful messages | `LoginHalted("The last login was rejected: …. Fix the password, then run: parro_cli.py login")` |
| `logging` instead of `print` to stderr | `log.info("refreshing access token")`. Tokens and passwords are never logged (a test checks this) |
| Readability tooling (dev only) | `ruff` (lint + format) and `mypy` |

A short `docs/CODE-TOUR.md` explains the flow of one request through the modules, for reading the code for the first time.

## 3. Choosing the login method

New setting **`PARRO_LOGIN_METHOD`** (CLI: `--login-method`; MCP: optional `method` argument on `parro_login`):

| Value | What happens | Password checks per login |
| --- | --- | --- |
| `login-form` (**default, decided**) | GET authorize (PKCE) → POST the ParnasSys login form → code → token exchange. Exactly what a browser does | **1** |
| `password-grant` | OAuth2 password grant only, no fallback | 1 |
| `auto` | today's behaviour: password grant, on `invalid_grant` the form once | up to **2** |

- **Default `login-form`.** Your account answers `invalid_grant` to the password grant anyway, so `auto` would waste an
  attempt on every login. Also, a broken form layout fails *before* the password is sent (no form found →
  clear error, no attempt spent).
- **The lockout latch is kept for all methods.** After a rejected password the `login_halted` flag is saved in the token file,
  and every automatic login refuses until an explicit `login` (CLI) / `parro_login` (MCP). That explicit call clears the flag and spends
  exactly **one** attempt with the chosen method.
- **The browser copy-paste flow stays**: `login-url` + `login-finish <redirect-url>`.
- **Credentials:** `PARRO_USERNAME` + `PARRO_PASSWORD_FILE` (preferred) or `PARRO_PASSWORD`, as today. The CLI can also
  prompt (`login --prompt`, hidden input via `getpass`, nothing stored).
- **After login:** with scope `openid offline_access`, later runs only **refresh**. No password check happens until the refresh token dies.

## 4. Behaviour: what stays, what gets fixed

**Stays (proven in practice):** request headers; `Range` paging and the `Content-Range` total; role derived from
`/account/me` (called without the role header); token endpoint quirks (query params + empty body for code/refresh,
form body for password); no `Authorization` header to CloudFront; token file format and path (`~/.parro-mcp/tokens.json`,
so existing logins keep working); revoke on logout; PDF/docx/html/text extraction; photo downscaling; all `PARRO_*` env vars.

**Fixes, each with a test** (findings from Plan 1):
1. **Contract `224`, app version `web:2.27.0`** as defaults (today 221 / 2.25.4).
2. **Single announcement:** `dtype=event.RAnnouncementEventPrimer`. Today `RAnnouncementEvent` → **401** breaks `parro_announcement` and `parro_attachment`.
3. **401 handling:** today the *whole token file* is deleted, which also throws away the refresh token and the lockout flag. New: refresh once and retry once.
   If it's still 401, report it ("token rejected, or wrong `dtype` for this endpoint"). **Never** start a password login because of a 401.
4. **Calendar-item attachments** live under `calendarItem.attachments`. Today they're never found.
5. **`--unread-only`:** filter first, then apply `limit`. Today it truncates first and can miss unread items.
6. **Pick the parser by `contentType`**, not by the entry's dtype. Accept `image/jpg`.
7. **CDN links are unsigned:** never log full attachment URLs.

**Found while implementing (2026-11-04), each with a test:**
8. **Calendar `count`:** today `count` is the number of items *fetched* (all groups together) while `items` is cut to
   `limit`. New: `count` is the number of items shown.
9. **`login-finish` checks `state`:** today the `state` from `login-url` is stored but never compared. New: a redirect
   with a different `state` is refused ("belongs to another login attempt").
10. **The login form latches on any failure after the password POST:** today the latch is set only when the answer
    matches a few words ("onjuist", "invalid", …); any other wording leaves automatic logins on. New: a password POST
    that does not yield a code always sets the latch, and so does no answer at all. The page's own error text
    (e.g. "Account has 2 attempts remaining") goes into the reason. The form must contain `emailadres` and
    `wachtwoord` before the password is sent.
11. **`status` never spends a password check:** today `parro_auth_status` can start an automatic login. New: it uses
    the cached or refreshed token only.
12. **Logout keeps the latch;** a browser login (`login-url`/`login-finish`) does not clear it either, because it says
    nothing about the configured password. Only an explicit `login` / `parro_login` clears it.
13. **`--unread-only`** also looks further back per group (50 items), so older unread items are not missed.
14. **`get` / `parro_get` refuse full URLs:** the token only ever goes to the configured API host.
15. **`parro_attachment` handles calendar items:** the id is tried as an announcement first (without refreshing on
    401) and then as `event.RCalendarItemEvent`.

## 5. Standalone CLI (`parro_cli.py`)

```
parro_cli.py [--login-method login-form|password-grant|auto] [--raw] [--compact] [--verbose] <command>

login [--prompt]            logout                  status          token     # prints a valid access token (refreshes if needed)
login-url                   login-finish <url>
me      children      groups [--previous]      unread      system-news
announcements [--group ID] [--limit N] [--unread-only]      announcement <id>
calendar [--group ID] [--limit N]
attachment <event-id> [--attachment-id ID | --all] [--save-to DIR] [--text]
chatrooms   chat-messages <chatroom-id> [--limit N]
get <path> [--param key=value ...] [--limit N] [--offset N]
```
- **Output:** JSON on stdout (pipe into `jq`), log messages on stderr. `--raw` gives the untouched geon payload.
- **`token`** prints a fresh access token, e.g. for Swagger UI's **bearerToken** or for curl.
- **Exit codes:** `0` ok · `1` API/network error · `2` usage · `3` not logged in · `4` login halted (lockout latch).

## 6. MCP server (`parro_mcp.py`)

- **Same 16 tool names and argument schemas as today**, so existing MCP clients keep working. `parro_login` gets an optional `method`.
- **The JSON-RPC over stdio is hand-written with the stdlib (decided)**, split into `handle_request()` / `list_tools()` / `call_tool()`.
  This means no dependency and no change to the Docker image. The official `mcp` SDK becomes worth it only if a native HTTP transport is
  wanted later; thanks to the split, that would touch only `parro_mcp.py`.
- **The tool descriptions get the lockout warning and the login-method hint.**

## 7. Tests (pytest, dev only)

- **Unit tests:** PKCE (RFC 7636 App. B vector), Content-Range parsing, `strip_geon_metadata`, source-entry choice
  (announcement and calendar-item paths), summaries built from every `samples/*.json`.
- **Login safety** (fake HTTP transport, no network):
  - `login-form` makes exactly one credential POST;
  - `auto` makes at most two;
  - with `login_halted` set, **zero** requests are made;
  - a 401 never triggers a credential login;
  - tokens and passwords never appear in log output.
- **Login form parsing:** against a saved copy of the public ParnasSys login page (no personal data; captured in phase 2).
- **Behaviour comparison (local only):** run the old and new MCP servers on the same fake responses and compare the tool
  output. Differences are allowed only for the intended fixes (§4). This compares *behaviour*, never code. The test is skipped when `legacy/` is absent (e.g. in CI).
- **Contract:** every fixture the tests feed the client validates against `openapi/parro.openapi.json`.

## 8. Phases

| # | Phase | Done when |
| --- | --- | --- |
| 0 | Settle §0. Move the old file to `legacy/parro_mcp_original.py` (add `/legacy/` to `.gitignore`); it's used only to run behaviour comparisons. Scaffold `parro/`, `tests/`, `pyproject.toml` (ruff, mypy, pytest config) | `pytest` runs (0 tests) |
| 1 | `settings`, `errors`, `http`, `pkce`, `token_store`, `geon` + tests | unit tests pass |
| 2 | `login_methods` + `authenticator` incl. the three methods and the latch; capture the login page HTML fixture | login-safety tests pass |
| 3 | `api_client` (all endpoints, fixes 1–3) + `summaries` (fix 5) | parity tests pass |
| 4 | `attachments` (fixes 4, 6, 7; optional PDF/image libs) | attachment tests pass |
| 5 | `parro_cli.py` | every command runs against the fake transport; `--help` reads well |
| 6 | `parro_mcp.py` on the new core; README + DEPLOY.md updated; Dockerfile copies `parro/` | old and new MCP give the same `tools/list` (plus `method`) |
| 7 | **Live check with you present**, ≤ 1 password check: `login --login-method login-form`, `status`, `me`, `announcements --limit 5`, `attachment` on the PDF, `token` → paste into Swagger UI, `logout`. Then go public if §0b allows | outputs recorded in the README; `.gitignore` TEMPORARY block removed |

## 9. Credits

In the README, under **Credits**:

> Inspired by **[fobatai/parro-mcp](https://github.com/fobatai/parro-mcp)**, a read-only MCP server for Parro by
> fobatai. Its working login and API calls were the starting point for this follow-up. The client here is an
> independent implementation based on the OpenAPI specification in this repository.

Also one line in the `parro/__init__.py` and `parro_mcp.py` docstrings ("Inspired by fobatai/parro-mcp; independent
implementation"). The spec's `info.description` already carries the credit (done 2026-11-04).

## 10. Decisions (2026-11-04)

1. Default login method: **`login-form`**.
2. MCP protocol layer: **stdlib**, hand-written JSON-RPC over stdio.
3. Licensing: **independent implementation** from the spec; the original is used only to check behaviour (§0b).

---

## Kickoff prompt (paste into the implementation session)

```text
Work in the parro-api-client folder. Read docs/PLAN-api-client.md (especially §0b), openapi/parro.openapi.json,
README.md and samples/. Write the code independently from the spec and the plan: do not copy or paraphrase code,
regexes, docstrings or comments from parro_mcp.py. Only run or read it to compare behaviour and spot gaps. Implement the plan phase by phase (0–6), running pytest,
ruff and mypy after each phase and showing the results. Hard rules: stdlib only in parro/ (PyMuPDF,
pypdf, Pillow optional); read-only (GET to the API, POST only to the IdP token/revoke/login form);
never log tokens, passwords or full attachment URLs; keep the lockout latch exactly as in §3; follow
the readability rules in §2. Use samples/ as fixtures. Do not edit .gitignore and do not push. Stop
before phase 7 and ask me to be present for the live run, which allows one password check at most.
```
