# Code tour

A first read of the client code. It follows one request, `parro-client announcements --limit 5`,
through the modules. The MCP tool `parro_announcements` takes the same path from step 2 on.

```
parro/cli.py / parro/mcp_server.py   entry points: parse arguments, print the result
        │                    └── parro/rendering.py   markdown views of the same result
parro/operations.py              one function per command, shared by both entry points
        │            │
parro/api_client.py  parro/summaries.py     fetch raw JSON  │  shape it for people
        │                    │
parro/authenticator.py   parro/geon.py      valid token     │  geon helpers (ids, totals, stripping)
        │
parro/login_methods.py  parro/token_store.py  parro/pkce.py   OAuth steps │ tokens.json │ PKCE
        │                parro/cache.py          attachments and calendar details on disk
        │
parro/http.py                    the only place a request leaves the process
```

## 1. The entry point

The commands `parro-client` and `parro-client-mcp` (from `[project.scripts]` in `pyproject.toml`)
call `run()` in `parro/cli.py` and `parro/mcp_server.py`. `run()` switches the output to UTF-8 (a
Windows console cannot print the markers otherwise), records the program's name for help and hints
(`parro/naming.py`), and calls `main()`. In a source folder or a release archive the launchers
`parro_cli.py` and `parro_mcp.py` call the same `run()`, naming the program `parro_cli.py`.

`parro/cli.py` builds an argparse parser. `main()` reads the settings once with
`Settings.from_environment()` (`parro/settings.py`). Command-line flags such as `--login-method`
override them through `Settings.with_overrides()`. It creates a `ParroClient` and calls the handler
for the command, here `operations.list_announcements(client, group_id=None, limit=5, ...)`.

`parro/mcp_server.py` does the same per `tools/call` message. `McpServer.call_tool()` looks the tool up in
`TOOL_FUNCTIONS` and calls the same `operations` function. That is why CLI output and MCP output are
always identical.

What gets printed depends on the format. `rendering.choose_format()` decides between JSON and
markdown (CLI: `--format`, `PARRO_FORMAT`, else markdown at a terminal; MCP: the `format`
argument). For markdown, `rendering.render(view, result)` turns the very same result into text:
`COMMAND_VIEWS` (CLI) and `TOOL_VIEWS` (MCP) name the view for each command.

## 2. The operation

`operations.list_announcements()` asks the client for the feed of every current group
(`ParroClient.collect_feed()`), then hands the events to
`summaries.summarize_announcement_feed()`, which sorts them newest first, merges announcements that came in through
several groups, applies the unread filter *before* the limit, and builds compact dicts.

## 3. The API client

`ParroClient.collect_feed()` calls `GET /group?dtype=identity.RHomeGroup` once, then
`GET /event?dtype=event.RAnnouncementEventPrimer&group=<id>` per group. Every call goes through
`ParroClient.get()`, which:

1. builds the URL on the configured API host (full URLs are refused, so a token never leaves for
   another host);
2. asks the `Authenticator` for an access token;
3. adds the headers from the spec: `Accept`/`Content-Type` with the geon contract version,
   `parro-app-version`, `parro-authorization-role` (derived once from `GET /account/me`, which
   itself is called *without* that header), and `Range` for collections;
4. sends the request through the transport;
5. on a **401**: asks the authenticator for one refresh and retries once. A second 401 raises
   `TokenRejected`, which also explains the `dtype` pitfall. **A 401 never starts a password login.**

**The two writes.** `ParroClient.mark_read(kind, id)` sends one of the three calls in
`READ_STATE_WRITES` (`PUT …/read`, empty body), through the same headers and 401 handling as `get()`.
Only commands the user runs on purpose call it (`operations.mark_read`,
`mark_group_announcements_read`, and the `--mark-read` flags); the MCP tool `parro_mark_read` exists
only with `PARRO_ALLOW_MARK_READ=1`.

`ParroClient.send_chat_message(chatroom_id, text)` builds the one captured body and POSTs it, once:
after a timeout or a `5xx` it says the outcome is unknown and does not send again (the request has no
idempotency key). `operations.prepare_chat_message` does the reading and the refusals;
`send_prepared_message` sends. Between those two, `chat-send` asks (`cli.run_chat_send`) and the MCP
tool wants `confirm: true` (`send_or_preview_chat_message`, only with `PARRO_ALLOW_SEND_CHAT=1`).

