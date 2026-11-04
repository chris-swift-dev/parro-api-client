# Parro REST API: unofficial OpenAPI specification

An unofficial, **read-only** OpenAPI 3.0.3 description of the REST API behind
[talk.parro.com](https://talk.parro.com), the Dutch parent–school communication app by
Topicus (ParnasSys). It documents the API as observed from the web client (contract version 224).

**→ Browse it in Swagger UI: https://chris-swift-dev.github.io/parro-api-client/**

> Not affiliated with or endorsed by Topicus, ParnasSys or Parro. Behaviour was observed, not
> documented by the vendor, and may change at any time. Only documented `GET` endpoints and the
> standard OAuth2 login flow are described.

## What's in it

- **Account, children, groups, announcements, calendar items, chats, unread counts, system news**:
  12 verified operations, plus 6 paths that appear in the web app's code but were never called
  (tagged *Unverified*).
- **Authentication** against the ParnasSys IdP: authorization code + PKCE, password grant,
  refresh, revoke, OIDC discovery.
- **The non-obvious parts**: the geon media type and client headers, `Range`-based paging (`206`
  even without `Range`), `dtype` polymorphism, the `dtype` that answers `401` instead of `406`,
  and where attachments live and how their CDN links behave.

Response schemas contain **only fields seen in real responses**. They were inferred from
sanitized samples, which are not part of this repository, so this published spec carries no example payloads.

## Files

| Path | Purpose |
| --- | --- |
| `openapi/parro.public.openapi.json` | The specification (also served by the Swagger UI page) |
| `openapi/README.md` | How the spec is generated, validated and published |
| `tools/` | Spec generator, validator and site assembly script |
| `site/swagger-initializer.js` | Swagger UI configuration |
| `.github/workflows/pages.yml` | Validates the spec and deploys Swagger UI to GitHub Pages |

## Using the spec

- **Swagger Editor / other tools:** import `openapi/parro.public.openapi.json`.
- **"Try it out" won't work from the browser.** The API only allows browser calls from
  `https://talk.parro.com` (CORS). Copy the generated `curl` command and run it in a terminal
  with your own access token.
- **Local preview:** `npm ci --ignore-scripts && npm run preview`, then open http://localhost:8000.

## Be careful with your account

The ParnasSys IdP **locks an account after a few failed logins**, so never retry a rejected
password automatically. Attachment URLs need no authentication, so treat them as secrets.

## License

The specification and documentation in this repository are licensed under
[Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)
(see [`LICENSE`](../LICENSE)). You may share and adapt them for any purpose, provided you give
appropriate credit (link to this repository), indicate the license and note any changes you made.

"Parro", "ParnasSys" and "Topicus" are names of their respective owners. They are used here only
to identify the API being described.
