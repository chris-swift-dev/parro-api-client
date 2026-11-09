"""The `parro-client-gui` command. Qt is imported late, so a plain install can say what to do."""

import sys

MISSING_QT = (
    "The desktop app needs Qt, which is not installed. Install it with:\n"
    '    pipx install --force "parro-api-client[gui]"'
)


def run() -> None:
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
