## Docker image

Since 0.5.0 the simplest image installs the package, and runs the command it provides:

```dockerfile
RUN pip install --no-cache-dir "parro-api-client[attachments]"
CMD ["parro-client-mcp"]
```

The setup below (copying the files) keeps working too.

### Copying the files: copy `parro/` too

`parro_mcp.py` is no longer a single file: it imports the `parro/` package next to it. The
Dockerfile (not in this folder) must copy both, for example:

```dockerfile
COPY parro_mcp.py /app/parro_mcp.py
COPY parro/ /app/parro/
```

Nothing else changes: still standard library only (plus the optional `pymupdf` / `pillow` from
`requirements.txt`), same entry point, same environment variables. New and optional:
`PARRO_LOGIN_METHOD` (`login-form` is the default; see docs/LOGIN.md → Login methods).

Since 0.2.0 the server keeps a cache of attachments and calendar details (docs/CALENDAR-AND-ARCHIVE.md → Your own archive → The cache).
Point it at the volume, so it survives a rebuild and stays out of the image:
`PARRO_DATA_DIR=/data/parro`. Or switch it off with `PARRO_CACHE=off`. The `sync` archive (0.3.0)
is a CLI command; run it where you want the files, not inside the MCP container.

Check after a rebuild:

```bash
docker exec <container> /opt/venv/bin/python /app/parro_mcp.py tools   # lists 20 tools
docker exec <container> parro-client-mcp tools                         # (installed package)
```

## Logging in to Parro itself

Two separate logins live here: one into *this server* (above), and one into
*Parro* (below).

The container ships no Parro credentials. Call `parro_login_url`, open the URL,
log in, and hand the redirect URL to `parro_login_finish`. Tokens land in
`/data/parro-tokens.json` and refresh themselves, but a login lasts at most 8 hours; then the
browser flow is needed again.

For unattended login instead, set `PARRO_USERNAME` and point
`PARRO_PASSWORD_FILE` at a file on the `/data` volume holding the password.
Note the IdP locks the account after a few failed attempts, so a typo there is
costly. Dokploy will hand you one for free if you use `PARRO_PASSWORD`
instead: it strips everything from a `#` onwards, quoted or not, so a password
containing one arrives truncated and every login attempt burns a try. The file
keeps the password out of Dokploy's database and out of the image layers too.
After one rejected password the server stops logging in on its own (the
lockout latch); call `parro_login` once the password is fixed.

Check what actually arrived before trusting it:

```bash
docker exec <container> /opt/venv/bin/python -c \
  "import os,hashlib; p=open(os.environ['PARRO_PASSWORD_FILE']).read().rstrip('\r\n'); \
   print(len(p), hashlib.sha256(p.encode()).hexdigest()[:16])"
```
