"""The desktop app for Parro: an optional layer on top of the `parro` package.

Installed with the `gui` extra. It imports Qt, so nothing in `parro/` may import it. Every call to
Parro goes through `parro.operations`, the same functions the CLI and the MCP server use.
"""
