# Plan 2 — Swift API client for Parro (Linux, Foundation only)

**Deliverable:** a SwiftPM package in `swift/` with a library (`ParroKit`), a CLI (`parro`)
and unit tests. It builds and runs on Linux with **zero package dependencies**.
**Parity target:** the read-only behaviour of `parro_mcp.py`, minus the MCP layer and PDF/docx text extraction.
**Decisions taken:** SwiftPM package, attachments are **download-only** (text extracted only for txt/csv/json/html).

---

## 1. Constraints and Linux gotchas (read first)

| Topic | On Linux | Approach |
| --- | --- | --- |
| Networking | `URLSession` lives in `FoundationNetworking` | `#if canImport(FoundationNetworking) import FoundationNetworking #endif` in every file that uses it |
| async URLSession | the async overloads are less battle-tested in corelibs | wrap `dataTask`/`downloadTask` completion handlers in `withCheckedThrowingContinuation`, which works on every toolchain |
| SHA-256 (PKCE) | **no CryptoKit / CommonCrypto** | hand-written SHA-256 (~80 lines) checked against FIPS 180-2 vectors **and** RFC 7636 App. B (`dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk` → `E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM`) |
| Random | no `SecRandomCopyBytes` | `SystemRandomNumberGenerator` (getrandom/urandom on Linux, cryptographically secure) |
| base64url | — | `Data.base64EncodedString()` then swap `+/` → `-_` and strip `=` |
| Blocking redirects | needed for form login (`Location: …?code=`) | `URLSessionTaskDelegate.willPerformHTTPRedirection` → `completionHandler(nil)`, using a dedicated session |
| Cookies | `HTTPCookieStorage` on Linux has had quirks | small in-memory cookie jar (parse `Set-Cookie`, send `Cookie`), used only by form login |
| Argument parsing | swift-argument-parser is a dependency | hand-written parser (subcommand + `--flag value` / `--bool`) |
| zip / PDF | no API | out of scope: download only |
| File mode 0600 | — | `FileManager.setAttributes([.posixPermissions: 0o600])` |
| Large ids | ids exceed Int32 | `Int64` everywhere |

Toolchain: `swift-tools-version:5.9`; must build on **Swift 5.10 and 6.x** (6.x uses the new
swift-foundation on Linux). Verify in Docker: `swift:5.10-jammy` and `swift:6.0-jammy`.

## 2. Package layout

```
swift/
  Package.swift                    # targets: ParroKit (library), parro (executable), ParroKitTests
  Sources/ParroKit/
    Config.swift                   # PARRO_* env vars (same names/defaults as the Python), CLI overrides
    Crypto/SHA256.swift            # hand-written
    Crypto/PKCE.swift              # verifier/challenge, base64url, state
    HTTP/Transport.swift           # protocol HTTPTransport { send(Request) async throws -> Response }
    HTTP/URLSessionTransport.swift # real impl; redirect on/off; cookie jar hook; max-size guard
    HTTP/CookieJar.swift
    Auth/TokenStore.swift          # JSON file, Python-compatible format
    Auth/OAuthClient.swift         # authorize URL, code exchange, refresh, password grant, revoke
    Auth/FormLogin.swift           # Wicket signInForm fallback
    Auth/Authenticator.swift       # accessToken(): cached → refresh → headless login; lockout latch
    API/ParroClient.swift          # get(path, query, range, count, role) + 401 handling
    API/Endpoints.swift            # typed calls: me, children, groups, events, event, chat…
    API/Pagination.swift           # Range header, Content-Range parsing
    Model/JSONValue.swift          # enum JSONValue: Codable (raw payloads, escape hatch)
    Model/Geon.swift               # GeonLink, selfId, slim()
    Model/*.swift                  # Account, Identity, Child, Group, Event, Attachment, ChatRoom, …
    Attachments/Attachments.swift  # pick SOURCE entry, download (no auth to CDN), save, textual extract
    Output/Formatter.swift         # summaries mirroring the Python _fmt_* functions
  Sources/parro/main.swift         # CLI entry, argument parsing, exit codes
  Tests/ParroKitTests/
    SHA256Tests, PKCETests, ContentRangeTests, SlimTests, TokenStoreTests,
    AuthenticatorTests (lockout latch, refresh fallback), ClientTests (401 retry, role header rules),
    FormLoginTests (form-action extraction), AttachmentTests (SOURCE pick, CDN without auth)
    Fixtures/ → symlink or copy of ../../samples (shared with Plan 1)
```

