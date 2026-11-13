"""The app's own small settings file, desktop-app.json in the data folder.

It holds parts that are written separately: what the login dialog remembered (auto_login.py) and
the answer about the update check (updates.py). Writing one part keeps the others. Private to the
user, like every file in the data folder; never a password or a token.
"""

import json
from pathlib import Path
from typing import Any

from parro.cache import write_private_file

FILE_NAME = "desktop-app.json"


def path_in(data_dir: Path) -> Path:
    return data_dir / FILE_NAME


def read_all(data_dir: Path) -> dict[str, Any]:
    """Everything in the file; an empty dict when it is missing or damaged."""
    try:
        saved = json.loads(path_in(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def read_part(data_dir: Path, name: str) -> Any:
    return read_all(data_dir).get(name)


def write_part(data_dir: Path, name: str, value: Any) -> None:
    """Set one part, or remove it (None). The file goes when nothing is left in it."""
    saved = read_all(data_dir)
    if value is None:
        saved.pop(name, None)
    else:
        saved[name] = value
    path = path_in(data_dir)
    if not saved:
        path.unlink(missing_ok=True)
        return
    write_private_file(path, json.dumps(saved, indent=2).encode("utf-8"))
