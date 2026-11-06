#!/usr/bin/env python3
"""Start the MCP server from a source folder or a release archive (existing MCP configurations).

    python3 parro_mcp.py tools

The server itself is parro/mcp_server.py; installed (pipx, uv, pip), the same server is the
`parro-client-mcp` command.
"""

if __name__ == "__main__":
    from parro.mcp_server import run

    run()
