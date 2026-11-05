## Docker image: copy `parro/` too

`parro_mcp.py` is no longer a single file: it imports the `parro/` package next to it. The
Dockerfile (not in this folder) must copy both, for example:

```dockerfile
COPY parro_mcp.py /app/parro_mcp.py
COPY parro/ /app/parro/
```

Nothing else changes: still standard library only (plus the optional `pymupdf` / `pillow` from
`requirements.txt`), same entry point, same environment variables. New and optional:
`PARRO_LOGIN_METHOD` (`login-form` is the default; see README → Login methods).

Since 0.2.0 the server keeps a cache of attachments and calendar details (README → Local data).
Point it at the volume, so it survives a rebuild and stays out of the image:
`PARRO_DATA_DIR=/data/parro`. Or switch it off with `PARRO_CACHE=off`.

Check after a rebuild:

```bash
docker exec <container> /opt/venv/bin/python /app/parro_mcp.py tools   # lists 18 tools
```

## Logging in to Parro itself

Two separate logins live here: one into *this server* (above), and one into
*Parro* (below).

The container ships no Parro credentials. Call `parro_login_url`, open the URL,
log in, and hand the redirect URL to `parro_login_finish`. Tokens land in
`/data/parro-tokens.json` and refresh themselves.

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
