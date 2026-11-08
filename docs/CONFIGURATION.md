# Configuration

Every setting is an environment variable; the command line and the MCP tools need none of them for
normal use. Back to the [README](../README.md).

| Variable | Default |
| --- | --- |
| `PARRO_USERNAME` | (none; enables password login) |
| `PARRO_PASSWORD_FILE` / `PARRO_PASSWORD` | (none; the file wins; only trailing line breaks are stripped) |
| `PARRO_LOGIN_METHOD` | `login-form` (or `password-grant`, `auto`) |
| `PARRO_TOKEN_FILE` | `~/.parro-mcp/tokens.json` |
| `PARRO_ROLE` | derived from `/account/me`, e.g. `GUARDIAN:1234567890` |
| `PARRO_ACCESS_TOKEN` | bootstrap with an existing token (no refresh, not stored) |
| `PARRO_BASE_URI` | `https://rest-v2.parro.com` |
| `PARRO_LOGIN_URI` | `https://inloggen.parnassys.net` |
| `PARRO_CLIENT_ID` / `PARRO_REDIRECT_URI` | the talk.parro.com web client |
| `PARRO_CONTRACT_VERSION` | `224` |
| `PARRO_APP_VERSION` | `web:2.27.0` |
| `PARRO_SCOPE` | `openid offline_access` |
| `PARRO_TIMEOUT` | `30` (seconds) |
| `PARRO_MAX_DOWNLOAD` | `62914560` (60 MB) |
| `PARRO_MAX_IMAGE_PX` | `1400` |
| `PARRO_FORMAT` | `auto` (CLI: markdown at a terminal, JSON when piped), `json` or `markdown` |
| `PARRO_DATA_DIR` | `~/.parro/data` (the cache in `cache/`, the `sync` archive in `archive/`) |
| `PARRO_CACHE` | `on` (`off` = never read or write the cache; CLI: `--no-cache`) |
| `PARRO_CACHE_MAX_MB` | `500` |
| `PARRO_ALLOW_MARK_READ` | `off`; `1` adds the MCP tool `parro_mark_read` ([the school sees it](../README.md#marking-as-read)). The CLI's `mark-read` needs no switch |
| `PARRO_ALLOW_SEND_CHAT` | `off`; `1` adds the MCP tool `parro_send_chat_message` ([read this first](../README.md#sending-a-chat-message)). The CLI's `chat-send` needs no switch |

Switch to the acceptance environment by overriding `PARRO_BASE_URI`, `PARRO_LOGIN_URI` and
`PARRO_CLIENT_ID`.
