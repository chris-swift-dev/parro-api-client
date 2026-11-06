# Logging in

How the client logs in to Parro, and what keeps your account from being locked. The short version
is in the [README](../README.md#logging-in).

Everything is OAuth2 against the ParnasSys IdP. Tokens are stored in `~/.parro-mcp/tokens.json`
(mode 0600) and refreshed automatically: the access token lasts 1 hour.

**A login lasts at most 8 hours.** Measured on 2026-11-06: the refresh token expires 8 hours after the
login, and a refresh returns a new refresh token with the *same* expiry (its `iat` stays the login
time; only `refresh_count` goes up). So refreshing does not extend a login, and neither does the
scope `offline_access`, which the client asks for and the IdP grants. An earlier version of this
page said otherwise.

After 8 hours:
* with `PARRO_USERNAME` and a password (file) set, the next call logs in again on its own, which is
  one password check per 8 hours; a rejected password stops it (the latch below);
* without them, `status` and every call say "not logged in" (exit code 3) and nothing is retried:
  run `login --prompt` again, or use the browser flow.

## Login methods (`PARRO_LOGIN_METHOD`, CLI `--login-method`, MCP `method`)

| Value | What happens | Password checks per login |
| --- | --- | --- |
| `login-form` (**default**) | Exactly what a browser does: login page → form POST → code → token exchange | 1 |
| `password-grant` | OAuth2 password grant only, no fallback | 1 |
| `auto` | Password grant; on failure the login form once | up to 2 |

`login-form` is the default because some accounts answer `invalid_grant` to the password grant
anyway, so `auto` would waste an attempt on every login. A changed login page fails *before* the
password is sent (no form found: clear error, no attempt spent).

## The lockout latch

> **The IdP locks the account after a few failed logins** ("Account has N attempts remaining").

When a password is rejected, the client saves that in the token file and **stops logging in on its
own**. A typo therefore costs one attempt, not one per call. `status` / `parro_auth_status` then
shows `automatic_login_halted`. Fix the password, then run `parro-client login` (MCP: `parro_login`).
That explicit call clears the latch and spends exactly one attempt. A response the client cannot
interpret after the password was sent counts as a rejection too: it is the safe side. A 401 from the
API never triggers a password login: the client refreshes once, and otherwise reports the error.

## Credentials

* `PARRO_USERNAME` plus `PARRO_PASSWORD_FILE` (preferred) or `PARRO_PASSWORD`;
* or `parro-client login --prompt` (hidden input, nothing stored);
* or no password at all: `login-url`, open the URL, log in, then hand the address you land on to
  `login-finish` (MCP: `parro_login_url` / `parro_login_finish`). Copy it promptly: the Parro web app
  also tries to redeem the code, and each code works only once.

## Why not a proper loopback redirect?

The tidy modern pattern (RFC 8252: spin up `http://127.0.0.1:PORT/callback`, let the browser deliver
the code automatically) needs a client registered with that redirect URI. This IdP:

- publishes **no `registration_endpoint`**: no Dynamic Client Registration, so we cannot register one;
- validates redirect URIs strictly. Asking for `http://localhost:8765/callback` on the Parro client
  returns `invalid_client — Callback url does not match one of [registered]`;
- advertises **no device authorization grant**, so that route is out too.

So a local tool must borrow the web client's `client_id`, which is pinned to
`https://talk.parro.com/oauth2`. Hence the copy-paste step, or the login form.

## Note on the HAR

A captured `talk.parro.com.har` contains the login POST **in plaintext**, including the password,
plus valid OAuth tokens. Treat it as a secret: don't commit it (`*.har` is ignored), and consider
changing that password if it has been sitting in a file on disk.