No other method sends anything but GET. In the tests, the fake API fails any test that sends another
write (`tests/fakes.py`, `ForbiddenWrite`), and for messages it accepts only the captured body.

## 4. The authenticator and the lockout latch

`Authenticator.get_access_token()` uses the cached token while it is fresh, else the refresh token,
else an automatic login with the configured method (`login_methods.py`).

The ParnasSys IdP locks the account after a few failed logins. So the moment a password is
rejected, `TokenStore.halt_logins()` writes the latch (`login_failed`) to `tokens.json`. From then
on `refuse_if_login_halted()` stops every automatic login *before any request is sent*. Only an
explicit `login` / `parro_login` (`Authenticator.login()`) clears it and spends exactly one attempt.

`login_methods.login_with_login_form()` is split into the steps a browser takes:
`fetch_login_page()` → `find_login_form_action()` → `submit_login_form()` → read the code from the
redirect → `exchange_authorization_code()`. Problems with the page layout are detected before the
password is sent, so they cost no attempt.

## 5. Tokens on disk

`TokenStore` (`parro/token_store.py`) reads `~/.parro-mcp/tokens.json` once and writes it atomically
with mode 0600. The key names are those of the original server, so existing logins keep working.

## 6. HTTP

`parro/http.py` has `UrllibTransport.send()`. It never raises for an HTTP status, only for "no answer
at all" (`NetworkError`). Log lines name the method and host, never the path or query: query strings
carry OAuth codes, and attachment paths on the CDN are unsigned download links. Tests swap the
transport for the fakes in `tests/fakes.py`, so no test touches the network.

## 7. Attachments

`parro/attachments.py` finds attachments in `attachments[]` (announcements) and
`calendarItem.attachments[]` (calendar items). It picks the SOURCE entry and chooses the reader by
content type. Downloads from the CDN go without any Parro header. PDF text needs PyMuPDF or pypdf,
and photo downscaling needs Pillow. All three are optional.

## 8. The cache

`ParroClient.cache` (`parro/cache.py`) keeps attachment files with their text, and calendar details,
under `PARRO_DATA_DIR/cache`. `attachments.download_or_reuse()` and `extract_or_reuse()` use it with
`AttachmentFile.cache_key()` (attachment id + upload id + size: the same key always means the same
bytes). `operations.calendar_details()` stores each item's details with its `lastModifiedAt` and uses
them only while the list shows the same value; items that ask for helpers are always fetched, since
sign-ups may not change that value. Lists are never cached, and neither are the two secret links
(calendar subscription, privacy page).

## 9. The archive

`parro-client sync` calls `operations.sync_archive()`. It reads every list in full
(`read_all_pages()`), skips items whose version (`lastModifiedAt`) is already archived, and for the
others writes markdown (`rendering.render_archived_*`) and JSON through `parro/archive.py`.
`Archive` knows the file names, the YAML header, renames, `index.md` and the state file
`.sync-state.json` that remembers what was written. Attachments are copied from the cache when they
are there, otherwise downloaded once (`store_attachment()`).

## Where to look when…

| …you want to | look at |
| --- | --- |
| add a CLI command or MCP tool | `parro/operations.py`, then `HANDLERS` / `COMMAND_VIEWS` in `parro/cli.py` and `TOOL_DEFINITIONS` / `TOOL_FUNCTIONS` / `TOOL_VIEWS` / `TOOL_HINTS` in `parro/mcp_server.py` |
| change how something looks | `parro/rendering.py`, then `UPDATE_SNAPSHOTS=1 .venv/bin/pytest tests/test_rendering.py` and read the diff in `tests/snapshots/` |
| call a new endpoint | a small method on `ParroClient` (`parro/api_client.py`); GET only: a new write needs a decision first, see the two writes in step 3 and `SECURITY.md` |
| change output fields | `parro/summaries.py` (keep existing field names: clients depend on them) |
| understand a login failure | `parro/authenticator.py`, `parro/login_methods.py`, `tests/test_login_safety.py` |
| check what the API really does | `openapi/parro.openapi.json` and `samples/` (private) |
| add test data | `tests/fixtures/make_api_fixtures.py` (invented data only), then run it |
| change the .ics export | `parro/icalendar.py` and `tests/test_calendar_export.py` |
| change the archive | `parro/archive.py` (files), `operations.sync_archive()` (fetching), `tests/test_archive.py` |
