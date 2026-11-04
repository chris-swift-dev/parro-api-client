"""Read-only client for the Parro REST API (talk.parro.com), shared by the CLI and the MCP server.

Everything that talks to Parro or to the ParnasSys login server lives in this package. The two entry
points only translate between their own interface (command line, MCP JSON-RPC) and this core.

This package must never:
  * send anything other than GET to the Parro API (POST goes only to the IdP's token, revoke and
    login-form endpoints);
  * write tokens, passwords or full attachment URLs to a log;
  * start a password login on its own after a password was rejected (see authenticator.py).

Inspired by fobatai/parro-mcp; independent implementation based on openapi/parro.openapi.json.
"""

# The one place the version lives. pyproject.toml repeats it; a test keeps the two equal, and the
# release workflow checks that the git tag matches.
__version__ = "0.1.0"
