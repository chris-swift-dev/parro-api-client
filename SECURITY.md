# Security

This client handles passwords, OAuth tokens and school data about children, so security reports are
very welcome.

## Reporting a problem

Please report privately, not in a public issue:
**[Report a vulnerability](https://github.com/chris-swift-dev/parro-api-client/security/advisories/new)**
(GitHub's private vulnerability reporting). Describe what you found, how to reproduce it, and which
version or commit you used. You will get an answer as soon as possible; a fix goes into a new
release, and the advisory is published once that release is out.

**Never include real credentials or data**: no passwords, tokens, HAR files, calendar subscription
links, or names and messages from a real Parro account. Use invented data, like the test suite does.

## What is in scope

- This repository: `parro/`, `parro_cli.py`, `parro_mcp.py`, the release archives, the GitHub
  Actions workflows and the published OpenAPI spec.
- For example: a token, password or download link that ends up in a log, a file or an error
  message; files written with permissions that are too open; anything that makes the client write
  to the Parro API; a way around the lockout latch ([docs/LOGIN.md](docs/LOGIN.md)).

**Problems in Parro itself** (its API, the login server, the app) are not ours to fix: please
report them to Topicus / ParnasSys directly.

## Supported versions

Only the [latest release](https://github.com/chris-swift-dev/parro-api-client/releases/latest)
gets fixes.
