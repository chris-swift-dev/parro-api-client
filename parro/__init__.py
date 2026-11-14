"""Client for the Parro REST API (talk.parro.com), shared by the CLI and the MCP server.

It reads; the only writes are marking items as read, sending a text message to a chat, signing up
or withdrawing as a helper, and answering an invitation, on request (see the rules in
api_client.py).

Everything that talks to Parro or to the ParnasSys login server lives in this package. The two entry
points only translate between their own interface (command line, MCP JSON-RPC) and this core.

This package must never:
  * send anything to the Parro API but GET, the PUT …/read calls of READ_STATE_WRITES when asked
    to mark something as read, the POST of send_chat_message when asked to send a message, and
    the POST and DELETE of the helper commitment calls when asked to change one (other POSTs go
    only to the IdP's token, revoke and login-form endpoints);
  * log the text of a chat message that is being sent;
  * write tokens, passwords or full attachment URLs to a log;
  * start a password login on its own after a password was rejected (see authenticator.py).

Inspired by fobatai/parro-mcp; independent implementation based on openapi/parro.openapi.json.
"""

# The one place the version lives. pyproject.toml repeats it; a test keeps the two equal, and the
# release workflow checks that the git tag matches.
__version__ = "0.13.0"
