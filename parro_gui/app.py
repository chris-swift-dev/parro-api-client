"""The `parro-client-gui` command. Qt is imported late, so a plain install can say what to do."""

import sys

# PySide6 loses references to None, True and False each time a signal reaches Python. Before 3.12
# those counts can reach zero, which crashes the interpreter, also while the app is running. Python
# 3.12 made these objects immortal (PLAN-desktop-app §9).
MINIMUM_PYTHON = (3, 12)
PYTHON_TOO_OLD = (
    "The desktop app needs Python 3.12 or newer; this is Python {found}. Install it with a newer "
    'Python, for example:\n    pipx install --python python3.12 "parro-api-client[gui]"\n'
    "The command-line client and the MCP server work on this Python."
)
MISSING_QT = (
    "The desktop app needs Qt, which is not installed. Install it with:\n"
    '    pipx install --force "parro-api-client[gui]"'
)


def run() -> None:
    if sys.version_info[:2] < MINIMUM_PYTHON:
        found = ".".join(str(part) for part in sys.version_info[:2])
        print(PYTHON_TOO_OLD.format(found=found), file=sys.stderr)
        sys.exit(2)
    try:
        from .window import main
    except ModuleNotFoundError as problem:
        if str(problem.name).split(".")[0] not in ("PySide6", "shiboken6"):
            raise
        print(MISSING_QT, file=sys.stderr)
        sys.exit(2)
    except ImportError as problem:  # Qt is there, but a system library it needs is not
        print(f"Qt could not start: {problem}", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv))
