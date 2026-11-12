"""The tool hints can be seen by reading parro/mcp_server.py, without running it.

Some services grade an MCP server by reading its code instead of starting it. They only see a hint
that is written into the tool's definition as a plain value. These tests read the file the same way,
with `ast`: each tool is a dictionary literal with a literal `title` and a literal `annotations`
holding the four hints as True or False. Whether the hints are right is checked in
tests/test_tool_hints.py.
"""

import ast
from pathlib import Path

import pytest

from parro import mcp_server as parro_mcp

SOURCE = Path(parro_mcp.__file__)
HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


def literal_keys(node: ast.Dict) -> dict[str, ast.expr]:
    return {
        key.value: value
        for key, value in zip(node.keys, node.values, strict=True)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def tool_literals() -> dict[str, dict[str, ast.expr]]:
    """Every dictionary in the file with a "name" and an "inputSchema": the tool definitions."""
    found: dict[str, dict[str, ast.expr]] = {}
    for node in ast.walk(ast.parse(SOURCE.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Dict):
            continue
        keys = literal_keys(node)
        name = keys.get("name")
        if "inputSchema" in keys and isinstance(name, ast.Constant) and isinstance(name.value, str):
            assert name.value not in found, f"{name.value} is defined twice"
            found[name.value] = keys
    return found


TOOLS = tool_literals()


def test_every_tool_is_found_in_the_source():
    assert set(TOOLS) == set(parro_mcp.TOOL_FUNCTIONS)


@pytest.mark.parametrize("name", sorted(parro_mcp.TOOL_FUNCTIONS))
def test_the_hints_are_written_out(name):
    annotations = TOOLS[name].get("annotations")
    assert isinstance(annotations, ast.Dict), f"{name}: no literal annotations"
    written = literal_keys(annotations)
    for hint in HINTS:
        value = written.get(hint)
        assert isinstance(value, ast.Constant) and type(value.value) is bool, f"{name}: {hint}"


@pytest.mark.parametrize("name", sorted(parro_mcp.TOOL_FUNCTIONS))
def test_the_title_is_written_out_in_both_places(name):
    title = TOOLS[name].get("title")
    annotations = TOOLS[name]["annotations"]
    assert isinstance(annotations, ast.Dict)
    inner = literal_keys(annotations).get("title")
    assert isinstance(title, ast.Constant) and isinstance(title.value, str) and title.value
    assert isinstance(inner, ast.Constant) and inner.value == title.value


def test_nothing_changes_the_annotations_after_the_definitions():
    """A loop that adds hints at import time is what a reader of the source cannot see."""
    for node in ast.walk(ast.parse(SOURCE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
            key = node.slice.value if isinstance(node.slice, ast.Constant) else None
            assert key not in ("annotations", "title"), f"line {node.lineno}"


def test_the_source_and_the_running_server_agree():
    running = {
        tool["name"]: tool
        for tool in (
            *parro_mcp.TOOL_DEFINITIONS,
            parro_mcp.MARK_READ_TOOL,
            parro_mcp.SEND_CHAT_TOOL,
            parro_mcp.HELPER_SIGNUP_TOOL,
            parro_mcp.HELPER_WITHDRAW_TOOL,
            parro_mcp.RSVP_TOOL,
        )
    }
    for name, keys in TOOLS.items():
        assert running[name]["annotations"] == ast.literal_eval(keys["annotations"])
        assert running[name]["title"] == ast.literal_eval(keys["title"])