`ParroKit` contains no `print`: logging goes through a `Logger` closure (stderr in the CLI).
That keeps the library ready for a later MCP server target.

## 3. Behaviour to port faithfully (from parro_mcp.py)

**Requests**
- Base `PARRO_BASE_URI` + `/rest/v2` + path (paths already starting `/rest/` are left alone).
- Headers: `Authorization: Bearer`, `Accept` and `Content-Type: application/vnd.topicus.geon+json;version=<CONTRACT>`,
  `parro-app-version: web:2.25.4`, and `parro-authorization-role` on **everything except `/account/me`**.
- Pagination: `Range: items=<offset>-<offset+limit-1>`, optionally `topicus-Range-Count: Exact`;
  accept `200` and `206`; parse the total from `Content-Range` (`…/123`).
- Collections: accept both `{items:[…]}` and a bare array.
- `/event/{id}` always sends a `dtype` (default `event.RAnnouncementEvent`). Without it: `406 EVENT_BAD_TYPE`.

**Role derivation.** `PARRO_ROLE` if set. Otherwise `/account/me` →
`kind = accountType ?? identity.role ?? "GUARDIAN"` uppercased, id = self-link id of the first entry in
`identity.guardians`, then `teachers`, then `children`. Cached for the process.

**Token store.** Same JSON keys as the Python file (`access_token`, `refresh_token`, `expires_at`
as epoch seconds, `obtained_at`, `login_failed`, `pending_verifier`, `pending_state`), so the two tools
can share a file. **Default path `~/.parro/tokens.json`, separate from the Python one:** if the IdP
rotates refresh tokens, two clients refreshing the same file will log each other out. Sharing is
still possible with `PARRO_TOKEN_FILE`. `expires_at = now + expires_in - 60`. Bootstrap from `PARRO_ACCESS_TOKEN`.

**OAuth details (non-obvious, all from the Python):**
- `authorization_code` and `refresh_token` grants: parameters go in the **query string**, the body is
  **empty**, with `Content-Type: application/x-www-form-urlencoded`.
- `password` grant: normal form body incl. `scope` (default `openid offline_access`).
- `revoke`: form body `token`, `token_type_hint`, `client_id`, sent for refresh and access tokens.
- Credentials: `PARRO_PASSWORD_FILE` wins over `PARRO_PASSWORD` (strip trailing CR/LF only).

**Login order and the lockout latch.** This is the safety-critical part.
1. Valid cached access token → use it.
2. Refresh token → refresh. If that fails, log it and continue.
3. Credentials present → **check the latch first** (`login_failed` set → refuse with a clear error).
   - Password grant. On `invalid_grant` → try the **form login once**. Any other error → form login.
   - Form login rejects (body matches `onjuist|niet juist|invalid|incorrect`) → set the latch and fail.
   - Success → clear the latch.
4. Otherwise → "not authenticated" error naming `login` / `login-url`.
`parro login` (explicit) clears the latch and spends exactly one attempt.

**Form login.** GET authorize (follow redirects, keep the **final URL** and cookies) → find
`<form action="…signInForm…">` (fallback: first form) → resolve `action` relative to the
final URL, un-escaping `&amp;` → POST `aanmelden=x&emailadres=…&wachtwoord=…` **without following
redirects** → `code` from the `Location` header → code exchange.

**Attachments.** Pick the entry with `type == "SOURCE"`, else the first; handle both `entries` and a single `entry`.
Send `Authorization`/role headers **only** if the URL starts with `BASE_URI`. The CDN URLs are pre-signed and break with them.
Enforce `PARRO_MAX_DOWNLOAD` (60 MB) up front from `size` and again while downloading. Filename from the entry, or the
last URL path component (percent-decoded).

### Deliberate deviations (fixes, flagged for your approval)
1. **401 handling.** The Python deletes the whole token file on a 401, which also throws away the refresh
   token *and the lockout latch*. Swift drops only the access token, then runs the normal sequence above
   (refresh first), and retries once.
2. **`announcements --unread-only`.** The Python truncates to `limit` and *then* filters, so it can return
   fewer items than are unread. Swift filters first, then truncates.
3. **Calendar sort.** Kept as in the Python (ascending `sortDate`), but the order becomes explicit (`--order asc|desc`).

