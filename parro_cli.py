#!/usr/bin/env python3
"""Start the command-line client from a source folder or a release archive.

    python3 parro_cli.py --help

The program itself is parro/cli.py; installed (pipx, uv, pip), the same program is the
`parro-client` command.
"""

if __name__ == "__main__":
    from parro.cli import run

    run()
