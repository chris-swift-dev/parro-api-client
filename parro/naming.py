"""The name of the command-line client, as the user starts it, for help texts, hints and messages.

Installed (pipx, uv, pip) the client is the `parro-client` command; from a source folder or a
release archive it is `parro_cli.py`. The launchers say which (`run(program=...)`), so messages
such as "run `parro-client login`" name a command that works where the user is.
"""

INSTALLED = "parro-client"
FROM_SOURCE = "parro_cli.py"

_name = INSTALLED


def cli_name() -> str:
    """'parro-client' or 'parro_cli.py'."""
    return _name


def set_cli_name(name: str) -> None:
    global _name
    _name = name


def cli_command(arguments: str) -> str:
    """'parro-client login --prompt' for 'login --prompt'."""
    return f"{_name} {arguments}"