## 4. CLI surface

```
parro [global options] <command> [args]

Global:  --raw (untouched geon JSON)  --compact (no pretty-print)  --verbose (log requests, token redacted)
         --token-file PATH  --role ROLE  --base-uri URI

auth-status                    login                       logout
login-url                      login-finish <url-or-code>
me                             children [--limit N]
groups [--scope current|previous] [--limit N]
announcements [--group ID] [--limit N] [--unread-only]
announcement <id> [--dtype T]
attachment <announcement-id> [--attachment-id ID | --all] [--out DIR] [--print-text]
attachment --url URL [--filename F] [--content-type T] [--out DIR]
calendar [--group ID] [--limit N] [--dtype T] [--order asc|desc]
chatrooms [--limit N]          chat-messages <chatroom-id> [--limit N]
unread
get <path> [--param k=v]... [--limit N] [--offset N]
```

- stdout: JSON only (pretty, sorted keys, `withoutEscapingSlashes`); stderr: logs. Pipes cleanly into `jq`.
- Summaries mirror the Python `_fmt_*` / `t_*` output keys, so outputs are comparable side by side.
- `attachment`: saves files into `--out` (default cwd) and prints `{filename, contentType, bytes, path}`.
  `--print-text` adds `text` for textual types only. For anything else (PDF, docx) it explains that only the download is supported.
- Exit codes: `0` ok · `1` API/network error · `2` usage · `3` not authenticated · `4` login latched.

## 5. Models

Hand-written `Decodable` structs for the fields in Plan 1 §4, with every property optional and unknown keys ignored,
because geon adds fields across contract versions. A `JSONValue` enum carries `--raw`, `get`,
and fields without a model yet. `slim()` works on `JSONValue` (drop `permissions/links/dtype/additionalObjects`,
lift the self-link id to `id`, `dtype` → last segment as `type`, drop null/empty), so its output matches the Python `slim()` structurally (same keys, same pruning).
Dates stay `String` until the samples confirm the format. Then parse them with `ISO8601DateFormatter` (with fractional seconds if needed).

## 6. Phases

| # | Phase | Done when |
| --- | --- | --- |
| 0 | Scaffold package, Docker build script (`swift/scripts/linux-test.sh` runs `swift build && swift test` in `swift:5.10` and `swift:6.0`) | empty CLI builds on both |
| 1 | SHA256, PKCE, base64url, Config, TokenStore, Transport + mock transport | crypto vectors and token round-trip tests pass |
| 2 | OAuthClient, FormLogin, Authenticator (incl. latch) | auth tests pass against the mock (incl. "latched → no network call") |
| 3 | ParroClient: headers, role rules, Range/Content-Range, 401 path | client tests pass |
| 4 | Models + slim + formatters, tested on `samples/` fixtures | fixtures decode; slim output matches the Python's for the same input |
| 5 | CLI commands | `parro --help` and every command run against the mock |
| 6 | Attachments (download, size limit, no-auth CDN) | attachment tests pass |
| 7 | **Live verification** (read-only, with you present): `auth-status`, `login` (one attempt), `me`, `groups`, `announcements --limit 5`, `attachment` on a PDF, `chatrooms`, `unread`, `logout` | outputs side by side with `python parro_mcp.py call …`; findings recorded in `swift/README.md` |

Live calls run **only** in phase 7, and phase 7 makes at most **one** credential login attempt. A rejected login
stops the run.

## 7. Out of scope (for now)

MCP server target, PDF/docx text extraction, writes of any kind, Keychain/secret-service storage,
macOS-specific APIs (the code must also *compile* on macOS, but Linux is the target).

---

## Kickoff prompt (paste into the implementation session)

```text
Work in the parro-api-client folder. Read docs/PLAN-swift-client.md, docs/PLAN-openapi.md,
parro_mcp.py and README.md. Build the SwiftPM package in swift/ phase by phase (0–6), running
`swift build && swift test` on Linux (Docker swift:5.10-jammy and swift:6.0-jammy) after each phase.
Hard rules: Foundation/FoundationNetworking/Glibc only, no package dependencies; read-only (GET to the
API; POST only to the IdP token/revoke endpoints); never log tokens or passwords; keep the lockout
latch semantics exactly as in §3. Use samples/ as test fixtures. Stop before phase 7 and ask me to be
present for the live run, which allows one login attempt at most.
```
