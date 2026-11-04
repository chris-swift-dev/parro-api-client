# Code tour

A first read of the client code. It follows one request, `parro_cli.py announcements --limit 5`,
through the modules. The MCP tool `parro_announcements` takes the same path from step 2 on.

```
parro_cli.py / parro_mcp.py      entry points: parse arguments, print the result
        │
parro/operations.py              one function per command, shared by both entry points
        │            │
parro/api_client.py  parro/summaries.py     fetch raw JSON  │  shape it for people
        │                    │
parro/authenticator.py   parro/geon.py      valid token     │  geon helpers (ids, totals, stripping)
        │
parro/login_methods.py  parro/token_store.py  parro/pkce.py   OAuth steps │ tokens.json │ PKCE
        │
parro/http.py                    the only place a request leaves the process
```

## 1. The entry point

`parro_cli.py` builds an argparse parser. `main()` reads the settings once with
`Settings.from_environment()` (`parro/settings.py`). Command-line flags such as `--login-method`
override them through `Settings.with_overrides()`. It creates a `ParroClient` and calls the handler
for the command, here `operations.list_announcements(client, group_id=None, limit=5, ...)`.

`parro_mcp.py` does the same per `tools/call` message. `McpServer.call_tool()` looks the tool up in
`TOOL_FUNCTIONS` and calls the same `operations` function. That is why CLI output and MCP output are
always identical.

## 2. The operation

`operations.list_announcements()` asks the client for the feed of every current group
(`ParroClient.collect_feed()`), then hands the events to
`summaries.summarize_announcement_feed()`, which sorts them newest first, applies the unread filter
*before* the limit, and builds compact dicts.

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

## Where to look when…

| …you want to | look at |
| --- | --- |
| add a CLI command or MCP tool | `parro/operations.py`, then `HANDLERS` in `parro_cli.py` and `TOOL_DEFINITIONS` / `TOOL_FUNCTIONS` in `parro_mcp.py` |
| call a new endpoint | a small method on `ParroClient` (`parro/api_client.py`) |
| change output fields | `parro/summaries.py` (keep existing field names: clients depend on them) |
| understand a login failure | `parro/authenticator.py`, `parro/login_methods.py`, `tests/test_login_safety.py` |
| check what the API really does | `openapi/parro.openapi.json` and `samples/` |
